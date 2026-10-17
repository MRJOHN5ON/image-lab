"""In-memory image queue and batch runner.

Each batch slot is a thread that hands one image at a time to a worker process and
records the result, so status stays live while the heavy work runs on every core.
"""

from __future__ import annotations

import dataclasses
import io
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from PIL import Image, ImageOps

from processor.convert import source_format
from processor.pipeline import (
    ProcessingSettings,
    ProcessResult,
    discover_images,
    open_image,
    plan_output_path,
    unique_path,
)
from workers import BrokenProcessPool, WorkerPool

log = logging.getLogger("imagelab.queue")

MAX_QUEUE_ITEMS = 20_000

# Output pixels allowed in flight at once (~4 bytes each, several copies while encoding).
# Keeps a batch of huge upscales from exhausting memory; ordinary photos run fully parallel.
PIXEL_BUDGET = 300_000_000


def estimate_output_pixels(item: "QueueItem", settings: ProcessingSettings) -> int:
    pixels = max(1, (item.width or 1) * (item.height or 1))
    if settings.resize_enabled:
        if settings.resize_mode == "scale" and settings.scale_percent:
            pixels = int(pixels * (settings.scale_percent / 100) ** 2)
        elif settings.resize_mode == "exact" and settings.exact_width and settings.exact_height:
            pixels = settings.exact_width * settings.exact_height
    if settings.upscale_enabled and settings.upscale_factor > 1:
        pixels = int(pixels * settings.upscale_factor**2)
    return max(1, pixels)


class _Budget:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.used = 0
        self._cond = threading.Condition()

    def acquire(self, amount: int, cancelled: threading.Event) -> Optional[int]:
        amount = min(amount, self.capacity)
        with self._cond:
            while self.used and self.used + amount > self.capacity:
                if cancelled.is_set():
                    return None
                self._cond.wait(0.2)
            self.used += amount
            return amount

    def release(self, amount: int) -> None:
        with self._cond:
            self.used -= amount
            self._cond.notify_all()


class ItemStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


ACTIVE_STATUSES = {ItemStatus.QUEUED, ItemStatus.PROCESSING}
FINISHED_STATUSES = {ItemStatus.DONE, ItemStatus.SKIPPED}


@dataclass
class QueueItem:
    id: str
    path: str
    filename: str
    original_size: int
    width: int
    height: int
    format: str
    source: str  # "upload" | "path"
    added_at: float
    upload_dir: Optional[str] = None
    status: ItemStatus = ItemStatus.PENDING
    result: Optional[ProcessResult] = None
    error: Optional[str] = None
    thumbnail: Optional[bytes] = None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id,
            "path": self.path,
            "filename": self.filename,
            "original_size": self.original_size,
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "source": self.source,
            "status": self.status.value,
            "error": self.error,
        }
        if self.result and self.result.success:
            data["result"] = {
                "output_path": self.result.output_path,
                "new_size": self.result.new_size,
                "savings_percent": self.result.savings_percent,
                "method_used": self.result.method_used,
                "quality_used": self.result.quality_used,
                "processing_time_ms": self.result.processing_time_ms,
                "warnings": self.result.warnings,
                "new_dimensions": list(self.result.new_dimensions),
                "format": self.result.format,
            }
        return data


@dataclass
class BatchState:
    id: str = ""
    running: bool = False
    cancelling: bool = False
    total: int = 0
    done: int = 0
    failed: int = 0
    skipped: int = 0
    cancelled: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    current: Set[str] = field(default_factory=set)
    results: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def completed(self) -> int:
        return self.done + self.failed + self.skipped + self.cancelled


def make_thumbnail(path: Path, size: int = 160) -> Optional[bytes]:
    try:
        with open_image(path) as img:
            if img.format == "JPEG":
                img.draft("RGB", (size * 2, size * 2))
            img = ImageOps.exif_transpose(img)
            img.thumbnail((size, size), Image.Resampling.LANCZOS)
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGBA")
                bg = Image.new("RGB", img.size, (40, 42, 48))
                bg.paste(img, mask=img.getchannel("A"))
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=82)
            return buf.getvalue()
    except Exception:  # noqa: BLE001 - thumbnails are best effort
        return None


def _probe(path: Path) -> Optional[Tuple[int, int, str]]:
    """Header-only read: displayed size (after EXIF rotation) and format, or None if unreadable."""
    try:
        with open_image(path) as img:
            w, h = img.size
            exif_orientation = img.getexif().get(0x0112, 1)
            if exif_orientation in (5, 6, 7, 8):
                w, h = h, w
            return w, h, source_format(path, img.format)
    except Exception:  # noqa: BLE001
        return None


class ImageQueue:
    def __init__(self, max_workers: Optional[int] = None):
        self._items: "OrderedDict[str, QueueItem]" = OrderedDict()
        self._paths: Dict[str, str] = {}
        self._lock = threading.RLock()
        self._batch = BatchState()
        self._cancel = threading.Event()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._version = 0
        cpu = os.cpu_count() or 4
        self.workers = max(1, min(max_workers or max(cpu - 1, 1), 8))
        self.pool = WorkerPool(self.workers, "batch")
        self._budget = _Budget(PIXEL_BUDGET)
        self.on_items_removed: Optional[Callable[[List[QueueItem]], None]] = None

    def shutdown(self) -> None:
        self.cancel_batch()
        self.pool.shutdown()

    # ── state ─────────────────────────────────────────────────────────
    @property
    def version(self) -> int:
        return self._version

    @property
    def running(self) -> bool:
        return self._batch.running

    def _bump(self) -> None:
        self._version += 1

    # ── queue contents ────────────────────────────────────────────────
    def add_paths(
        self,
        paths: Iterable[str],
        *,
        recursive: bool = True,
        source: str = "path",
        upload_dirs: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        discovered = discover_images(paths, recursive=recursive)
        upload_dirs = upload_dirs or {}
        probed = []
        unreadable: List[str] = []
        duplicates = 0
        for p in discovered:
            key = str(p.resolve())
            with self._lock:
                if key in self._paths:
                    duplicates += 1
                    continue
            try:
                size = p.stat().st_size
            except OSError:
                unreadable.append(str(p))
                continue
            info = _probe(p)
            if info is None:
                unreadable.append(str(p))
                continue
            probed.append((key, p, size, *info))

        added: List[QueueItem] = []
        with self._lock:
            for key, p, size, w, h, fmt in probed:
                if key in self._paths:
                    duplicates += 1
                    continue
                if len(self._items) >= MAX_QUEUE_ITEMS:
                    break
                item = QueueItem(
                    id=uuid.uuid4().hex,
                    path=key,
                    filename=p.name,
                    original_size=size,
                    width=w,
                    height=h,
                    format=fmt,
                    source=source,
                    added_at=time.time(),
                    upload_dir=upload_dirs.get(str(p)),
                )
                self._items[item.id] = item
                self._paths[key] = item.id
                added.append(item)
            if added:
                self._bump()
        return {
            "added": [a.to_dict() for a in added],
            "duplicates": duplicates,
            "unreadable": unreadable,
            "found": len(discovered),
            "limit_reached": len(self._items) >= MAX_QUEUE_ITEMS,
        }

    def list_items(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [item.to_dict() for item in self._items.values()]

    def get(self, item_id: str) -> Optional[QueueItem]:
        with self._lock:
            return self._items.get(item_id)

    def all_items(self) -> List[QueueItem]:
        with self._lock:
            return list(self._items.values())

    def remove(self, ids: Iterable[str]) -> int:
        removed: List[QueueItem] = []
        with self._lock:
            for item_id in ids:
                item = self._items.get(item_id)
                if not item:
                    continue
                if item.status in ACTIVE_STATUSES:
                    raise RuntimeError("Can't remove images that are being processed")
                removed.append(self._items.pop(item_id))
                self._paths.pop(item.path, None)
            if removed:
                self._bump()
        self._notify_removed(removed)
        return len(removed)

    def clear(self, scope: str = "all") -> int:
        with self._lock:
            if scope == "finished":
                ids = [i.id for i in self._items.values() if i.status in FINISHED_STATUSES]
            else:
                if self._batch.running:
                    raise RuntimeError("Can't clear the queue while processing")
                ids = list(self._items.keys())
        return self.remove(ids)

    def _notify_removed(self, removed: List[QueueItem]) -> None:
        if removed and self.on_items_removed:
            try:
                self.on_items_removed(removed)
            except Exception:  # noqa: BLE001
                log.exception("Cleanup after removal failed")

    def thumbnail(self, item_id: str) -> Optional[bytes]:
        item = self.get(item_id)
        if not item:
            return None
        if item.thumbnail is None:
            item.thumbnail = make_thumbnail(Path(item.path)) or b""
        return item.thumbnail or None

    # ── batch processing ──────────────────────────────────────────────
    def start_batch(
        self,
        settings: ProcessingSettings,
        item_ids: Optional[List[str]] = None,
        *,
        default_output_dir: Optional[Callable[[QueueItem], Optional[Path]]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            if self._batch.running:
                raise RuntimeError("A batch is already running")
            ids = [i for i in (item_ids or list(self._items.keys())) if i in self._items]
            if not ids:
                raise ValueError("Nothing to process — add images first")

            plan: Dict[str, Path] = {}
            taken: Set[str] = set()
            sources = set(self._paths.keys())
            for item_id in ids:
                item = self._items[item_id]
                src = Path(item.path)
                base = default_output_dir(item) if default_output_dir else None
                item_settings = settings
                if settings.replace_originals and item.source == "upload":
                    # An upload's "original" is a private temp copy; replacing it would lose the result.
                    item_settings = dataclasses.replace(settings, replace_originals=False)
                out = plan_output_path(src, item.format, item_settings, default_dir=base)
                is_original = str(out) == item.path
                clobbers_other_source = str(out) in sources and not is_original
                if str(out) in taken or clobbers_other_source or (
                    settings.on_conflict == "rename" and out.exists() and not is_original
                ):
                    out = unique_path(out, taken | sources)
                taken.add(str(out))
                plan[item_id] = out

                item.status = ItemStatus.QUEUED
                item.result = None
                item.error = None

            self._cancel.clear()
            self._batch = BatchState(
                id=uuid.uuid4().hex,
                running=True,
                total=len(ids),
                started_at=time.time(),
            )
            batch = self._batch
            self._executor = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="imagelab")
            futures = [self._executor.submit(self._process_one, batch, i, plan[i], settings) for i in ids]
            self._bump()

        threading.Thread(target=self._finish_when_done, args=(batch, futures), daemon=True).start()
        log.info("Batch %s started: %d images, %d workers", batch.id[:8], len(ids), self.workers)
        return self.status()

    def _process_one(self, batch: BatchState, item_id: str, out: Path, settings: ProcessingSettings) -> None:
        with self._lock:
            item = self._items.get(item_id)
            if item is None:
                return
            if self._cancel.is_set():
                item.status = ItemStatus.CANCELLED
                batch.cancelled += 1
                self._bump()
                return
            source_path = item.path
            weight = estimate_output_pixels(item, settings)

        reserved = self._budget.acquire(weight, self._cancel)
        with self._lock:
            if reserved is None or self._cancel.is_set():
                if reserved is not None:
                    self._budget.release(reserved)
                item.status = ItemStatus.CANCELLED
                batch.cancelled += 1
                self._bump()
                return
            item.status = ItemStatus.PROCESSING
            batch.current.add(item.filename)
            self._bump()

        try:
            result = self.pool.run(source_path, settings, output_path=str(out), resolve_conflicts=False)
        except BrokenProcessPool:
            result = ProcessResult(
                success=False,
                error="The image engine crashed on this file — it may be too large for available memory",
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("Unexpected failure processing %s", source_path)
            result = ProcessResult(success=False, error=str(exc) or exc.__class__.__name__)
        finally:
            self._budget.release(reserved)

        with self._lock:
            batch.current.discard(item.filename)
            item.result = result
            if not result.success:
                item.status = ItemStatus.FAILED
                item.error = result.error
                batch.failed += 1
            else:
                item.status = ItemStatus.SKIPPED if result.skipped else ItemStatus.DONE
                if result.skipped:
                    batch.skipped += 1
                else:
                    batch.done += 1
                    batch.bytes_in += result.original_size
                    batch.bytes_out += result.new_size
            batch.results.append(
                {
                    "filename": item.filename,
                    "source_path": item.path,
                    "output_path": result.output_path,
                    "status": item.status.value,
                    "original_size": result.original_size,
                    "new_size": result.new_size if result.success else None,
                    "savings_percent": result.savings_percent if result.success else None,
                    "original_dimensions": "×".join(map(str, result.original_dimensions)),
                    "new_dimensions": "×".join(map(str, result.new_dimensions)),
                    "format": result.format,
                    "method": result.method_used,
                    "quality": result.quality_used,
                    "time_ms": result.processing_time_ms,
                    "warnings": result.warning or "",
                    "error": result.error or "",
                }
            )
            self._bump()

    def _finish_when_done(self, batch: BatchState, futures: List[Future]) -> None:
        try:
            # Futures cancelled by shutdown(cancel_futures=True) never wake wait(); poll done().
            while not all(f.done() for f in futures):
                wait(futures, timeout=0.2)
        finally:
            with self._lock:
                for item in self._items.values():
                    if item.status in ACTIVE_STATUSES:
                        item.status = ItemStatus.CANCELLED
                        batch.cancelled += 1
                batch.running = False
                batch.cancelling = False
                batch.current.clear()
                batch.finished_at = time.time()
                executor, self._executor = self._executor, None
                self._bump()
            if executor:
                executor.shutdown(wait=False)
            log.info(
                "Batch %s finished: %d done, %d skipped, %d failed, %d cancelled in %.1fs",
                batch.id[:8],
                batch.done,
                batch.skipped,
                batch.failed,
                batch.cancelled,
                (batch.finished_at or 0) - (batch.started_at or 0),
            )

    def cancel_batch(self) -> None:
        with self._lock:
            if not self._batch.running:
                return
            self._cancel.set()
            self._batch.cancelling = True
            executor = self._executor
            self._bump()
        if executor:
            executor.shutdown(wait=False, cancel_futures=True)

    def wait_idle(self, timeout: float = 30) -> bool:
        deadline = time.time() + timeout
        while self._batch.running and time.time() < deadline:
            time.sleep(0.02)
        return not self._batch.running

    def status(self) -> Dict[str, Any]:
        with self._lock:
            b = self._batch
            now = b.finished_at or time.time()
            elapsed = (now - b.started_at) if b.started_at else 0.0
            processed = b.done + b.failed + b.skipped
            rate = processed / elapsed if elapsed > 0 and processed else 0.0
            remaining = b.total - b.completed
            eta = remaining / rate if rate > 0 and b.running else 0.0
            saved = max(0, b.bytes_in - b.bytes_out)
            return {
                "batch_id": b.id,
                "running": b.running,
                "cancelling": b.cancelling,
                "total": b.total,
                "completed": b.completed,
                "done": b.done,
                "failed": b.failed,
                "skipped": b.skipped,
                "cancelled": b.cancelled,
                "current_files": sorted(b.current),
                "elapsed_seconds": round(elapsed, 2),
                "files_per_second": round(rate, 2),
                "eta_seconds": round(eta, 1),
                "bytes_in": b.bytes_in,
                "bytes_out": b.bytes_out,
                "bytes_saved": saved,
                "savings_percent": round(saved / b.bytes_in * 100, 1) if b.bytes_in else 0,
                "started_at": b.started_at,
                "finished_at": b.finished_at,
                "version": self._version,
            }

    def report(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._batch.results)

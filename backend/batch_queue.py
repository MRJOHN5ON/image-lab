"""Batch queue and processing state."""

from __future__ import annotations

import base64
import io
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image

from processor.pipeline import ProcessingSettings, ProcessResult, discover_images, process_image


class ItemStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


@dataclass
class QueueItem:
    id: str
    path: str
    filename: str
    original_size: int
    width: int
    height: int
    format: str
    status: ItemStatus = ItemStatus.PENDING
    result: Optional[ProcessResult] = None
    error: Optional[str] = None
    thumbnail: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "path": self.path,
            "filename": self.filename,
            "original_size": self.original_size,
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "status": self.status.value,
            "error": self.error,
        }
        if self.result:
            d["result"] = {
                "output_path": self.result.output_path,
                "new_size": self.result.new_size,
                "savings_percent": self.result.savings_percent,
                "method_used": self.result.method_used,
                "quality_used": self.result.quality_used,
                "processing_time_ms": self.result.processing_time_ms,
                "warning": self.result.warning,
                "new_dimensions": list(self.result.new_dimensions),
            }
        if self.thumbnail:
            d["thumbnail"] = self.thumbnail
        return d


def _make_thumbnail(path: Path, max_size: int = 64) -> Optional[str]:
    try:
        img = Image.open(path)
        img.thumbnail((max_size, max_size))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None


@dataclass
class BatchState:
    running: bool = False
    cancelled: bool = False
    total: int = 0
    completed: int = 0
    failed: int = 0
    current_file: Optional[str] = None
    start_time: Optional[float] = None
    bytes_saved: int = 0
    results: List[Dict[str, Any]] = field(default_factory=list)


class ImageQueue:
    def __init__(self, max_workers: Optional[int] = None):
        self._items: Dict[str, QueueItem] = {}
        self._order: List[str] = []
        self._lock = threading.Lock()
        self._batch = BatchState()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._max_workers = max_workers

    @property
    def batch(self) -> BatchState:
        return self._batch

    def add_paths(self, paths: List[str], recursive: bool = True) -> List[QueueItem]:
        discovered = discover_images(paths, recursive=recursive)
        added: List[QueueItem] = []
        with self._lock:
            for p in discovered:
                key = str(p.resolve())
                if any(self._items[i].path == key for i in self._order):
                    continue
                try:
                    img = Image.open(p)
                    w, h = img.size
                    fmt = (img.format or p.suffix.lstrip(".")).upper()
                except Exception:
                    w, h, fmt = 0, 0, p.suffix.lstrip(".").upper()

                item_id = str(uuid.uuid4())
                thumb = _make_thumbnail(p)
                item = QueueItem(
                    id=item_id,
                    path=key,
                    filename=p.name,
                    original_size=p.stat().st_size,
                    width=w,
                    height=h,
                    format=fmt,
                    thumbnail=thumb,
                )
                self._items[item_id] = item
                self._order.append(item_id)
                added.append(item)
        return added

    def clear(self) -> None:
        with self._lock:
            if self._batch.running:
                return
            self._items.clear()
            self._order.clear()

    def list_items(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [self._items[i].to_dict() for i in self._order]

    def get_item(self, item_id: str) -> Optional[QueueItem]:
        return self._items.get(item_id)

    def remove_item(self, item_id: str) -> bool:
        with self._lock:
            if item_id in self._items:
                del self._items[item_id]
                self._order = [i for i in self._order if i != item_id]
                return True
        return False

    def start_batch(self, settings: ProcessingSettings, item_ids: Optional[List[str]] = None) -> None:
        with self._lock:
            if self._batch.running:
                raise RuntimeError("Batch already running")

            ids = item_ids or list(self._order)
            ids = [i for i in ids if i in self._items]

            self._batch = BatchState(
                running=True,
                total=len(ids),
                start_time=time.time(),
            )

        import os

        workers = self._max_workers or min(os.cpu_count() or 4, 8)
        self._executor = ThreadPoolExecutor(max_workers=workers)

        def process_one(item_id: str) -> None:
            if self._batch.cancelled:
                with self._lock:
                    item = self._items.get(item_id)
                    if item:
                        item.status = ItemStatus.CANCELLED
                return

            with self._lock:
                item = self._items.get(item_id)
                if not item:
                    return
                item.status = ItemStatus.PROCESSING
                self._batch.current_file = item.filename

            try:
                result = process_image(item.path, settings)
                with self._lock:
                    item = self._items[item_id]
                    if result.success:
                        item.status = ItemStatus.SKIPPED if result.method_used == "skipped" else ItemStatus.DONE
                        item.result = result
                        saved = max(0, result.original_size - result.new_size)
                        self._batch.bytes_saved += saved
                        self._batch.results.append(
                            {
                                "filename": item.filename,
                                "path": item.path,
                                "original_size": result.original_size,
                                "new_size": result.new_size,
                                "savings_percent": result.savings_percent,
                                "method_used": result.method_used,
                                "quality_used": result.quality_used,
                                "settings": settings.to_dict(),
                            }
                        )
                    else:
                        item.status = ItemStatus.FAILED
                        item.error = result.error
                        self._batch.failed += 1
            except Exception as e:
                with self._lock:
                    item = self._items[item_id]
                    item.status = ItemStatus.FAILED
                    item.error = str(e)
                    self._batch.failed += 1
            finally:
                with self._lock:
                    self._batch.completed += 1

        def run_batch() -> None:
            futures = [self._executor.submit(process_one, i) for i in ids]
            for f in as_completed(futures):
                if self._batch.cancelled:
                    break
                f.result()
            with self._lock:
                self._batch.running = False
                self._batch.current_file = None
            if self._executor:
                self._executor.shutdown(wait=False)

        threading.Thread(target=run_batch, daemon=True).start()

    def cancel_batch(self) -> None:
        self._batch.cancelled = True

    def status(self) -> Dict[str, Any]:
        with self._lock:
            elapsed = 0.0
            files_per_sec = 0.0
            eta = 0.0
            if self._batch.start_time:
                elapsed = time.time() - self._batch.start_time
                if elapsed > 0 and self._batch.completed > 0:
                    files_per_sec = self._batch.completed / elapsed
                    remaining = self._batch.total - self._batch.completed
                    if files_per_sec > 0:
                        eta = remaining / files_per_sec

            return {
                "running": self._batch.running,
                "cancelled": self._batch.cancelled,
                "total": self._batch.total,
                "completed": self._batch.completed,
                "failed": self._batch.failed,
                "current_file": self._batch.current_file,
                "elapsed_seconds": round(elapsed, 2),
                "files_per_second": round(files_per_sec, 2),
                "eta_seconds": round(eta, 1),
                "bytes_saved": self._batch.bytes_saved,
                "mb_saved": round(self._batch.bytes_saved / (1024 * 1024), 2),
            }

    def export_report(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._batch.results)

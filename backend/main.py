"""Image Lab — FastAPI backend."""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import uuid
import zipfile
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

import config
from batch_queue import ImageQueue, QueueItem
from display import BROWSER_SAFE, MIME_TYPES, display_copy, fits_display
from workers import BrokenProcessPool, WorkerPool
from processor.compress import jpegtran_available
from processor.pipeline import (
    HEIF_AVAILABLE,
    SUPPORTED_EXTENSIONS,
    ProcessingSettings,
    SettingsError,
    open_image,
)

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("imagelab")

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

@asynccontextmanager
async def lifespan(_app: FastAPI):
    if config.WARM_WORKERS:
        threading.Thread(target=lambda: (preview_pool.warm(), queue.pool.warm()), daemon=True).start()
    yield
    queue.shutdown()
    preview_pool.shutdown()


app = FastAPI(title=config.APP_NAME, version=config.VERSION, docs_url="/api/docs", redoc_url=None, lifespan=lifespan)
queue = ImageQueue(max_workers=config.WORKERS)
preview_pool = WorkerPool(2, "preview")
_presets_lock = threading.Lock()
_preview_slots = threading.BoundedSemaphore(2)
_preview_lock = threading.Lock()
_preview_generation = 0


# ── housekeeping ──────────────────────────────────────────────────────────
def _reset_uploads() -> None:
    """The queue lives in memory, so uploads left from a previous run are orphans."""
    for child in config.UPLOAD_DIR.iterdir():
        try:
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        except OSError:
            log.warning("Could not remove stale upload %s", child)


class BlobCache:
    """Small LRU of rendered previews, bounded by total bytes."""

    def __init__(self, max_items: int = 24, max_bytes: int = 512 * 1024 * 1024):
        self._items: "OrderedDict[str, Tuple[bytes, str]]" = OrderedDict()
        self._max_items = max_items
        self._max_bytes = max_bytes
        self._lock = threading.Lock()

    def put(self, data: bytes, media_type: str, key: Optional[str] = None) -> str:
        key = key or uuid.uuid4().hex
        with self._lock:
            self._items.pop(key, None)
            self._items[key] = (data, media_type)
            while len(self._items) > self._max_items or self._size() > self._max_bytes:
                if len(self._items) <= 1:
                    break
                self._items.popitem(last=False)
        return key

    def get(self, key: str) -> Optional[Tuple[bytes, str]]:
        with self._lock:
            value = self._items.get(key)
            if value is not None:
                self._items.move_to_end(key)
            return value

    def drop_prefix(self, prefix: str) -> None:
        with self._lock:
            for key in [k for k in self._items if k.startswith(prefix)]:
                del self._items[key]

    def _size(self) -> int:
        return sum(len(v[0]) for v in self._items.values())


blobs = BlobCache()


def _on_items_removed(items: List[QueueItem]) -> None:
    for item in items:
        blobs.drop_prefix(f"src:{item.id}")
        if item.upload_dir:
            shutil.rmtree(item.upload_dir, ignore_errors=True)


queue.on_items_removed = _on_items_removed
_reset_uploads()


# ── security + errors ─────────────────────────────────────────────────────
def _host_name(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):
        return value[1 : value.find("]")] if "]" in value else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


@app.middleware("http")
async def local_only(request: Request, call_next):
    """Reject DNS-rebinding hosts and cross-site writes; this server can read the user's disk."""
    if _host_name(request.headers.get("host", "")) not in LOOPBACK_HOSTS:
        return JSONResponse({"detail": "Image Lab only accepts local connections"}, status_code=400)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin is not None and (urlparse(origin).hostname or "") not in LOOPBACK_HOSTS:
            return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith("/api/") and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(SettingsError)
async def settings_error_handler(_: Request, exc: SettingsError) -> JSONResponse:
    return JSONResponse({"detail": exc.message, "field": exc.field}, status_code=422)


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": f"Unexpected error: {exc}"}, status_code=500)


def _settings(data: Any) -> ProcessingSettings:
    return ProcessingSettings.from_dict(data or {})


def _item_or_404(item_id: str) -> QueueItem:
    item = queue.get(item_id)
    if not item:
        raise HTTPException(404, "Image is no longer in the queue")
    return item


# ── models ────────────────────────────────────────────────────────────────
class PathsRequest(BaseModel):
    paths: List[str] = Field(..., max_length=1000)
    recursive: bool = True


class RemoveRequest(BaseModel):
    ids: List[str] = Field(..., max_length=20_000)


class ProcessRequest(BaseModel):
    settings: Dict[str, Any] = Field(default_factory=dict)
    item_ids: Optional[List[str]] = None


class PreviewRequest(BaseModel):
    item_id: str
    settings: Dict[str, Any] = Field(default_factory=dict)


class PresetSaveRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    description: str = Field("", max_length=200)
    settings: Dict[str, Any]
    id: Optional[str] = Field(None, max_length=80)


class RevealRequest(BaseModel):
    path: str


class PickRequest(BaseModel):
    kind: str = Field("folder", pattern="^(folder|files|output)$")


# ── health ────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health() -> Dict[str, Any]:
    from PIL import __version__ as pillow_version
    from PIL import features

    return {
        "status": "ok",
        "app": config.APP_NAME,
        "version": config.VERSION,
        "packaged": config.PACKAGED,
        "platform": sys.platform,
        "pillow_version": pillow_version,
        "jpegtran_available": jpegtran_available(),
        "heif_available": HEIF_AVAILABLE,
        "avif_supported": bool(features.check("avif")),
        "workers": queue.workers,
        "default_output_dir": str(config.DEFAULT_OUTPUT_DIR),
        "native_dialogs": sys.platform == "darwin",
        "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
        "max_upload_mb": config.MAX_UPLOAD_BYTES // (1024 * 1024),
    }


# ── queue ─────────────────────────────────────────────────────────────────
def _queue_payload() -> Dict[str, Any]:
    items = queue.list_items()
    return {
        "items": items,
        "count": len(items),
        "total_size": sum(i["original_size"] for i in items),
        "version": queue.version,
        "running": queue.running,
    }


@app.get("/api/queue")
def list_queue() -> Dict[str, Any]:
    return _queue_payload()


_UNSAFE_NAME = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')


def safe_filename(name: str) -> str:
    base = unicodedata.normalize("NFC", (name or "").replace("\\", "/")).rsplit("/", 1)[-1]
    base = _UNSAFE_NAME.sub("_", base).strip(" .")
    if not base:
        base = "image"
    stem, dot, ext = base.rpartition(".")
    if dot and len(base) > 180:
        base = stem[: 180 - len(ext) - 1] + "." + ext
    return base[:180]


class _TooLarge(Exception):
    pass


@app.post("/api/queue/upload")
@app.post("/api/queue", include_in_schema=False)
def upload_files(files: List[UploadFile] = File(...)) -> Dict[str, Any]:
    saved: List[str] = []
    upload_dirs: Dict[str, str] = {}
    rejected: List[Dict[str, str]] = []

    for upload in files:
        name = safe_filename(upload.filename or "image")
        if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
            rejected.append({"name": name, "reason": "Unsupported file type"})
            continue
        folder = config.UPLOAD_DIR / uuid.uuid4().hex
        folder.mkdir(parents=True)
        dest = folder / name
        size = 0
        try:
            with dest.open("wb") as out:
                while chunk := upload.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > config.MAX_UPLOAD_BYTES:
                        raise _TooLarge
                    out.write(chunk)
        except _TooLarge:
            shutil.rmtree(folder, ignore_errors=True)
            rejected.append({"name": name, "reason": f"Larger than {config.MAX_UPLOAD_BYTES // 2**20} MB"})
            continue
        except OSError as exc:
            shutil.rmtree(folder, ignore_errors=True)
            rejected.append({"name": name, "reason": f"Couldn't save: {exc.strerror or exc}"})
            continue
        finally:
            upload.file.close()
        if size == 0:
            shutil.rmtree(folder, ignore_errors=True)
            rejected.append({"name": name, "reason": "File is empty"})
            continue
        saved.append(str(dest))
        upload_dirs[str(dest)] = str(folder)

    result = queue.add_paths(saved, recursive=False, source="upload", upload_dirs=upload_dirs)
    added_paths = {item["path"] for item in result["added"]}
    for path in saved:
        if str(Path(path).resolve()) not in added_paths:
            shutil.rmtree(upload_dirs[path], ignore_errors=True)
    for path in result["unreadable"]:
        rejected.append({"name": Path(path).name, "reason": "Not a readable image"})
    return {**result, "rejected": rejected, "queue_version": queue.version}


@app.post("/api/queue/paths")
def add_paths(req: PathsRequest) -> Dict[str, Any]:
    paths = [p for p in (s.strip() for s in req.paths) if p]
    if not paths:
        raise HTTPException(400, "No files or folders provided")
    missing = [p for p in paths if not Path(p).expanduser().exists()]
    result = queue.add_paths(paths, recursive=req.recursive)
    rejected = [{"name": p, "reason": "Not found"} for p in missing]
    rejected += [{"name": Path(p).name, "reason": "Not a readable image"} for p in result["unreadable"]]
    return {**result, "rejected": rejected, "queue_version": queue.version}


@app.delete("/api/queue")
def clear_queue(scope: str = Query("all", pattern="^(all|finished)$")) -> Dict[str, Any]:
    try:
        removed = queue.clear(scope)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"removed": removed}


@app.post("/api/queue/remove")
def remove_items(req: RemoveRequest) -> Dict[str, Any]:
    try:
        removed = queue.remove(req.ids)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"removed": removed}


@app.delete("/api/queue/{item_id}")
def remove_item(item_id: str) -> Dict[str, Any]:
    _item_or_404(item_id)
    return remove_items(RemoveRequest(ids=[item_id]))


# ── item images ───────────────────────────────────────────────────────────
_PRIVATE_CACHE = {"Cache-Control": "private, max-age=3600"}


@app.get("/api/items/{item_id}/thumbnail")
def item_thumbnail(item_id: str) -> Response:
    _item_or_404(item_id)
    data = queue.thumbnail(item_id)
    if not data:
        raise HTTPException(404, "No thumbnail")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/items/{item_id}/source")
def item_source(item_id: str) -> Response:
    item = _item_or_404(item_id)
    path = Path(item.path)
    if not path.is_file():
        raise HTTPException(404, "Original file is missing")
    if item.format in BROWSER_SAFE and fits_display(item.width or 0, item.height or 0):
        return FileResponse(path, media_type=MIME_TYPES[item.format], headers=_PRIVATE_CACHE)
    key = f"src:{item.id}"
    cached = blobs.get(key)
    if cached is None:
        try:
            with open_image(path) as img:
                data, media_type, _ = display_copy(img)
                cached = (data, media_type)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(422, f"Can't display this image: {exc}") from exc
        blobs.put(cached[0], cached[1], key=key)
    return Response(cached[0], media_type=cached[1], headers=_PRIVATE_CACHE)


@app.get("/api/items/{item_id}/output")
def item_output(item_id: str, download: bool = False) -> Response:
    item = _item_or_404(item_id)
    out = item.result.output_path if item.result and item.result.success else None
    if not out or not Path(out).is_file():
        raise HTTPException(404, "This image hasn't been processed yet")
    fmt = item.result.format
    return FileResponse(
        out,
        media_type=MIME_TYPES.get(fmt, "application/octet-stream"),
        filename=Path(out).name if download else None,
        headers={"Cache-Control": "no-cache"},
    )


# ── preview ───────────────────────────────────────────────────────────────
@app.post("/api/preview")
def preview(req: PreviewRequest) -> Dict[str, Any]:
    global _preview_generation
    item = _item_or_404(req.item_id)
    settings = _settings(req.settings)
    with _preview_lock:
        _preview_generation += 1
        generation = _preview_generation
    with _preview_slots:
        # The UI only shows the newest preview; don't burn time on ones it has abandoned.
        if generation < _preview_generation:
            raise HTTPException(409, "Superseded by a newer preview")
        try:
            rendered = preview_pool.preview(item.path, settings)
        except BrokenProcessPool as exc:
            raise HTTPException(500, "The preview engine crashed — the image may be too large for available memory") from exc
    result = rendered["result"]
    if not result.success:
        raise HTTPException(422, result.error or "Preview failed")
    shown, media_type, display_size = rendered["shown"], rendered["media_type"], rendered["display_size"]
    token = blobs.put(shown, media_type)
    full_w = result.new_dimensions[0] or display_size[0]
    return {
        "item_id": item.id,
        "before_url": f"/api/items/{item.id}/source",
        "after_url": f"/api/preview/{token}",
        "format": result.format,
        "original_size": result.original_size,
        "new_size": result.new_size,
        "original_dimensions": list(result.original_dimensions),
        "new_dimensions": list(result.new_dimensions),
        "display_dimensions": list(display_size),
        "display_scale": round(display_size[0] / full_w, 4) if full_w else 1,
        "quality_used": result.quality_used,
        "method_used": result.method_used,
        "processing_time_ms": result.processing_time_ms,
        "savings_percent": result.savings_percent,
        "warnings": result.warnings,
        "steps": result.steps,
    }


@app.get("/api/preview/{token}")
def preview_image(token: str) -> Response:
    cached = blobs.get(token)
    if cached is None:
        raise HTTPException(404, "Preview expired — run it again")
    return Response(cached[0], media_type=cached[1], headers=_PRIVATE_CACHE)


@app.post("/api/settings/validate")
def validate_settings(body: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, "settings": _settings(body.get("settings", body)).to_dict()}


# ── processing ────────────────────────────────────────────────────────────
def _default_output_dir(item: QueueItem) -> Optional[Path]:
    return config.DEFAULT_OUTPUT_DIR if item.source == "upload" else None


@app.post("/api/process")
def start_process(req: ProcessRequest) -> Dict[str, Any]:
    settings = _settings(req.settings)
    try:
        progress = queue.start_batch(settings, req.item_ids, default_output_dir=_default_output_dir)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"status": "started", "progress": progress}


@app.post("/api/process/cancel")
def cancel_process() -> Dict[str, Any]:
    queue.cancel_batch()
    return {"status": "cancelling", "progress": queue.status()}


@app.get("/api/process/status")
def process_status() -> Dict[str, Any]:
    return queue.status()


# ── presets ───────────────────────────────────────────────────────────────
def _read_presets(path: Path) -> List[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        presets = data.get("presets", []) if isinstance(data, dict) else []
        return [p for p in presets if isinstance(p, dict) and p.get("id") and p.get("name")]
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        log.warning("Could not read presets from %s", path)
        return []


def _write_custom_presets(presets: List[Dict[str, Any]]) -> None:
    path = config.CUSTOM_PRESETS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".presets.", suffix=".tmp")
    with open(fd, "w", encoding="utf-8") as handle:
        json.dump({"presets": presets}, handle, indent=2)
    Path(tmp).replace(path)


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", text).lower()).strip("-")
    return slug[:60] or "preset"


@app.get("/api/presets")
def get_presets() -> Dict[str, Any]:
    builtin = [{**p, "builtin": True} for p in _read_presets(config.BUILTIN_PRESETS_FILE)]
    with _presets_lock:
        custom = [{**p, "builtin": False} for p in _read_presets(config.CUSTOM_PRESETS_FILE)]
    return {"presets": builtin + custom}


@app.post("/api/presets")
def save_preset(req: PresetSaveRequest) -> Dict[str, Any]:
    settings = _settings(req.settings)
    builtin_ids = {p["id"] for p in _read_presets(config.BUILTIN_PRESETS_FILE)}
    preset_id = req.id or f"custom-{_slug(req.name)}"
    if preset_id in builtin_ids:
        raise HTTPException(409, "Built-in presets can't be overwritten")
    entry = {
        "id": preset_id,
        "name": req.name.strip(),
        "description": req.description.strip(),
        "settings": settings.to_dict(),
        "updated_at": time.time(),
    }
    with _presets_lock:
        custom = [p for p in _read_presets(config.CUSTOM_PRESETS_FILE) if p["id"] != preset_id]
        custom.append(entry)
        _write_custom_presets(custom)
    return {"preset": {**entry, "builtin": False}}


@app.delete("/api/presets/{preset_id}")
def delete_preset(preset_id: str) -> Dict[str, Any]:
    with _presets_lock:
        custom = _read_presets(config.CUSTOM_PRESETS_FILE)
        remaining = [p for p in custom if p["id"] != preset_id]
        if len(remaining) == len(custom):
            raise HTTPException(404, "Preset not found")
        _write_custom_presets(remaining)
    return {"deleted": preset_id}


# ── exports ───────────────────────────────────────────────────────────────
REPORT_FIELDS = [
    "filename",
    "status",
    "original_size",
    "new_size",
    "savings_percent",
    "original_dimensions",
    "new_dimensions",
    "format",
    "method",
    "quality",
    "time_ms",
    "warnings",
    "error",
    "source_path",
    "output_path",
]


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


@app.get("/api/report")
def export_report(format: str = Query("json", pattern="^(json|csv)$")) -> Any:
    rows = queue.report()
    if format == "json":
        return {"report": rows}
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=REPORT_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="image-lab-report-{_stamp()}.csv"'},
    )


_STORED_FORMATS = {"JPEG", "PNG", "WEBP", "AVIF", "GIF"}


@app.get("/api/export/zip")
def export_zip(ids: Optional[str] = None) -> FileResponse:
    wanted = set(ids.split(",")) if ids else None
    outputs: List[Tuple[Path, str]] = []
    for item in queue.all_items():
        if wanted is not None and item.id not in wanted:
            continue
        result = item.result
        if result and result.success and result.output_path and Path(result.output_path).is_file():
            outputs.append((Path(result.output_path), result.format))
    if not outputs:
        raise HTTPException(404, "No processed images to export yet")

    fd, tmp_name = tempfile.mkstemp(prefix="image-lab-", suffix=".zip")
    tmp = Path(tmp_name)
    used: set[str] = set()
    try:
        with open(fd, "wb") as handle, zipfile.ZipFile(handle, "w") as archive:
            for path, fmt in outputs:
                name = path.name
                stem, suffix = path.stem, path.suffix
                index = 1
                while name.lower() in used:
                    name = f"{stem}-{index}{suffix}"
                    index += 1
                used.add(name.lower())
                compression = zipfile.ZIP_STORED if fmt in _STORED_FORMATS else zipfile.ZIP_DEFLATED
                archive.write(path, name, compress_type=compression)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return FileResponse(
        tmp,
        media_type="application/zip",
        filename=f"image-lab-{_stamp()}.zip",
        background=BackgroundTask(tmp.unlink, missing_ok=True),
    )


# ── native integration ───────────────────────────────────────────────────
def _known_paths() -> set[str]:
    known = {str(config.DEFAULT_OUTPUT_DIR)}
    for item in queue.all_items():
        known.add(item.path)
        known.add(str(Path(item.path).parent))
        if item.result and item.result.output_path:
            known.add(item.result.output_path)
            known.add(str(Path(item.result.output_path).parent))
    return known


@app.post("/api/system/reveal")
def reveal(req: RevealRequest) -> Dict[str, Any]:
    target = Path(req.path).expanduser()
    if str(target) not in _known_paths():
        raise HTTPException(403, "Can only reveal images and folders Image Lab is working with")
    if target == config.DEFAULT_OUTPUT_DIR:
        target.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        raise HTTPException(404, "That file or folder no longer exists")
    if sys.platform == "darwin":
        args = ["open", "-R", str(target)] if target.is_file() else ["open", str(target)]
    elif sys.platform.startswith("win"):
        args = ["explorer", f"/select,{target}"] if target.is_file() else ["explorer", str(target)]
    else:
        args = ["xdg-open", str(target if target.is_dir() else target.parent)]
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise HTTPException(500, f"Couldn't open Finder: {exc}") from exc
    return {"ok": True}


_PICK_SCRIPTS = {
    "folder": 'choose folder with prompt "Add a folder of images" with multiple selections allowed',
    "files": 'choose file with prompt "Add images" of type {"public.image"} with multiple selections allowed',
    "output": 'choose folder with prompt "Save processed images to…"',
}


@app.post("/api/system/pick")
def pick(req: PickRequest) -> Dict[str, Any]:
    if sys.platform != "darwin":
        raise HTTPException(501, "Native file dialogs are only available on macOS")
    script = (
        f"set chosen to ({_PICK_SCRIPTS[req.kind]})\n"
        "if class of chosen is not list then set chosen to {chosen}\n"
        'set out to ""\n'
        "repeat with f in chosen\n"
        "set out to out & POSIX path of f & linefeed\n"
        "end repeat\n"
        "return out"
    )
    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {"paths": [], "cancelled": True}
    if result.returncode != 0:
        if "-128" in result.stderr:
            return {"paths": [], "cancelled": True}
        raise HTTPException(500, result.stderr.strip() or "Dialog failed")
    paths = [line.rstrip("/") or "/" for line in result.stdout.splitlines() if line.strip()]
    return {"paths": paths, "cancelled": not paths}


# ── frontend ──────────────────────────────────────────────────────────────
class FrontendFiles(StaticFiles):
    async def get_response(self, path: str, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        if path.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response


if config.FRONTEND_DIR.is_dir() and (config.FRONTEND_DIR / "index.html").is_file():
    app.mount("/", FrontendFiles(directory=str(config.FRONTEND_DIR), html=True), name="frontend")
else:

    @app.get("/", include_in_schema=False)
    def frontend_missing() -> HTMLResponse:
        return HTMLResponse(
            "<h1>Image Lab</h1><p>The UI isn't built yet. Run <code>./start.sh</code> "
            "or <code>cd frontend &amp;&amp; npm run build</code>.</p>",
            status_code=503,
        )

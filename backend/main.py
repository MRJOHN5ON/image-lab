"""Image Lab — FastAPI backend."""

from __future__ import annotations

import base64
import io
import json
import os
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from processor.compress import jpegtran_available
from processor.pipeline import HEIF_AVAILABLE, ProcessingSettings, process_image
from batch_queue import ImageQueue

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
PRESETS_FILE = ROOT_DIR / "presets" / "default.json"
CUSTOM_PRESETS_FILE = ROOT_DIR / "presets" / "custom.json"
UPLOAD_DIR = ROOT_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Image Lab", version="1.0.0")
queue = ImageQueue()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PathsRequest(BaseModel):
    paths: List[str]
    recursive: bool = True


class ProcessRequest(BaseModel):
    settings: Dict[str, Any]
    item_ids: Optional[List[str]] = None


class PreviewRequest(BaseModel):
    path: str
    settings: Dict[str, Any]


class PresetSaveRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    settings: Dict[str, Any]


def _load_presets() -> List[Dict[str, Any]]:
    presets: List[Dict[str, Any]] = []
    if PRESETS_FILE.exists():
        presets.extend(json.loads(PRESETS_FILE.read_text()).get("presets", []))
    if CUSTOM_PRESETS_FILE.exists():
        presets.extend(json.loads(CUSTOM_PRESETS_FILE.read_text()).get("presets", []))
    return presets


def _save_custom_presets(presets: List[Dict[str, Any]]) -> None:
    CUSTOM_PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CUSTOM_PRESETS_FILE.write_text(json.dumps({"presets": presets}, indent=2))


@app.get("/api/health")
def health() -> Dict[str, Any]:
    from PIL import __version__ as pillow_version

    avif_supported = False
    try:
        from PIL import features

        avif_supported = features.check("avif")
    except Exception:
        pass

    return {
        "status": "ok",
        "pillow_version": pillow_version,
        "jpegtran_available": jpegtran_available(),
        "heif_available": HEIF_AVAILABLE,
        "avif_supported": avif_supported,
        "cpu_count": os.cpu_count() or 4,
    }


@app.get("/api/queue")
def list_queue() -> Dict[str, Any]:
    items = queue.list_items()
    total_size = sum(i["original_size"] for i in items)
    return {
        "items": items,
        "count": len(items),
        "total_size": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
    }


@app.post("/api/queue")
async def add_to_queue(files: List[UploadFile] = File(...)) -> Dict[str, Any]:
    paths: List[str] = []
    for f in files:
        dest = UPLOAD_DIR / (f.filename or "upload")
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = await f.read()
        dest.write_bytes(content)
        paths.append(str(dest))
    return _add_paths(paths, recursive=True)


@app.post("/api/queue/paths")
def add_paths(req: PathsRequest) -> Dict[str, Any]:
    return _add_paths(req.paths, req.recursive)


def _add_paths(paths: List[str], recursive: bool) -> Dict[str, Any]:
    if not paths:
        raise HTTPException(400, "No files or paths provided")
    added = queue.add_paths(paths, recursive=recursive)
    if len(added) > 500:
        pass  # frontend shows warning
    return {
        "added": len(added),
        "items": [a.to_dict() for a in added],
        "queue": queue.list_items(),
    }


@app.delete("/api/queue")
def clear_queue() -> Dict[str, str]:
    if queue.batch.running:
        raise HTTPException(409, "Cannot clear queue while processing")
    queue.clear()
    return {"status": "cleared"}


@app.delete("/api/queue/{item_id}")
def remove_queue_item(item_id: str) -> Dict[str, str]:
    if not queue.remove_item(item_id):
        raise HTTPException(404, "Item not found")
    return {"status": "removed"}


@app.post("/api/process")
def start_process(req: ProcessRequest) -> Dict[str, Any]:
    settings = ProcessingSettings.from_dict(req.settings)
    if settings.overwrite:
        pass  # frontend handles confirmation
    try:
        queue.start_batch(settings, req.item_ids)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return {"status": "started", "progress": queue.status()}


@app.post("/api/process/cancel")
def cancel_process() -> Dict[str, str]:
    queue.cancel_batch()
    return {"status": "cancelling"}


@app.get("/api/process/status")
def process_status() -> Dict[str, Any]:
    return queue.status()


@app.post("/api/preview")
def preview(req: PreviewRequest) -> Dict[str, Any]:
    settings = ProcessingSettings.from_dict(req.settings)
    result = process_image(req.path, settings, return_bytes=True)
    if not result.success:
        raise HTTPException(400, result.error or "Preview failed")

    before_b64 = None
    try:
        from PIL import Image

        img = Image.open(req.path)
        if settings.auto_rotate:
            from PIL import ImageOps

            img = ImageOps.exif_transpose(img)
        img.thumbnail((800, 800))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        before_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        pass

    after_b64 = None
    if result.output_data:
        after_b64 = base64.b64encode(result.output_data).decode("ascii")

    return {
        "before": before_b64,
        "after": after_b64,
        "after_format": result.format.lower(),
        "original_size": result.original_size,
        "new_size": result.new_size,
        "original_dimensions": list(result.original_dimensions),
        "new_dimensions": list(result.new_dimensions),
        "quality_used": result.quality_used,
        "method_used": result.method_used,
        "processing_time_ms": result.processing_time_ms,
        "savings_percent": result.savings_percent,
        "warning": result.warning,
        "steps": result.steps,
    }


@app.get("/api/presets")
def get_presets() -> Dict[str, Any]:
    return {"presets": _load_presets()}


@app.post("/api/presets")
def save_preset(req: PresetSaveRequest) -> Dict[str, Any]:
    custom: List[Dict[str, Any]] = []
    if CUSTOM_PRESETS_FILE.exists():
        custom = json.loads(CUSTOM_PRESETS_FILE.read_text()).get("presets", [])

    existing = next((i for i, p in enumerate(custom) if p["id"] == req.id), None)
    entry = {
        "id": req.id,
        "name": req.name,
        "description": req.description,
        "settings": req.settings,
        "custom": True,
    }
    if existing is not None:
        custom[existing] = entry
    else:
        custom.append(entry)

    _save_custom_presets(custom)
    return {"status": "saved", "preset": entry}


@app.get("/api/report")
def export_report(format: str = "json") -> Any:
    report = queue.export_report()
    if format == "csv":
        import csv
        from io import StringIO

        output = StringIO()
        if report:
            writer = csv.DictWriter(
                output,
                fieldnames=[
                    "filename",
                    "path",
                    "original_size",
                    "new_size",
                    "savings_percent",
                    "method_used",
                    "quality_used",
                ],
            )
            writer.writeheader()
            for row in report:
                writer.writerow({k: row.get(k) for k in writer.fieldnames})
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=image-lab-report.csv"},
        )
    return {"report": report}


@app.post("/api/export/zip")
def export_zip() -> FileResponse:
    items = queue.list_items()
    done = [i for i in items if i.get("status") == "done" and i.get("result", {}).get("output_path")]
    if not done:
        raise HTTPException(400, "No processed files to zip")

    zip_path = UPLOAD_DIR / "export.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in done:
            out = item["result"]["output_path"]
            if out and Path(out).exists():
                zf.write(out, Path(out).name)

    return FileResponse(zip_path, filename="image-lab-export.zip", media_type="application/zip")


# Serve frontend in production
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")

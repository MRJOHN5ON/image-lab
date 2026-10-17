"""Native bridge exposed to the web UI as window.pywebview.api.*"""

from __future__ import annotations

import os
import shutil
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

APP_SUPPORT = Path.home() / "Library" / "Application Support" / "Image Lab"
LAST_DIR_FILE = APP_SUPPORT / "last_save_directory"

IMAGE_TYPES = ("Images (*.jpg;*.jpeg;*.jpe;*.jfif;*.png;*.webp;*.avif;*.heic;*.heif;*.tif;*.tiff;*.gif;*.bmp)",)


def _dialog(kind: str):
    import webview

    file_dialog = getattr(webview, "FileDialog", None)
    if file_dialog is not None:
        return getattr(file_dialog, kind)
    return getattr(webview, f"{kind}_DIALOG")


def _window():
    import webview

    return webview.active_window() or (webview.windows[0] if webview.windows else None)


def _last_directory() -> str:
    try:
        last = LAST_DIR_FILE.read_text(encoding="utf-8").strip()
        if last and os.path.isdir(last):
            return last
    except OSError:
        pass
    downloads = Path.home() / "Downloads"
    return str(downloads if downloads.is_dir() else Path.home())


def _remember(path: str) -> None:
    directory = os.path.dirname(path)
    if os.path.isdir(directory):
        try:
            APP_SUPPORT.mkdir(parents=True, exist_ok=True)
            LAST_DIR_FILE.write_text(directory, encoding="utf-8")
        except OSError:
            pass


def _as_list(result: Any) -> List[str]:
    if not result:
        return []
    if isinstance(result, (list, tuple)):
        return [str(p) for p in result]
    return [str(result)]


class NativeApi:
    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")

    def pick(self, kind: str) -> Dict[str, Any]:
        """kind: 'files' | 'folder' | 'output'. Returns {'paths': [...]} (empty when cancelled)."""
        window = _window()
        if window is None:
            return {"paths": [], "error": "App window is not available."}
        try:
            if kind == "files":
                result = window.create_file_dialog(_dialog("OPEN"), allow_multiple=True, file_types=IMAGE_TYPES)
            else:
                result = window.create_file_dialog(_dialog("FOLDER"), allow_multiple=kind == "folder")
        except Exception as exc:  # noqa: BLE001
            print(f"Open dialog failed: {exc}", flush=True)
            return {"paths": [], "error": "Could not open the dialog."}
        return {"paths": _as_list(result)}

    def _save_dialog(self, filename: str) -> str | None:
        window = _window()
        if window is None:
            return None
        result = window.create_file_dialog(_dialog("SAVE"), directory=_last_directory(), save_filename=filename or "")
        paths = _as_list(result)
        if not paths:
            return None
        path = paths[0]
        ext = os.path.splitext(filename)[1]
        if ext and not path.lower().endswith(ext.lower()):
            path += ext
        return path

    def save_url(self, url: str, filename: str) -> Dict[str, Any]:
        """Save a same-origin URL (export ZIP, report, single output) through the macOS save panel."""
        if not url.startswith("/"):
            return {"ok": False, "error": "Only app files can be saved."}
        try:
            path = self._save_dialog(filename)
        except Exception as exc:  # noqa: BLE001
            print(f"Save dialog failed: {exc}", flush=True)
            return {"ok": False, "error": "Could not open the save dialog."}
        if not path:
            return {"ok": False, "cancelled": True}
        tmp = f"{path}.partial"
        try:
            with urllib.request.urlopen(self._base_url + url, timeout=600) as response, open(tmp, "wb") as out:
                shutil.copyfileobj(response, out, length=1024 * 1024)
            os.replace(tmp, path)
        except Exception as exc:  # noqa: BLE001
            try:
                os.unlink(tmp)
            except OSError:
                pass
            print(f"Save failed: {exc}", flush=True)
            return {"ok": False, "error": f"Could not save the file: {exc}"}
        _remember(path)
        return {"ok": True, "path": path}

    def save_text(self, text: str, filename: str) -> Dict[str, Any]:
        try:
            path = self._save_dialog(filename)
        except Exception as exc:  # noqa: BLE001
            print(f"Save dialog failed: {exc}", flush=True)
            return {"ok": False, "error": "Could not open the save dialog."}
        if not path:
            return {"ok": False, "cancelled": True}
        try:
            Path(path).write_text(text, encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": f"Could not save the file: {exc}"}
        _remember(path)
        return {"ok": True, "path": path}

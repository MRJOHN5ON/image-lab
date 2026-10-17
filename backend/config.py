"""Runtime configuration. Read once at import; the packaged launcher sets env vars first."""

from __future__ import annotations

import os
import sys
from pathlib import Path

__version__ = "2.0.0"

APP_NAME = "Image Lab"
APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent

PACKAGED = os.environ.get("IMAGE_LAB_PACKAGED") == "1"
VERSION = os.environ.get("IMAGE_LAB_VERSION") or __version__


def _path_env(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else default


if PACKAGED and sys.platform == "darwin":
    _default_data = Path.home() / "Library" / "Application Support" / APP_NAME
else:
    _default_data = ROOT_DIR / "data"

DATA_DIR = _path_env("IMAGE_LAB_DATA_DIR", _default_data)
UPLOAD_DIR = DATA_DIR / "uploads"
CUSTOM_PRESETS_FILE = DATA_DIR / "presets.json"
BUILTIN_PRESETS_FILE = _path_env("IMAGE_LAB_PRESETS_FILE", ROOT_DIR / "presets" / "default.json")
FRONTEND_DIR = _path_env("IMAGE_LAB_FRONTEND_DIR", ROOT_DIR / "frontend" / "dist")

# Where results of browser-uploaded files go (they have no folder of their own on disk).
DEFAULT_OUTPUT_DIR = _path_env("IMAGE_LAB_OUTPUT_DIR", Path.home() / "Pictures" / APP_NAME)

MAX_UPLOAD_BYTES = int(os.environ.get("IMAGE_LAB_MAX_UPLOAD_MB", "1024")) * 1024 * 1024
WORKERS = int(os.environ.get("IMAGE_LAB_WORKERS", "0") or 0) or None
WARM_WORKERS = os.environ.get("IMAGE_LAB_WARM_WORKERS", "1") != "0"

for directory in (DATA_DIR, UPLOAD_DIR):
    directory.mkdir(parents=True, exist_ok=True)

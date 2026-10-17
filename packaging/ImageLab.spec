# PyInstaller spec for Image Lab.app — bundles Python, so users need nothing installed.
# Built by scripts/build_release.sh; expects frontend/dist, build/VERSION and build/jpegtran/jpegtran.

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent
VERSION = os.environ.get("IMAGE_LAB_VERSION", "0.0.0-dev")
FOLDER_ACCESS = "Image Lab reads the photos you add and saves the processed copies next to them."

datas = [
    (str(ROOT / "frontend" / "dist"), "frontend/dist"),
    (str(ROOT / "presets" / "default.json"), "presets"),
    (str(ROOT / "build" / "VERSION"), "."),
]
binaries = [(str(ROOT / "build" / "jpegtran" / "jpegtran"), "bin")]
hiddenimports = [
    "main",
    "config",
    "batch_queue",
    "workers",
    "display",
    "native_api",
    "macos_about",
    *collect_submodules("processor"),
]

for package in ("pillow_heif", "webview", "uvicorn"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "backend"), str(ROOT / "packaging")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "gi", "matplotlib", "IPython", "pytest", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ImageLab",
    console=False,
    upx=False,
    target_arch="arm64",
    codesign_identity=None,
)

coll = COLLECT(exe, a.binaries, a.datas, name="ImageLab", upx=False)

app = BUNDLE(
    coll,
    name="Image Lab.app",
    icon=str(ROOT / "packaging" / "ImageLab.icns"),
    bundle_identifier="com.imagelab.app",
    version=VERSION,
    info_plist={
        "CFBundleName": "Image Lab",
        "CFBundleDisplayName": "Image Lab",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "12.0",
        "LSApplicationCategoryType": "public.app-category.photography",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
        "NSDesktopFolderUsageDescription": FOLDER_ACCESS,
        "NSDocumentsFolderUsageDescription": FOLDER_ACCESS,
        "NSDownloadsFolderUsageDescription": FOLDER_ACCESS,
        "NSRemovableVolumesUsageDescription": FOLDER_ACCESS,
        "NSNetworkVolumesUsageDescription": FOLDER_ACCESS,
        "NSHumanReadableCopyright": "© 2026 Image Lab. MIT License. Your images never leave your Mac.",
    },
)

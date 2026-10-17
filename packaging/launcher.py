#!/usr/bin/env python3
"""Image Lab macOS app launcher: local engine + native window."""

from __future__ import annotations

import multiprocessing
import os
import socket
import sys
import threading
import time
from pathlib import Path

APP_NAME = "Image Lab"


def resources_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def pick_port() -> int:
    preferred = int(os.environ.get("IMAGE_LAB_PORT", "8766") or "8766")
    for port in (preferred, 0):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", port))
                return sock.getsockname()[1]
        except OSError:
            continue
    raise SystemExit("Could not bind a local port for Image Lab")


def read_version(root: Path) -> str:
    try:
        return (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "dev"


def configure_environment(root: Path) -> None:
    """main.py reads these at import time, and worker processes inherit them."""
    frozen = getattr(sys, "frozen", False)
    if frozen:
        frontend = root / "frontend" / "dist"
        presets = root / "presets" / "default.json"
        jpegtran = root / "bin" / "jpegtran"
    else:
        frontend = root / "frontend" / "dist"
        presets = root / "presets" / "default.json"
        jpegtran = root / "build" / "jpegtran" / "jpegtran"
        sys.path.insert(0, str(root / "backend"))
    if not (frontend / "index.html").is_file():
        raise SystemExit(f"Missing frontend build: {frontend}")

    os.environ["IMAGE_LAB_PACKAGED"] = "1"
    os.environ["IMAGE_LAB_FRONTEND_DIR"] = str(frontend)
    os.environ["IMAGE_LAB_PRESETS_FILE"] = str(presets)
    os.environ["IMAGE_LAB_VERSION"] = read_version(root)
    if jpegtran.is_file():
        os.environ["IMAGE_LAB_JPEGTRAN"] = str(jpegtran)
    sys.path.insert(0, str(Path(__file__).resolve().parent))


def redirect_output_to_log() -> Path:
    """A windowed app has no terminal; keep output where the README says it is."""
    log_dir = Path.home() / "Library" / "Logs" / APP_NAME
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "image-lab.log"
    if path.exists() and path.stat().st_size > 5 * 1024 * 1024:
        path.replace(path.with_suffix(".log.1"))
    log = open(path, "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stderr = log
    return path


def run_server(port: int) -> None:
    import uvicorn

    from main import app

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=1)
    uvicorn.Server(config).run()


def wait_for_server(port: int, timeout: float = 45.0) -> None:
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.0) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.1)
    raise SystemExit(f"Image Lab engine did not start on port {port}")


def window_geometry() -> tuple[int, int]:
    try:
        from AppKit import NSScreen

        visible = NSScreen.mainScreen().visibleFrame()
        return min(1480, int(visible.size.width * 0.92)), min(940, int(visible.size.height * 0.92))
    except Exception:  # noqa: BLE001
        return 1360, 860


def stop_workers() -> None:
    for child in multiprocessing.active_children():
        child.terminate()


def install_native_drop(window) -> None:
    """Hand real paths of dropped files to the page so they're processed in place, not copied."""
    import json

    try:
        from webview.dom import DOMEventHandler
    except ImportError:
        return

    def on_drop(event) -> None:
        files = (event.get("dataTransfer") or {}).get("files") or []
        paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        if paths:
            window.evaluate_js(f"window.__imageLabNativeDrop && window.__imageLabNativeDrop({json.dumps(paths)})")

    try:
        window.dom.document.events.drop += DOMEventHandler(on_drop, True, False)
    except Exception as exc:  # noqa: BLE001
        print(f"Native drop unavailable: {exc}", flush=True)


def smoke_test(port: int) -> int:
    """Headless end-to-end check of a built bundle: engine, worker processes, jpegtran."""
    import json
    import tempfile
    import urllib.request

    from PIL import Image, ImageDraw

    base = f"http://127.0.0.1:{port}"

    def call(method: str, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, method=method, headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read())

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "smoke.jpg"
        img = Image.new("RGB", (1600, 1200), (40, 90, 160))
        ImageDraw.Draw(img).ellipse((200, 200, 1200, 1000), fill=(240, 200, 60))
        img.save(src, quality=95)
        health = call("GET", "/api/health")
        call("POST", "/api/queue/paths", {"paths": [str(src)]})
        call("POST", "/api/process", {"settings": {"compress_mode": "quality", "quality": 70}})
        deadline = time.time() + 60
        status = call("GET", "/api/process/status")
        while status["running"] and time.time() < deadline:
            time.sleep(0.2)
            status = call("GET", "/api/process/status")
        outputs = list((Path(tmp) / "processed").glob("*.jpg"))
    ok = status["done"] == 1 and len(outputs) == 1 and health["jpegtran_available"] and health["heif_available"]
    print(
        f"smoke test {'passed' if ok else 'FAILED'}: done={status['done']} failed={status['failed']} "
        f"outputs={len(outputs)} jpegtran={health['jpegtran_available']} heif={health['heif_available']} "
        f"version={health['version']}",
        flush=True,
    )
    return 0 if ok else 1


def main() -> None:
    smoke = os.environ.get("IMAGE_LAB_SMOKE_TEST") == "1"
    log_path = redirect_output_to_log() if getattr(sys, "frozen", False) and not smoke else None
    if sys.platform == "darwin":
        sys.argv[0] = APP_NAME

    root = resources_dir()
    configure_environment(root)
    port = pick_port()
    url = f"http://127.0.0.1:{port}"
    print(f"{APP_NAME} {os.environ['IMAGE_LAB_VERSION']} starting at {url}" + (f" (log: {log_path})" if log_path else ""), flush=True)

    threading.Thread(target=run_server, args=(port,), daemon=True, name="engine").start()
    wait_for_server(port)

    if smoke:
        code = 1
        try:
            code = smoke_test(port)
        finally:
            stop_workers()
            os._exit(code)

    import webview

    from macos_about import configure_app_menu, patch_bundle_display_name
    from native_api import NativeApi

    patch_bundle_display_name(APP_NAME)
    width, height = window_geometry()
    window = webview.create_window(
        APP_NAME,
        url,
        width=width,
        height=height,
        min_size=(1080, 680),
        background_color="#0d0e11",
        text_select=False,
        js_api=NativeApi(url),
    )

    def on_loaded() -> None:
        configure_app_menu(APP_NAME)
        install_native_drop(window)

    def on_closing() -> None:
        # pywebview waits on the engine thread at quit, and keep-alive connections never
        # drain, so macOS would report an unexpected quit. Exit directly instead.
        print(f"{APP_NAME} quitting", flush=True)
        stop_workers()
        os._exit(0)

    window.events.loaded += on_loaded
    window.events.closing += on_closing
    webview.start(lambda: configure_app_menu(APP_NAME))
    stop_workers()
    os._exit(0)


if __name__ == "__main__":
    # Worker processes start by re-running this executable; this hands them off to
    # multiprocessing before any app or window code runs.
    multiprocessing.freeze_support()
    main()

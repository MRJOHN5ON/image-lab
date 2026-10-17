"""Process pools for image work.

Pillow holds the GIL through much of its encoding, so threads serialise and starve the
API. Separate processes use every core and keep the server responsive.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import threading
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any, Dict, Optional

log = logging.getLogger("imagelab.workers")

__all__ = ["BrokenProcessPool", "WorkerPool"]


def _init_worker() -> None:
    import signal

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        os.nice(4)
    except OSError:
        pass


def _noop() -> int:
    return os.getpid()


def _process(path: str, settings: Any, kwargs: Dict[str, Any]) -> Any:
    from processor.pipeline import process_image

    return process_image(path, settings, **kwargs)


def _preview(path: str, settings: Any) -> Dict[str, Any]:
    from display import displayable
    from processor.pipeline import process_image

    result = process_image(path, settings, return_bytes=True)
    out: Dict[str, Any] = {"result": result}
    if result.success:
        out["shown"], out["media_type"], out["display_size"] = displayable(
            result.output_data or b"", result.format, tuple(result.new_dimensions)
        )
    result.output_data = None
    return out


class WorkerPool:
    def __init__(self, size: int, name: str):
        self.size = max(1, size)
        self.name = name
        self._executor: Optional[ProcessPoolExecutor] = None
        self._lock = threading.Lock()

    def _get(self) -> ProcessPoolExecutor:
        with self._lock:
            if self._executor is None:
                self._executor = ProcessPoolExecutor(
                    max_workers=self.size,
                    mp_context=multiprocessing.get_context("spawn"),
                    initializer=_init_worker,
                )
            return self._executor

    def _reset(self, broken: ProcessPoolExecutor) -> None:
        with self._lock:
            if self._executor is broken:
                self._executor = None
        broken.shutdown(wait=False, cancel_futures=True)

    def warm(self) -> None:
        """Start the worker processes now so the first job doesn't pay for interpreter startup."""
        try:
            executor = self._get()
            for _ in range(self.size):
                executor.submit(_noop)
        except Exception:  # noqa: BLE001
            log.exception("Could not start %s workers", self.name)

    def _call(self, fn: Any, *args: Any) -> Any:
        executor = self._get()
        try:
            return executor.submit(fn, *args).result()
        except BrokenProcessPool:
            log.error("%s worker crashed; restarting the pool", self.name)
            self._reset(executor)
            raise

    def run(self, path: str, settings: Any, **kwargs: Any) -> Any:
        """Process one image in a worker. Raises BrokenProcessPool if a worker died."""
        return self._call(_process, path, settings, kwargs)

    def preview(self, path: str, settings: Any) -> Dict[str, Any]:
        """Render a preview plus its browser rendition: {'result', 'shown', 'media_type', 'display_size'}."""
        return self._call(_preview, path, settings)

    def shutdown(self) -> None:
        with self._lock:
            executor, self._executor = self._executor, None
        if executor:
            executor.shutdown(wait=False, cancel_futures=True)

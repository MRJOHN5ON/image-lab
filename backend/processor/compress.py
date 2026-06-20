"""JPEG compression with lossless jpegtran + binary search quality."""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image


@dataclass
class CompressResult:
    data: bytes
    quality: Optional[int]
    method: str  # "copy" | "lossless" | "reencode"
    format: str = "JPEG"


def jpegtran_available() -> bool:
    return shutil.which("jpegtran") is not None


def _run_jpegtran(input_path: Path, output_path: Path) -> bool:
    """Run jpegtran -optimize -progressive -copy none."""
    if not jpegtran_available():
        return False
    try:
        result = subprocess.run(
            [
                "jpegtran",
                "-optimize",
                "-progressive",
                "-copy",
                "none",
                "-outfile",
                str(output_path),
                str(input_path),
            ],
            capture_output=True,
            timeout=120,
        )
        return result.returncode == 0 and output_path.exists()
    except (subprocess.SubprocessError, OSError):
        return False


def _save_jpeg(
    img: Image.Image,
    quality: int,
    *,
    progressive: bool = True,
    subsampling: int = 0,
    optimize: bool = True,
) -> bytes:
    buf = io.BytesIO()
    img.save(
        buf,
        format="JPEG",
        quality=quality,
        progressive=progressive,
        subsampling=subsampling,
        optimize=optimize,
    )
    return buf.getvalue()


def compress_to_target_size(
    img: Image.Image,
    limit_bytes: int,
    *,
    lossless_first: bool = True,
    progressive: bool = True,
    subsampling: int = 0,
    optimize: bool = True,
    source_path: Optional[Path] = None,
) -> CompressResult:
    """
    Compress JPEG to target max size.
    1. Copy as-is if already under limit (when source_path provided)
    2. Try jpegtran lossless optimization
    3. Binary search quality 1-100 with subsampling=0
    """
    if source_path and source_path.suffix.lower() in (".jpg", ".jpeg"):
        original = source_path.read_bytes()
        if len(original) <= limit_bytes:
            return CompressResult(
                data=original,
                quality=None,
                method="copy",
            )

        if lossless_first and jpegtran_available():
            with tempfile.TemporaryDirectory() as tmp:
                tmp_in = Path(tmp) / "in.jpg"
                tmp_out = Path(tmp) / "out.jpg"
                tmp_in.write_bytes(original)
                if _run_jpegtran(tmp_in, tmp_out):
                    lossless_data = tmp_out.read_bytes()
                    if len(lossless_data) <= limit_bytes:
                        return CompressResult(
                            data=lossless_data,
                            quality=None,
                            method="lossless",
                        )

    work = img.convert("RGB") if img.mode not in ("RGB", "L") else img

    lo, hi = 1, 100
    best_data: Optional[bytes] = None
    best_q = 1

    while lo <= hi:
        mid = (lo + hi) // 2
        data = _save_jpeg(
            work,
            mid,
            progressive=progressive,
            subsampling=subsampling,
            optimize=optimize,
        )
        if len(data) <= limit_bytes:
            best_data = data
            best_q = mid
            lo = mid + 1
        else:
            hi = mid - 1

    if best_data is None:
        best_data = _save_jpeg(
            work,
            1,
            progressive=progressive,
            subsampling=subsampling,
            optimize=optimize,
        )
        best_q = 1

    return CompressResult(
        data=best_data,
        quality=best_q,
        method="reencode",
    )


def compress_to_quality(
    img: Image.Image,
    quality: int,
    *,
    progressive: bool = True,
    subsampling: int = 0,
    optimize: bool = True,
    lossless_first: bool = False,
    source_path: Optional[Path] = None,
) -> CompressResult:
    if lossless_first and source_path and source_path.suffix.lower() in (".jpg", ".jpeg"):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_in = Path(tmp) / "in.jpg"
            tmp_out = Path(tmp) / "out.jpg"
            tmp_in.write_bytes(source_path.read_bytes())
            if _run_jpegtran(tmp_in, tmp_out):
                return CompressResult(
                    data=tmp_out.read_bytes(),
                    quality=None,
                    method="lossless",
                )

    work = img.convert("RGB") if img.mode not in ("RGB", "L") else img
    data = _save_jpeg(
        work,
        quality,
        progressive=progressive,
        subsampling=subsampling,
        optimize=optimize,
    )
    return CompressResult(data=data, quality=quality, method="reencode")


def compress_png(img: Image.Image, compression_level: int = 6, palette: bool = False) -> bytes:
    buf = io.BytesIO()
    work = img
    if palette and img.mode in ("RGBA", "RGB", "P"):
        work = img.convert("P", palette=Image.ADAPTIVE, colors=256)
    work.save(buf, format="PNG", compress_level=compression_level, optimize=True)
    return buf.getvalue()


def compress_webp(
    img: Image.Image,
    quality: int = 80,
    *,
    lossless: bool = False,
    method: int = 4,
) -> bytes:
    buf = io.BytesIO()
    img.save(
        buf,
        format="WEBP",
        quality=quality,
        lossless=lossless,
        method=method,
    )
    return buf.getvalue()


def compress_avif(img: Image.Image, quality: int = 80, speed: int = 6) -> bytes:
    buf = io.BytesIO()
    work = img.convert("RGB") if img.mode not in ("RGB", "RGBA") else img
    save_kwargs: dict = {"format": "AVIF", "quality": quality}
    try:
        save_kwargs["speed"] = speed
        work.save(buf, **save_kwargs)
    except Exception:
        work.save(buf, format="AVIF", quality=quality)
    return buf.getvalue()

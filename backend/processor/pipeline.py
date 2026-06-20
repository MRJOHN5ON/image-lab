"""Image processing pipeline — chains all operations."""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image, ImageOps

from .compress import (
    compress_avif,
    compress_png,
    compress_to_quality,
    compress_to_target_size,
    compress_webp,
)
from .convert import convert_format, output_extension
from .resize import FitMode, resize_image
from .upscale import upscale_image

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF_AVAILABLE = True
except ImportError:
    HEIF_AVAILABLE = False


SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
}


@dataclass
class ProcessingSettings:
    # Operation toggles
    compress_enabled: bool = True
    resize_enabled: bool = False
    upscale_enabled: bool = False
    convert_enabled: bool = False
    strip_exif: bool = True
    keep_icc: bool = False
    auto_rotate: bool = True
    trim_transparent: bool = False

    # Compress
    compress_mode: str = "target_size"  # target_size | quality | lossless_first
    target_size_mb: float = 12.0
    target_size_kb: Optional[float] = None
    quality: int = 85
    lossless_first: bool = True
    progressive: bool = True
    subsampling: int = 0
    optimize: bool = True
    png_compression: int = 6
    png_palette: bool = False
    webp_quality: int = 80
    webp_lossless: bool = False
    webp_method: int = 4
    avif_quality: int = 80
    avif_speed: int = 6

    # Resize
    max_width: Optional[int] = None
    max_height: Optional[int] = None
    exact_width: Optional[int] = None
    exact_height: Optional[int] = None
    scale_percent: Optional[float] = None
    fit_mode: str = "contain"
    resample: str = "lanczos"

    # Upscale
    upscale_factor: float = 2.0
    upscale_method: str = "standard"

    # Convert
    output_format: str = "keep"
    bg_color: str = "#ffffff"

    # Output
    output_dir: Optional[str] = None
    naming_suffix: str = "_processed"
    naming_prefix: str = ""
    mirror_structure: bool = False
    overwrite: bool = False
    skip_existing: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProcessingSettings":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    def to_dict(self) -> Dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in self.__dataclass_fields__.values()}


@dataclass
class ProcessResult:
    success: bool
    output_path: Optional[str] = None
    output_data: Optional[bytes] = None
    original_size: int = 0
    new_size: int = 0
    original_dimensions: tuple = (0, 0)
    new_dimensions: tuple = (0, 0)
    format: str = ""
    quality_used: Optional[int] = None
    method_used: str = ""
    processing_time_ms: float = 0
    savings_percent: float = 0
    warning: Optional[str] = None
    error: Optional[str] = None
    steps: List[str] = field(default_factory=list)


def _target_bytes(settings: ProcessingSettings) -> int:
    if settings.target_size_kb is not None:
        return int(settings.target_size_kb * 1024)
    return int(settings.target_size_mb * 1024 * 1024)


def _strip_metadata(img: Image.Image, keep_icc: bool) -> Image.Image:
    data = list(img.getdata())
    icc = img.info.get("icc_profile") if keep_icc else None
    clean = Image.new(img.mode, img.size)
    clean.putdata(data)
    if icc:
        clean.info["icc_profile"] = icc
    return clean


def _trim_transparent(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        bbox = img.getbbox()
        if bbox:
            return img.crop(bbox)
    return img


def open_image(path: Path) -> Image.Image:
    ext = path.suffix.lower()
    if ext in (".heic", ".heif") and not HEIF_AVAILABLE:
        raise ValueError("HEIC format requires pillow-heif. Install with: pip install pillow-heif")
    return Image.open(path)


def _encode_image(img: Image.Image, fmt: str, settings: ProcessingSettings, source_path: Path) -> tuple[bytes, Optional[int], str]:
    fmt = fmt.upper()
    if fmt in ("JPEG", "JPG"):
        if settings.compress_mode == "target_size":
            limit = _target_bytes(settings)
            result = compress_to_target_size(
                img,
                limit,
                lossless_first=settings.lossless_first,
                progressive=settings.progressive,
                subsampling=settings.subsampling,
                optimize=settings.optimize,
                source_path=source_path,
            )
            return result.data, result.quality, result.method
        if settings.compress_mode == "lossless_first":
            result = compress_to_quality(
                img,
                settings.quality,
                progressive=settings.progressive,
                subsampling=settings.subsampling,
                optimize=settings.optimize,
                lossless_first=True,
                source_path=source_path,
            )
            return result.data, result.quality, result.method
        result = compress_to_quality(
            img,
            settings.quality,
            progressive=settings.progressive,
            subsampling=settings.subsampling,
            optimize=settings.optimize,
            source_path=source_path,
        )
        return result.data, result.quality, result.method

    if fmt == "PNG":
        data = compress_png(img, settings.png_compression, settings.png_palette)
        return data, None, "png_compress"

    if fmt == "WEBP":
        data = compress_webp(
            img,
            settings.webp_quality,
            lossless=settings.webp_lossless,
            method=settings.webp_method,
        )
        return data, settings.webp_quality, "webp"

    if fmt == "AVIF":
        try:
            data = compress_avif(img, settings.avif_quality, settings.avif_speed)
            return data, settings.avif_quality, "avif"
        except Exception as e:
            raise ValueError(f"AVIF not supported by your Pillow build: {e}") from e

    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue(), None, "save"


def process_image(
    input_path: str | Path,
    settings: ProcessingSettings,
    *,
    output_path: Optional[str | Path] = None,
    return_bytes: bool = False,
) -> ProcessResult:
    start = time.perf_counter()
    path = Path(input_path)
    steps: List[str] = []

    if not path.exists():
        return ProcessResult(success=False, error=f"File not found: {path}")

    original_size = path.stat().st_size

    try:
        img = open_image(path)
        img.load()
    except Exception as e:
        return ProcessResult(success=False, original_size=original_size, error=str(e))

    orig_dims = img.size
    steps.append(f"loaded {orig_dims[0]}×{orig_dims[1]}")

    if settings.auto_rotate:
        img = ImageOps.exif_transpose(img)
        steps.append("auto-rotated")

    if settings.trim_transparent:
        img = _trim_transparent(img)
        steps.append("trimmed transparent borders")

    if settings.resize_enabled:
        img = resize_image(
            img,
            max_width=settings.max_width,
            max_height=settings.max_height,
            exact_width=settings.exact_width,
            exact_height=settings.exact_height,
            scale_percent=settings.scale_percent,
            fit_mode=FitMode(settings.fit_mode),
            resample=settings.resample,
        )
        steps.append(f"resized to {img.size[0]}×{img.size[1]}")

    if settings.upscale_enabled:
        img = upscale_image(img, settings.upscale_factor, settings.upscale_method, settings.resample)
        steps.append(f"upscaled {settings.upscale_factor}× to {img.size[0]}×{img.size[1]}")

    out_fmt = settings.output_format
    if settings.convert_enabled and out_fmt and out_fmt.lower() != "keep":
        img = convert_format(img, out_fmt, bg_color=settings.bg_color)
        steps.append(f"converted to {out_fmt.upper()}")
    else:
        out_fmt = path.suffix.lstrip(".").upper()
        if out_fmt == "JPG":
            out_fmt = "JPEG"

    if settings.strip_exif and not settings.keep_icc:
        img = _strip_metadata(img, keep_icc=False)
        steps.append("stripped metadata")
    elif settings.strip_exif and settings.keep_icc:
        img = _strip_metadata(img, keep_icc=True)
        steps.append("stripped EXIF, kept ICC")

    ext = output_extension(out_fmt if settings.convert_enabled else settings.output_format, str(path))
    if settings.convert_enabled and settings.output_format.lower() != "keep":
        fmt_for_encode = settings.output_format.upper()
        if fmt_for_encode == "JPG":
            fmt_for_encode = "JPEG"
    else:
        fmt_for_encode = ext.lstrip(".").upper()
        if fmt_for_encode == "JPG":
            fmt_for_encode = "JPEG"

    quality_used: Optional[int] = None
    method_used = ""

    if settings.compress_enabled or fmt_for_encode in ("JPEG", "PNG", "WEBP", "AVIF"):
        data, quality_used, method_used = _encode_image(img, fmt_for_encode, settings, path)
        steps.append(f"encoded ({method_used}" + (f", q{quality_used}" if quality_used else "") + ")")
    else:
        buf = io.BytesIO()
        img.save(buf, format=fmt_for_encode)
        data = buf.getvalue()
        method_used = "save"

    new_size = len(data)
    warning = None
    if settings.compress_enabled and new_size > original_size:
        warning = "Output is larger than input"

    if output_path is None and not return_bytes:
        out_dir = Path(settings.output_dir) if settings.output_dir else path.parent / "processed"
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = settings.naming_prefix + path.stem + settings.naming_suffix
        output_path = out_dir / (stem + ext)
    elif output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path and not return_bytes:
        if output_path.exists() and settings.skip_existing and not settings.overwrite:
            return ProcessResult(
                success=True,
                output_path=str(output_path),
                original_size=original_size,
                new_size=original_size,
                original_dimensions=orig_dims,
                new_dimensions=img.size,
                format=fmt_for_encode,
                method_used="skipped",
                warning="File exists, skipped",
                steps=steps,
                processing_time_ms=(time.perf_counter() - start) * 1000,
            )
        output_path.write_bytes(data)

    elapsed = (time.perf_counter() - start) * 1000
    savings = ((original_size - new_size) / original_size * 100) if original_size else 0

    return ProcessResult(
        success=True,
        output_path=str(output_path) if output_path else None,
        output_data=data if return_bytes else None,
        original_size=original_size,
        new_size=new_size,
        original_dimensions=orig_dims,
        new_dimensions=img.size,
        format=fmt_for_encode,
        quality_used=quality_used,
        method_used=method_used,
        processing_time_ms=elapsed,
        savings_percent=round(savings, 1),
        warning=warning,
        steps=steps,
    )


def discover_images(
    paths: List[str],
    *,
    recursive: bool = True,
) -> List[Path]:
    found: List[Path] = []
    seen: set[str] = set()

    for p in paths:
        path = Path(p)
        if path.is_file():
            if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                key = str(path.resolve())
                if key not in seen:
                    seen.add(key)
                    found.append(path)
        elif path.is_dir():
            pattern = "**/*" if recursive else "*"
            for f in sorted(path.glob(pattern)):
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS:
                    key = str(f.resolve())
                    if key not in seen:
                        seen.add(key)
                        found.append(f)
    return found

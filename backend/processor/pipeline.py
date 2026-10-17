"""Image processing pipeline — validates settings and chains all operations."""

from __future__ import annotations

import math
import os
import tempfile
import time
import warnings
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from PIL import Image, ImageOps

from .compress import (
    EncodeOptions,
    encode,
    insert_orientation,
    jpegtran_optimize,
    strip_jpeg_metadata,
)
from .convert import (
    has_alpha,
    is_valid_color,
    normalize_format,
    normalize_mode,
    output_extension,
    output_name,
    prepare_for_format,
    resolve_output_format,
    source_format,
    to_editable,
)
from .resize import MAX_OUTPUT_PIXELS, resize_image
from .upscale import upscale_image

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on install
    HEIF_AVAILABLE = False

# Pillow raises DecompressionBombError at 2× this value.
Image.MAX_IMAGE_PIXELS = MAX_OUTPUT_PIXELS
warnings.simplefilter("ignore", Image.DecompressionBombWarning)

SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".jpe",
    ".jfif",
    ".png",
    ".webp",
    ".avif",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
}

OUTPUT_FORMATS = ("keep", "JPEG", "PNG", "WEBP", "AVIF", "TIFF")
_ANIMATABLE = {"GIF", "WEBP", "PNG"}
_SKIP_DIRS = {"processed", "__MACOSX", "node_modules"}
MAX_DISCOVERED = 20_000

ORIENTATION_TAG = 0x0112


class SettingsError(ValueError):
    def __init__(self, field_name: str, message: str):
        super().__init__(message)
        self.field = field_name
        self.message = message


# name -> (kind, constraint). kind: bool | int | float | str | choice | opt_int | opt_float | opt_str
_SPEC: Dict[str, Tuple[str, Any]] = {
    "compress_enabled": ("bool", None),
    "resize_enabled": ("bool", None),
    "upscale_enabled": ("bool", None),
    "strip_metadata": ("bool", None),
    "keep_icc": ("bool", None),
    "auto_rotate": ("bool", None),
    "trim_transparent": ("bool", None),
    "compress_mode": ("choice", ("target_size", "quality", "lossless")),
    "target_size": ("float", (0.001, 100_000)),
    "target_unit": ("choice", ("KB", "MB")),
    "quality": ("int", (1, 100)),
    "progressive": ("bool", None),
    "subsampling": ("int", (0, 2)),
    "png_palette": ("bool", None),
    "png_colors": ("int", (2, 256)),
    "never_larger": ("bool", None),
    "resize_mode": ("choice", ("fit", "exact", "scale")),
    "max_width": ("opt_int", (1, 65_535)),
    "max_height": ("opt_int", (1, 65_535)),
    "exact_width": ("opt_int", (1, 65_535)),
    "exact_height": ("opt_int", (1, 65_535)),
    "fit_mode": ("choice", ("cover", "contain", "pad")),
    "scale_percent": ("opt_float", (1, 1000)),
    "allow_enlarge": ("bool", None),
    "resample": ("choice", ("lanczos", "bicubic", "bilinear", "nearest")),
    "upscale_factor": ("float", (1, 8)),
    "output_format": ("choice", OUTPUT_FORMATS),
    "bg_color": ("str", 9),
    "output_dir": ("opt_str", 4096),
    "naming_prefix": ("str", 120),
    "naming_suffix": ("str", 120),
    "on_conflict": ("choice", ("overwrite", "rename", "skip")),
    "replace_originals": ("bool", None),
    "preserve_dates": ("bool", None),
}

_LABELS = {
    "target_size": "Target size",
    "quality": "Quality",
    "png_colors": "PNG colours",
    "max_width": "Max width",
    "max_height": "Max height",
    "exact_width": "Width",
    "exact_height": "Height",
    "scale_percent": "Scale",
    "upscale_factor": "Upscale factor",
    "bg_color": "Background colour",
    "output_dir": "Output folder",
    "naming_prefix": "Prefix",
    "naming_suffix": "Suffix",
}


def _label(name: str) -> str:
    return _LABELS.get(name, name.replace("_", " ").capitalize())


def _coerce(name: str, value: Any) -> Any:
    kind, constraint = _SPEC[name]
    label = _label(name)

    if kind == "bool":
        if isinstance(value, bool):
            return value
        if value in (0, 1, "0", "1", "true", "false"):
            return value in (1, "1", "true")
        raise SettingsError(name, f"{label} must be true or false")

    if kind in ("opt_int", "opt_float", "opt_str") and (value is None or value == ""):
        return None

    if kind in ("int", "float", "opt_int", "opt_float"):
        if isinstance(value, bool):
            raise SettingsError(name, f"{label} must be a number")
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise SettingsError(name, f"{label} must be a number") from None
        if not math.isfinite(number):
            raise SettingsError(name, f"{label} must be a number")
        lo, hi = constraint
        if number < lo or number > hi:
            raise SettingsError(name, f"{label} must be between {lo:g} and {hi:g}")
        if kind in ("int", "opt_int"):
            if number != int(number):
                raise SettingsError(name, f"{label} must be a whole number")
            return int(number)
        return number

    if kind == "choice":
        text = str(value)
        if name == "output_format" and text.lower() != "keep":
            text = normalize_format(text)
        elif name == "target_unit":
            text = text.upper()
        elif name == "output_format":
            text = "keep"
        if text not in constraint:
            raise SettingsError(name, f"{label} must be one of: {', '.join(constraint)}")
        return text

    if not isinstance(value, str):
        raise SettingsError(name, f"{label} must be text")
    text = value.strip() if name != "naming_suffix" and name != "naming_prefix" else value
    if len(text) > constraint:
        raise SettingsError(name, f"{label} is too long")
    if name in ("naming_prefix", "naming_suffix") and any(ch in text for ch in '/\\:\0'):
        raise SettingsError(name, f"{label} can't contain / \\ or :")
    if name == "bg_color" and not is_valid_color(text):
        raise SettingsError(name, f"{label} must be a hex colour like #ffffff")
    if name == "output_dir":
        return text or None
    return text


def _migrate(data: Dict[str, Any]) -> Dict[str, Any]:
    """Accept settings saved by Image Lab 1.x."""
    if "strip_metadata" not in data and "strip_exif" in data:
        data["strip_metadata"] = data["strip_exif"]
    if "target_size" not in data:
        if data.get("target_size_kb") not in (None, ""):
            data["target_size"], data["target_unit"] = data["target_size_kb"], "KB"
        elif data.get("target_size_mb") not in (None, ""):
            data["target_size"], data["target_unit"] = data["target_size_mb"], "MB"
    if data.get("compress_mode") == "lossless_first":
        data["compress_mode"] = "lossless"
    if data.get("convert_enabled") is False and "output_format" in data:
        data["output_format"] = "keep"
    if "on_conflict" not in data and data.get("overwrite") is True:
        data["on_conflict"] = "overwrite"
    if data.get("fit_mode") == "crop_center":
        data["fit_mode"] = "cover"
    if "resize_mode" not in data:
        if data.get("scale_percent"):
            data["resize_mode"] = "scale"
        elif data.get("exact_width") or data.get("exact_height"):
            data["resize_mode"] = "exact"
    if "quality" not in data and data.get("webp_quality") is not None:
        data["quality"] = data["webp_quality"]
    return data


@dataclass
class ProcessingSettings:
    # Operations
    compress_enabled: bool = True
    resize_enabled: bool = False
    upscale_enabled: bool = False
    strip_metadata: bool = True
    keep_icc: bool = True
    auto_rotate: bool = True
    trim_transparent: bool = False

    # Compression
    compress_mode: str = "target_size"
    target_size: float = 12.0
    target_unit: str = "MB"
    quality: int = 85
    progressive: bool = True
    subsampling: int = 0
    png_palette: bool = False
    png_colors: int = 256
    never_larger: bool = True

    # Resize
    resize_mode: str = "fit"
    max_width: Optional[int] = None
    max_height: Optional[int] = None
    exact_width: Optional[int] = None
    exact_height: Optional[int] = None
    fit_mode: str = "cover"
    scale_percent: Optional[float] = None
    allow_enlarge: bool = False
    resample: str = "lanczos"

    # Upscale
    upscale_factor: float = 2.0

    # Format
    output_format: str = "keep"
    bg_color: str = "#ffffff"

    # Output
    output_dir: Optional[str] = None
    naming_prefix: str = ""
    naming_suffix: str = "_processed"
    on_conflict: str = "overwrite"
    replace_originals: bool = False
    preserve_dates: bool = False

    @classmethod
    def from_dict(cls, data: Any) -> "ProcessingSettings":
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise SettingsError("settings", "Settings must be an object")
        data = _migrate(dict(data))
        values = {f.name: _coerce(f.name, data[f.name]) for f in fields(cls) if f.name in data}
        settings = cls(**values)
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.resize_enabled:
            if self.resize_mode == "fit" and not (self.max_width or self.max_height):
                raise SettingsError("max_width", "Resize: enter a max width or max height")
            if self.resize_mode == "exact" and not (self.exact_width or self.exact_height):
                raise SettingsError("exact_width", "Resize: enter a width or height")
            if self.resize_mode == "scale" and not self.scale_percent:
                raise SettingsError("scale_percent", "Resize: enter a scale percentage")

    def to_dict(self) -> Dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @property
    def target_bytes(self) -> int:
        multiplier = 1024 if self.target_unit == "KB" else 1024 * 1024
        return max(1, int(self.target_size * multiplier))


@dataclass
class ProcessResult:
    success: bool
    output_path: Optional[str] = None
    output_data: Optional[bytes] = None
    original_size: int = 0
    new_size: int = 0
    original_dimensions: Tuple[int, int] = (0, 0)
    new_dimensions: Tuple[int, int] = (0, 0)
    format: str = ""
    quality_used: Optional[int] = None
    method_used: str = ""
    processing_time_ms: float = 0
    savings_percent: float = 0
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None
    steps: List[str] = field(default_factory=list)
    skipped: bool = False

    @property
    def warning(self) -> Optional[str]:
        return " · ".join(self.warnings) if self.warnings else None


def format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.2f} MB"


def open_image(path: Path) -> Image.Image:
    if path.suffix.lower() in (".heic", ".heif") and not HEIF_AVAILABLE:
        raise ValueError("HEIC support requires pillow-heif (pip install pillow-heif)")
    return Image.open(path)


def plan_output_path(
    source: Path,
    src_format: str,
    settings: ProcessingSettings,
    *,
    default_dir: Optional[Path] = None,
) -> Path:
    fmt = resolve_output_format(src_format, settings.output_format)
    ext = output_extension(fmt, source)
    if settings.replace_originals:
        return source.with_name(source.stem + ext)
    base = default_dir or (source.parent / "processed")
    if settings.output_dir:
        custom = Path(settings.output_dir).expanduser()
        base = custom if custom.is_absolute() else (default_dir or source.parent) / custom
    return base / output_name(source, settings.naming_prefix, settings.naming_suffix, ext)


def unique_path(path: Path, taken: Optional[Set[str]] = None) -> Path:
    taken = taken or set()
    if str(path) not in taken and not path.exists():
        return path
    for index in range(1, 100_000):
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if str(candidate) not in taken and not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find a free filename for {path.name}")


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def atomic_write(path: Path, data: bytes, *, times_from: Optional[os.stat_result] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    if times_from is not None:
        os.utime(path, (times_from.st_atime, times_from.st_mtime))


_KEEP_INFO_KEYS = ("transparency", "duration", "loop", "background")


def _friendly_error(exc: BaseException) -> str:
    if isinstance(exc, Image.DecompressionBombError):
        return "Image is too large to open safely"
    if isinstance(exc, MemoryError):
        return "Not enough memory to process this image"
    if isinstance(exc, Image.UnidentifiedImageError):
        return "Not a supported image, or the file is damaged"
    message = str(exc).strip()
    if isinstance(exc, OSError) and "truncated" in message.lower():
        return "Image file is truncated or damaged"
    return message or exc.__class__.__name__


@dataclass
class _Rendered:
    data: bytes
    fmt: str
    quality: Optional[int]
    method: str
    original_dimensions: Tuple[int, int]
    new_dimensions: Tuple[int, int]
    steps: List[str]
    warnings: List[str]


def _lossless_candidate(
    path: Path,
    src_fmt: str,
    settings: ProcessingSettings,
    animated: bool,
    orientation: int,
    steps: List[str],
    *,
    optimize: bool = True,
) -> Optional[Tuple[bytes, str]]:
    """Bytes that represent the unchanged image without re-encoding, if any are possible.

    For JPEG, rotation stays lossless: the orientation tag survives metadata stripping.
    optimize=False skips jpegtran (a subprocess, ~0.2 s for 12 MP) for a cheap size estimate.
    """
    original = path.read_bytes()
    if src_fmt != "JPEG" or animated:
        if settings.strip_metadata and not animated:
            return None
        return original, "copy"

    data, method = original, "copy"
    if settings.strip_metadata:
        try:
            data = strip_jpeg_metadata(original, keep_icc=settings.keep_icc)
            if orientation not in (None, 1):
                data = insert_orientation(data, orientation)
            method = "lossless_strip"
        except ValueError:
            return None
    if optimize:
        return _jpegtran_candidate((data, method), settings, steps)
    return data, method


def _jpegtran_candidate(candidate: Tuple[bytes, str], settings: ProcessingSettings, steps: List[str]) -> Tuple[bytes, str]:
    data, method = candidate
    if not settings.compress_enabled or not data.startswith(b"\xff\xd8"):
        return candidate
    optimized = jpegtran_optimize(data, progressive=settings.progressive)
    if optimized and len(optimized) < len(data):
        steps.append("jpegtran optimised")
        return optimized, "lossless"
    return candidate


# jpegtran -optimize rarely saves more than ~15%; below this ratio it can't beat a re-encode.
_JPEGTRAN_BEST_RATIO = 0.8


def _render(path: Path, settings: ProcessingSettings) -> _Rendered:
    steps: List[str] = []
    notes: List[str] = []
    img = open_image(path)
    try:
        src_fmt = source_format(path, img.format)
        animated = src_fmt in _ANIMATABLE and getattr(img, "n_frames", 1) > 1
        out_fmt = resolve_output_format(src_fmt, settings.output_format)
        icc = img.info.get("icc_profile")
        dpi = img.info.get("dpi")
        exif = img.getexif()
        orientation = exif.get(ORIENTATION_TAG, 1)
        img.load()
        orig_dims = img.size
        steps.append(f"loaded {orig_dims[0]}×{orig_dims[1]} {src_fmt}")

        work = img
        changed = False
        rotated = False

        if settings.auto_rotate and orientation not in (None, 1):
            work = ImageOps.exif_transpose(work)
            rotated = True
            steps.append("auto-rotated")

        upscaling = settings.upscale_enabled and settings.upscale_factor > 1
        if settings.trim_transparent or settings.resize_enabled or upscaling:
            work = to_editable(normalize_mode(work))

        if settings.trim_transparent and has_alpha(work):
            bbox = work.getchannel("A").getbbox()
            if bbox and bbox != (0, 0, work.width, work.height):
                work = work.crop(bbox)
                changed = True
                steps.append(f"trimmed to {work.width}×{work.height}")

        if settings.resize_enabled:
            resized = resize_image(
                work,
                mode=settings.resize_mode,
                max_width=settings.max_width,
                max_height=settings.max_height,
                exact_width=settings.exact_width,
                exact_height=settings.exact_height,
                scale_percent=settings.scale_percent,
                fit_mode=settings.fit_mode,
                allow_enlarge=settings.allow_enlarge,
                resample=settings.resample,
                bg_color=settings.bg_color,
            )
            if resized is not work:
                work = resized
                changed = True
                steps.append(f"resized to {work.width}×{work.height}")

        if upscaling:
            work = upscale_image(work, settings.upscale_factor, settings.resample)
            changed = True
            steps.append(f"upscaled {settings.upscale_factor:g}× to {work.width}×{work.height}")

        format_changed = out_fmt != src_fmt
        if animated and (changed or format_changed):
            notes.append("Animated image: only the first frame was kept")

        mode = settings.compress_mode if settings.compress_enabled else "quality"
        limit = settings.target_bytes if mode == "target_size" else None

        eligible = not changed and not format_changed and (not rotated or src_fmt == "JPEG")
        candidate = None
        if eligible and (
            not settings.compress_enabled
            or mode == "lossless"
            or (mode == "target_size" and path.stat().st_size <= limit / _JPEGTRAN_BEST_RATIO)
        ):
            candidate = _lossless_candidate(path, src_fmt, settings, animated, orientation, steps)
        displayed_dims = work.size

        if candidate is not None:
            data, method = candidate
            use_candidate = (
                not settings.compress_enabled
                or mode == "lossless"
                or (mode == "target_size" and len(data) <= limit)
            )
            if use_candidate:
                steps.append("kept original pixels" if method != "copy" else "copied original")
                return _Rendered(data, out_fmt, None, method, orig_dims, displayed_dims, steps, notes)

        keep_icc = (not settings.strip_metadata) or settings.keep_icc
        prepared, icc_out = prepare_for_format(
            work,
            out_fmt,
            bg_color=settings.bg_color,
            icc_profile=icc if keep_icc else None,
        )
        if prepared.mode != work.mode:
            steps.append(f"converted {work.mode}→{prepared.mode}")

        exif_bytes = None
        if not settings.strip_metadata and len(exif):
            if rotated:
                exif[ORIENTATION_TAG] = 1
            exif_bytes = exif.tobytes()

        if prepared is img:
            prepared = img.copy()
        prepared.info = {k: v for k, v in prepared.info.items() if k in _KEEP_INFO_KEYS}

        quality = settings.quality if settings.compress_enabled else max(settings.quality, 95)
        if mode == "lossless" and out_fmt == "JPEG":
            mode = "quality"
            quality = max(settings.quality, 95)
            notes.append(f"JPEG can't stay lossless after edits — encoded at quality {quality}")

        opts = EncodeOptions(
            quality=quality,
            progressive=settings.progressive,
            subsampling=settings.subsampling,
            png_palette=settings.png_palette,
            png_colors=settings.png_colors,
            exif=exif_bytes,
            icc_profile=icc_out,
            dpi=dpi if not settings.strip_metadata else None,
        )
        result = encode(prepared, out_fmt, opts, mode=mode, limit_bytes=limit)
        data, quality_used, method = result.data, result.quality, result.method
        steps.append(f"encoded {out_fmt} ({method}" + (f", q{quality_used}" if quality_used else "") + ")")

        if mode == "target_size" and not result.reached_target:
            notes.append(
                f"Couldn't reach {format_bytes(limit)} — smallest result is "
                f"{format_bytes(len(data))}. Try resizing."
            )

        new_dims = prepared.size
        if eligible and candidate is None and settings.compress_enabled and settings.never_larger:
            cheap = _lossless_candidate(path, src_fmt, settings, animated, orientation, steps, optimize=False)
            if cheap is not None and len(cheap[0]) * _JPEGTRAN_BEST_RATIO <= len(data):
                candidate = _jpegtran_candidate(cheap, settings, steps)
        if (
            candidate is not None
            and settings.compress_enabled
            and settings.never_larger
            and len(candidate[0]) <= len(data)
        ):
            data, method = candidate
            quality_used = None
            new_dims = displayed_dims
            notes.append("Re-encoding was larger — kept the original encoding")
            steps.append("kept original (smaller)")

        return _Rendered(data, out_fmt, quality_used, method, orig_dims, new_dims, steps, notes)
    finally:
        img.close()


def process_image(
    input_path: str | Path,
    settings: ProcessingSettings,
    *,
    output_path: Optional[str | Path] = None,
    return_bytes: bool = False,
    default_output_dir: Optional[Path] = None,
    resolve_conflicts: bool = True,
) -> ProcessResult:
    start = time.perf_counter()
    path = Path(input_path)

    def elapsed() -> float:
        return round((time.perf_counter() - start) * 1000, 1)

    try:
        stat = path.stat()
    except OSError:
        return ProcessResult(success=False, error=f"File not found: {path.name}")
    if not path.is_file():
        return ProcessResult(success=False, error=f"Not a file: {path.name}")
    original_size = stat.st_size

    target: Optional[Path] = None
    if not return_bytes:
        if output_path is not None:
            target = Path(output_path)
        else:
            try:
                with Image.open(path) as probe:
                    fmt = source_format(path, probe.format)
            except Exception:
                fmt = source_format(path)
            target = plan_output_path(path, fmt, settings, default_dir=default_output_dir)

        if _same_file(target, path) and not settings.replace_originals:
            return ProcessResult(
                success=False,
                original_size=original_size,
                error="Output would overwrite the original — change the suffix or folder, "
                "or enable Replace originals",
            )
        if target.exists() and not _same_file(target, path):
            if settings.on_conflict == "skip":
                return ProcessResult(
                    success=True,
                    skipped=True,
                    output_path=str(target),
                    original_size=original_size,
                    new_size=target.stat().st_size,
                    method_used="skipped",
                    warnings=["Output already exists — skipped"],
                    processing_time_ms=elapsed(),
                )
            if settings.on_conflict == "rename" and resolve_conflicts:
                target = unique_path(target)

    try:
        rendered = _render(path, settings)
    except Exception as exc:  # noqa: BLE001 - every failure must become a per-file error
        return ProcessResult(
            success=False,
            original_size=original_size,
            error=_friendly_error(exc),
            processing_time_ms=elapsed(),
        )

    new_size = len(rendered.data)
    notes = list(rendered.warnings)
    if settings.compress_enabled and new_size > original_size:
        notes.append("Output is larger than the original")

    if target is not None:
        try:
            atomic_write(target, rendered.data, times_from=stat if settings.preserve_dates else None)
        except OSError as exc:
            return ProcessResult(
                success=False,
                original_size=original_size,
                error=f"Couldn't write {target.name}: {exc.strerror or exc}",
                processing_time_ms=elapsed(),
            )

    savings = ((original_size - new_size) / original_size * 100) if original_size else 0
    return ProcessResult(
        success=True,
        output_path=str(target) if target else None,
        output_data=rendered.data if return_bytes else None,
        original_size=original_size,
        new_size=new_size,
        original_dimensions=rendered.original_dimensions,
        new_dimensions=rendered.new_dimensions,
        format=rendered.fmt,
        quality_used=rendered.quality,
        method_used=rendered.method,
        processing_time_ms=elapsed(),
        savings_percent=round(savings, 1),
        warnings=notes,
        steps=rendered.steps,
    )


def _is_candidate(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS and not path.name.startswith(".")


def discover_images(paths: Iterable[str], *, recursive: bool = True) -> List[Path]:
    found: List[Path] = []
    seen: Set[str] = set()

    def add(candidate: Path) -> None:
        key = str(candidate.resolve())
        if key not in seen and len(found) < MAX_DISCOVERED:
            seen.add(key)
            found.append(candidate)

    for raw in paths:
        path = Path(os.path.expanduser(str(raw)))
        if path.is_file():
            if _is_candidate(path):
                add(path)
        elif path.is_dir():
            if recursive:
                for root, dirs, files in os.walk(path):
                    dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in _SKIP_DIRS)
                    for name in sorted(files):
                        candidate = Path(root) / name
                        if _is_candidate(candidate):
                            add(candidate)
            else:
                for candidate in sorted(path.iterdir()):
                    if candidate.is_file() and _is_candidate(candidate):
                        add(candidate)
    return found

"""Format resolution and pixel-mode preparation for each output encoder."""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageCms

FORMAT_EXT = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
    "AVIF": ".avif",
    "TIFF": ".tiff",
    "GIF": ".gif",
    "BMP": ".bmp",
}

EXT_FORMAT = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".jpe": "JPEG",
    ".jfif": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".avif": "AVIF",
    ".gif": "GIF",
    ".bmp": "BMP",
    ".tif": "TIFF",
    ".tiff": "TIFF",
    ".heic": "HEIF",
    ".heif": "HEIF",
}

# Pillow reports some sources under names that are not writable encoders.
_SOURCE_ALIASES = {"MPO": "JPEG", "JPG": "JPEG", "HEIC": "HEIF", "TIF": "TIFF"}

# Sources we can read but should not write back as-is.
_KEEP_FALLBACK = {"HEIF": "JPEG"}

WRITABLE_FORMATS = ("JPEG", "PNG", "WEBP", "AVIF", "TIFF", "GIF", "BMP")
ALPHA_FORMATS = {"PNG", "WEBP", "AVIF", "TIFF", "GIF"}

_HEX_COLOR = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def normalize_format(fmt: Optional[str]) -> str:
    value = (fmt or "").strip().upper()
    return _SOURCE_ALIASES.get(value, value)


def source_format(path: Path, pil_format: Optional[str] = None) -> str:
    fmt = normalize_format(pil_format)
    if fmt:
        return fmt
    return EXT_FORMAT.get(path.suffix.lower(), "JPEG")


def resolve_output_format(src_format: str, requested: str) -> str:
    requested = normalize_format(requested)
    if requested and requested != "KEEP":
        return requested
    src = normalize_format(src_format)
    if src in WRITABLE_FORMATS:
        return src
    return _KEEP_FALLBACK.get(src, "JPEG")


def output_extension(fmt: str, source_path: Optional[Path] = None) -> str:
    """Reuse the source's spelling (.jpeg, .JPG) when the format is unchanged."""
    fmt = normalize_format(fmt)
    if source_path is not None:
        suffix = source_path.suffix
        if EXT_FORMAT.get(suffix.lower()) == fmt:
            return suffix
    return FORMAT_EXT.get(fmt, ".jpg")


def is_valid_color(color: str) -> bool:
    return bool(_HEX_COLOR.match(color.strip()))


def parse_color(color: str) -> Tuple[int, int, int]:
    match = _HEX_COLOR.match((color or "").strip())
    if not match:
        return (255, 255, 255)
    value = match.group(1)
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def has_alpha(img: Image.Image) -> bool:
    if img.mode in ("RGBA", "LA", "PA", "RGBa", "La"):
        return True
    return img.mode == "P" and "transparency" in img.info


def _color_family(mode: str) -> str:
    if mode in ("1", "L", "LA", "La", "I", "I;16", "I;16B", "I;16L", "I;16N", "F"):
        return "gray"
    if mode == "CMYK":
        return "cmyk"
    return "rgb"


def normalize_mode(img: Image.Image) -> Image.Image:
    """Bring exotic modes (16-bit, float, premultiplied, LAB…) into 8-bit L/LA/RGB/RGBA/P/CMYK."""
    mode = img.mode
    if mode.startswith("I;16") or mode == "I":
        work = img if mode == "I" else img.convert("I")
        return work.point(lambda v: v * (1 / 256)).convert("L")
    if mode == "F":
        return img.convert("L")
    if mode == "RGBa":
        return img.convert("RGBA")
    if mode == "La":
        return img.convert("LA")
    if mode == "PA":
        return img.convert("RGBA")
    if mode in ("YCbCr", "LAB", "HSV", "RGBX"):
        return img.convert("RGB")
    return img


def to_editable(img: Image.Image) -> Image.Image:
    """Palette and 1-bit images resize with nearest-neighbour only; expand them first."""
    if img.mode == "P":
        return img.convert("RGBA" if has_alpha(img) else "RGB")
    if img.mode == "1":
        return img.convert("L")
    return img


def flatten(img: Image.Image, bg: Tuple[int, int, int]) -> Image.Image:
    if img.mode in ("P", "LA", "PA"):
        img = img.convert("RGBA")
    base = Image.new("RGB", img.size, bg)
    base.paste(img, mask=img.getchannel("A"))
    return base


def _cmyk_to_rgb(img: Image.Image, icc: Optional[bytes]) -> Tuple[Image.Image, Optional[bytes]]:
    if icc:
        try:
            src_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            srgb = ImageCms.createProfile("sRGB")
            converted = ImageCms.profileToProfile(img, src_profile, srgb, outputMode="RGB")
            if converted is not None:
                return converted, ImageCms.ImageCmsProfile(srgb).tobytes()
        except Exception:
            pass
    return img.convert("RGB"), None


def prepare_for_format(
    img: Image.Image,
    fmt: str,
    *,
    bg_color: str = "#ffffff",
    icc_profile: Optional[bytes] = None,
) -> Tuple[Image.Image, Optional[bytes]]:
    """Return an image in a mode the encoder accepts, plus an ICC profile that still matches it."""
    fmt = normalize_format(fmt)
    bg = parse_color(bg_color)
    family_before = _color_family(img.mode)
    img = normalize_mode(img)

    if img.mode == "CMYK" and fmt not in ("JPEG", "TIFF"):
        img, icc_profile = _cmyk_to_rgb(img, icc_profile)
        family_before = "rgb"

    if fmt == "JPEG":
        if has_alpha(img):
            img = flatten(img, bg)
        elif img.mode == "P":
            img = img.convert("RGB")
        elif img.mode == "1":
            img = img.convert("L")
        elif img.mode not in ("L", "RGB", "CMYK"):
            img = img.convert("RGB")
    elif fmt == "PNG":
        if img.mode not in ("1", "L", "LA", "P", "RGB", "RGBA"):
            img = img.convert("RGBA" if has_alpha(img) else "RGB")
    elif fmt in ("WEBP", "AVIF"):
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if has_alpha(img) else "RGB")
    elif fmt == "BMP":
        if has_alpha(img):
            img = flatten(img, bg)
        elif img.mode not in ("1", "L", "P", "RGB"):
            img = img.convert("RGB")
    elif fmt == "GIF":
        if img.mode not in ("1", "L", "P", "RGB", "RGBA"):
            img = img.convert("RGBA" if has_alpha(img) else "RGB")
    elif fmt == "TIFF":
        if img.mode not in ("1", "L", "LA", "P", "RGB", "RGBA", "CMYK"):
            img = img.convert("RGBA" if has_alpha(img) else "RGB")

    if icc_profile and _color_family(img.mode) != family_before:
        icc_profile = None
    return img, icc_profile


def output_name(source: Path, prefix: str, suffix: str, ext: str) -> str:
    return f"{prefix}{source.stem}{suffix}{ext}"

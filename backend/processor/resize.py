"""Resize, pad, crop and upscale operations."""

from __future__ import annotations

from enum import Enum
from typing import Optional, Tuple

from PIL import Image

from .convert import has_alpha, parse_color

# Keeps a mistyped scale factor from allocating tens of gigabytes.
MAX_OUTPUT_PIXELS = 250_000_000


class FitMode(str, Enum):
    CONTAIN = "contain"
    COVER = "cover"
    PAD = "pad"


RESAMPLE_MAP = {
    "lanczos": Image.Resampling.LANCZOS,
    "bicubic": Image.Resampling.BICUBIC,
    "bilinear": Image.Resampling.BILINEAR,
    "nearest": Image.Resampling.NEAREST,
}


def ensure_pixel_budget(width: int, height: int) -> None:
    if width * height > MAX_OUTPUT_PIXELS:
        megapixels = width * height / 1_000_000
        raise ValueError(
            f"Output would be {width}×{height} ({megapixels:.0f} MP), "
            f"above the {MAX_OUTPUT_PIXELS // 1_000_000} MP safety limit"
        )


def _resample(name: str) -> Image.Resampling:
    return RESAMPLE_MAP.get(name, Image.Resampling.LANCZOS)


def _scaled(img: Image.Image, size: Tuple[int, int], resample: str) -> Image.Image:
    size = (max(1, size[0]), max(1, size[1]))
    if size == img.size:
        return img
    ensure_pixel_budget(*size)
    shrinking = size[0] < img.width and size[1] < img.height
    # reducing_gap pre-shrinks with a box filter: several times faster, visually identical.
    return img.resize(size, _resample(resample), reducing_gap=3.0 if shrinking else None)


def fit_within(
    img: Image.Image,
    max_width: Optional[int],
    max_height: Optional[int],
    *,
    allow_enlarge: bool = False,
    resample: str = "lanczos",
) -> Image.Image:
    if not max_width and not max_height:
        return img
    w, h = img.size
    ratio = min(
        (max_width / w) if max_width else float("inf"),
        (max_height / h) if max_height else float("inf"),
    )
    if ratio >= 1 and not allow_enlarge:
        return img
    return _scaled(img, (round(w * ratio), round(h * ratio)), resample)


def exact_size(
    img: Image.Image,
    width: Optional[int],
    height: Optional[int],
    *,
    fit_mode: FitMode = FitMode.COVER,
    resample: str = "lanczos",
    bg_color: str = "#ffffff",
) -> Image.Image:
    w, h = img.size
    if width and not height:
        return _scaled(img, (width, round(h * width / w)), resample)
    if height and not width:
        return _scaled(img, (round(w * height / h), height), resample)
    if not width or not height:
        return img

    if fit_mode == FitMode.COVER:
        ratio = max(width / w, height / h)
        nw, nh = max(width, round(w * ratio)), max(height, round(h * ratio))
        resized = _scaled(img, (nw, nh), resample)
        left = (nw - width) // 2
        top = (nh - height) // 2
        return resized.crop((left, top, left + width, top + height))

    ratio = min(width / w, height / h)
    resized = _scaled(img, (round(w * ratio), round(h * ratio)), resample)
    if fit_mode == FitMode.CONTAIN:
        return resized

    ensure_pixel_budget(width, height)
    if has_alpha(resized):
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        resized = resized.convert("RGBA")
    else:
        mode = "L" if resized.mode == "L" else "RGB"
        fill = parse_color(bg_color)
        canvas = Image.new(mode, (width, height), fill[0] if mode == "L" else fill)
        resized = resized.convert(mode)
    offset = ((width - resized.width) // 2, (height - resized.height) // 2)
    canvas.paste(resized, offset)
    canvas.info = dict(resized.info)
    return canvas


def scale_by(img: Image.Image, percent: Optional[float], resample: str = "lanczos") -> Image.Image:
    if not percent or percent == 100:
        return img
    w, h = img.size
    return _scaled(img, (round(w * percent / 100), round(h * percent / 100)), resample)


def resize_image(
    img: Image.Image,
    *,
    mode: str = "fit",
    max_width: Optional[int] = None,
    max_height: Optional[int] = None,
    exact_width: Optional[int] = None,
    exact_height: Optional[int] = None,
    scale_percent: Optional[float] = None,
    fit_mode: str = "cover",
    allow_enlarge: bool = False,
    resample: str = "lanczos",
    bg_color: str = "#ffffff",
) -> Image.Image:
    if mode == "scale":
        return scale_by(img, scale_percent, resample)
    if mode == "exact":
        return exact_size(
            img,
            exact_width,
            exact_height,
            fit_mode=FitMode(fit_mode),
            resample=resample,
            bg_color=bg_color,
        )
    return fit_within(img, max_width, max_height, allow_enlarge=allow_enlarge, resample=resample)

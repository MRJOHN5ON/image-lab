"""Image resize operations."""

from __future__ import annotations

from enum import Enum
from typing import Optional, Tuple

from PIL import Image


class FitMode(str, Enum):
    CONTAIN = "contain"
    COVER = "cover"
    CROP_CENTER = "crop_center"


RESAMPLE_MAP = {
    "lanczos": Image.Resampling.LANCZOS,
    "bilinear": Image.Resampling.BILINEAR,
    "nearest": Image.Resampling.NEAREST,
}


def resize_image(
    img: Image.Image,
    *,
    max_width: Optional[int] = None,
    max_height: Optional[int] = None,
    exact_width: Optional[int] = None,
    exact_height: Optional[int] = None,
    scale_percent: Optional[float] = None,
    fit_mode: FitMode = FitMode.CONTAIN,
    resample: str = "lanczos",
) -> Image.Image:
    filter_ = RESAMPLE_MAP.get(resample, Image.Resampling.LANCZOS)
    w, h = img.size

    if scale_percent is not None:
        nw = max(1, int(w * scale_percent / 100))
        nh = max(1, int(h * scale_percent / 100))
        return img.resize((nw, nh), filter_)

    if exact_width and exact_height:
        target = (exact_width, exact_height)
        if fit_mode == FitMode.CONTAIN:
            img.thumbnail(target, filter_)
            return img
        if fit_mode == FitMode.COVER:
            ratio = max(exact_width / w, exact_height / h)
            nw, nh = int(w * ratio), int(h * ratio)
            resized = img.resize((nw, nh), filter_)
            left = (nw - exact_width) // 2
            top = (nh - exact_height) // 2
            return resized.crop((left, top, left + exact_width, top + exact_height))
        # crop_center from current size to exact
        ratio = min(w / exact_width, h / exact_height)
        nw, nh = int(exact_width * ratio), int(exact_height * ratio)
        left = (w - nw) // 2
        top = (h - nh) // 2
        cropped = img.crop((left, top, left + nw, top + nh))
        return cropped.resize((exact_width, exact_height), filter_)

    if max_width or max_height:
        nw, nh = w, h
        if max_width and nw > max_width:
            nh = int(nh * max_width / nw)
            nw = max_width
        if max_height and nh > max_height:
            nw = int(nw * max_height / nh)
            nh = max_height
        if (nw, nh) != (w, h):
            return img.resize((nw, nh), filter_)

    return img


def get_dimensions(img: Image.Image) -> Tuple[int, int]:
    return img.size

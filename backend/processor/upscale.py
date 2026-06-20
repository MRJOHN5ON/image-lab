"""Upscale operations — honest Lanczos by default."""

from __future__ import annotations

from PIL import Image

from .resize import RESAMPLE_MAP


def upscale_image(
    img: Image.Image,
    scale_factor: float,
    method: str = "standard",
    resample: str = "lanczos",
) -> Image.Image:
    """
    Upscale image by scale_factor.
    method 'standard' uses Pillow Lanczos (not AI).
    """
    if scale_factor <= 1.0:
        return img

    filter_ = RESAMPLE_MAP.get(resample, Image.Resampling.LANCZOS)
    w, h = img.size
    nw = max(1, int(w * scale_factor))
    nh = max(1, int(h * scale_factor))
    return img.resize((nw, nh), filter_)

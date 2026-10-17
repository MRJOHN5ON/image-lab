"""Upscale operations — honest interpolation, not AI."""

from __future__ import annotations

from PIL import Image

from .resize import RESAMPLE_MAP, ensure_pixel_budget


def upscale_image(img: Image.Image, scale_factor: float, resample: str = "lanczos") -> Image.Image:
    if scale_factor <= 1.0:
        return img
    w, h = img.size
    nw = max(1, round(w * scale_factor))
    nh = max(1, round(h * scale_factor))
    ensure_pixel_budget(nw, nh)
    return img.resize((nw, nh), RESAMPLE_MAP.get(resample, Image.Resampling.LANCZOS))

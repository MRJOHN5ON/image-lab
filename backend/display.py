"""Browser-friendly renditions for the compare view."""

from __future__ import annotations

import io
from typing import Tuple

MIME_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    "BMP": "image/bmp",
    "AVIF": "image/avif",
    "TIFF": "image/tiff",
}
BROWSER_SAFE = {"JPEG", "PNG", "WEBP", "GIF", "BMP"}

# Browsers freeze decoding and compositing very large images, so previews are capped.
MAX_DISPLAY_PIXELS = 16_000_000
MAX_DISPLAY_SIDE = 6000


def fits_display(width: int, height: int) -> bool:
    return width * height <= MAX_DISPLAY_PIXELS and max(width, height) <= MAX_DISPLAY_SIDE


def display_copy(img) -> Tuple[bytes, str, Tuple[int, int]]:
    """Encode `img` for the browser, downscaled when over the display budget."""
    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA", "L", "LA"):
        img = img.convert("RGBA" if "A" in img.getbands() or "transparency" in img.info else "RGB")
    scaled = not fits_display(*img.size)
    if scaled:
        w, h = img.size
        factor = min((MAX_DISPLAY_PIXELS / (w * h)) ** 0.5, MAX_DISPLAY_SIDE / max(w, h))
        img = img.resize((max(1, int(w * factor)), max(1, int(h * factor))), Image.Resampling.LANCZOS, reducing_gap=3.0)
    buf = io.BytesIO()
    if scaled and img.mode in ("RGB", "L"):
        img.save(buf, format="JPEG", quality=92, subsampling=0)
        return buf.getvalue(), "image/jpeg", img.size
    img.save(buf, format="PNG", compress_level=1)
    return buf.getvalue(), "image/png", img.size


def displayable(data: bytes, fmt: str, size: Tuple[int, int]) -> Tuple[bytes, str, Tuple[int, int]]:
    if fmt in BROWSER_SAFE and fits_display(*size):
        return data, MIME_TYPES[fmt], size
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        return display_copy(img)

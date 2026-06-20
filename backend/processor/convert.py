"""Format conversion."""

from __future__ import annotations

from typing import Optional, Tuple

from PIL import Image


FORMAT_EXT = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
    "AVIF": ".avif",
    "GIF": ".gif",
    "BMP": ".bmp",
    "TIFF": ".tiff",
}

EXT_FORMAT = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".avif": "AVIF",
    ".gif": "GIF",
    ".bmp": "BMP",
    ".tif": "TIFF",
    ".tiff": "TIFF",
    ".heic": "HEIC",
    ".heif": "HEIC",
}


def parse_bg_color(color: str) -> Tuple[int, int, int]:
    color = color.strip().lstrip("#")
    if len(color) == 6:
        return (
            int(color[0:2], 16),
            int(color[2:4], 16),
            int(color[4:6], 16),
        )
    return (255, 255, 255)


def convert_format(
    img: Image.Image,
    output_format: str,
    *,
    bg_color: str = "#ffffff",
) -> Image.Image:
    fmt = output_format.upper()
    if fmt == "JPEG":
        if img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", img.size, parse_bg_color(bg_color))
            if img.mode == "P":
                img = img.convert("RGBA")
            if img.mode in ("RGBA", "LA"):
                background.paste(img, mask=img.split()[-1])
            else:
                background.paste(img)
            return background
        return img.convert("RGB")
    if fmt == "PNG":
        if img.mode not in ("RGBA", "RGB", "P", "L"):
            return img.convert("RGBA")
        return img
    if fmt in ("WEBP", "AVIF"):
        if img.mode not in ("RGB", "RGBA"):
            return img.convert("RGBA" if img.mode == "P" else "RGB")
        return img
    return img


def output_extension(output_format: Optional[str], source_path: str) -> str:
    if not output_format or output_format.lower() == "keep":
        from pathlib import Path

        return Path(source_path).suffix or ".jpg"
    fmt = output_format.upper()
    return FORMAT_EXT.get(fmt, ".jpg")

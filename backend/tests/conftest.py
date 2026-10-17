from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# Isolate app data before `config` is imported anywhere.
_SESSION_DIR = Path(tempfile.mkdtemp(prefix="imagelab-tests-"))
os.environ["IMAGE_LAB_DATA_DIR"] = str(_SESSION_DIR / "data")
os.environ["IMAGE_LAB_OUTPUT_DIR"] = str(_SESSION_DIR / "output")
os.environ["IMAGE_LAB_FRONTEND_DIR"] = str(_SESSION_DIR / "no-frontend")
os.environ["IMAGE_LAB_WARM_WORKERS"] = "0"
os.environ["IMAGE_LAB_WORKERS"] = "2"

from PIL import Image, ImageCms  # noqa: E402


def noise_image(size=(800, 600), mode="RGB") -> Image.Image:
    img = Image.effect_noise(size, 70).convert("L")
    if mode == "L":
        return img
    rgb = Image.merge("RGB", (img, img.rotate(90, expand=False), img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)))
    return rgb.convert(mode) if mode != "RGB" else rgb


def srgb_icc() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def jpeg_with_metadata(path: Path, *, orientation: int = 1, size=(800, 600)) -> Path:
    exif = Image.Exif()
    exif[0x010F] = "Canon"
    exif[0x0112] = orientation
    noise_image(size).save(path, format="JPEG", quality=95, exif=exif.tobytes(), icc_profile=srgb_icc())
    return path


@pytest.fixture
def tmp_images(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    return tmp_path / "src"


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageChops, features

from conftest import jpeg_with_metadata, noise_image, srgb_icc
from processor.compress import strip_jpeg_metadata
from processor.pipeline import (
    ProcessingSettings,
    SettingsError,
    discover_images,
    plan_output_path,
    process_image,
)


def settings(**overrides) -> ProcessingSettings:
    return ProcessingSettings.from_dict(overrides)


def same_pixels(a: Path, b: Path) -> bool:
    with Image.open(a) as x, Image.open(b) as y:
        return ImageChops.difference(x.convert("RGB"), y.convert("RGB")).getbbox() is None


# ── settings ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "payload, field",
    [
        ({"quality": "high"}, "quality"),
        ({"quality": 0}, "quality"),
        ({"quality": 85.5}, "quality"),
        ({"target_size": -1}, "target_size"),
        ({"output_format": "EXE"}, "output_format"),
        ({"naming_suffix": "/../x"}, "naming_suffix"),
        ({"bg_color": "red"}, "bg_color"),
        ({"resize_enabled": True}, "max_width"),
        ({"resize_enabled": True, "resize_mode": "scale"}, "scale_percent"),
        ({"upscale_factor": 50}, "upscale_factor"),
        ({"max_width": float("nan")}, "max_width"),
    ],
)
def test_invalid_settings_name_the_field(payload, field):
    with pytest.raises(SettingsError) as info:
        ProcessingSettings.from_dict(payload)
    assert info.value.field == field


def test_v1_settings_are_migrated():
    s = ProcessingSettings.from_dict(
        {
            "strip_exif": False,
            "target_size_kb": 500,
            "compress_mode": "lossless_first",
            "fit_mode": "crop_center",
            "exact_width": 100,
            "convert_enabled": False,
            "output_format": "WEBP",
            "webp_quality": 70,
            "unknown_key": 1,
        }
    )
    assert s.strip_metadata is False
    assert (s.target_size, s.target_unit) == (500, "KB")
    assert s.compress_mode == "lossless"
    assert s.fit_mode == "cover"
    assert s.resize_mode == "exact"
    assert s.output_format == "keep"
    assert s.quality == 70


def test_empty_optional_numbers_become_none():
    s = settings(max_width="", scale_percent=None, output_dir="  ")
    assert s.max_width is None and s.scale_percent is None and s.output_dir is None


# ── JPEG paths ────────────────────────────────────────────────────────────
def test_target_size_is_respected_and_capped_by_quality(tmp_images):
    src = jpeg_with_metadata(tmp_images / "a.jpg", size=(1600, 1200))
    limit_kb = 150
    r = process_image(src, settings(target_size=limit_kb, target_unit="KB", quality=80))
    assert r.success, r.error
    assert r.new_size <= limit_kb * 1024
    assert r.quality_used is not None and r.quality_used <= 80
    assert Path(r.output_path).parent.name == "processed"


def test_lossless_strip_keeps_pixels_and_icc_but_drops_exif(tmp_images):
    src = jpeg_with_metadata(tmp_images / "a.jpg")
    r = process_image(src, settings(compress_mode="lossless", keep_icc=True))
    assert r.success and r.method_used in ("lossless", "lossless_strip")
    assert same_pixels(src, Path(r.output_path))
    with Image.open(r.output_path) as out:
        assert out.info.get("icc_profile") == srgb_icc()
        assert 0x010F not in out.getexif()


def test_lossless_keeps_orientation_instead_of_reencoding(tmp_images):
    src = jpeg_with_metadata(tmp_images / "rot.jpg", orientation=6, size=(400, 200))
    r = process_image(src, settings(compress_mode="lossless"))
    assert r.success and r.method_used != "reencode"
    assert r.new_dimensions == (200, 400)
    with Image.open(r.output_path) as out:
        assert out.getexif().get(0x0112) == 6
        assert 0x010F not in out.getexif()


def test_reencode_bakes_rotation_and_resets_orientation_when_keeping_metadata(tmp_images):
    src = jpeg_with_metadata(tmp_images / "rot.jpg", orientation=6, size=(400, 200))
    r = process_image(src, settings(compress_mode="quality", strip_metadata=False, never_larger=False))
    assert r.success
    with Image.open(r.output_path) as out:
        assert out.size == (200, 400)
        exif = out.getexif()
        assert exif.get(0x0112) == 1
        assert exif.get(0x010F) == "Canon"


def test_target_mode_copies_files_already_under_the_limit(tmp_images):
    src = jpeg_with_metadata(tmp_images / "a.jpg", size=(200, 100))
    r = process_image(src, settings(target_size=10, target_unit="MB", strip_metadata=False))
    assert r.method_used in ("copy", "lossless")
    assert same_pixels(src, Path(r.output_path))
    with Image.open(r.output_path) as out:
        assert out.getexif().get(0x010F) == "Canon"


def test_never_larger_keeps_original_encoding(tmp_images):
    src = tmp_images / "small.jpg"
    noise_image((300, 300)).save(src, quality=40)
    r = process_image(src, settings(compress_mode="quality", quality=100, strip_metadata=False))
    assert r.success
    assert r.new_size <= src.stat().st_size
    assert any("kept the original" in w for w in r.warnings)


def test_resize_after_target_copy_is_not_skipped(tmp_images):
    """v1 bug: files under the target size were copied even when a resize was requested."""
    src = jpeg_with_metadata(tmp_images / "a.jpg", size=(1600, 1200))
    r = process_image(src, settings(resize_enabled=True, max_width=400, target_size=50, target_unit="MB"))
    assert r.new_dimensions == (400, 300)
    with Image.open(r.output_path) as out:
        assert out.size == (400, 300)


# ── formats and modes ─────────────────────────────────────────────────────
def test_png_strip_removes_icc_profile(tmp_images):
    src = tmp_images / "icc.png"
    noise_image((64, 64)).save(src, icc_profile=srgb_icc())
    r = process_image(src, settings(compress_mode="quality", keep_icc=False))
    with Image.open(r.output_path) as out:
        assert "icc_profile" not in out.info


def test_rgba_to_jpeg_flattens_on_background(tmp_images):
    src = tmp_images / "alpha.png"
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(src)
    r = process_image(src, settings(output_format="JPEG", bg_color="#00ff00", compress_mode="quality"))
    assert r.success and r.output_path.endswith(".jpg")
    with Image.open(r.output_path) as out:
        r_, g, b = out.convert("RGB").getpixel((5, 5))
        assert g > 240 and r_ < 15 and b < 15


@pytest.mark.parametrize("mode", ["I;16", "CMYK", "P", "LA", "1"])
@pytest.mark.parametrize("fmt", ["JPEG", "WEBP", "PNG"])
def test_exotic_modes_encode(tmp_images, mode, fmt):
    base = noise_image((64, 48))
    if mode == "I;16":
        src_img = base.convert("L").point(lambda v: v * 256).convert("I;16")
        ext = ".png"
    elif mode == "CMYK":
        src_img, ext = base.convert("CMYK"), ".jpg"
    elif mode == "P":
        src_img = base.convert("P")
        src_img.info["transparency"] = 0
        ext = ".png"
    else:
        src_img, ext = base.convert(mode), ".png"
    src = tmp_images / f"m{ext}"
    src_img.save(src)
    r = process_image(src, settings(output_format=fmt, compress_mode="quality", resize_enabled=True, max_width=32))
    assert r.success, r.error
    assert r.new_dimensions == (32, 24)


def test_palette_with_transparency_keeps_alpha_in_webp(tmp_images):
    src = tmp_images / "p.png"
    img = Image.new("P", (20, 20), 0)
    img.putpalette([255, 0, 0] * 256)
    img.info["transparency"] = 0
    img.save(src, transparency=0)
    r = process_image(src, settings(output_format="WEBP", compress_mode="quality"))
    with Image.open(r.output_path) as out:
        assert out.mode == "RGBA"


def test_png_target_size_quantizes(tmp_images):
    src = tmp_images / "big.png"
    noise_image((400, 400)).save(src)
    r = process_image(src, settings(target_size=120, target_unit="KB"))
    assert r.success
    assert r.method_used.startswith("png_")


@pytest.mark.skipif(not features.check("avif"), reason="AVIF not available")
def test_avif_output(tmp_images):
    src = jpeg_with_metadata(tmp_images / "a.jpg")
    r = process_image(src, settings(output_format="AVIF", compress_mode="quality", quality=50))
    assert r.success and r.output_path.endswith(".avif")


def test_animated_gif_warns_when_edited(tmp_images):
    src = tmp_images / "anim.gif"
    frames = [Image.new("RGB", (40, 40), c) for c in ("red", "blue")]
    frames[0].save(src, save_all=True, append_images=frames[1:], duration=100)
    r = process_image(src, settings(output_format="PNG", compress_mode="quality"))
    assert r.success
    assert any("first frame" in w for w in r.warnings)
    untouched = process_image(src, settings(compress_mode="lossless", naming_suffix="_same"))
    assert untouched.method_used == "copy"


# ── resize ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "opts, expected",
    [
        ({"resize_mode": "fit", "max_width": 200}, (200, 150)),
        ({"resize_mode": "fit", "max_width": 2000}, (800, 600)),
        ({"resize_mode": "fit", "max_width": 2000, "allow_enlarge": True}, (2000, 1500)),
        ({"resize_mode": "exact", "exact_width": 300, "exact_height": 300, "fit_mode": "cover"}, (300, 300)),
        ({"resize_mode": "exact", "exact_width": 300, "exact_height": 300, "fit_mode": "contain"}, (300, 225)),
        ({"resize_mode": "exact", "exact_width": 300, "exact_height": 300, "fit_mode": "pad"}, (300, 300)),
        ({"resize_mode": "exact", "exact_width": 400}, (400, 300)),
        ({"resize_mode": "scale", "scale_percent": 25}, (200, 150)),
    ],
)
def test_resize_modes(tmp_images, opts, expected):
    src = tmp_images / "r.png"
    noise_image((800, 600)).save(src)
    r = process_image(src, settings(resize_enabled=True, compress_mode="quality", **opts))
    assert r.success, r.error
    assert r.new_dimensions == expected


def test_upscale_has_a_pixel_budget(tmp_images):
    src = tmp_images / "big.png"
    Image.new("RGB", (8000, 8000)).save(src)
    r = process_image(src, settings(upscale_enabled=True, upscale_factor=8), return_bytes=True)
    assert not r.success and "safety limit" in r.error


# ── output handling ───────────────────────────────────────────────────────
def test_conflict_policies(tmp_images):
    src = jpeg_with_metadata(tmp_images / "a.jpg")
    first = process_image(src, settings(on_conflict="overwrite"))
    again = process_image(src, settings(on_conflict="overwrite"))
    assert first.output_path == again.output_path

    renamed = process_image(src, settings(on_conflict="rename"))
    assert renamed.output_path != first.output_path and renamed.output_path.endswith("-1.jpg")

    skipped = process_image(src, settings(on_conflict="skip"))
    assert skipped.skipped and skipped.method_used == "skipped"


def test_refuses_to_overwrite_original_without_permission(tmp_images):
    src = jpeg_with_metadata(tmp_images / "a.jpg")
    before = src.read_bytes()
    r = process_image(src, settings(output_dir=str(tmp_images), naming_suffix=""))
    assert not r.success and "original" in r.error
    assert src.read_bytes() == before

    replaced = process_image(src, settings(replace_originals=True, compress_mode="quality", quality=50))
    assert replaced.success and replaced.output_path == str(src)
    assert src.read_bytes() != before


def test_relative_output_dir_is_relative_to_source(tmp_images):
    src = tmp_images / "x.png"
    Image.new("RGB", (4, 4)).save(src)
    out = plan_output_path(src, "PNG", settings(output_dir="web", naming_prefix="p_", output_format="WEBP"))
    assert out == tmp_images / "web" / "p_x_processed.webp"


def test_preserve_dates(tmp_images):
    import os

    src = jpeg_with_metadata(tmp_images / "a.jpg")
    os.utime(src, (1_000_000_000, 1_000_000_000))
    r = process_image(src, settings(preserve_dates=True, compress_mode="quality"))
    assert int(Path(r.output_path).stat().st_mtime) == 1_000_000_000


def test_corrupt_file_reports_friendly_error(tmp_images):
    bad = tmp_images / "bad.jpg"
    bad.write_bytes(b"definitely not a jpeg")
    r = process_image(bad, settings())
    assert not r.success and "supported image" in r.error
    assert not (tmp_images / "processed").exists() or not any((tmp_images / "processed").iterdir())


def test_missing_file(tmp_images):
    r = process_image(tmp_images / "nope.jpg", settings())
    assert not r.success and "not found" in r.error.lower()


def test_strip_jpeg_metadata_rejects_garbage():
    with pytest.raises(ValueError):
        strip_jpeg_metadata(b"\xff\xd8\xff\xe1\x00", keep_icc=False)
    with pytest.raises(ValueError):
        strip_jpeg_metadata(b"PNG", keep_icc=False)


def test_discover_skips_hidden_and_processed(tmp_images):
    for rel in ("a.jpg", "sub/b.png", ".hidden/c.jpg", "processed/d.jpg", "._e.jpg", "notes.txt"):
        path = tmp_images / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    names = sorted(p.name for p in discover_images([str(tmp_images)]))
    assert names == ["a.jpg", "b.png"]
    assert [p.name for p in discover_images([str(tmp_images)], recursive=False)] == ["a.jpg"]

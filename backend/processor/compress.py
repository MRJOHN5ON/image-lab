"""Encoders: lossless JPEG paths (segment strip, jpegtran), quality search, PNG/WEBP/AVIF/TIFF."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from PIL import Image

from .convert import has_alpha

# GUI apps launched from Finder don't inherit the shell PATH, so look where Homebrew/MacPorts install.
_EXTRA_BIN_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin")

_AVIF_SUBSAMPLING = {0: "4:4:4", 1: "4:2:2", 2: "4:2:0"}


@dataclass
class EncodeOptions:
    quality: int = 85
    progressive: bool = True
    subsampling: int = 0
    png_palette: bool = False
    png_colors: int = 256
    exif: Optional[bytes] = None
    icc_profile: Optional[bytes] = None
    dpi: Optional[Tuple[float, float]] = None


@dataclass
class EncodeResult:
    data: bytes
    quality: Optional[int]
    method: str
    reached_target: bool = True


@lru_cache(maxsize=1)
def jpegtran_path() -> Optional[str]:
    override = os.environ.get("IMAGE_LAB_JPEGTRAN", "").strip()
    if override:
        return override if os.access(override, os.X_OK) else None
    found = shutil.which("jpegtran")
    if found:
        return found
    for directory in _EXTRA_BIN_DIRS:
        candidate = Path(directory) / "jpegtran"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def jpegtran_available() -> bool:
    return jpegtran_path() is not None


def jpegtran_optimize(data: bytes, *, progressive: bool = True) -> Optional[bytes]:
    """Lossless Huffman optimisation. Keeps every marker; metadata is stripped separately."""
    exe = jpegtran_path()
    if not exe:
        return None
    args = [exe, "-copy", "all", "-optimize"]
    if progressive:
        args.append("-progressive")
    try:
        result = subprocess.run(args, input=data, capture_output=True, timeout=120)
    except (subprocess.SubprocessError, OSError):
        return None
    if result.returncode != 0 or not result.stdout.startswith(b"\xff\xd8"):
        return None
    return result.stdout


_STANDALONE_MARKERS = {0x01, *range(0xD0, 0xD8)}


def strip_jpeg_metadata(data: bytes, *, keep_icc: bool) -> bytes:
    """Drop EXIF/XMP/IPTC/comments from a JPEG without touching the compressed image data.

    Keeps JFIF (APP0), Adobe (APP14, needed for correct colour decoding) and optionally
    the ICC profile (APP2 "ICC_PROFILE").
    """
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("Not a JPEG stream")
    out = bytearray(b"\xff\xd8")
    i, n = 2, len(data)
    while i < n:
        if data[i] != 0xFF:
            raise ValueError("Corrupt JPEG marker stream")
        while i < n and data[i] == 0xFF:
            i += 1
        if i >= n:
            break
        marker = data[i]
        i += 1
        if marker == 0xDA or marker == 0xD9:
            out += bytes((0xFF, marker)) + data[i:]
            return bytes(out)
        if marker in _STANDALONE_MARKERS:
            out += bytes((0xFF, marker))
            continue
        if i + 2 > n:
            raise ValueError("Truncated JPEG segment")
        length = int.from_bytes(data[i : i + 2], "big")
        if length < 2 or i + length > n:
            raise ValueError("Invalid JPEG segment length")
        segment = data[i : i + length]
        i += length

        keep = True
        if 0xE1 <= marker <= 0xEF or marker == 0xFE:
            keep = marker == 0xEE or (
                marker == 0xE2 and keep_icc and segment[2:14] == b"ICC_PROFILE\x00"
            )
        if keep:
            out += bytes((0xFF, marker)) + segment
    raise ValueError("JPEG has no image data")


def insert_orientation(data: bytes, orientation: int) -> bytes:
    """Add a minimal EXIF block holding only the orientation tag (after SOI/APP0)."""
    exif = Image.Exif()
    exif[0x0112] = orientation
    payload = exif.tobytes()
    segment = b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload
    pos = 2
    if data[2:4] == b"\xff\xe0":
        pos = 4 + int.from_bytes(data[4:6], "big")
    return data[:pos] + segment + data[pos:]


def _metadata_kwargs(fmt: str, opts: EncodeOptions) -> dict:
    kwargs: dict = {}
    if opts.icc_profile and fmt in ("JPEG", "PNG", "WEBP", "AVIF", "TIFF"):
        kwargs["icc_profile"] = opts.icc_profile
    if opts.exif and fmt in ("JPEG", "PNG", "WEBP", "AVIF"):
        kwargs["exif"] = opts.exif
    if opts.dpi and fmt in ("JPEG", "PNG", "TIFF"):
        kwargs["dpi"] = opts.dpi
    return kwargs


def quantize(img: Image.Image, colors: int) -> Image.Image:
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if has_alpha(img) else "RGB")
    return img.quantize(
        colors=colors,
        method=Image.Quantize.FASTOCTREE,
        dither=Image.Dither.FLOYDSTEINBERG,
    )


def encode_once(
    img: Image.Image,
    fmt: str,
    opts: EncodeOptions,
    *,
    quality: Optional[int] = None,
    lossless: bool = False,
    palette_colors: Optional[int] = None,
    draft: bool = False,
    progressive: Optional[bool] = None,
) -> bytes:
    """draft: fastest JPEG encoding, used only to measure sizes (about 7× faster)."""
    q = quality if quality is not None else opts.quality
    buf = io.BytesIO()
    meta = _metadata_kwargs(fmt, opts)

    if fmt == "JPEG":
        img.save(
            buf,
            format="JPEG",
            quality=q,
            optimize=not draft,
            progressive=False if draft else (opts.progressive if progressive is None else progressive),
            subsampling=opts.subsampling,
            **meta,
        )
    elif fmt == "PNG":
        work = quantize(img, palette_colors) if palette_colors else img
        work.save(buf, format="PNG", optimize=True, **meta)
    elif fmt == "WEBP":
        if lossless:
            img.save(buf, format="WEBP", lossless=True, quality=100, method=6, **meta)
        else:
            img.save(buf, format="WEBP", quality=q, method=5, **meta)
    elif fmt == "AVIF":
        params = {"quality": 100 if lossless else q, "speed": 6}
        subsampling = _AVIF_SUBSAMPLING.get(opts.subsampling)
        if subsampling:
            params["subsampling"] = "4:4:4" if lossless else subsampling
        try:
            img.save(buf, format="AVIF", **params, **meta)
        except TypeError:
            buf = io.BytesIO()
            img.save(buf, format="AVIF", quality=params["quality"], **meta)
    elif fmt == "TIFF":
        img.save(buf, format="TIFF", compression="tiff_lzw", **meta)
    elif fmt == "GIF":
        img.save(buf, format="GIF", optimize=True)
    else:
        img.save(buf, format=fmt, **meta)
    return buf.getvalue()


def search_quality(
    encode: Callable[[int], bytes],
    limit: int,
    *,
    lo: int = 1,
    hi: int = 95,
) -> Tuple[bytes, int, bool]:
    """Highest quality in [lo, hi] whose output fits `limit` bytes."""
    top = encode(hi)
    if len(top) <= limit:
        return top, hi, True

    best: Optional[bytes] = None
    best_q = lo
    hi -= 1
    while lo <= hi:
        mid = (lo + hi) // 2
        data = encode(mid)
        if len(data) <= limit:
            best, best_q = data, mid
            lo = mid + 1
        else:
            hi = mid - 1

    if best is None:
        floor = 1
        return encode(floor), floor, False
    return best, best_q, True


def _jpeg_target(img: Image.Image, opts: EncodeOptions, limit: int) -> EncodeResult:
    """Search on fast baseline encodes, then encode the winner properly.

    Optimised Huffman tables never make a baseline JPEG larger than the unoptimised draft,
    so the optimised baseline is a guaranteed fallback if progressive comes out bigger.
    """
    drafts: Dict[int, bytes] = {}

    def draft(quality: int) -> bytes:
        if quality not in drafts:
            drafts[quality] = encode_once(img, "JPEG", opts, quality=quality, draft=True)
        return drafts[quality]

    def final(quality: int) -> bytes:
        data = encode_once(img, "JPEG", opts, quality=quality)
        if len(data) > limit and opts.progressive:
            data = encode_once(img, "JPEG", opts, quality=quality, progressive=False)
        return data

    hi = opts.quality
    _, q, ok = search_quality(draft, limit, hi=hi)
    if not ok:
        # Even the roughest draft is too big; the real encoder may still fit, so search on it.
        data, q, ok = search_quality(final, limit, hi=hi)
        return EncodeResult(data, q, "reencode", ok)
    data = final(q)
    # Drafts run ~10–20% larger than the final encode; search again with that ratio so
    # the file uses the budget instead of landing well under it.
    if ok and q < hi and len(data) <= limit:
        ratio = len(data) / len(draft(q))
        _, q2, ok2 = search_quality(draft, int(limit / ratio), lo=q + 1, hi=hi)
        # The calibrated guess is usually exact or one step high, so walk down from it.
        for guess in range(q2 if ok2 else q + 1, q, -1):
            candidate = final(guess)
            if len(candidate) <= limit:
                data, q = candidate, guess
                break
    return EncodeResult(data, q, "reencode", ok and len(data) <= limit)


_PALETTE_LADDER = (256, 128, 64, 32, 16)


def encode(
    img: Image.Image,
    fmt: str,
    opts: EncodeOptions,
    *,
    mode: str,
    limit_bytes: Optional[int] = None,
) -> EncodeResult:
    """mode: 'quality' | 'target_size' | 'lossless'."""
    if fmt in ("JPEG", "WEBP", "AVIF"):
        if mode == "lossless" and fmt != "JPEG":
            return EncodeResult(encode_once(img, fmt, opts, lossless=True), None, f"{fmt.lower()}_lossless")
        if mode == "target_size" and limit_bytes and fmt == "JPEG":
            return _jpeg_target(img, opts, limit_bytes)
        if mode == "target_size" and limit_bytes:
            data, q, ok = search_quality(
                lambda quality: encode_once(img, fmt, opts, quality=quality),
                limit_bytes,
                hi=opts.quality,
            )
            return EncodeResult(data, q, "reencode", ok)
        return EncodeResult(encode_once(img, fmt, opts), opts.quality, "reencode")

    if fmt == "PNG":
        if mode == "target_size" and limit_bytes:
            data = encode_once(img, fmt, opts)
            if len(data) <= limit_bytes:
                return EncodeResult(data, None, "png_optimize")
            smallest = data
            for colors in _PALETTE_LADDER:
                data = encode_once(img, fmt, opts, palette_colors=colors)
                if len(data) <= limit_bytes:
                    return EncodeResult(data, None, f"png_{colors}_colors")
                if len(data) < len(smallest):
                    smallest = data
            return EncodeResult(smallest, None, "png_quantized", False)
        if opts.png_palette and mode != "lossless":
            colors = opts.png_colors
            return EncodeResult(encode_once(img, fmt, opts, palette_colors=colors), None, f"png_{colors}_colors")
        return EncodeResult(encode_once(img, fmt, opts), None, "png_optimize")

    data = encode_once(img, fmt, opts)
    reached = not (mode == "target_size" and limit_bytes and len(data) > limit_bytes)
    return EncodeResult(data, None, fmt.lower(), reached)

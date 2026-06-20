#!/usr/bin/env python3
"""CLI JPEG compressor — target max file size with lossless jpegtran first."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from processor.pipeline import ProcessingSettings, process_image


def main() -> int:
    parser = argparse.ArgumentParser(description="Compress JPEG to target max size")
    parser.add_argument("input", type=Path, help="Input JPEG file")
    parser.add_argument("-o", "--output", type=Path, help="Output path")
    parser.add_argument("-m", "--max-mb", type=float, default=12.0, help="Max size in MB (default: 12)")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: {args.input} not found", file=sys.stderr)
        return 1

    settings = ProcessingSettings(
        compress_enabled=True,
        compress_mode="target_size",
        target_size_mb=args.max_mb,
        lossless_first=True,
        strip_exif=True,
        output_dir=str(args.output.parent) if args.output else None,
        naming_suffix="" if args.output else "_compressed",
    )

    result = process_image(args.input, settings, output_path=args.output)
    if not result.success:
        print(f"Error: {result.error}", file=sys.stderr)
        return 1

    orig_mb = result.original_size / (1024 * 1024)
    new_mb = result.new_size / (1024 * 1024)
    print(f"{args.input.name}: {orig_mb:.2f} MB → {new_mb:.2f} MB ({result.method_used})")
    if result.output_path:
        print(f"Saved: {result.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

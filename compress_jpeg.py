#!/usr/bin/env python3
"""CLI: compress images to a target max size — same engine as the app."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from processor.pipeline import (  # noqa: E402
    ProcessingSettings,
    SettingsError,
    discover_images,
    format_bytes,
    process_image,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compress images to a target max size (lossless first)")
    parser.add_argument("inputs", nargs="+", type=Path, help="Image files or folders")
    parser.add_argument("-o", "--output", type=Path, help="Output file (single input) or folder")
    parser.add_argument("-m", "--max-mb", type=float, default=12.0, help="Max size in MB (default: 12)")
    parser.add_argument("-q", "--max-quality", type=int, default=95, help="Highest JPEG quality to try")
    parser.add_argument("-f", "--format", default="keep", help="keep | JPEG | PNG | WEBP | AVIF | TIFF")
    parser.add_argument("--keep-metadata", action="store_true", help="Keep EXIF/GPS metadata")
    args = parser.parse_args()

    files = discover_images([str(p) for p in args.inputs])
    if not files:
        print("Error: no supported images found", file=sys.stderr)
        return 1

    single_output = args.output if args.output and len(files) == 1 and args.output.suffix else None
    try:
        settings = ProcessingSettings.from_dict(
            {
                "compress_mode": "target_size",
                "target_size": args.max_mb,
                "target_unit": "MB",
                "quality": args.max_quality,
                "output_format": args.format,
                "strip_metadata": not args.keep_metadata,
                "output_dir": str(args.output) if args.output and not single_output else None,
                "naming_suffix": "_compressed",
            }
        )
    except SettingsError as exc:
        print(f"Error: {exc.message}", file=sys.stderr)
        return 2

    failures = 0
    for path in files:
        result = process_image(path, settings, output_path=single_output)
        if not result.success:
            failures += 1
            print(f"✗ {path.name}: {result.error}", file=sys.stderr)
            continue
        detail = result.method_used + (f" q{result.quality_used}" if result.quality_used else "")
        print(
            f"✓ {path.name}: {format_bytes(result.original_size)} → {format_bytes(result.new_size)} "
            f"({detail}) → {result.output_path}"
        )
        for warning in result.warnings:
            print(f"  ! {warning}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

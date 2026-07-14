#!/usr/bin/env python3
"""Crop a selector-bound image into a new, exclusively created output."""

from __future__ import annotations

import argparse
import io
import sys

from safe_image_io import (
    ScreenshotSafetyError,
    read_image_snapshot,
    reject_pillow_decompression_bombs,
    require_absent_output,
    require_bounded_image_dimensions,
    require_distinct_paths,
    save_image_exclusive,
)


def _coordinates(value: str, option: str) -> tuple[int, int, int, int]:
    try:
        coordinates = tuple(int(item.strip()) for item in value.split(","))
        if len(coordinates) != 4:
            raise ValueError
        return coordinates
    except ValueError as exc:
        raise ScreenshotSafetyError(
            f'{option} must use the form "x1,y1,x2,y2"'
        ) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="crop one selector-bound image")
    parser.add_argument("--input", required=True)
    parser.add_argument("--input-identity", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--crop", required=True)
    parser.add_argument("--resize")
    args = parser.parse_args(argv)

    try:
        require_distinct_paths(args.input, args.output)
        require_absent_output(args.output)
        crop = _coordinates(args.crop, "--crop")
        snapshot = read_image_snapshot(args.input, args.input_identity)
    except ScreenshotSafetyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        from PIL import Image
    except ImportError:
        print("ERROR: Pillow is required for image processing", file=sys.stderr)
        return 1

    try:
        with reject_pillow_decompression_bombs(Image):
            with Image.open(io.BytesIO(snapshot.data)) as source:
                width, height = source.size
                require_bounded_image_dimensions(width, height)
                source.load()
                x1, y1, x2, y2 = crop
                x1 = max(0, min(x1, width))
                y1 = max(0, min(y1, height))
                x2 = max(x1, min(x2, width))
                y2 = max(y1, min(y2, height))
                if x2 <= x1 or y2 <= y1:
                    raise ScreenshotSafetyError("crop has zero area after clipping")
                result = source.crop((x1, y1, x2, y2))

        if args.resize:
            try:
                resize = tuple(int(item.strip()) for item in args.resize.split(","))
                if len(resize) != 2 or resize[0] <= 0 or resize[1] <= 0:
                    raise ValueError
            except ValueError as exc:
                raise ScreenshotSafetyError(
                    '--resize must use positive "width,height" values'
                ) from exc
            require_bounded_image_dimensions(*resize)
            result = result.resize(resize, Image.Resampling.LANCZOS)

        save_image_exclusive(result, args.output)
    except ScreenshotSafetyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: image processing failed: {exc}", file=sys.stderr)
        return 1

    print(f"OK: {args.output} ({result.size[0]}x{result.size[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

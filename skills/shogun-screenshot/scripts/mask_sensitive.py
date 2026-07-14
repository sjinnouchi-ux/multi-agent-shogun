#!/usr/bin/env python3
"""Opaque-mask effective regions in a selector-bound image."""

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


def _triplet(value: str) -> tuple[int, int, int]:
    try:
        result = tuple(int(item.strip()) for item in value.split(","))
        if len(result) != 3 or any(item < 0 or item > 255 for item in result):
            raise ValueError
        return result
    except ValueError as exc:
        raise ScreenshotSafetyError(
            '--color must use three values from 0 to 255: "R,G,B"'
        ) from exc


def _region(value: str, index: int) -> tuple[int, int, int, int]:
    try:
        result = tuple(int(item.strip()) for item in value.split(","))
        if len(result) != 4:
            raise ValueError
        return result
    except ValueError as exc:
        raise ScreenshotSafetyError(
            f'region {index} must use the form "x1,y1,x2,y2"'
        ) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="mask one selector-bound image")
    parser.add_argument("--input", required=True)
    parser.add_argument("--input-identity", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--regions", nargs="+", required=True)
    parser.add_argument("--color", default="0,0,0")
    parser.add_argument("--preview", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.preview:
        print(
            "ERROR: preview output is forbidden because it contains unredacted data",
            file=sys.stderr,
        )
        return 2

    try:
        require_distinct_paths(args.input, args.output)
        require_absent_output(args.output)
        fill_color = _triplet(args.color)
        snapshot = read_image_snapshot(args.input, args.input_identity)
    except ScreenshotSafetyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("ERROR: Pillow is required for image processing", file=sys.stderr)
        return 1

    try:
        with reject_pillow_decompression_bombs(Image):
            with Image.open(io.BytesIO(snapshot.data)) as source:
                require_bounded_image_dimensions(*source.size)
                source.load()
                result = source.copy()
        width, height = result.size

        clipped_regions: list[tuple[int, int, int, int]] = []
        for index, value in enumerate(args.regions, 1):
            x1, y1, x2, y2 = _region(value, index)
            if x2 <= x1 or y2 <= y1:
                raise ScreenshotSafetyError(f"region {index} has zero area")
            clipped = (
                max(0, min(x1, width)),
                max(0, min(y1, height)),
                max(0, min(x2, width)),
                max(0, min(y2, height)),
            )
            if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
                raise ScreenshotSafetyError(
                    f"region {index} does not overlap the image"
                )
            clipped_regions.append(clipped)

        draw = ImageDraw.Draw(result)
        for x1, y1, x2, y2 in clipped_regions:
            draw.rectangle((x1, y1, x2 - 1, y2 - 1), fill=fill_color)

        save_image_exclusive(result, args.output)
    except ScreenshotSafetyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: image processing failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"OK: {args.output} ({width}x{height}, {len(clipped_regions)} regions masked)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

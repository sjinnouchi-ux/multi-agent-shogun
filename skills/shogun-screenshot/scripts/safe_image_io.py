#!/usr/bin/env python3
"""Race-resistant input selection and exclusive image output helpers."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import errno
import hashlib
import hmac
import json
import os
import secrets
import stat
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_IMAGE_DIMENSION = 16_384
MAX_IMAGE_PIXELS = 40_000_000


class ScreenshotSafetyError(Exception):
    """An image operation would violate the screenshot safety boundary."""


@dataclass(frozen=True)
class ImageSnapshot:
    canonical_path: str
    identity: str
    data: bytes


def _canonical_leaf_path(raw_path: str | os.PathLike[str]) -> str:
    path = os.fspath(raw_path)
    if not path or "\n" in path or "\r" in path:
        raise ScreenshotSafetyError("image path is empty or contains a line break")
    absolute = os.path.abspath(path)
    parent, leaf = os.path.split(absolute)
    if not leaf:
        raise ScreenshotSafetyError("image path must name one file")
    return os.path.join(os.path.realpath(parent), leaf)


def paths_are_same_leaf(
    input_path: str | os.PathLike[str], output_path: str | os.PathLike[str]
) -> bool:
    return os.path.normcase(_canonical_leaf_path(input_path)) == os.path.normcase(
        _canonical_leaf_path(output_path)
    )


def require_distinct_paths(
    input_path: str | os.PathLike[str], output_path: str | os.PathLike[str]
) -> None:
    if paths_are_same_leaf(input_path, output_path):
        raise ScreenshotSafetyError("input and output must differ")


def _fingerprint(file_stat: os.stat_result) -> tuple[int, ...]:
    return (
        int(file_stat.st_dev),
        int(file_stat.st_ino),
        int(file_stat.st_mode),
        int(file_stat.st_size),
        int(file_stat.st_mtime_ns),
        int(file_stat.st_ctime_ns),
    )


def _validate_image_signature(path: str, data: bytes) -> None:
    suffix = Path(path).suffix.lower()
    if suffix == ".png":
        valid = data.startswith(b"\x89PNG\r\n\x1a\n")
        kind = "PNG"
    elif suffix in {".jpg", ".jpeg"}:
        valid = data.startswith(b"\xff\xd8\xff")
        kind = "JPEG"
    else:
        raise ScreenshotSafetyError("input extension must be .png, .jpg, or .jpeg")
    if not valid:
        raise ScreenshotSafetyError(f"input does not have a valid {kind} signature")


def _identity_for(file_stat: os.stat_result, data: bytes) -> str:
    content_hash = hashlib.sha256(data).hexdigest()
    material = json.dumps(
        ["shogun-image-v1", *_fingerprint(file_stat), content_hash],
        separators=(",", ":"),
    ).encode("ascii")
    return f"sha256:{hashlib.sha256(material).hexdigest()}"


def read_image_snapshot(
    raw_path: str | os.PathLike[str], expected_identity: str | None = None
) -> ImageSnapshot:
    """Read one coherent regular-file snapshot without following a leaf symlink."""

    canonical_path = _canonical_leaf_path(raw_path)
    try:
        before = os.lstat(raw_path)
    except FileNotFoundError as exc:
        raise ScreenshotSafetyError("input must be an existing regular file") from exc
    except OSError as exc:
        raise ScreenshotSafetyError(f"cannot inspect input: {exc.strerror or exc}") from exc

    if stat.S_ISLNK(before.st_mode):
        raise ScreenshotSafetyError("symlink images are not accepted")
    if not stat.S_ISREG(before.st_mode):
        raise ScreenshotSafetyError("input must be an existing regular file")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(raw_path, flags)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOENT}:
            raise ScreenshotSafetyError("input changed or became a symlink") from exc
        raise ScreenshotSafetyError(f"cannot open input: {exc.strerror or exc}") from exc

    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _fingerprint(opened) != _fingerprint(before):
            raise ScreenshotSafetyError("input changed while it was being selected")
        if opened.st_size > MAX_INPUT_BYTES:
            raise ScreenshotSafetyError(
                f"input exceeds the {MAX_INPUT_BYTES}-byte limit"
            )

        chunks: list[bytes] = []
        total_bytes = 0
        while True:
            remaining_with_sentinel = MAX_INPUT_BYTES - total_bytes + 1
            chunk = os.read(descriptor, min(1024 * 1024, remaining_with_sentinel))
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > MAX_INPUT_BYTES:
                raise ScreenshotSafetyError(
                    f"input exceeds the {MAX_INPUT_BYTES}-byte limit"
                )
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)

    if _fingerprint(after) != _fingerprint(opened):
        raise ScreenshotSafetyError("input changed while it was being read")

    data = b"".join(chunks)
    _validate_image_signature(canonical_path, data)
    identity = _identity_for(opened, data)
    if expected_identity is not None:
        try:
            expected_bytes = expected_identity.encode("ascii")
        except UnicodeEncodeError:
            expected_bytes = b""
        valid_shape = (
            len(expected_bytes) == 71
            and expected_bytes.startswith(b"sha256:")
            and all(byte in b"0123456789abcdef" for byte in expected_bytes[7:])
        )
        if not valid_shape or not hmac.compare_digest(
            identity.encode("ascii"), expected_bytes
        ):
            raise ScreenshotSafetyError(
                "input identity mismatch; select the image again"
            )

    return ImageSnapshot(canonical_path=canonical_path, identity=identity, data=data)


def selection_record(raw_path: str | os.PathLike[str]) -> dict[str, str]:
    snapshot = read_image_snapshot(raw_path)
    return {"path": snapshot.canonical_path, "identity": snapshot.identity}


def require_bounded_image_dimensions(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise ScreenshotSafetyError("image dimensions must be positive")
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        raise ScreenshotSafetyError(
            f"maximum dimension is {MAX_IMAGE_DIMENSION} pixels"
        )
    if width * height > MAX_IMAGE_PIXELS:
        raise ScreenshotSafetyError(
            f"maximum pixel count is {MAX_IMAGE_PIXELS}"
        )


@contextmanager
def reject_pillow_decompression_bombs(image_module: Any):
    """Convert Pillow's decompression-bomb warning and error into a safety failure."""

    bomb_types: list[type[BaseException]] = []
    for name in ("DecompressionBombWarning", "DecompressionBombError"):
        candidate = getattr(image_module, name, None)
        if (
            isinstance(candidate, type)
            and issubclass(candidate, BaseException)
            and candidate not in bomb_types
        ):
            bomb_types.append(candidate)

    warning_type = getattr(image_module, "DecompressionBombWarning", None)
    previous_pixel_limit = getattr(image_module, "MAX_IMAGE_PIXELS", None)
    image_module.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with warnings.catch_warnings():
            if (
                isinstance(warning_type, type)
                and issubclass(warning_type, Warning)
            ):
                warnings.simplefilter("error", warning_type)
            try:
                yield
            except tuple(bomb_types) as exc:
                raise ScreenshotSafetyError(
                    "Pillow decompression bomb detected"
                ) from exc
    finally:
        image_module.MAX_IMAGE_PIXELS = previous_pixel_limit


def _output_format(output_name: str) -> str:
    suffix = Path(output_name).suffix.lower()
    if suffix == ".png":
        return "PNG"
    if suffix in {".jpg", ".jpeg"}:
        return "JPEG"
    raise ScreenshotSafetyError("output extension must be .png, .jpg, or .jpeg")


def _entry_exists(parent_descriptor: int, leaf: str, absolute_path: str) -> bool:
    try:
        os.stat(leaf, dir_fd=parent_descriptor, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False
    except (NotImplementedError, TypeError):
        return os.path.lexists(absolute_path)


def require_absent_output(raw_output_path: str | os.PathLike[str]) -> None:
    """Fail early for an existing output; the commit repeats this check atomically."""

    output_path = _canonical_leaf_path(raw_output_path)
    parent_path, output_name = os.path.split(output_path)
    _output_format(output_name)
    directory_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(
        os, "O_DIRECTORY", 0
    )
    try:
        parent_descriptor = os.open(parent_path, directory_flags)
    except OSError as exc:
        raise ScreenshotSafetyError(
            f"output parent must be an existing directory: {exc.strerror or exc}"
        ) from exc
    try:
        if _entry_exists(parent_descriptor, output_name, output_path):
            raise ScreenshotSafetyError(
                "output already exists; refusing to overwrite it"
            )
    finally:
        os.close(parent_descriptor)


def _link_without_replace(
    parent_descriptor: int,
    parent_path: str,
    temporary_name: str,
    output_name: str,
) -> None:
    try:
        os.link(
            temporary_name,
            output_name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except (NotImplementedError, TypeError):
        os.link(
            os.path.join(parent_path, temporary_name),
            os.path.join(parent_path, output_name),
            follow_symlinks=False,
        )


def save_image_exclusive(image: Any, raw_output_path: str | os.PathLike[str]) -> None:
    """Save to a private sibling and atomically link it into an absent output leaf."""

    output_path = _canonical_leaf_path(raw_output_path)
    parent_path, output_name = os.path.split(output_path)
    image_format = _output_format(output_name)
    directory_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(
        os, "O_DIRECTORY", 0
    )
    try:
        parent_descriptor = os.open(parent_path, directory_flags)
    except OSError as exc:
        raise ScreenshotSafetyError(
            f"output parent must be an existing directory: {exc.strerror or exc}"
        ) from exc

    temporary_name: str | None = None
    temporary_descriptor: int | None = None
    try:
        if _entry_exists(parent_descriptor, output_name, output_path):
            raise ScreenshotSafetyError(
                "output already exists; refusing to overwrite it"
            )

        open_flags = (
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        for _ in range(128):
            temporary_name = (
                f".{output_name[:64]}.tmp-{secrets.token_hex(16)}"
            )
            try:
                temporary_descriptor = os.open(
                    temporary_name,
                    open_flags,
                    0o600,
                    dir_fd=parent_descriptor,
                )
                break
            except FileExistsError:
                continue
        else:
            raise ScreenshotSafetyError("could not reserve a private output temporary")

        with os.fdopen(temporary_descriptor, "w+b") as temporary_file:
            temporary_descriptor = None
            image.save(temporary_file, format=image_format)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        try:
            _link_without_replace(
                parent_descriptor, parent_path, temporary_name, output_name
            )
        except FileExistsError as exc:
            raise ScreenshotSafetyError(
                "output already exists; refusing to overwrite it"
            ) from exc
        except OSError as exc:
            raise ScreenshotSafetyError(
                f"cannot atomically create output: {exc.strerror or exc}"
            ) from exc
    finally:
        if temporary_descriptor is not None:
            os.close(temporary_descriptor)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass
        os.close(parent_descriptor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="select one bounded local image")
    parser.add_argument("--select", required=True, metavar="FILE")
    args = parser.parse_args(argv)
    try:
        record = selection_record(args.select)
    except ScreenshotSafetyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

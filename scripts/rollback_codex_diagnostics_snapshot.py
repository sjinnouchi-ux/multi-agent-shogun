#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Sequence

SNAPSHOT_PATH = Path("/home/jinnouchi/.local/libexec/shogun-codex-diagnostics")
MAX_SOURCE_BYTES = 1_048_576
SHA256 = re.compile(r"[0-9a-f]{64}")


class RollbackRefused(Exception):
    pass


class RollbackCommittedIndeterminate(Exception):
    pass


def _stat_key(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        stat.S_IMODE(value.st_mode),
    )


def _read_regular(path: Path, required_mode: int | None) -> bytes:
    if not hasattr(os, "O_NOFOLLOW"):
        raise RollbackRefused
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise RollbackRefused from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise RollbackRefused
        if required_mode is not None and stat.S_IMODE(before.st_mode) != required_mode:
            raise RollbackRefused
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_SOURCE_BYTES:
            chunk = os.read(fd, min(65_536, MAX_SOURCE_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > MAX_SOURCE_BYTES:
            raise RollbackRefused
        after = os.fstat(fd)
        if _stat_key(before) != _stat_key(after):
            raise RollbackRefused
        return b"".join(chunks)
    except OSError as exc:
        raise RollbackRefused from exc
    finally:
        os.close(fd)


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_rollback(
    *,
    snapshot: Path,
    target_blob: Path,
    failing_sha256: str,
    target_sha256: str,
) -> None:
    if SHA256.fullmatch(failing_sha256) is None or SHA256.fullmatch(
        target_sha256
    ) is None:
        raise RollbackRefused
    if failing_sha256 == target_sha256:
        raise RollbackRefused
    current = _read_regular(snapshot, 0o555)
    if _digest(current) != failing_sha256:
        raise RollbackRefused
    target = _read_regular(target_blob, None)
    if _digest(target) != target_sha256:
        raise RollbackRefused
    parent = snapshot.parent
    parent_before = os.lstat(parent)
    if not stat.S_ISDIR(parent_before.st_mode) or stat.S_ISLNK(parent_before.st_mode):
        raise RollbackRefused
    fd, raw_temp = tempfile.mkstemp(
        prefix=".shogun-codex-diagnostics.rollback.",
        dir=parent,
    )
    temp_path: Path | None = Path(raw_temp)
    try:
        view = memoryview(target)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise RollbackRefused
            view = view[written:]
        os.fchmod(fd, 0o555)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        if _digest(_read_regular(temp_path, 0o555)) != target_sha256:
            raise RollbackRefused
        if _digest(_read_regular(snapshot, 0o555)) != failing_sha256:
            raise RollbackRefused
        parent_after = os.lstat(parent)
        if (parent_before.st_dev, parent_before.st_ino) != (
            parent_after.st_dev,
            parent_after.st_ino,
        ):
            raise RollbackRefused
        try:
            os.replace(temp_path, snapshot)
        except OSError as exc:
            try:
                observed = _digest(_read_regular(snapshot, 0o555))
            except (OSError, RollbackRefused) as verify_exc:
                raise RollbackCommittedIndeterminate from verify_exc
            if observed != failing_sha256:
                raise RollbackCommittedIndeterminate from exc
            raise
        temp_path = None
        try:
            directory_fd = os.open(
                parent,
                os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            if _digest(_read_regular(snapshot, 0o555)) != target_sha256:
                raise RollbackRefused
        except (OSError, RollbackRefused) as exc:
            raise RollbackCommittedIndeterminate from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--failing-sha256", required=True)
    parser.add_argument("--target-sha256", required=True)
    parser.add_argument("--target-blob", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        atomic_rollback(
            snapshot=SNAPSHOT_PATH,
            target_blob=args.target_blob,
            failing_sha256=args.failing_sha256,
            target_sha256=args.target_sha256,
        )
    except RollbackCommittedIndeterminate:
        return 4
    except (OSError, RollbackRefused):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

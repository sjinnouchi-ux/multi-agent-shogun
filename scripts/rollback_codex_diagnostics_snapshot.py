#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
import re
import secrets
import stat
from pathlib import Path
from typing import Sequence

SNAPSHOT_PATH = Path("/home/jinnouchi/.local/libexec/shogun-codex-diagnostics")
MAX_SOURCE_BYTES = 1_048_576
SHA256 = re.compile(r"[0-9a-f]{64}")
TEMP_PREFIX = ".shogun-codex-diagnostics.rollback."
MAX_TEMP_ATTEMPTS = 16


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


def _identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _require_platform_support() -> None:
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise RollbackRefused


def _leaf_name(path: Path) -> str:
    name = path.name
    if not name or name in (".", "..") or os.sep in name or (
        os.altsep is not None and os.altsep in name
    ):
        raise RollbackRefused
    return name


def _open_parent(path: Path) -> tuple[int, os.stat_result]:
    _require_platform_support()
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except (OSError, TypeError, NotImplementedError) as exc:
        raise RollbackRefused from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISDIR(metadata.st_mode):
            raise RollbackRefused
        return fd, metadata
    except BaseException:
        os.close(fd)
        raise


def _parent_still_bound(
    path: Path,
    directory_fd: int,
    expected: os.stat_result,
) -> None:
    try:
        opened = os.fstat(directory_fd)
        visible = os.stat(path, follow_symlinks=False)
    except (OSError, TypeError, NotImplementedError) as exc:
        raise RollbackRefused from exc
    if (
        not stat.S_ISDIR(opened.st_mode)
        or not stat.S_ISDIR(visible.st_mode)
        or _identity(opened) != _identity(expected)
        or _identity(visible) != _identity(expected)
    ):
        raise RollbackRefused


def _open_regular_at(
    directory_fd: int,
    name: str,
    required_mode: int | None,
) -> int:
    _require_platform_support()
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, dir_fd=directory_fd)
    except (OSError, TypeError, NotImplementedError) as exc:
        raise RollbackRefused from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise RollbackRefused
        if required_mode is not None and (
            stat.S_IMODE(metadata.st_mode) != required_mode
        ):
            raise RollbackRefused
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_regular_fd(fd: int, required_mode: int | None) -> bytes:
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise RollbackRefused
        if required_mode is not None and (
            stat.S_IMODE(before.st_mode) != required_mode
        ):
            raise RollbackRefused
        os.lseek(fd, 0, os.SEEK_SET)
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


def _read_regular_at(
    directory_fd: int,
    name: str,
    required_mode: int | None,
) -> bytes:
    fd = _open_regular_at(directory_fd, name, required_mode)
    try:
        return _read_regular_fd(fd, required_mode)
    finally:
        os.close(fd)


def _require_leaf_matches_fd(
    directory_fd: int,
    name: str,
    fd: int,
    required_mode: int,
) -> None:
    try:
        opened = os.fstat(fd)
        visible = os.stat(
            name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except (OSError, TypeError, NotImplementedError) as exc:
        raise RollbackRefused from exc
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(visible.st_mode)
        or stat.S_IMODE(opened.st_mode) != required_mode
        or stat.S_IMODE(visible.st_mode) != required_mode
        or _identity(opened) != _identity(visible)
    ):
        raise RollbackRefused


def _lock_exclusive(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        raise RollbackRefused from exc


def _create_temp_at(directory_fd: int) -> tuple[int, str]:
    _require_platform_support()
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | os.O_CLOEXEC
        | os.O_NOFOLLOW
    )
    for _attempt in range(MAX_TEMP_ATTEMPTS):
        name = TEMP_PREFIX + secrets.token_hex(16)
        try:
            fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
        except FileExistsError:
            continue
        except (OSError, TypeError, NotImplementedError) as exc:
            raise RollbackRefused from exc
        try:
            _lock_exclusive(fd)
            return fd, name
        except BaseException:
            try:
                _cleanup_exact_temp_at(directory_fd, name, fd)
            finally:
                os.close(fd)
            raise
    raise RollbackRefused


def _write_temp(fd: int, value: bytes) -> None:
    try:
        view = memoryview(value)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise RollbackRefused
            view = view[written:]
        os.fchmod(fd, 0o555)
        os.fsync(fd)
    except OSError as exc:
        raise RollbackRefused from exc


def _cleanup_exact_temp_at(directory_fd: int, name: str, fd: int) -> None:
    try:
        opened = os.fstat(fd)
        visible = os.stat(
            name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(visible.st_mode)
            or _identity(opened) != _identity(visible)
            or opened.st_nlink != 1
            or visible.st_nlink != 1
        ):
            raise RollbackCommittedIndeterminate
        os.unlink(name, dir_fd=directory_fd)
        try:
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RollbackCommittedIndeterminate
        if os.fstat(fd).st_nlink != 0:
            raise RollbackCommittedIndeterminate
        os.fsync(directory_fd)
    except RollbackCommittedIndeterminate:
        raise
    except (OSError, TypeError, NotImplementedError) as exc:
        raise RollbackCommittedIndeterminate from exc


def _destination_state(
    directory_fd: int,
    name: str,
    old_fd: int,
    new_fd: int,
    failing_sha256: str,
    target_sha256: str,
) -> str:
    try:
        visible = os.stat(
            name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if not stat.S_ISREG(visible.st_mode):
            return "unknown"
        old_stat = os.fstat(old_fd)
        new_stat = os.fstat(new_fd)
        if _identity(visible) == _identity(old_stat):
            value = _read_regular_fd(old_fd, 0o555)
            return "old" if _digest(value) == failing_sha256 else "unknown"
        if _identity(visible) == _identity(new_stat):
            value = _read_regular_fd(new_fd, 0o555)
            return "new" if _digest(value) == target_sha256 else "unknown"
    except (OSError, RollbackRefused, TypeError, NotImplementedError):
        return "unknown"
    return "unknown"


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
    snapshot_name = _leaf_name(snapshot)
    target_name = _leaf_name(target_blob)
    parent_fd = -1
    target_parent_fd = -1
    snapshot_fd = -1
    temp_fd = -1
    temp_name: str | None = None
    cleanup_error: RollbackCommittedIndeterminate | None = None
    try:
        parent_fd, parent_identity = _open_parent(snapshot.parent)
        _parent_still_bound(snapshot.parent, parent_fd, parent_identity)
        target_parent_fd, target_parent_identity = _open_parent(target_blob.parent)
        _parent_still_bound(
            target_blob.parent,
            target_parent_fd,
            target_parent_identity,
        )

        snapshot_fd = _open_regular_at(parent_fd, snapshot_name, 0o555)
        _lock_exclusive(snapshot_fd)
        _require_leaf_matches_fd(parent_fd, snapshot_name, snapshot_fd, 0o555)
        current = _read_regular_fd(snapshot_fd, 0o555)
        if _digest(current) != failing_sha256:
            raise RollbackRefused

        target = _read_regular_at(target_parent_fd, target_name, None)
        _parent_still_bound(
            target_blob.parent,
            target_parent_fd,
            target_parent_identity,
        )
        if _digest(target) != target_sha256:
            raise RollbackRefused

        temp_fd, temp_name = _create_temp_at(parent_fd)
        _write_temp(temp_fd, target)
        _require_leaf_matches_fd(parent_fd, temp_name, temp_fd, 0o555)
        if _digest(_read_regular_fd(temp_fd, 0o555)) != target_sha256:
            raise RollbackRefused

        _parent_still_bound(snapshot.parent, parent_fd, parent_identity)
        _require_leaf_matches_fd(parent_fd, snapshot_name, snapshot_fd, 0o555)
        if _digest(_read_regular_fd(snapshot_fd, 0o555)) != failing_sha256:
            raise RollbackRefused

        try:
            os.replace(
                temp_name,
                snapshot_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
        except (OSError, TypeError, NotImplementedError) as exc:
            destination = _destination_state(
                parent_fd,
                snapshot_name,
                snapshot_fd,
                temp_fd,
                failing_sha256,
                target_sha256,
            )
            if destination == "new":
                temp_name = None
                raise RollbackCommittedIndeterminate from exc
            try:
                _parent_still_bound(snapshot.parent, parent_fd, parent_identity)
            except RollbackRefused as binding_exc:
                raise RollbackCommittedIndeterminate from binding_exc
            if destination != "old":
                raise RollbackCommittedIndeterminate from exc
            if isinstance(exc, OSError):
                raise
            raise RollbackRefused from exc
        temp_name = None

        try:
            os.fsync(parent_fd)
            _parent_still_bound(snapshot.parent, parent_fd, parent_identity)
            _require_leaf_matches_fd(parent_fd, snapshot_name, temp_fd, 0o555)
            if _digest(_read_regular_fd(temp_fd, 0o555)) != target_sha256:
                raise RollbackRefused
        except (OSError, RollbackRefused) as exc:
            raise RollbackCommittedIndeterminate from exc
    finally:
        if temp_name is not None and temp_fd >= 0 and parent_fd >= 0:
            try:
                _cleanup_exact_temp_at(parent_fd, temp_name, temp_fd)
            except RollbackCommittedIndeterminate as exc:
                cleanup_error = exc
        for fd in (temp_fd, snapshot_fd, target_parent_fd, parent_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if cleanup_error is not None:
            raise cleanup_error


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

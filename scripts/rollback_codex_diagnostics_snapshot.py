#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
import re
import secrets
import stat
import sys
from pathlib import Path
from typing import Sequence

SNAPSHOT_PATH = Path("/home/jinnouchi/.local/libexec/shogun-codex-diagnostics")
MAX_SOURCE_BYTES = 1_048_576
SHA256 = re.compile(r"[0-9a-f]{64}")
TEMP_PREFIX = ".shogun-codex-diagnostics.rollback."
INSTALL_TEMP_PREFIX = ".shogun-codex-diagnostics.install."
MAX_TEMP_ATTEMPTS = 16


class RollbackRefused(Exception):
    pass


class RollbackCommitOrCleanupIndeterminate(Exception):
    pass


class SnapshotInstallCommitOrCleanupIndeterminate(Exception):
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
    value = Path(path)
    if ".." in value.parts:
        raise RollbackRefused
    start = Path(value.anchor) if value.is_absolute() else Path(".")
    try:
        fd = os.open(start, flags)
    except (OSError, TypeError, NotImplementedError) as exc:
        raise RollbackRefused from exc
    try:
        parts = value.parts[1:] if value.is_absolute() else value.parts
        for part in parts:
            if part in ("", "."):
                continue
            next_fd = os.open(part, flags, dir_fd=fd)
            try:
                metadata = os.fstat(next_fd)
                if not stat.S_ISDIR(metadata.st_mode):
                    raise RollbackRefused
            except BaseException:
                os.close(next_fd)
                raise
            os.close(fd)
            fd = next_fd
        metadata = os.fstat(fd)
        if not stat.S_ISDIR(metadata.st_mode):
            raise RollbackRefused
        return fd, metadata
    except (OSError, TypeError, NotImplementedError) as exc:
        os.close(fd)
        raise RollbackRefused from exc
    except BaseException:
        os.close(fd)
        raise


def _open_or_create_install_parent(path: Path) -> tuple[int, os.stat_result]:
    _require_platform_support()
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    value = Path(path)
    if ".." in value.parts:
        raise RollbackRefused
    start = Path(value.anchor) if value.is_absolute() else Path(".")
    created_any = False
    try:
        fd = os.open(start, flags)
    except (OSError, TypeError, NotImplementedError) as exc:
        raise RollbackRefused from exc
    try:
        parts = value.parts[1:] if value.is_absolute() else value.parts
        for part in parts:
            if part in ("", "."):
                continue
            created = False
            try:
                next_fd = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                try:
                    os.mkdir(part, 0o755, dir_fd=fd)
                except FileExistsError:
                    pass
                else:
                    created = True
                    created_any = True
                    os.fsync(fd)
                next_fd = os.open(part, flags, dir_fd=fd)
            try:
                metadata = os.fstat(next_fd)
                if not stat.S_ISDIR(metadata.st_mode):
                    raise RollbackRefused
                if created:
                    os.fchmod(next_fd, 0o755)
                    os.fsync(next_fd)
                    metadata = os.fstat(next_fd)
                    if (
                        metadata.st_uid != os.geteuid()
                        or stat.S_IMODE(metadata.st_mode) != 0o755
                    ):
                        raise SnapshotInstallCommitOrCleanupIndeterminate
            except BaseException:
                os.close(next_fd)
                raise
            os.close(fd)
            fd = next_fd
        metadata = os.fstat(fd)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise RollbackRefused
        return fd, metadata
    except SnapshotInstallCommitOrCleanupIndeterminate:
        os.close(fd)
        raise
    except (OSError, TypeError, NotImplementedError) as exc:
        os.close(fd)
        if created_any:
            raise SnapshotInstallCommitOrCleanupIndeterminate from exc
        raise RollbackRefused from exc
    except BaseException as exc:
        os.close(fd)
        if created_any and isinstance(exc, RollbackRefused):
            raise SnapshotInstallCommitOrCleanupIndeterminate from exc
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


def _require_trusted_snapshot_parent(
    path: Path,
    directory_fd: int,
    expected: os.stat_result,
) -> None:
    _parent_still_bound(path, directory_fd, expected)
    try:
        opened = os.fstat(directory_fd)
    except (OSError, TypeError, NotImplementedError) as exc:
        raise RollbackRefused from exc
    if (
        not stat.S_ISDIR(opened.st_mode)
        or opened.st_uid != os.geteuid()
        or stat.S_IMODE(opened.st_mode) & 0o022
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


def _require_owned_snapshot_leaf_matches_fd(
    directory_fd: int,
    name: str,
    fd: int,
) -> None:
    _require_leaf_matches_fd(directory_fd, name, fd, 0o555)
    try:
        opened = os.fstat(fd)
        visible = os.stat(
            name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except (OSError, TypeError, NotImplementedError) as exc:
        raise RollbackRefused from exc
    effective_uid = os.geteuid()
    if opened.st_uid != effective_uid or visible.st_uid != effective_uid:
        raise RollbackRefused


def _lock_exclusive(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        raise RollbackRefused from exc


def _create_temp_at(
    directory_fd: int, *, prefix: str = TEMP_PREFIX
) -> tuple[int, str]:
    _require_platform_support()
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | os.O_CLOEXEC
        | os.O_NOFOLLOW
    )
    for _attempt in range(MAX_TEMP_ATTEMPTS):
        name = prefix + secrets.token_hex(16)
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
            raise RollbackCommitOrCleanupIndeterminate
        os.unlink(name, dir_fd=directory_fd)
        try:
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RollbackCommitOrCleanupIndeterminate
        if os.fstat(fd).st_nlink != 0:
            raise RollbackCommitOrCleanupIndeterminate
        os.fsync(directory_fd)
    except RollbackCommitOrCleanupIndeterminate:
        raise
    except (OSError, TypeError, NotImplementedError) as exc:
        raise RollbackCommitOrCleanupIndeterminate from exc


def _cleanup_published_install_temp_at(
    directory_fd: int,
    temp_name: str,
    destination_name: str,
    fd: int,
) -> None:
    try:
        opened = os.fstat(fd)
        temp_visible = os.stat(
            temp_name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        destination_visible = os.stat(
            destination_name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(temp_visible.st_mode)
            or not stat.S_ISREG(destination_visible.st_mode)
            or _identity(opened) != _identity(temp_visible)
            or _identity(opened) != _identity(destination_visible)
            or opened.st_nlink != 2
            or temp_visible.st_nlink != 2
            or destination_visible.st_nlink != 2
        ):
            raise SnapshotInstallCommitOrCleanupIndeterminate
        os.unlink(temp_name, dir_fd=directory_fd)
        try:
            os.stat(
                temp_name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        else:
            raise SnapshotInstallCommitOrCleanupIndeterminate
        remaining = os.fstat(fd)
        destination_remaining = os.stat(
            destination_name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(remaining.st_mode)
            or not stat.S_ISREG(destination_remaining.st_mode)
            or _identity(remaining) != _identity(destination_remaining)
            or remaining.st_nlink != 1
            or destination_remaining.st_nlink != 1
        ):
            raise SnapshotInstallCommitOrCleanupIndeterminate
        os.fsync(directory_fd)
    except SnapshotInstallCommitOrCleanupIndeterminate:
        raise
    except (OSError, TypeError, NotImplementedError) as exc:
        raise SnapshotInstallCommitOrCleanupIndeterminate from exc


def _existing_install_matches(
    directory_fd: int,
    destination_name: str,
    expected: bytes,
) -> bool:
    fd = _open_regular_at(directory_fd, destination_name, 0o555)
    try:
        _require_leaf_matches_fd(
            directory_fd, destination_name, fd, 0o555
        )
        metadata = os.fstat(fd)
        if metadata.st_uid != os.geteuid():
            raise RollbackRefused
        value = _read_regular_fd(fd, 0o555)
        _require_leaf_matches_fd(
            directory_fd, destination_name, fd, 0o555
        )
        return value == expected
    finally:
        os.close(fd)


def _install_initial_snapshot(
    *,
    source: Path,
    destination: Path,
) -> str:
    source_name = _leaf_name(source)
    destination_name = _leaf_name(destination)
    source_parent_fd = -1
    destination_parent_fd = -1
    temp_fd = -1
    temp_name: str | None = None
    published = False
    cleanup_indeterminate: SnapshotInstallCommitOrCleanupIndeterminate | None = None
    try:
        source_parent_fd, source_parent_identity = _open_parent(source.parent)
        _parent_still_bound(
            source.parent, source_parent_fd, source_parent_identity
        )
        source_bytes = _read_regular_at(
            source_parent_fd, source_name, None
        )
        _parent_still_bound(
            source.parent, source_parent_fd, source_parent_identity
        )

        destination_parent_fd, destination_parent_identity = (
            _open_or_create_install_parent(destination.parent)
        )
        _parent_still_bound(
            destination.parent,
            destination_parent_fd,
            destination_parent_identity,
        )
        try:
            os.stat(
                destination_name,
                dir_fd=destination_parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        except (OSError, TypeError, NotImplementedError) as exc:
            raise RollbackRefused from exc
        else:
            if _existing_install_matches(
                destination_parent_fd, destination_name, source_bytes
            ):
                _parent_still_bound(
                    destination.parent,
                    destination_parent_fd,
                    destination_parent_identity,
                )
                return "already_current"
            raise RollbackRefused

        temp_fd, temp_name = _create_temp_at(
            destination_parent_fd,
            prefix=INSTALL_TEMP_PREFIX,
        )
        _write_temp(temp_fd, source_bytes)
        _require_leaf_matches_fd(
            destination_parent_fd, temp_name, temp_fd, 0o555
        )
        if _read_regular_fd(temp_fd, 0o555) != source_bytes:
            raise RollbackRefused
        _parent_still_bound(
            destination.parent,
            destination_parent_fd,
            destination_parent_identity,
        )
        try:
            os.link(
                temp_name,
                destination_name,
                src_dir_fd=destination_parent_fd,
                dst_dir_fd=destination_parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            if _existing_install_matches(
                destination_parent_fd, destination_name, source_bytes
            ):
                _parent_still_bound(
                    destination.parent,
                    destination_parent_fd,
                    destination_parent_identity,
                )
                return "already_current"
            raise RollbackRefused
        except (OSError, TypeError, NotImplementedError) as exc:
            raise RollbackRefused from exc
        published = True
        try:
            os.fsync(destination_parent_fd)
        except OSError as exc:
            raise SnapshotInstallCommitOrCleanupIndeterminate from exc

        _cleanup_published_install_temp_at(
            destination_parent_fd,
            temp_name,
            destination_name,
            temp_fd,
        )
        temp_name = None
        try:
            _parent_still_bound(
                destination.parent,
                destination_parent_fd,
                destination_parent_identity,
            )
            _require_leaf_matches_fd(
                destination_parent_fd, destination_name, temp_fd, 0o555
            )
            installed_bytes = _read_regular_fd(temp_fd, 0o555)
            _parent_still_bound(
                destination.parent,
                destination_parent_fd,
                destination_parent_identity,
            )
            _require_leaf_matches_fd(
                destination_parent_fd, destination_name, temp_fd, 0o555
            )
            installed = os.fstat(temp_fd)
            if (
                installed.st_uid != os.geteuid()
                or installed_bytes != source_bytes
            ):
                raise SnapshotInstallCommitOrCleanupIndeterminate
        except SnapshotInstallCommitOrCleanupIndeterminate:
            raise
        except (OSError, RollbackRefused) as exc:
            raise SnapshotInstallCommitOrCleanupIndeterminate from exc
        return "installed"
    finally:
        if (
            temp_name is not None
            and temp_fd >= 0
            and destination_parent_fd >= 0
        ):
            try:
                if published:
                    _cleanup_published_install_temp_at(
                        destination_parent_fd,
                        temp_name,
                        destination_name,
                        temp_fd,
                    )
                else:
                    _cleanup_exact_temp_at(
                        destination_parent_fd, temp_name, temp_fd
                    )
            except (
                RollbackCommitOrCleanupIndeterminate,
                SnapshotInstallCommitOrCleanupIndeterminate,
            ) as exc:
                cleanup_indeterminate = (
                    SnapshotInstallCommitOrCleanupIndeterminate()
                )
                cleanup_indeterminate.__cause__ = exc
        for fd in (temp_fd, destination_parent_fd, source_parent_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if cleanup_indeterminate is not None:
            raise cleanup_indeterminate


def install_initial_snapshot(
    *,
    source: Path,
) -> str:
    try:
        return _install_initial_snapshot(
            source=Path(source),
            destination=SNAPSHOT_PATH,
        )
    except RollbackCommitOrCleanupIndeterminate as exc:
        raise SnapshotInstallCommitOrCleanupIndeterminate from exc


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


def _cleanup_temp_and_reconcile_old_snapshot(
    *,
    snapshot: Path,
    parent_fd: int,
    parent_identity: os.stat_result,
    snapshot_name: str,
    snapshot_fd: int,
    failing_sha256: str,
    temp_name: str,
    temp_fd: int,
) -> None:
    _cleanup_exact_temp_at(parent_fd, temp_name, temp_fd)
    try:
        _require_trusted_snapshot_parent(snapshot.parent, parent_fd, parent_identity)
        _require_owned_snapshot_leaf_matches_fd(
            parent_fd, snapshot_name, snapshot_fd
        )
        if _digest(_read_regular_fd(snapshot_fd, 0o555)) != failing_sha256:
            raise RollbackRefused
        _require_owned_snapshot_leaf_matches_fd(
            parent_fd, snapshot_name, snapshot_fd
        )
    except (OSError, RollbackRefused, TypeError, NotImplementedError) as exc:
        raise RollbackCommitOrCleanupIndeterminate from exc


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
    cleanup_indeterminate: RollbackCommitOrCleanupIndeterminate | None = None
    try:
        parent_fd, parent_identity = _open_parent(snapshot.parent)
        _require_trusted_snapshot_parent(
            snapshot.parent, parent_fd, parent_identity
        )
        target_parent_fd, target_parent_identity = _open_parent(target_blob.parent)
        _parent_still_bound(
            target_blob.parent,
            target_parent_fd,
            target_parent_identity,
        )

        snapshot_fd = _open_regular_at(parent_fd, snapshot_name, 0o555)
        _lock_exclusive(snapshot_fd)
        _require_owned_snapshot_leaf_matches_fd(
            parent_fd, snapshot_name, snapshot_fd
        )
        current = _read_regular_fd(snapshot_fd, 0o555)
        _require_owned_snapshot_leaf_matches_fd(
            parent_fd, snapshot_name, snapshot_fd
        )
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
        _require_owned_snapshot_leaf_matches_fd(parent_fd, temp_name, temp_fd)
        if _digest(_read_regular_fd(temp_fd, 0o555)) != target_sha256:
            raise RollbackRefused
        _require_owned_snapshot_leaf_matches_fd(parent_fd, temp_name, temp_fd)

        _require_trusted_snapshot_parent(
            snapshot.parent, parent_fd, parent_identity
        )
        _require_owned_snapshot_leaf_matches_fd(
            parent_fd, snapshot_name, snapshot_fd
        )
        if _digest(_read_regular_fd(snapshot_fd, 0o555)) != failing_sha256:
            raise RollbackRefused
        _require_owned_snapshot_leaf_matches_fd(
            parent_fd, snapshot_name, snapshot_fd
        )

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
                raise RollbackCommitOrCleanupIndeterminate from exc
            if destination != "old":
                raise RollbackCommitOrCleanupIndeterminate from exc
            try:
                _cleanup_temp_and_reconcile_old_snapshot(
                    snapshot=snapshot,
                    parent_fd=parent_fd,
                    parent_identity=parent_identity,
                    snapshot_name=snapshot_name,
                    snapshot_fd=snapshot_fd,
                    failing_sha256=failing_sha256,
                    temp_name=temp_name,
                    temp_fd=temp_fd,
                )
            finally:
                temp_name = None
            if isinstance(exc, OSError):
                raise
            raise RollbackRefused from exc
        temp_name = None

        try:
            os.fsync(parent_fd)
            _require_trusted_snapshot_parent(
                snapshot.parent, parent_fd, parent_identity
            )
            _require_owned_snapshot_leaf_matches_fd(
                parent_fd, snapshot_name, temp_fd
            )
            if _digest(_read_regular_fd(temp_fd, 0o555)) != target_sha256:
                raise RollbackRefused
            _require_owned_snapshot_leaf_matches_fd(
                parent_fd, snapshot_name, temp_fd
            )
        except (OSError, RollbackRefused) as exc:
            raise RollbackCommitOrCleanupIndeterminate from exc
    finally:
        if temp_name is not None and temp_fd >= 0 and parent_fd >= 0:
            try:
                try:
                    _cleanup_temp_and_reconcile_old_snapshot(
                        snapshot=snapshot,
                        parent_fd=parent_fd,
                        parent_identity=parent_identity,
                        snapshot_name=snapshot_name,
                        snapshot_fd=snapshot_fd,
                        failing_sha256=failing_sha256,
                        temp_name=temp_name,
                        temp_fd=temp_fd,
                    )
                finally:
                    temp_name = None
            except RollbackCommitOrCleanupIndeterminate as exc:
                cleanup_indeterminate = exc
        for fd in (temp_fd, snapshot_fd, target_parent_fd, parent_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if cleanup_indeterminate is not None:
            raise cleanup_indeterminate


def _rollback_main(argv: Sequence[str]) -> int:
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
    except RollbackCommitOrCleanupIndeterminate:
        return 4
    except (OSError, RollbackRefused):
        return 3
    return 0


def _install_initial_main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = install_initial_snapshot(source=args.source)
    except SnapshotInstallCommitOrCleanupIndeterminate:
        return 4
    except (OSError, RollbackRefused):
        return 3
    print(f"snapshot_install={result}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    values = tuple(sys.argv[1:] if argv is None else argv)
    if values[:1] == ("install-initial",):
        return _install_initial_main(values[1:])
    return _rollback_main(values)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import concurrent.futures
import fcntl
import hashlib
import importlib.util
import io
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts" / "rollback_codex_diagnostics_snapshot.py"
PLAN = (
    ROOT
    / "docs"
    / "superpowers"
    / "plans"
    / "2026-07-14-codex-readonly-diagnostics.md"
)
BOUNDARY_OPERATION = ROOT / "docs" / "github-boundary-operation.md"


def load_module():
    spec = importlib.util.spec_from_file_location("rollback_diagnostics_test", SOURCE)
    if spec is None or spec.loader is None:
        raise AssertionError("rollback module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def stat_with_uid(value: os.stat_result, uid: int) -> os.stat_result:
    fields = list(value)
    fields[4] = uid
    return os.stat_result(fields)


class AtomicRollbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.snapshot = self.root / "shogun-codex-diagnostics"
        self.target = self.root / "target.py"
        self.current_bytes = b"#!/usr/bin/python3\nprint('current')\n"
        self.target_bytes = b"#!/usr/bin/python3\nprint('target')\n"
        self.snapshot.write_bytes(self.current_bytes)
        self.snapshot.chmod(0o555)
        self.target.write_bytes(self.target_bytes)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def rollback(self) -> None:
        self.rollback_paths(self.snapshot, self.target)

    def rollback_paths(
        self,
        snapshot: Path,
        target: Path,
        *,
        current_bytes: bytes | None = None,
        target_bytes: bytes | None = None,
    ) -> None:
        current = self.current_bytes if current_bytes is None else current_bytes
        replacement = self.target_bytes if target_bytes is None else target_bytes
        self.module.atomic_rollback(
            snapshot=snapshot,
            target_blob=target,
            failing_sha256=sha(current),
            target_sha256=sha(replacement),
        )

    def install_initial(self, source: Path, destination: Path) -> str:
        return self.module._install_initial_snapshot(
            source=source,
            destination=destination,
        )

    def assert_commit_or_cleanup_indeterminate(self, action) -> None:
        try:
            action()
        except self.module.RollbackCommitOrCleanupIndeterminate:
            return
        except Exception as exc:  # pragma: no cover - regression assertion
            self.fail(
                "expected RollbackCommitOrCleanupIndeterminate, got "
                f"{type(exc).__name__}"
            )
        self.fail("RollbackCommitOrCleanupIndeterminate not raised")

    def make_parent_swap_fixture(self):
        container = self.root / "parent-swap"
        parent = container / "live"
        parent.mkdir(parents=True)
        snapshot = parent / "shogun-codex-diagnostics"
        target = container / "target.py"
        snapshot.write_bytes(self.current_bytes)
        snapshot.chmod(0o555)
        target.write_bytes(self.target_bytes)
        moved = container / "pinned-parent"
        return parent, moved, snapshot, target

    def test_success_uses_mode_0555_temp_in_same_directory_and_atomic_replace(self) -> None:
        real_replace = os.replace
        observed = {}

        def checked_replace(
            source,
            destination,
            *,
            src_dir_fd=None,
            dst_dir_fd=None,
        ):
            self.assertNotIn(os.sep, os.fspath(source))
            self.assertNotIn(os.sep, os.fspath(destination))
            self.assertIsInstance(src_dir_fd, int)
            self.assertEqual(src_dir_fd, dst_dir_fd)
            parent_stat = os.fstat(src_dir_fd)
            observed["parent"] = (parent_stat.st_dev, parent_stat.st_ino)
            source_stat = os.stat(
                source,
                dir_fd=src_dir_fd,
                follow_symlinks=False,
            )
            observed["mode"] = stat.S_IMODE(source_stat.st_mode)
            observed["destination"] = destination
            real_replace(
                source,
                destination,
                src_dir_fd=src_dir_fd,
                dst_dir_fd=dst_dir_fd,
            )

        with mock.patch.object(self.module.os, "replace", side_effect=checked_replace):
            self.rollback()
        expected_parent = self.snapshot.parent.stat()
        self.assertEqual(
            observed["parent"],
            (expected_parent.st_dev, expected_parent.st_ino),
        )
        self.assertEqual(observed["mode"], 0o555)
        self.assertEqual(observed["destination"], self.snapshot.name)
        self.assertEqual(self.snapshot.read_bytes(), self.target_bytes)

    def test_initial_install_is_no_replace_durable_and_idempotent(self) -> None:
        parent = self.root / "install"
        parent.mkdir()
        destination = parent / "shogun-codex-diagnostics"
        source = self.root / "source.py"
        source.write_bytes(self.target_bytes)
        real_link = os.link
        real_open = os.open
        real_fsync = os.fsync
        real_unlink = os.unlink
        open_calls: list[tuple[object, int, int, int | None, int]] = []
        events: list[tuple[str, int, str]] = []

        def recorded_open(path, flags, mode=0o777, *, dir_fd=None):
            opened_fd = real_open(path, flags, mode, dir_fd=dir_fd)
            open_calls.append((path, flags, mode, dir_fd, opened_fd))
            return opened_fd

        def recorded_fsync(fd):
            kind = "directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"
            events.append(("fsync", fd, kind))
            return real_fsync(fd)

        def recorded_link(*args, **kwargs):
            events.append(("link", kwargs["src_dir_fd"], "directory"))
            return real_link(*args, **kwargs)

        def recorded_unlink(path, *args, **kwargs):
            if os.fspath(path).startswith(
                ".shogun-codex-diagnostics.install."
            ):
                events.append(("unlink", kwargs["dir_fd"], "directory"))
            return real_unlink(path, *args, **kwargs)

        with mock.patch.object(
            self.module.os, "link", side_effect=recorded_link
        ) as link, mock.patch.object(
            self.module.os, "replace", side_effect=AssertionError("no replace")
        ), mock.patch.object(
            self.module.os, "open", side_effect=recorded_open
        ), mock.patch.object(
            self.module.os, "fsync", side_effect=recorded_fsync
        ) as fsync, mock.patch.object(
            self.module.os, "unlink", side_effect=recorded_unlink
        ) as unlink:
            result = self.install_initial(source, destination)
        self.assertEqual(result, "installed")
        self.assertEqual(destination.read_bytes(), self.target_bytes)
        metadata = destination.stat()
        self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o555)
        self.assertEqual(metadata.st_uid, os.geteuid())
        self.assertEqual(link.call_count, 1)
        self.assertGreaterEqual(fsync.call_count, 3)
        self.assertEqual(unlink.call_count, 1)
        temp_opens = [
            call for call in open_calls
            if os.fspath(call[0]).startswith(
                ".shogun-codex-diagnostics.install."
            )
        ]
        self.assertEqual(len(temp_opens), 1)
        temp_name, temp_flags, temp_mode, temp_dir_fd, _temp_fd = temp_opens[0]
        required_flags = os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        self.assertEqual(temp_flags & required_flags, required_flags)
        self.assertEqual(temp_mode, 0o600)
        self.assertIsInstance(temp_dir_fd, int)
        self.assertNotIn(os.sep, os.fspath(temp_name))
        link_args, link_kwargs = link.call_args
        self.assertEqual(link_args, (temp_name, destination.name))
        self.assertEqual(link_kwargs["src_dir_fd"], temp_dir_fd)
        self.assertEqual(link_kwargs["dst_dir_fd"], temp_dir_fd)
        self.assertIs(link_kwargs["follow_symlinks"], False)
        link_index = next(
            index for index, event in enumerate(events) if event[0] == "link"
        )
        unlink_index = next(
            index for index, event in enumerate(events) if event[0] == "unlink"
        )
        self.assertTrue(any(
            event[0] == "fsync" and event[2] == "file"
            for event in events[:link_index]
        ))
        self.assertTrue(any(
            event == ("fsync", temp_dir_fd, "directory")
            for event in events[link_index + 1:unlink_index]
        ))
        self.assertTrue(any(
            event == ("fsync", temp_dir_fd, "directory")
            for event in events[unlink_index + 1:]
        ))
        previous_directory_fd: int | None = None
        root_directory_opens = 0
        for path, flags, _mode, dir_fd, opened_fd in open_calls:
            if not flags & os.O_DIRECTORY:
                continue
            self.assertEqual(
                flags & (os.O_DIRECTORY | os.O_NOFOLLOW),
                os.O_DIRECTORY | os.O_NOFOLLOW,
            )
            component = os.fspath(path)
            if component in (os.sep, "."):
                root_directory_opens += 1
                self.assertIsNone(dir_fd)
                previous_directory_fd = opened_fd
            else:
                self.assertFalse(os.path.isabs(component))
                self.assertNotIn(os.sep, component)
                if os.altsep is not None:
                    self.assertNotIn(os.altsep, component)
                self.assertEqual(dir_fd, previous_directory_fd)
                previous_directory_fd = opened_fd
        self.assertGreaterEqual(root_directory_opens, 2)
        self.assertEqual(
            list(parent.glob(".shogun-codex-diagnostics.install.*")), []
        )

        inode = destination.stat().st_ino
        with mock.patch.object(
            self.module.os, "link", side_effect=AssertionError("no republish")
        ):
            result = self.install_initial(source, destination)
        self.assertEqual(result, "already_current")
        self.assertEqual(destination.stat().st_ino, inode)
        self.assertEqual(destination.read_bytes(), self.target_bytes)

    def test_initial_install_rejects_different_or_unsafe_existing_destination(
        self,
    ) -> None:
        parent = self.root / "install-existing"
        parent.mkdir()
        source = self.root / "source-existing.py"
        source.write_bytes(self.target_bytes)

        different = parent / "different"
        different.write_bytes(self.current_bytes)
        different.chmod(0o555)
        inode = different.stat().st_ino
        with self.assertRaises(self.module.RollbackRefused):
            self.install_initial(source, different)
        self.assertEqual(different.stat().st_ino, inode)
        self.assertEqual(different.read_bytes(), self.current_bytes)

        wrong_mode = parent / "wrong-mode"
        wrong_mode.write_bytes(self.target_bytes)
        wrong_mode.chmod(0o755)
        wrong_mode_inode = wrong_mode.stat().st_ino
        with self.assertRaises(self.module.RollbackRefused):
            self.install_initial(source, wrong_mode)
        self.assertEqual(wrong_mode.stat().st_ino, wrong_mode_inode)
        self.assertEqual(stat.S_IMODE(wrong_mode.stat().st_mode), 0o755)
        self.assertEqual(wrong_mode.read_bytes(), self.target_bytes)

        link_target = parent / "link-target"
        link_target.write_bytes(self.target_bytes)
        link_target.chmod(0o555)
        link_target_inode = link_target.stat().st_ino
        destination_link = parent / "destination-link"
        destination_link.symlink_to(link_target)
        destination_link_value = os.readlink(destination_link)
        with self.assertRaises(self.module.RollbackRefused):
            self.install_initial(source, destination_link)
        self.assertTrue(destination_link.is_symlink())
        self.assertEqual(os.readlink(destination_link), destination_link_value)
        self.assertEqual(link_target.stat().st_ino, link_target_inode)
        self.assertEqual(link_target.read_bytes(), self.target_bytes)

        source_link = self.root / "source-link.py"
        source_link.symlink_to(source)
        absent = parent / "from-source-link"
        with self.assertRaises(self.module.RollbackRefused):
            self.install_initial(source_link, absent)
        self.assertFalse(absent.exists())

    def test_initial_install_rejects_symlinked_parent_chain(self) -> None:
        source = self.root / "source-parent.py"
        source.write_bytes(self.target_bytes)
        real_parent = self.root / "real-parent"
        nested = real_parent / "nested"
        nested.mkdir(parents=True)
        alias = self.root / "parent-alias"
        alias.symlink_to(real_parent, target_is_directory=True)
        destination = alias / "nested" / "snapshot"
        with self.assertRaises(self.module.RollbackRefused):
            self.install_initial(source, destination)
        self.assertFalse((nested / "snapshot").exists())

    def test_initial_install_creates_missing_parent_chain_durably(self) -> None:
        source = self.root / "source-new-parent.py"
        source.write_bytes(self.target_bytes)
        destination = self.root / "new-parent" / "libexec" / "snapshot"
        real_mkdir = os.mkdir
        real_fsync = os.fsync
        with mock.patch.object(
            self.module.os, "mkdir", wraps=real_mkdir
        ) as mkdir, mock.patch.object(
            self.module.os, "fsync", wraps=real_fsync
        ) as fsync:
            result = self.install_initial(source, destination)
        self.assertEqual(result, "installed")
        self.assertEqual(destination.read_bytes(), self.target_bytes)
        self.assertGreaterEqual(mkdir.call_count, 2)
        self.assertGreaterEqual(fsync.call_count, 7)

    def test_concurrent_initial_install_never_replaces_winner(self) -> None:
        parent = self.root / "install-race"
        parent.mkdir()
        destination = parent / "shogun-codex-diagnostics"
        source = self.root / "source-race.py"
        source.write_bytes(self.target_bytes)
        barrier = threading.Barrier(2)
        real_link = os.link

        def synchronized_link(*args, **kwargs):
            barrier.wait(timeout=3)
            return real_link(*args, **kwargs)

        with mock.patch.object(
            self.module.os, "link", side_effect=synchronized_link
        ), concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(self.install_initial, source, destination)
                for _ in range(2)
            ]
            results = sorted(future.result(timeout=5) for future in futures)
        self.assertEqual(results, ["already_current", "installed"])
        self.assertEqual(destination.read_bytes(), self.target_bytes)
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o555)
        self.assertEqual(
            list(parent.glob(".shogun-codex-diagnostics.install.*")), []
        )

    def test_initial_install_same_race_winner_preserves_inode_and_cleans_temp(
        self,
    ) -> None:
        parent = self.root / "install-race-same"
        parent.mkdir()
        destination = parent / "shogun-codex-diagnostics"
        source = self.root / "source-race-same.py"
        source.write_bytes(self.target_bytes)
        winner_inode: int | None = None

        def publish_same_then_conflict(*_args, **_kwargs):
            nonlocal winner_inode
            destination.write_bytes(self.target_bytes)
            destination.chmod(0o555)
            winner_inode = destination.stat().st_ino
            raise FileExistsError

        with mock.patch.object(
            self.module.os, "link", side_effect=publish_same_then_conflict
        ):
            result = self.install_initial(source, destination)
        self.assertEqual(result, "already_current")
        self.assertIsNotNone(winner_inode)
        self.assertEqual(destination.stat().st_ino, winner_inode)
        self.assertEqual(destination.read_bytes(), self.target_bytes)
        self.assertEqual(
            list(parent.glob(".shogun-codex-diagnostics.install.*")), []
        )

    def test_initial_install_race_with_different_winner_is_blocked(self) -> None:
        parent = self.root / "install-race-different"
        parent.mkdir()
        destination = parent / "shogun-codex-diagnostics"
        source = self.root / "source-race-different.py"
        source.write_bytes(self.target_bytes)
        winner = b"#!/usr/bin/python3\nprint('winner')\n"

        def publish_other_then_conflict(*_args, **_kwargs):
            destination.write_bytes(winner)
            destination.chmod(0o555)
            raise FileExistsError

        with mock.patch.object(
            self.module.os, "link", side_effect=publish_other_then_conflict
        ), self.assertRaises(self.module.RollbackRefused):
            self.install_initial(source, destination)
        self.assertEqual(destination.read_bytes(), winner)

    def test_existing_already_current_rechecks_parent_binding_before_return(
        self,
    ) -> None:
        parent = self.root / "install-existing-parent-swap"
        parent.mkdir()
        moved = self.root / "install-existing-parent-moved"
        destination = parent / "shogun-codex-diagnostics"
        source = self.root / "source-existing-parent-swap.py"
        source.write_bytes(self.target_bytes)
        destination.write_bytes(self.target_bytes)
        destination.chmod(0o555)
        original_inode = destination.stat().st_ino
        real_matches = self.module._existing_install_matches

        def match_then_swap(*args, **kwargs):
            matched = real_matches(*args, **kwargs)
            parent.rename(moved)
            parent.mkdir()
            return matched

        with mock.patch.object(
            self.module,
            "_existing_install_matches",
            side_effect=match_then_swap,
        ), self.assertRaises(self.module.RollbackRefused):
            self.install_initial(source, destination)
        moved_destination = moved / destination.name
        self.assertEqual(moved_destination.stat().st_ino, original_inode)
        self.assertEqual(moved_destination.read_bytes(), self.target_bytes)

    def test_race_winner_already_current_rechecks_parent_binding_before_return(
        self,
    ) -> None:
        parent = self.root / "install-race-parent-swap"
        parent.mkdir()
        moved = self.root / "install-race-parent-moved"
        destination = parent / "shogun-codex-diagnostics"
        source = self.root / "source-race-parent-swap.py"
        source.write_bytes(self.target_bytes)
        real_matches = self.module._existing_install_matches

        def publish_same_then_conflict(*_args, **_kwargs):
            destination.write_bytes(self.target_bytes)
            destination.chmod(0o555)
            raise FileExistsError

        def match_then_swap(*args, **kwargs):
            matched = real_matches(*args, **kwargs)
            parent.rename(moved)
            parent.mkdir()
            return matched

        with mock.patch.object(
            self.module.os, "link", side_effect=publish_same_then_conflict
        ), mock.patch.object(
            self.module,
            "_existing_install_matches",
            side_effect=match_then_swap,
        ), self.assertRaises(self.module.RollbackRefused):
            self.install_initial(source, destination)
        moved_destination = moved / destination.name
        self.assertEqual(moved_destination.read_bytes(), self.target_bytes)
        self.assertEqual(
            list(moved.glob(".shogun-codex-diagnostics.install.*")), []
        )

    def test_initial_install_rejects_extra_published_hardlink_as_indeterminate(
        self,
    ) -> None:
        parent = self.root / "install-extra-hardlink"
        parent.mkdir()
        destination = parent / "shogun-codex-diagnostics"
        extra = parent / "hostile-extra-link"
        source = self.root / "source-extra-hardlink.py"
        source.write_bytes(self.target_bytes)
        real_link = os.link

        def publish_then_add_extra(source_name, destination_name, **kwargs):
            real_link(source_name, destination_name, **kwargs)
            real_link(
                source_name,
                extra.name,
                src_dir_fd=kwargs["src_dir_fd"],
                dst_dir_fd=kwargs["dst_dir_fd"],
                follow_symlinks=False,
            )

        with mock.patch.object(
            self.module.os, "link", side_effect=publish_then_add_extra
        ), self.assertRaises(
            self.module.SnapshotInstallCommitOrCleanupIndeterminate
        ):
            self.install_initial(source, destination)
        self.assertEqual(destination.read_bytes(), self.target_bytes)
        self.assertEqual(extra.stat().st_ino, destination.stat().st_ino)
        install_temps = list(
            parent.glob(".shogun-codex-diagnostics.install.*")
        )
        self.assertEqual(len(install_temps), 1)
        self.assertEqual(install_temps[0].stat().st_nlink, 3)

    def test_initial_install_rejects_temp_inode_substitution_as_indeterminate(
        self,
    ) -> None:
        parent = self.root / "install-temp-substitution"
        parent.mkdir()
        destination = parent / "shogun-codex-diagnostics"
        source = self.root / "source-temp-substitution.py"
        source.write_bytes(self.target_bytes)
        hostile = b"hostile replacement temp"
        real_cleanup = self.module._cleanup_published_install_temp_at
        substituted = False

        def substitute_then_cleanup(
            directory_fd, temp_name, destination_name, temp_fd
        ):
            nonlocal substituted
            if not substituted:
                substituted = True
                os.unlink(temp_name, dir_fd=directory_fd)
                replacement_fd = os.open(
                    temp_name,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | os.O_CLOEXEC
                    | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory_fd,
                )
                try:
                    os.write(replacement_fd, hostile)
                    os.fchmod(replacement_fd, 0o555)
                    os.fsync(replacement_fd)
                finally:
                    os.close(replacement_fd)
            return real_cleanup(
                directory_fd, temp_name, destination_name, temp_fd
            )

        with mock.patch.object(
            self.module,
            "_cleanup_published_install_temp_at",
            side_effect=substitute_then_cleanup,
        ), self.assertRaises(
            self.module.SnapshotInstallCommitOrCleanupIndeterminate
        ):
            self.install_initial(source, destination)
        self.assertEqual(destination.read_bytes(), self.target_bytes)
        install_temps = list(
            parent.glob(".shogun-codex-diagnostics.install.*")
        )
        self.assertEqual(len(install_temps), 1)
        self.assertEqual(install_temps[0].read_bytes(), hostile)

    def test_initial_install_post_publish_uncertainty_never_reports_success(
        self,
    ) -> None:
        parent = self.root / "install-indeterminate"
        parent.mkdir()
        destination = parent / "shogun-codex-diagnostics"
        source = self.root / "source-indeterminate.py"
        source.write_bytes(self.target_bytes)
        real_fsync = os.fsync
        calls = 0

        def fail_first_directory_fsync(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("publish directory fsync failed")
            return real_fsync(fd)

        with mock.patch.object(
            self.module.os, "fsync", side_effect=fail_first_directory_fsync
        ), self.assertRaises(
            self.module.SnapshotInstallCommitOrCleanupIndeterminate
        ):
            self.install_initial(source, destination)
        self.assertEqual(destination.read_bytes(), self.target_bytes)

    def test_initial_install_cleanup_uncertainty_preserves_visible_snapshot(
        self,
    ) -> None:
        parent = self.root / "install-cleanup-indeterminate"
        parent.mkdir()
        destination = parent / "shogun-codex-diagnostics"
        source = self.root / "source-cleanup-indeterminate.py"
        source.write_bytes(self.target_bytes)
        real_unlink = os.unlink

        def fail_install_temp_unlink(path, *args, **kwargs):
            if os.fspath(path).startswith(
                ".shogun-codex-diagnostics.install."
            ):
                raise OSError("install temp cleanup failed")
            return real_unlink(path, *args, **kwargs)

        with mock.patch.object(
            self.module.os, "unlink", side_effect=fail_install_temp_unlink
        ), self.assertRaises(
            self.module.SnapshotInstallCommitOrCleanupIndeterminate
        ):
            self.install_initial(source, destination)
        self.assertEqual(destination.read_bytes(), self.target_bytes)
        self.assertTrue(
            list(parent.glob(".shogun-codex-diagnostics.install.*"))
        )

    def test_initial_install_post_publish_destination_swap_is_indeterminate(
        self,
    ) -> None:
        parent = self.root / "install-post-publish-swap"
        parent.mkdir()
        destination = parent / "shogun-codex-diagnostics"
        source = self.root / "source-post-publish-swap.py"
        source.write_bytes(self.target_bytes)
        replacement = b"changed-after-publish"
        real_cleanup = self.module._cleanup_published_install_temp_at

        def cleanup_then_swap(*args, **kwargs):
            real_cleanup(*args, **kwargs)
            destination.unlink()
            destination.write_bytes(replacement)
            destination.chmod(0o555)

        with mock.patch.object(
            self.module,
            "_cleanup_published_install_temp_at",
            side_effect=cleanup_then_swap,
        ), self.assertRaises(
            self.module.SnapshotInstallCommitOrCleanupIndeterminate
        ):
            self.install_initial(source, destination)
        self.assertEqual(destination.read_bytes(), replacement)

    def test_initial_install_cli_preserves_legacy_and_has_fixed_subcommand(
        self,
    ) -> None:
        parent = self.root / "install-cli"
        parent.mkdir()
        destination = parent / "shogun-codex-diagnostics"
        source = self.root / "source-cli.py"
        source.write_bytes(self.target_bytes)
        with mock.patch.object(
            self.module, "SNAPSHOT_PATH", destination
        ), mock.patch("builtins.print") as output:
            result = self.module.main((
                "install-initial",
                "--source",
                str(source),
            ))
        self.assertEqual(result, 0)
        output.assert_called_once_with("snapshot_install=installed")
        self.assertEqual(destination.read_bytes(), self.target_bytes)
        self.assertEqual(self.snapshot.stat().st_mode & 0o777, 0o555)
        self.assertEqual(
            list(self.root.glob(".shogun-codex-diagnostics.rollback.*")), []
        )

    def test_initial_install_public_api_uses_only_fixed_snapshot_destination(
        self,
    ) -> None:
        self.assertEqual(
            self.module.SNAPSHOT_PATH,
            Path("/home/jinnouchi/.local/libexec/shogun-codex-diagnostics"),
        )
        parent = self.root / "install-fixed-destination"
        parent.mkdir()
        destination = parent / "shogun-codex-diagnostics"
        source = self.root / "source-fixed-destination.py"
        source.write_bytes(self.target_bytes)
        with mock.patch.object(self.module, "SNAPSHOT_PATH", destination):
            result = self.module.install_initial_snapshot(source=source)
        self.assertEqual(result, "installed")
        self.assertEqual(destination.read_bytes(), self.target_bytes)
        with self.assertRaises(TypeError):
            self.module.install_initial_snapshot(
                source=source,
                destination=parent / "override-forbidden",
            )

    def test_initial_install_cli_rejects_destination_override(self) -> None:
        parent = self.root / "install-cli-override"
        parent.mkdir()
        source = self.root / "source-cli-override.py"
        source.write_bytes(self.target_bytes)
        with mock.patch.object(sys, "stderr", io.StringIO()), self.assertRaises(
            SystemExit
        ) as raised:
            self.module.main((
                "install-initial",
                "--source",
                str(source),
                "--destination",
                str(parent / "override"),
            ))
        self.assertEqual(raised.exception.code, 2)
        self.assertFalse((parent / "override").exists())

    def test_initial_install_cli_post_publish_uncertainty_is_exit_four_silent(
        self,
    ) -> None:
        parent = self.root / "install-cli-indeterminate"
        parent.mkdir()
        destination = parent / "shogun-codex-diagnostics"
        source = self.root / "source-cli-indeterminate.py"
        source.write_bytes(self.target_bytes)
        real_fsync = os.fsync
        failed_directory_fsync = False

        def fail_publish_directory_fsync(fd):
            nonlocal failed_directory_fsync
            if stat.S_ISDIR(os.fstat(fd).st_mode) and not failed_directory_fsync:
                failed_directory_fsync = True
                raise OSError("publish directory fsync uncertain")
            return real_fsync(fd)

        with mock.patch.object(
            self.module, "SNAPSHOT_PATH", destination
        ), mock.patch.object(
            self.module.os, "fsync", side_effect=fail_publish_directory_fsync
        ), mock.patch("builtins.print") as output:
            result = self.module.main((
                "install-initial",
                "--source",
                str(source),
            ))
        self.assertEqual(result, 4)
        output.assert_not_called()
        self.assertTrue(failed_directory_fsync)
        self.assertEqual(destination.read_bytes(), self.target_bytes)

    def test_initial_install_cli_leaf_swap_after_readback_is_exit_four_silent(
        self,
    ) -> None:
        parent = self.root / "install-cli-final-leaf-swap"
        parent.mkdir()
        destination = parent / "shogun-codex-diagnostics"
        source = self.root / "source-cli-final-leaf-swap.py"
        source.write_bytes(self.target_bytes)
        replacement = b"replacement after final readback"
        real_read = self.module._read_regular_fd
        read_calls = 0

        def read_then_swap_leaf(fd, required_mode):
            nonlocal read_calls
            value = real_read(fd, required_mode)
            read_calls += 1
            if read_calls == 3:
                destination.unlink()
                destination.write_bytes(replacement)
                destination.chmod(0o555)
            return value

        with mock.patch.object(
            self.module, "SNAPSHOT_PATH", destination
        ), mock.patch.object(
            self.module, "_read_regular_fd", side_effect=read_then_swap_leaf
        ), mock.patch("builtins.print") as output:
            result = self.module.main((
                "install-initial",
                "--source",
                str(source),
            ))
        self.assertEqual(read_calls, 3)
        self.assertEqual(result, 4)
        output.assert_not_called()
        self.assertEqual(destination.read_bytes(), replacement)

    def test_initial_install_cli_parent_swap_after_readback_is_exit_four_silent(
        self,
    ) -> None:
        parent = self.root / "install-cli-final-parent-swap"
        parent.mkdir()
        moved = self.root / "install-cli-final-parent-moved"
        destination = parent / "shogun-codex-diagnostics"
        source = self.root / "source-cli-final-parent-swap.py"
        source.write_bytes(self.target_bytes)
        real_read = self.module._read_regular_fd
        read_calls = 0

        def read_then_swap_parent(fd, required_mode):
            nonlocal read_calls
            value = real_read(fd, required_mode)
            read_calls += 1
            if read_calls == 3:
                parent.rename(moved)
                parent.mkdir()
            return value

        with mock.patch.object(
            self.module, "SNAPSHOT_PATH", destination
        ), mock.patch.object(
            self.module, "_read_regular_fd", side_effect=read_then_swap_parent
        ), mock.patch("builtins.print") as output:
            result = self.module.main((
                "install-initial",
                "--source",
                str(source),
            ))
        self.assertEqual(read_calls, 3)
        self.assertEqual(result, 4)
        output.assert_not_called()
        self.assertFalse(destination.exists())
        self.assertEqual(
            (moved / destination.name).read_bytes(), self.target_bytes
        )

    def test_legacy_cli_success_path_remains_available_without_subcommand(
        self,
    ) -> None:
        with mock.patch.object(self.module, "SNAPSHOT_PATH", self.snapshot):
            result = self.module.main((
                "--failing-sha256",
                sha(self.current_bytes),
                "--target-sha256",
                sha(self.target_bytes),
                "--target-blob",
                str(self.target),
            ))
        self.assertEqual(result, 0)
        self.assertEqual(self.snapshot.read_bytes(), self.target_bytes)
        self.assertEqual(stat.S_IMODE(self.snapshot.stat().st_mode), 0o555)

    def test_current_hash_mismatch_refuses_without_changing_snapshot(self) -> None:
        with self.assertRaises(self.module.RollbackRefused):
            self.module.atomic_rollback(
                snapshot=self.snapshot,
                target_blob=self.target,
                failing_sha256="f" * 64,
                target_sha256=sha(self.target_bytes),
            )
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)

    def test_snapshot_parent_rejects_group_or_world_writable_mode(self) -> None:
        for unsafe_mode in (0o720, 0o702):
            with self.subTest(mode=oct(unsafe_mode)):
                self.root.chmod(unsafe_mode)
                with self.assertRaises(self.module.RollbackRefused):
                    self.rollback()
                self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)
                self.root.chmod(0o700)

    def test_snapshot_parent_must_be_owned_by_effective_user(self) -> None:
        real_fstat = os.fstat
        parent_identity = (
            self.snapshot.parent.stat().st_dev,
            self.snapshot.parent.stat().st_ino,
        )

        def nonowner_parent(fd):
            metadata = real_fstat(fd)
            if (
                stat.S_ISDIR(metadata.st_mode)
                and (metadata.st_dev, metadata.st_ino) == parent_identity
            ):
                return stat_with_uid(metadata, os.geteuid() + 1)
            return metadata

        with mock.patch.object(
            self.module.os, "fstat", side_effect=nonowner_parent
        ):
            with self.assertRaises(self.module.RollbackRefused):
                self.rollback()
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)

    def test_snapshot_leaf_must_be_owned_by_effective_user(self) -> None:
        real_fstat = os.fstat
        snapshot_identity = (
            self.snapshot.stat().st_dev,
            self.snapshot.stat().st_ino,
        )

        def nonowner_snapshot(fd):
            metadata = real_fstat(fd)
            if (
                stat.S_ISREG(metadata.st_mode)
                and (metadata.st_dev, metadata.st_ino) == snapshot_identity
            ):
                return stat_with_uid(metadata, os.geteuid() + 1)
            return metadata

        with mock.patch.object(
            self.module.os, "fstat", side_effect=nonowner_snapshot
        ):
            with self.assertRaises(self.module.RollbackRefused):
                self.rollback()
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)

    def test_read_regular_fd_accepts_exact_maximum_source_size(self) -> None:
        boundary = self.root / "exact-source-boundary"
        expected = b"x" * self.module.MAX_SOURCE_BYTES
        boundary.write_bytes(expected)
        fd = os.open(boundary, os.O_RDONLY | os.O_CLOEXEC)
        try:
            self.assertEqual(self.module._read_regular_fd(fd, None), expected)
        finally:
            os.close(fd)

    def test_read_regular_fd_rejects_one_byte_over_source_limit(self) -> None:
        boundary = self.root / "over-source-boundary"
        boundary.write_bytes(b"x" * (self.module.MAX_SOURCE_BYTES + 1))
        fd = os.open(boundary, os.O_RDONLY | os.O_CLOEXEC)
        try:
            with self.assertRaises(self.module.RollbackRefused):
                self.module._read_regular_fd(fd, None)
        finally:
            os.close(fd)

    def test_target_hash_mismatch_refuses_without_changing_snapshot(self) -> None:
        with self.assertRaises(self.module.RollbackRefused):
            self.module.atomic_rollback(
                snapshot=self.snapshot,
                target_blob=self.target,
                failing_sha256=sha(self.current_bytes),
                target_sha256="e" * 64,
            )
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)

    def test_equal_failing_and_target_hash_is_rejected_as_noop(self) -> None:
        self.target.write_bytes(self.current_bytes)
        with self.assertRaises(self.module.RollbackRefused):
            self.module.atomic_rollback(
                snapshot=self.snapshot,
                target_blob=self.target,
                failing_sha256=sha(self.current_bytes),
                target_sha256=sha(self.current_bytes),
            )
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)

    def test_symlink_target_is_rejected(self) -> None:
        real_target = self.root / "real-target.py"
        real_target.write_bytes(self.target_bytes)
        self.target.unlink()
        self.target.symlink_to(real_target)
        with self.assertRaises(self.module.RollbackRefused):
            self.rollback()
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)

    def test_target_and_snapshot_are_opened_relative_to_no_follow_parents(self) -> None:
        real_open = os.open
        calls = []

        def recorded_open(path, flags, mode=0o777, *, dir_fd=None):
            calls.append((os.fspath(path), flags, dir_fd))
            return real_open(path, flags, mode, dir_fd=dir_fd)

        with mock.patch.object(self.module.os, "open", side_effect=recorded_open):
            self.rollback()

        directory_calls = [item for item in calls if item[1] & os.O_DIRECTORY]
        self.assertTrue(directory_calls)
        self.assertTrue(any(path == os.sep for path, _flags, _fd in directory_calls))
        for path, flags, dir_fd in directory_calls:
            self.assertTrue(flags & os.O_NOFOLLOW)
            if path not in (os.sep, "."):
                self.assertIsInstance(dir_fd, int)
        self.assertFalse(any(
            path in (os.fspath(self.snapshot.parent), os.fspath(self.target.parent))
            for path, _flags, _dir_fd in calls
        ))
        self.assertTrue(any(
            path == self.snapshot.name and isinstance(dir_fd, int)
            for path, _flags, dir_fd in calls
        ))
        self.assertTrue(any(
            path == self.target.name and isinstance(dir_fd, int)
            for path, _flags, dir_fd in calls
        ))

    def test_snapshot_entry_is_revalidated_after_exclusive_lock(self) -> None:
        original_inode = self.snapshot.stat().st_ino
        replacement_inode = None
        real_flock = fcntl.flock
        swapped = False

        def swap_after_lock(fd, operation):
            nonlocal replacement_inode, swapped
            real_flock(fd, operation)
            if not swapped and operation & fcntl.LOCK_EX:
                swapped = True
                replacement = self.root / "same-hash-replacement"
                replacement.write_bytes(self.current_bytes)
                replacement.chmod(0o555)
                replacement_inode = replacement.stat().st_ino
                os.replace(replacement, self.snapshot)

        with mock.patch.object(fcntl, "flock", side_effect=swap_after_lock):
            with self.assertRaises(self.module.RollbackRefused):
                self.rollback()
        self.assertNotEqual(original_inode, replacement_inode)
        self.assertEqual(self.snapshot.stat().st_ino, replacement_inode)
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)
        self.assertEqual(
            list(self.root.glob(".shogun-codex-diagnostics.rollback.*")), []
        )

    def test_second_contender_is_refused_while_old_generation_is_locked(self) -> None:
        locked_fd = os.open(self.snapshot, os.O_RDONLY | os.O_CLOEXEC)
        try:
            fcntl.flock(locked_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(self.module.RollbackRefused):
                self.rollback()
        finally:
            os.close(locked_fd)
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)
        self.assertEqual(
            list(self.root.glob(".shogun-codex-diagnostics.rollback.*")), []
        )

    def test_new_generation_remains_locked_until_reconciliation(self) -> None:
        real_fsync = os.fsync
        observed_locked = []

        def inspect_directory_fsync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                probe = os.open(self.snapshot, os.O_RDONLY | os.O_CLOEXEC)
                try:
                    try:
                        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        observed_locked.append(True)
                    else:
                        observed_locked.append(False)
                        fcntl.flock(probe, fcntl.LOCK_UN)
                finally:
                    os.close(probe)
            return real_fsync(fd)

        with mock.patch.object(
            self.module.os, "fsync", side_effect=inspect_directory_fsync
        ):
            self.rollback()
        self.assertEqual(observed_locked, [True])
        self.assertEqual(self.snapshot.read_bytes(), self.target_bytes)

    def test_parent_swap_before_replace_is_indeterminate_after_cleanup(
        self,
    ) -> None:
        parent, moved, snapshot, target = self.make_parent_swap_fixture()
        real_fsync = os.fsync
        swapped = False
        decoy = self.current_bytes

        def swap_after_temp_fsync(fd):
            nonlocal swapped
            result = real_fsync(fd)
            if not swapped and stat.S_ISREG(os.fstat(fd).st_mode):
                swapped = True
                parent.rename(moved)
                parent.mkdir()
                replacement = parent / snapshot.name
                replacement.write_bytes(decoy)
                replacement.chmod(0o555)
            return result

        with mock.patch.object(
            self.module.os, "fsync", side_effect=swap_after_temp_fsync
        ):
            with self.assertRaises(
                self.module.RollbackCommitOrCleanupIndeterminate
            ):
                self.rollback_paths(snapshot, target)
        self.assertEqual((moved / snapshot.name).read_bytes(), self.current_bytes)
        self.assertEqual((parent / snapshot.name).read_bytes(), decoy)
        self.assertEqual(
            list(moved.glob(".shogun-codex-diagnostics.rollback.*")), []
        )
        self.assertEqual(
            list(parent.glob(".shogun-codex-diagnostics.rollback.*")), []
        )

    def test_snapshot_parent_trust_drift_is_indeterminate_after_cleanup(
        self,
    ) -> None:
        real_fsync = os.fsync
        drifted = False

        def make_parent_unsafe_after_temp_fsync(fd):
            nonlocal drifted
            result = real_fsync(fd)
            if not drifted and stat.S_ISREG(os.fstat(fd).st_mode):
                drifted = True
                self.snapshot.parent.chmod(0o777)
            return result

        with mock.patch.object(
            self.module.os,
            "fsync",
            side_effect=make_parent_unsafe_after_temp_fsync,
        ):
            with self.assertRaises(
                self.module.RollbackCommitOrCleanupIndeterminate
            ):
                self.rollback()
        self.assertTrue(drifted)
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)
        self.assertEqual(
            list(self.root.glob(".shogun-codex-diagnostics.rollback.*")), []
        )

    def test_snapshot_leaf_owner_drift_is_indeterminate_after_cleanup(
        self,
    ) -> None:
        real_fstat = os.fstat
        real_fsync = os.fsync
        snapshot_identity = (
            self.snapshot.stat().st_dev,
            self.snapshot.stat().st_ino,
        )
        drifted = False

        def mark_owner_drift_after_temp_fsync(fd):
            nonlocal drifted
            result = real_fsync(fd)
            if not drifted and stat.S_ISREG(real_fstat(fd).st_mode):
                drifted = True
            return result

        def drifted_snapshot_owner(fd):
            metadata = real_fstat(fd)
            if (
                drifted
                and stat.S_ISREG(metadata.st_mode)
                and (metadata.st_dev, metadata.st_ino) == snapshot_identity
            ):
                return stat_with_uid(metadata, os.geteuid() + 1)
            return metadata

        with mock.patch.object(
            self.module.os,
            "fsync",
            side_effect=mark_owner_drift_after_temp_fsync,
        ), mock.patch.object(
            self.module.os,
            "fstat",
            side_effect=drifted_snapshot_owner,
        ):
            with self.assertRaises(
                self.module.RollbackCommitOrCleanupIndeterminate
            ):
                self.rollback()
        self.assertTrue(drifted)
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)
        self.assertEqual(
            list(self.root.glob(".shogun-codex-diagnostics.rollback.*")), []
        )

    def test_parent_swap_during_replace_is_commit_or_cleanup_indeterminate(
        self,
    ) -> None:
        parent, moved, snapshot, target = self.make_parent_swap_fixture()
        real_replace = os.replace
        decoy = self.current_bytes

        def swap_then_replace(source, destination, **kwargs):
            parent.rename(moved)
            parent.mkdir()
            replacement = parent / snapshot.name
            replacement.write_bytes(decoy)
            replacement.chmod(0o555)
            return real_replace(source, destination, **kwargs)

        with mock.patch.object(
            self.module.os, "replace", side_effect=swap_then_replace
        ):
            self.assert_commit_or_cleanup_indeterminate(
                lambda: self.rollback_paths(snapshot, target)
            )
        self.assertEqual((moved / snapshot.name).read_bytes(), self.target_bytes)
        self.assertEqual((parent / snapshot.name).read_bytes(), decoy)
        self.assertEqual(
            list(moved.glob(".shogun-codex-diagnostics.rollback.*")), []
        )
        self.assertEqual(
            list(parent.glob(".shogun-codex-diagnostics.rollback.*")), []
        )

    def test_symlink_snapshot_is_rejected(self) -> None:
        real_snapshot = self.root / "real-snapshot"
        real_snapshot.write_bytes(self.current_bytes)
        real_snapshot.chmod(0o555)
        self.snapshot.unlink()
        self.snapshot.symlink_to(real_snapshot)
        with self.assertRaises(self.module.RollbackRefused):
            self.rollback()
        self.assertEqual(real_snapshot.read_bytes(), self.current_bytes)

    def test_missing_no_follow_support_fails_before_open(self) -> None:
        real_hasattr = hasattr

        def without_no_follow(value, name):
            if value is self.module.os and name == "O_NOFOLLOW":
                return False
            return real_hasattr(value, name)

        with mock.patch("builtins.hasattr", side_effect=without_no_follow):
            with self.assertRaises(self.module.RollbackRefused):
                self.rollback()
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)

    def test_missing_directory_open_support_fails_before_open(self) -> None:
        real_hasattr = hasattr

        def without_directory(value, name):
            if value is self.module.os and name == "O_DIRECTORY":
                return False
            return real_hasattr(value, name)

        with mock.patch("builtins.hasattr", side_effect=without_directory):
            with self.assertRaises(self.module.RollbackRefused):
                self.rollback()
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)

    def test_general_precommit_refusal_with_reconciled_old_leaf_is_exit_three(
        self,
    ) -> None:
        real_write_temp = self.module._write_temp

        def write_temp_then_refuse(fd, value):
            real_write_temp(fd, value)
            raise self.module.RollbackRefused

        with mock.patch.object(
            self.module, "SNAPSHOT_PATH", self.snapshot
        ), mock.patch.object(
            self.module,
            "_write_temp",
            side_effect=write_temp_then_refuse,
        ):
            result = self.module.main((
                "--failing-sha256", sha(self.current_bytes),
                "--target-sha256", sha(self.target_bytes),
                "--target-blob", str(self.target),
            ))

        self.assertEqual(result, 3)
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)
        self.assertEqual(
            list(self.root.glob(".shogun-codex-diagnostics.rollback.*")), []
        )

    def test_general_precommit_parent_drift_during_cleanup_is_exit_four(
        self,
    ) -> None:
        real_write_temp = self.module._write_temp
        real_unlink = os.unlink
        drifted = False

        def write_temp_then_refuse(fd, value):
            real_write_temp(fd, value)
            raise self.module.RollbackRefused

        def unlink_temp_then_drift_parent(path, *, dir_fd=None):
            nonlocal drifted
            result = real_unlink(path, dir_fd=dir_fd)
            if not drifted and os.fspath(path).startswith(self.module.TEMP_PREFIX):
                drifted = True
                self.snapshot.parent.chmod(0o777)
            return result

        with mock.patch.object(
            self.module, "SNAPSHOT_PATH", self.snapshot
        ), mock.patch.object(
            self.module,
            "_write_temp",
            side_effect=write_temp_then_refuse,
        ), mock.patch.object(
            self.module.os,
            "unlink",
            side_effect=unlink_temp_then_drift_parent,
        ):
            result = self.module.main((
                "--failing-sha256", sha(self.current_bytes),
                "--target-sha256", sha(self.target_bytes),
                "--target-blob", str(self.target),
            ))

        self.snapshot.parent.chmod(0o700)
        self.assertTrue(drifted)
        self.assertEqual(result, 4)
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)
        self.assertEqual(
            list(self.root.glob(".shogun-codex-diagnostics.rollback.*")), []
        )

    def test_general_precommit_old_leaf_swap_during_cleanup_is_exit_four(
        self,
    ) -> None:
        real_write_temp = self.module._write_temp
        real_replace = os.replace
        real_unlink = os.unlink
        swapped = False

        def write_temp_then_refuse(fd, value):
            real_write_temp(fd, value)
            raise self.module.RollbackRefused

        def unlink_temp_then_swap_old_leaf(path, *, dir_fd=None):
            nonlocal swapped
            result = real_unlink(path, dir_fd=dir_fd)
            if not swapped and os.fspath(path).startswith(self.module.TEMP_PREFIX):
                swapped = True
                replacement = self.root / "same-hash-general-cleanup-swap"
                replacement.write_bytes(self.current_bytes)
                replacement.chmod(0o555)
                real_replace(replacement, self.snapshot)
            return result

        with mock.patch.object(
            self.module, "SNAPSHOT_PATH", self.snapshot
        ), mock.patch.object(
            self.module,
            "_write_temp",
            side_effect=write_temp_then_refuse,
        ), mock.patch.object(
            self.module.os,
            "unlink",
            side_effect=unlink_temp_then_swap_old_leaf,
        ):
            result = self.module.main((
                "--failing-sha256", sha(self.current_bytes),
                "--target-sha256", sha(self.target_bytes),
                "--target-blob", str(self.target),
            ))

        self.assertTrue(swapped)
        self.assertEqual(result, 4)
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)
        self.assertEqual(
            list(self.root.glob(".shogun-codex-diagnostics.rollback.*")), []
        )

    def test_replace_failure_preserves_current_and_removes_temp(self) -> None:
        with mock.patch.object(self.module.os, "replace", side_effect=OSError):
            with self.assertRaises(OSError):
                self.rollback()
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)
        self.assertEqual(
            list(self.root.glob(".shogun-codex-diagnostics.rollback.*")), []
        )

    def test_destination_swap_during_old_temp_cleanup_is_indeterminate(
        self,
    ) -> None:
        real_replace = os.replace
        real_unlink = os.unlink
        swapped = False

        def unlink_temp_then_swap_destination(path, *, dir_fd=None):
            nonlocal swapped
            result = real_unlink(path, dir_fd=dir_fd)
            if not swapped and os.fspath(path).startswith(self.module.TEMP_PREFIX):
                swapped = True
                replacement = self.root / "same-hash-cleanup-swap"
                replacement.write_bytes(self.current_bytes)
                replacement.chmod(0o555)
                real_replace(replacement, self.snapshot)
            return result

        with mock.patch.object(self.module.os, "replace", side_effect=OSError), (
            mock.patch.object(
                self.module.os,
                "unlink",
                side_effect=unlink_temp_then_swap_destination,
            )
        ):
            self.assert_commit_or_cleanup_indeterminate(self.rollback)
        self.assertTrue(swapped)
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)
        self.assertEqual(
            list(self.root.glob(".shogun-codex-diagnostics.rollback.*")), []
        )

    def test_destination_swap_after_old_cleanup_durability_is_indeterminate(
        self,
    ) -> None:
        real_fsync = os.fsync
        real_replace = os.replace
        swapped = False

        def swap_destination_after_directory_fsync(fd):
            nonlocal swapped
            result = real_fsync(fd)
            if not swapped and stat.S_ISDIR(os.fstat(fd).st_mode):
                swapped = True
                replacement = self.root / "same-hash-post-cleanup-swap"
                replacement.write_bytes(self.current_bytes)
                replacement.chmod(0o555)
                real_replace(replacement, self.snapshot)
            return result

        with mock.patch.object(self.module.os, "replace", side_effect=OSError), (
            mock.patch.object(
                self.module.os,
                "fsync",
                side_effect=swap_destination_after_directory_fsync,
            )
        ):
            self.assert_commit_or_cleanup_indeterminate(self.rollback)
        self.assertTrue(swapped)
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)
        self.assertEqual(
            list(self.root.glob(".shogun-codex-diagnostics.rollback.*")), []
        )

    def test_cleanup_failure_is_commit_or_cleanup_indeterminate_not_exit_three(
        self,
    ) -> None:
        with mock.patch.object(self.module.os, "replace", side_effect=OSError), (
            mock.patch.object(self.module.os, "unlink", side_effect=OSError)
        ):
            self.assert_commit_or_cleanup_indeterminate(self.rollback)
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)

    def test_temp_name_inode_swap_is_not_blindly_unlinked(self) -> None:
        real_unlink = os.unlink
        sentinel = b"do-not-delete-unknown-inode"
        observed_path = None

        def replace_temp_name_then_fail(
            source,
            destination,
            *,
            src_dir_fd=None,
            dst_dir_fd=None,
        ):
            nonlocal observed_path
            if src_dir_fd is None:
                observed_path = Path(source)
                real_unlink(observed_path)
                observed_path.write_bytes(sentinel)
            else:
                observed_path = self.snapshot.parent / os.fspath(source)
                real_unlink(source, dir_fd=src_dir_fd)
                sentinel_fd = os.open(
                    source,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                    0o600,
                    dir_fd=src_dir_fd,
                )
                try:
                    os.write(sentinel_fd, sentinel)
                finally:
                    os.close(sentinel_fd)
            raise OSError("replace failed after temp name substitution")

        with mock.patch.object(
            self.module.os, "replace", side_effect=replace_temp_name_then_fail
        ):
            self.assert_commit_or_cleanup_indeterminate(self.rollback)
        self.assertIsNotNone(observed_path)
        self.assertEqual(observed_path.read_bytes(), sentinel)
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)

    def test_post_replace_fsync_failure_is_distinct_and_requires_reconciliation(self) -> None:
        real_fsync = os.fsync
        calls = 0

        def fail_directory_fsync(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("directory fsync failed")
            return real_fsync(fd)

        with mock.patch.object(self.module.os, "fsync", side_effect=fail_directory_fsync):
            with self.assertRaises(
                self.module.RollbackCommitOrCleanupIndeterminate
            ):
                self.rollback()
        self.assertEqual(self.snapshot.read_bytes(), self.target_bytes)
        self.assertEqual(self.snapshot.stat().st_mode & 0o777, 0o555)

    def test_replace_error_after_visible_commit_is_indeterminate(self) -> None:
        real_replace = os.replace

        def replace_then_error(source, destination, **kwargs):
            real_replace(source, destination, **kwargs)
            raise OSError("rename result uncertain")

        with mock.patch.object(
            self.module.os, "replace", side_effect=replace_then_error
        ):
            with self.assertRaises(
                self.module.RollbackCommitOrCleanupIndeterminate
            ):
                self.rollback()
        self.assertEqual(self.snapshot.read_bytes(), self.target_bytes)

    def test_cli_maps_commit_or_cleanup_indeterminate_to_exit_four(self) -> None:
        with mock.patch.object(
            self.module,
            "atomic_rollback",
            side_effect=self.module.RollbackCommitOrCleanupIndeterminate,
        ):
            result = self.module.main((
                "--failing-sha256", sha(self.current_bytes),
                "--target-sha256", sha(self.target_bytes),
                "--target-blob", str(self.target),
            ))
        self.assertEqual(result, 4)

    def test_plan_sanitization_fixture_uses_inert_placeholder(self) -> None:
        plan = PLAN.read_text(encoding="utf-8")
        has_realistic_assignment = re.search(
            r"(?i)(password|passwd|pwd|secret)\s*[=:]\s*['\"][^'\"]{8,}['\"]",
            plan,
        ) is not None
        self.assertFalse(
            has_realistic_assignment,
            "plan contains a realistic credential-shaped fixture",
        )
        self.assertTrue(
            'secret = "fixture"' in plan,
            "plan sanitization fixture does not use the inert placeholder",
        )

    def test_plan_task8_uses_delta_gate_and_clean_publication_branch(self) -> None:
        plan = PLAN.read_text(encoding="utf-8")
        task8 = plan.split(
            "### Task 8: Run the Frozen Source Verification and Open the Shogun PR",
            1,
        )[1]
        task9_marker = "### Task " "9:"
        task8 = task8.split(task9_marker, 1)[0]
        procedure_marker = (
            "**Step 2: Reconstruct the clean publication branch "
            "from trusted main**"
        )
        self.assertIn(procedure_marker, task8)
        procedure = task8.split(procedure_marker, 1)[1]

        def section(
            start_parts: tuple[str, ...],
            end_parts: tuple[str, ...],
        ) -> str:
            start = "".join(start_parts)
            end = "".join(end_parts)
            self.assertIn(start, procedure)
            self.assertIn(end, procedure)
            return procedure.split(start, 1)[1].split(end, 1)[0]

        def bash_block(markdown: str) -> str:
            opener = "`" * 3 + "bash"
            closer = "`" * 3
            self.assertIn(opener, markdown)
            return markdown.split(opener, 1)[1].split(closer, 1)[0]

        gitleaks_section = section(
            (
                "**Step 6: Run the pinned history-zero ",
                "and tracked-tree delta Gitleaks gate**",
            ),
            (
                "**Step 7: Obtain independent requirements ",
                "and security/code-quality reviews**",
            ),
        )
        gitleaks_bash = bash_block(gitleaks_section)
        push_section = section(
            (
                "**Step 8: Push the clean branch ",
                "and open a draft PR without merging**",
            ),
            (
                "**Step 9: Stop for the source ",
                "merge/deployment checkpoint**",
            ),
        )
        push_bash = bash_block(push_section)
        review_section = section(
            (
                "**Step 7: Obtain independent requirements ",
                "and security/code-quality reviews**",
            ),
            (
                "**Step 8: Push the clean branch ",
                "and open a draft PR without merging**",
            ),
        )
        review_bash = bash_block(review_section)
        functional_section = section(
            (
                "**Step 4: Run fresh functional ",
                "and generated-output verification**",
            ),
            (
                "**Step 5: Verify tracking does not expand ",
                "into runtime/private paths**",
            ),
        )
        functional_bash = bash_block(functional_section)
        ignore_section = section(
            (
                "**Step 5: Verify tracking does not expand ",
                "into runtime/private paths**",
            ),
            (
                "**Step 6: Run the pinned history-zero ",
                "and tracked-tree delta Gitleaks gate**",
            ),
        )
        ignore_bash = bash_block(ignore_section)
        scope_section = section(
            (
                "**Step 3: Verify the exact clean ",
                "publication scope**",
            ),
            (
                "**Step 4: Run fresh functional ",
                "and generated-output verification**",
            ),
        )
        scope_bash = bash_block(scope_section)
        step3_marker = "".join(
            (
                "**Step 3: Verify the exact clean ",
                "publication scope**",
            )
        )
        self.assertIn(step3_marker, procedure)
        reconstruct_section = procedure.split(step3_marker, 1)[0]
        reconstruct_bash = bash_block(reconstruct_section)

        def shell_array(shell: str, name: str) -> tuple[str, ...]:
            match = re.search(
                rf"(?ms)^{re.escape(name)}=\(\n(?P<body>.*?)^\)",
                shell,
            )
            self.assertIsNotNone(match)
            assert match is not None
            return tuple(
                line.strip()
                for line in match.group("body").splitlines()
                if line.strip()
            )

        expected_paths = (
            ".gitignore",
            "Makefile",
            "docs/codex-diagnostics.md",
            "docs/github-boundary-operation.md",
            "docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics-work-log.md",
            "docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics.md",
            "docs/superpowers/specs/2026-07-14-codex-readonly-diagnostics-design.md",
            "scripts/codex_diagnostics.py",
            "scripts/rollback_codex_diagnostics_snapshot.py",
            "tests/contract/__init__.py",
            "tests/contract/codex_diagnostics_consumer.py",
            "tests/contract/test_codex_diagnostics_consumer.py",
            "tests/integration/test_codex_diagnostics_tmux.bats",
            "tests/integration/test_codex_diagnostics_tmux.py",
            "tests/unit/test_codex_diagnostics.bats",
            "tests/unit/test_codex_diagnostics.py",
            "tests/unit/test_rollback_codex_diagnostics_snapshot.py",
        )
        for scope_contract in (reconstruct_bash, scope_bash):
            actual_paths = shell_array(scope_contract, "expected_paths")
            self.assertEqual(actual_paths, expected_paths)
            self.assertEqual(len(set(actual_paths)), 17)
            self.assertIn(
                'test "${#expected_paths[@]}" -eq 17',
                scope_contract,
            )

        required = (
            "publication_branch=codex/add-readonly-diagnostics-clean",
            'git diff --quiet "$base_sha"..."$head_sha" '
            "-- .gitleaks.toml",
            'git archive --format=tar "$base_sha"',
            'git archive --format=tar "$head_sha"',
            '--log-opts="$base_sha..$head_sha"',
            "--redact=100",
            '"RuleID"',
            '"StartLine"',
            '"EndLine"',
            '"StartColumn"',
            '"EndColumn"',
            'git push origin "$reviewed_head:refs/heads/$publication_branch"',
        )
        for snippet in required:
            self.assertIn(snippet, procedure)

        forbidden = (
            'gitleaks" git --redact --no-banner --config .gitleaks.toml .',
            'gitleaks" dir --redact --no-banner --config .gitleaks.toml .',
            "both scans exit 0",
        )
        for snippet in forbidden:
            self.assertNotIn(snippet, procedure)

        self.assertEqual(gitleaks_bash.count("--exit-code=42"), 2)
        self.assertIn("0|42)", gitleaks_bash)
        self.assertNotIn("0|1)", gitleaks_bash)
        self.assertIn("(42 if count else 0)", gitleaks_bash)
        self.assertIn(
            "except (OSError, RuntimeError, ValueError):",
            gitleaks_bash,
        )
        self.assertIn('or "\\\\" in raw', gitleaks_bash)
        self.assertNotIn('raw.replace("\\\\", "/")', gitleaks_bash)
        self.assertIn(
            'git merge-base --is-ancestor "$base_sha" "$head_sha"',
            gitleaks_bash,
        )
        self.assertNotIn("rev-parse HEAD^", gitleaks_bash)
        self.assertIn(
            'git diff --quiet "$base_sha"..."$head_sha" '
            "-- .gitleaks.toml",
            gitleaks_bash,
        )
        self.assertIn(
            'test "$(git rev-parse HEAD)" = "$head_sha"',
            gitleaks_bash,
        )
        for mutable_head_use in (
            'git merge-base --is-ancestor "$base_sha" HEAD',
            'git archive --format=tar HEAD',
            '--log-opts="$base_sha..HEAD"',
        ):
            self.assertNotIn(mutable_head_use, gitleaks_bash)
        self.assertIn(
            "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb",
            gitleaks_bash,
        )
        self.assertEqual(
            len(re.findall(r'"\$tool"\s+git\b', gitleaks_bash)),
            1,
        )
        self.assertEqual(
            len(re.findall(r'"\$tool"\s+dir\b', gitleaks_bash)),
            1,
        )
        self.assertIn(
            'cp "$base_tree/.gitleaks.toml" "$tmp_root/base-config.toml"',
            gitleaks_bash,
        )
        self.assertIn(
            'cmp "$tmp_root/base-config.toml" "$head_tree/.gitleaks.toml"',
            gitleaks_bash,
        )
        self.assertEqual(
            gitleaks_bash.count('>"$stdout_file" 2>"$stderr_file"'),
            2,
        )
        self.assertIn("if history or introduced:", gitleaks_bash)
        self.assertIn("raise SystemExit(1)", gitleaks_bash)
        self.assertIn("legacy_remote_head=", reconstruct_bash)
        self.assertEqual(
            reconstruct_bash.count(
                'git ls-remote --heads origin "$source_branch"'
            ),
            2,
        )
        self.assertIn("git fetch origin --prune", push_bash)
        self.assertIn(
            'git merge-base --is-ancestor "$reviewed_base" "$reviewed_head"',
            push_bash,
        )
        self.assertNotIn(
            "git merge-base --is-ancestor origin/main HEAD",
            push_bash,
        )
        self.assertIn(
            'test "$(git rev-parse HEAD)" = "$reviewed_head"',
            push_bash,
        )
        self.assertIn(
            'test "$(git rev-parse origin/main)" = "$reviewed_base"',
            push_bash,
        )
        self.assertIn("task8-review-tuple", push_bash)
        self.assertIn(
            'test "$(sha256sum "$review_package" | awk',
            push_bash,
        )
        self.assertLess(
            push_bash.index("git fetch origin --prune"),
            push_bash.index(
                'test "$(git rev-parse origin/main)" = "$reviewed_base"'
            ),
        )
        self.assertLess(
            push_bash.index(
                'test "$(git rev-parse origin/main)" = "$reviewed_base"'
            ),
            push_bash.index(
                'git push origin '
                '"$reviewed_head:refs/heads/$publication_branch"'
            ),
        )
        self.assertEqual(
            len(re.findall(r"(?m)^git push\b", push_bash)),
            1,
        )
        self.assertNotRegex(push_bash, r"(?m)^git push[^\n]* \+")
        for pr_field in (
            "baseRefName",
            "headRefName",
            "headRefOid",
            "isDraft",
        ):
            self.assertIn(pr_field, push_bash)
        pr_binding_body = push_bash.split(
            "verify_pr_binding() {",
            1,
        )[1].split("\n}\npr=", 1)[0]
        remote_oid_guard = (
            "  test \"$(git ls-remote --heads origin "
            "\"$publication_branch\" | awk '{print $1}')\" = \\\n"
            '    "$reviewed_head"'
        )
        self.assertIn(remote_oid_guard, pr_binding_body)
        pr_binding_calls = tuple(
            match.start()
            for match in re.finditer(
                r"(?m)^verify_pr_binding$",
                push_bash,
            )
        )
        self.assertEqual(len(pr_binding_calls), 2)
        checks_index = push_bash.index("gh pr checks --watch")
        self.assertLess(pr_binding_calls[0], checks_index)
        self.assertLess(checks_index, pr_binding_calls[1])
        for unsafe_push in (
            "git push -f",
            "git push --" "force",
            "--force-with-lease",
        ):
            self.assertNotIn(unsafe_push, push_bash)
        self.assertIn(
            "subagent-driven-development/scripts/review-package",
            review_bash,
        )
        self.assertIn(
            "review_script_sha256="
            "0c0629f6e2c46fc8bf68dcfb8a247ab24eb548b7004fe494035e6fcba9b5cdfb",
            review_bash,
        )
        self.assertIn(
            'test ! -e "$review_package"',
            review_bash,
        )
        self.assertIn(
            'test ! -L "$review_package"',
            review_bash,
        )
        self.assertIn(
            '/usr/bin/bash "$normalized_review_script" '
            '"$base_sha" "$review_head" "$review_package"',
            review_bash,
        )
        self.assertIn(
            'cmp "$expected_review_package" "$review_package"',
            review_bash,
        )
        self.assertIn(
            'git diff -U10 "${base_sha}..${review_head}"',
            review_bash,
        )
        self.assertIn("review_package_sha256=", review_bash)
        self.assertIn(
            'review_tuple_file="$review_dir/task8-review-tuple"',
            review_bash,
        )
        self.assertIn(
            'mv -T -- "$review_tuple_tmp" "$review_tuple_file"',
            review_bash,
        )
        self.assertIn(
            'git merge-base --is-ancestor "$base_sha" "$review_head"',
            review_bash,
        )
        for review_boundary_bash in (review_bash, push_bash):
            self.assertIn(
                'test ! -L "$review_parent"',
                review_boundary_bash,
            )
            self.assertIn(
                'test ! -L "$review_dir"',
                review_boundary_bash,
            )
            self.assertIn(
                'test "$(realpath -e "$review_dir")" = "$review_dir"',
                review_boundary_bash,
            )
        self.assertIn(
            "create a focused commit before rerunning Steps 3-6",
            review_section,
        )
        self.assertIn("make test-no-skip", functional_bash)
        self.assertNotRegex(functional_bash, r"(?m)^make test$")
        for strict_bash in (
            reconstruct_bash,
            scope_bash,
            functional_bash,
            ignore_bash,
            gitleaks_bash,
            review_bash,
            push_bash,
        ):
            self.assertTrue(
                strict_bash.lstrip().startswith("set -euo pipefail\n")
            )
        self.assertIn("\nset +e\n", ignore_bash)
        self.assertIn("\nset -e\n", ignore_bash)
        self.assertLess(
            ignore_bash.index("\nset +e\n"),
            ignore_bash.index("\nset -e\n"),
        )
        self.assertIn(
            'git merge-base --is-ancestor "$base_sha" "$scope_head"',
            scope_bash,
        )
        self.assertNotIn("rev-parse HEAD^", scope_bash)
        self.assertNotIn("source_head=", scope_bash)
        self.assertIn(
            'test "$(git rev-parse HEAD)" = "$scope_head"',
            scope_bash,
        )
        for mutable_scope_use in (
            'git diff --name-only "$base_sha"...HEAD',
            'git diff --check "$base_sha"...HEAD',
            'git diff --quiet "$base_sha"...HEAD',
        ):
            self.assertNotIn(mutable_scope_use, scope_bash)

        legacy_push_pattern = (
            r"git push origin codex/add-readonly-"
            r"diagnostics(?!-clean)\b"
        )
        legacy_head_pattern = (
            r"--head codex/add-readonly-"
            r"diagnostics(?!-clean)\b"
        )
        legacy_head_guard = (
            "headRefName -ne 'codex/add-readonly-"
            "diagnostics'"
        )
        self.assertNotRegex(plan, legacy_push_pattern)
        self.assertNotRegex(plan, legacy_head_pattern)
        self.assertNotIn(legacy_head_guard, plan)
        self.assertNotIn("git push --" "force", procedure)

    def test_plan_task7_policy_block_matches_canonical_boundary_bytes(self) -> None:
        begin = b"<!-- BEGIN CODEX_SHOGUN_READONLY_DIAGNOSTICS_V1 -->"
        end = b"<!-- END CODEX_SHOGUN_READONLY_DIAGNOSTICS_V1 -->"

        def marked_block(value: bytes) -> bytes:
            self.assertEqual(value.count(begin), 1)
            self.assertEqual(value.count(end), 1)
            start = value.index(begin)
            finish = value.index(end, start) + len(end)
            return value[start:finish]

        plan = PLAN.read_bytes()
        task7 = plan.split(b"### Task 7:", 1)[1].split(b"### Task 8:", 1)[0]
        task7 = task7.split(
            b"**Step 7: Add the exact trusted-gate policy block "
            b"to Shogun boundary docs**",
            1,
        )[1].split(b"**Step 8:", 1)[0]
        boundary = BOUNDARY_OPERATION.read_bytes()
        self.assertEqual(marked_block(task7), marked_block(boundary))

    def test_plan_merge_steps_bind_exact_reviewed_remote_heads(self) -> None:
        plan = PLAN.read_text(encoding="utf-8")
        tasks = (
            ("### Task 9:", "### Task 10:", "$ReviewedHead"),
            ("### Task 10:", "### Task 11:", '"$reviewed_head"'),
            ("### Task 11:", "### Task 12:", '"$reviewed_head"'),
        )
        for start, end, variable in tasks:
            with self.subTest(task=start):
                task = plan.split(start, 1)[1].split(end, 1)[0]
                self.assertIn("headRefOid", task)
                self.assertIn("git ls-remote --heads", task)
                self.assertIn("refs/heads/", task)
                self.assertIn("--match-head-commit", task)
                self.assertIn(variable, task)
                self.assertNotRegex(
                    task,
                    r"--json[^\n]*reviewDecision|\.reviewDecision",
                )
                self.assertEqual(
                    len(re.findall(r"(?m)^gh pr merge\b", task)),
                    1,
                )
                merge = task.split("gh pr merge", 1)[1].split("\n```", 1)[0]
                self.assertIn("--match-head-commit", merge)
                self.assertIn(variable, merge)
                post_merge = task.split("gh pr merge", 1)[1]
                self.assertIn("headRefOid", post_merge)

        task9 = plan.split("### Task 9:", 1)[1].split("### Task 10:", 1)[0]
        self.assertIn("task8-review-tuple", task9)
        self.assertIn("gh pr ready", task9)
        self.assertIn(
            "$ReviewedBase = $env:SHOGUN_DIAGNOSTICS_REVIEWED_BASE",
            task9,
        )
        self.assertIn(
            "$ReviewedHead = $env:SHOGUN_DIAGNOSTICS_REVIEWED_HEAD",
            task9,
        )
        self.assertIn(
            "$ReviewedPackageSha256 = "
            "$env:SHOGUN_DIAGNOSTICS_REVIEW_PACKAGE_SHA256",
            task9,
        )
        self.assertNotIn("$ReviewedBase = $ReviewTuple[0]", task9)
        self.assertNotIn("$ReviewedHead = $ReviewTuple[1]", task9)
        self.assertIn("$ReviewTuple[0] -ne $ReviewedBase", task9)
        self.assertIn("$ReviewTuple[1] -ne $ReviewedHead", task9)
        self.assertIn(
            "$ReviewTuple[2] -ne $ReviewedPackageSha256",
            task9,
        )
        self.assertIn("Get-FileHash", task9)
        self.assertIn("$ReviewedBase", task9)
        self.assertIn("baseRefOid", task9)
        self.assertIn("refs/heads/main", task9)
        self.assertIn("$ReviewTuple[0]", task9)
        self.assertIn("git diff --quiet $ReviewedHead $DeploySha", task9)
        self.assertIn("$LiveHead -ne $DeploySha", task9)
        self.assertIn("SHOGUN_DIAGNOSTICS_DEPLOY_SHA", task9)
        self.assertIn('test "$(git rev-parse HEAD)" = "$deploy_sha"', task9)
        self.assertIn('test "$(git rev-parse origin/main)" = "$deploy_sha"', task9)
        self.assertIn("function Assert-PrBinding", task9)
        self.assertGreaterEqual(task9.count("Assert-PrBinding"), 3)

        for start, end in (
            ("### Task 10:", "### Task 11:"),
            ("### Task 11:", "### Task 12:"),
        ):
            task = plan.split(start, 1)[1].split(end, 1)[0]
            self.assertIn('reviewed_base="$(git rev-parse origin/main)"', task)
            self.assertIn('reviewed_head="$(git rev-parse HEAD)"', task)
            self.assertIn("baseRefOid", task)
            self.assertIn("refs/heads/main", task)
            self.assertIn(
                'git push origin "$reviewed_head:refs/heads/$branch"',
                task,
            )
            self.assertIn(
                'git diff --quiet "$reviewed_head" "${merge_meta[2]}"',
                task,
            )
            self.assertIn("verify_pr_binding()", task)
            self.assertGreaterEqual(task.count("verify_pr_binding"), 3)

    def test_plan_precommit_scope_gates_cover_all_changed_paths(self) -> None:
        plan = PLAN.read_text(encoding="utf-8")
        tasks = (
            (
                "### Task 10:",
                "### Task 11:",
                (
                    "docs/superpowers/plans/"
                    "2026-07-14-codex-readonly-diagnostics-work-log.md",
                ),
            ),
            (
                "### Task 11:",
                "### Task 12:",
                (
                    "codex/CODEX_DESKTOP_CUSTOM_INSTRUCTIONS.md",
                    "codex/CODEX_DESKTOP_STARTUP.md",
                    "codex/work_log.md",
                ),
            ),
        )
        for start, end, expected_paths in tasks:
            with self.subTest(task=start):
                task = plan.split(start, 1)[1].split(end, 1)[0]
                step4 = task.split("**Step 4:", 1)[1].split(
                    "**Step 5:", 1
                )[0]
                self.assertIn("set -euo pipefail", step4)
                self.assertNotIn(
                    "git diff --name-only origin/main...HEAD",
                    step4,
                )
                self.assertIn(
                    "git diff --name-only -z --no-renames origin/main --",
                    step4,
                )
                self.assertIn(
                    "git ls-files --others --exclude-standard -z",
                    step4,
                )
                self.assertIn("worktree_scope=pass", step4)
                step5 = task.split("**Step 5:", 1)[1].split(
                    "**Step 6:", 1
                )[0]
                self.assertIn(
                    'git diff --name-only -z --no-renames',
                    step5,
                )
                self.assertIn('"$reviewed_base"', step5)
                self.assertIn('"$reviewed_head"', step5)
                self.assertIn("committed_scope=pass", step5)
                for expected_path in expected_paths:
                    self.assertIn(expected_path, step4)
                    self.assertIn(expected_path, step5)

    def test_plan_task11_compares_workspace_policy_to_canonical_raw_bytes(
        self,
    ) -> None:
        plan = PLAN.read_text(encoding="utf-8")
        task11 = plan.split("### Task 11:", 1)[1].split("### Task 12:", 1)[0]
        verification = task11.split(
            "**Step 4: Verify the Workspace three-file atomic diff**",
            1,
        )[1].split("**Step 5:", 1)[0]
        self.assertIn("raw.githubusercontent.com/sjinnouchi-ux/", verification)
        self.assertIn("multi-agent-shogun", verification)
        self.assertIn("python3 -I - <<'PY'", verification)
        self.assertIn("read_bytes()", verification)
        self.assertNotIn("read_text(", verification)
        self.assertIn(
            "startup_block == custom_block == canonical_block",
            verification,
        )
        begin = b"<!-- BEGIN CODEX_SHOGUN_READONLY_DIAGNOSTICS_V1 -->"
        end = b"<!-- END CODEX_SHOGUN_READONLY_DIAGNOSTICS_V1 -->"
        boundary = BOUNDARY_OPERATION.read_bytes().replace(b"\r\n", b"\n")
        start = boundary.index(begin)
        finish = boundary.index(end, start) + len(end)
        expected_block_sha256 = hashlib.sha256(
            boundary[start:finish]
        ).hexdigest()
        self.assertIn(expected_block_sha256, verification)
        merge_step = task11.split(
            "**Step 6: Merge Workspace and verify raw main**",
            1,
        )[1].split("**Step 7:", 1)[0]
        self.assertIn("raw-byte equality gate", merge_step)
        host_step = task11.split(
            "**Step 7: Perform the one-time host marker insertion",
            1,
        )[1].split("**Step 8:", 1)[0]
        self.assertIn(expected_block_sha256, host_step)
        self.assertIn("CandidateBlock", host_step)
        self.assertIn("SHA256", host_step)

    def test_plan_marks_obsolete_rollback_listings_non_executable(self) -> None:
        plan = PLAN.read_text(encoding="utf-8")
        rollback_step = plan.split(
            "- [ ] **Step 5: Implement and test the snapshot lifecycle primitives**",
            1,
        )[1]
        rollback_preamble = rollback_step.split(
            "#### SUPERSEDED NON-EXECUTABLE ROLLBACK LISTINGS", 1
        )[0]
        self.assertIn(
            "scripts/rollback_codex_diagnostics_snapshot.py",
            rollback_preamble,
        )
        self.assertIn(
            "tests/unit/test_rollback_codex_diagnostics_snapshot.py",
            rollback_preamble,
        )
        self.assertNotIn("from the second listing", rollback_preamble)
        self.assertIn("cleanup failure", rollback_preamble)
        self.assertIn("temporary-name inode substitution", rollback_preamble)
        consumer_preamble = plan.split(
            "Use this mandatory TDD execution order", 1
        )[1].split(
            "GREEN implementation listing for "
            "`tests/contract/codex_diagnostics_consumer.py`",
            1,
        )[0]
        self.assertNotIn("rollback_codex_diagnostics_snapshot", consumer_preamble)
        self.assertIn("SUPERSEDED NON-EXECUTABLE ROLLBACK LISTINGS", plan)
        self.assertNotIn(
            "GREEN implementation listing for "
            "`scripts/rollback_codex_diagnostics_snapshot.py`",
            plan,
        )
        self.assertNotIn(
            "RED-first listing for "
            "`tests/unit/test_rollback_codex_diagnostics_snapshot.py`",
            plan,
        )
        self.assertIn("RollbackCommitOrCleanupIndeterminate", plan)
        self.assertNotIn("RollbackCommittedIndeterminate", plan)
        self.assertIn("cleanup/durability", plan)

    def test_plan_task9_uses_tested_no_replace_initial_installer(self) -> None:
        plan = PLAN.read_text(encoding="utf-8")
        task9_install = plan.split(
            "- [ ] **Step 5: Atomically install the first snapshot or prove it is already identical**",
            1,
        )[1].split(
            "- [ ] **Step 6: Validate fixed JSON and suffix rejection without exposing raw output**",
            1,
        )[0]
        self.assertIn(
            "scripts/rollback_codex_diagnostics_snapshot.py", task9_install
        )
        self.assertIn("install-initial", task9_install)
        self.assertIn("snapshot_install=installed", task9_install)
        self.assertIn("snapshot_install=already_current", task9_install)
        self.assertIn("install_rc", task9_install)
        self.assertNotIn("mv -T", task9_install)
        self.assertNotIn("mktemp", task9_install)

    def test_plan_task12_uses_legacy_rollback_mode_only(self) -> None:
        plan = PLAN.read_text(encoding="utf-8")
        task12 = plan.split(
            "### Task 12: Smoke-Test Both Codex Task Boundaries, Record Completion, and Clean Up",
            1,
        )[1].split("## Spec Coverage Map", 1)[0]
        rollback_invocation = task12.split(
            "python3 -I scripts/rollback_codex_diagnostics_snapshot.py",
            1,
        )[1].split("rollback_rc=", 1)[0]
        self.assertIn("--failing-sha256", rollback_invocation)
        self.assertIn("--target-sha256", rollback_invocation)
        self.assertIn("--target-blob", rollback_invocation)
        self.assertNotIn("install-initial", rollback_invocation)
        self.assertIn("Never use", task12)
        self.assertIn("Task 9's first-install helper", task12)
        self.assertIn("Never invoke `install-initial`", task12)

    def test_plan_task11_host_agents_write_is_exclusive_same_handle_cas(
        self,
    ) -> None:
        plan = PLAN.read_text(encoding="utf-8")
        task11_step7 = plan.split(
            "- [ ] **Step 7: Perform the one-time host marker insertion without replacing the file**",
            1,
        )[1].split(
            "- [ ] **Step 8: Request only the complete persistent argv prefix**",
            1,
        )[0]
        required = (
            "function Invoke-HostAgentsSameHandleCas",
            "explicit single-file elevation",
            "[IO.FileMode]::Open",
            "[IO.FileAccess]::ReadWrite",
            "[IO.FileShare]::None",
            "[IO.FileOptions]::WriteThrough",
            "$Current = Read-StreamBytes $HostStream",
            "host changed since candidate review; no write performed",
            "[IO.FileMode]::CreateNew",
            "$BackupStream.Flush($true)",
            "$BackupReadback = Read-StreamBytes $BackupStream",
            "$BackupStream.Dispose()",
            "$HostStream.Write($Candidate",
            "$HostStream.SetLength($Candidate.Length)",
            "$HostStream.Flush($true)",
            "$Installed = Read-StreamBytes $HostStream",
            "$HostStream.Write($BackupReadback",
            "$HostStream.SetLength($BackupReadback.Length)",
            "$Restored = Read-StreamBytes $HostStream",
            "host write failed; exact same-handle restore verified; durable backup retained; stop before command approval",
            "durable backup retained; stop before command approval",
            "Assert-MarkerState $Installed",
            "Assert-MarkerState $Restored",
            "Remove-Item -LiteralPath $CandidatePath",
            "host committed but candidate cleanup failed; stop before command approval",
        )
        for fragment in required:
            self.assertIn(fragment, task11_step7)
        self.assertGreaterEqual(task11_step7.count("[IO.FileShare]::None"), 2)
        self.assertGreaterEqual(task11_step7.count("[IO.FileOptions]::WriteThrough"), 2)
        self.assertGreaterEqual(task11_step7.count("$HostStream.Flush($true)"), 2)
        self.assertGreaterEqual(
            task11_step7.count("Read-StreamBytes $HostStream"), 3
        )
        self.assertEqual(task11_step7.count("[IO.FileMode]::Open"), 1)
        self.assertEqual(task11_step7.count("[IO.FileStream]::new("), 2)
        self.assertEqual(task11_step7.count("ReadAllBytes($HostPath)"), 1)
        stale_check = task11_step7.index(
            "host changed since candidate review; no write performed"
        )
        backup_create = task11_step7.index("[IO.FileMode]::CreateNew")
        backup_readback = task11_step7.index(
            "$BackupReadback = Read-StreamBytes $BackupStream"
        )
        candidate_write = task11_step7.index("$HostStream.Write($Candidate")
        self.assertLess(stale_check, backup_create)
        self.assertLess(backup_create, backup_readback)
        self.assertLess(backup_readback, candidate_write)
        candidate_length = task11_step7.index(
            "$HostStream.SetLength($Candidate.Length)", candidate_write
        )
        candidate_flush = task11_step7.index(
            "$HostStream.Flush($true)", candidate_length
        )
        installed_read = task11_step7.index(
            "$Installed = Read-StreamBytes $HostStream", candidate_flush
        )
        installed_marker = task11_step7.index(
            "Assert-MarkerState $Installed", installed_read
        )
        restore_write = task11_step7.index(
            "$HostStream.Write($BackupReadback", installed_marker
        )
        restore_length = task11_step7.index(
            "$HostStream.SetLength($BackupReadback.Length)", restore_write
        )
        restore_flush = task11_step7.index(
            "$HostStream.Flush($true)", restore_length
        )
        restored_read = task11_step7.index(
            "$Restored = Read-StreamBytes $HostStream", restore_flush
        )
        restored_marker = task11_step7.index(
            "Assert-MarkerState $Restored", restored_read
        )
        backup_dispose = task11_step7.index(
            "$BackupStream.Dispose()", restored_marker
        )
        committed_guard = task11_step7.index(
            "if (-not $Committed)", backup_dispose
        )
        backup_remove = task11_step7.index(
            "Remove-Item -LiteralPath $BackupPath", committed_guard
        )
        self.assertLess(candidate_write, candidate_length)
        self.assertLess(candidate_length, candidate_flush)
        self.assertLess(candidate_flush, installed_read)
        self.assertLess(installed_read, installed_marker)
        self.assertLess(installed_marker, restore_write)
        self.assertLess(restore_write, restore_length)
        self.assertLess(restore_length, restore_flush)
        self.assertLess(restore_flush, restored_read)
        self.assertLess(restored_read, restored_marker)
        self.assertLess(restored_marker, backup_dispose)
        self.assertLess(backup_dispose, committed_guard)
        self.assertLess(committed_guard, backup_remove)
        self.assertNotIn("[IO.File]::WriteAllBytes", task11_step7)
        self.assertNotIn("Copy-Item", task11_step7)

    def test_plan_task12_host_marker_removal_reuses_same_handle_cas(self) -> None:
        plan = PLAN.read_text(encoding="utf-8")
        task12 = plan.split(
            "### Task 12: Smoke-Test Both Codex Task Boundaries, Record Completion, and Clean Up",
            1,
        )[1].split("## Spec Coverage Map", 1)[0]
        removal = task12.split(
            "2. Copy host `AGENTS.md` to a task candidate", 1
        )[1].split(
            "3. In a clean Workspace branch", 1
        )[0]
        required = (
            "Invoke-HostAgentsSameHandleCas",
            "reproduced verbatim below",
            "# BEGIN HOST_AGENTS_SAME_HANDLE_CAS_V1",
            "function Test-BytesEqual",
            "function Read-StreamBytes",
            "function Find-ByteOffsets",
            "function Assert-MarkerState",
            "function Invoke-HostAgentsSameHandleCas",
            "[IO.FileMode]::Open",
            "[IO.FileAccess]::ReadWrite",
            "[IO.FileShare]::None",
            "[IO.FileOptions]::WriteThrough",
            "[IO.FileMode]::CreateNew",
            "Flush($true)",
            "Read-StreamBytes $HostStream",
            "-ExpectedBeforeBeginCount 1",
            "-ExpectedBeforeEndCount 1",
            "-ExpectedCandidateBeginCount 0",
            "-ExpectedCandidateEndCount 0",
            "Assert-MarkerState $Before 1 1",
            "Assert-MarkerState $Candidate 0 0",
            "$WithoutBlock = [byte[]]::new($Before.Length - ($Finish - $Start))",
            "Test-BytesEqual $WithoutBlock $Candidate",
            "Remove-Item -LiteralPath $CandidatePath",
            "same handle",
            "durable backup retained",
            "command approval remains revoked",
        )
        for fragment in required:
            self.assertIn(fragment, removal)
        self.assertNotIn("[IO.File]::WriteAllBytes", removal)
        self.assertNotIn("Copy-Item", removal)

        block_begin = "# BEGIN HOST_AGENTS_SAME_HANDLE_CAS_V1"
        block_end = "# END HOST_AGENTS_SAME_HANDLE_CAS_V1"
        self.assertEqual(plan.count(block_begin), 2)
        self.assertEqual(plan.count(block_end), 2)
        first = plan.split(block_begin, 1)[1].split(block_end, 1)[0]
        second = plan.split(block_begin, 2)[2].split(block_end, 1)[0]
        self.assertEqual(first, second)

    def test_plan_host_agents_byte_contract_preserves_bom_and_eol_fixtures(
        self,
    ) -> None:
        begin = b"<!-- BEGIN CODEX_SHOGUN_READONLY_DIAGNOSTICS_V1 -->"
        end = b"<!-- END CODEX_SHOGUN_READONLY_DIAGNOSTICS_V1 -->"
        for bom in (b"", b"\xef\xbb\xbf"):
            for eol in (b"\n", b"\r\n"):
                before = bom + b"strict host rule" + eol + b"tail" + eol
                block = begin + eol + b"fixed policy" + eol + end + eol
                insertion = len(bom + b"strict host rule" + eol)
                candidate = before[:insertion] + block + before[insertion:]
                start = candidate.index(begin)
                finish = candidate.index(end) + len(end)
                if candidate[finish:finish + 2] == b"\r\n":
                    finish += 2
                elif candidate[finish:finish + 1] == b"\n":
                    finish += 1
                restored = candidate[:start] + candidate[finish:]
                self.assertEqual(restored, before)
                self.assertEqual(candidate[:len(bom)], bom)
        plan = PLAN.read_text(encoding="utf-8")
        task11_and_12 = plan.split(
            "### Task 11: Enable the Workspace Policy and Preserve Host-Specific Rules",
            1,
        )[1].split("## Spec Coverage Map", 1)[0]
        self.assertIn("including BOM and line endings", task11_and_12)
        self.assertIn("byte-identical", task11_and_12)
        self.assertNotIn("[IO.File]::ReadAllText", task11_and_12)

    def test_plan_host_agents_actual_powershell_remove_stale_restore_fixtures(
        self,
    ) -> None:
        powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell is unavailable outside the WSL host gate")
        plan = PLAN.read_text(encoding="utf-8")
        removal = plan.split(
            "2. Copy host `AGENTS.md` to a task candidate", 1
        )[1].split("3. In a clean Workspace branch", 1)[0]
        task12_block = removal.split("```powershell\n", 1)[1].split(
            "\n```", 1
        )[0]
        fixed_host = "$HostPath = 'C:\\Users\\jinnouchi\\.codex\\AGENTS.md'"
        fixed_candidate = (
            "$CandidatePath = "
            "(Resolve-Path '.\\AGENTS.host.rollback.candidate.md').Path"
        )
        self.assertEqual(task12_block.count(fixed_host), 1)
        self.assertEqual(task12_block.count(fixed_candidate), 1)
        task12_block = task12_block.replace(
            fixed_host, "$HostPath = $SyntheticHostPath"
        ).replace(
            fixed_candidate, "$CandidatePath = $SyntheticCandidatePath"
        )
        harness = r'''
$ErrorActionPreference = 'Stop'
$Root = Join-Path ([IO.Path]::GetTempPath()) (
    'shogun-host-cas-test-' + [Guid]::NewGuid().ToString('N')
)
[void][IO.Directory]::CreateDirectory($Root)
$FixtureError = $null
try {
    $FixtureUtf8 = [Text.UTF8Encoding]::new($false, $true)
    $Bom = [byte[]](0xef, 0xbb, 0xbf)
    $BeforeText = "strict host rule`r`n" +
        "<!-- BEGIN CODEX_SHOGUN_READONLY_DIAGNOSTICS_V1 -->`r`n" +
        "fixed policy`r`n" +
        "<!-- END CODEX_SHOGUN_READONLY_DIAGNOSTICS_V1 -->`r`n" +
        "tail`r`n"
    $CandidateText = "strict host rule`r`ntail`r`n"
    $FixtureBefore = [byte[]]($Bom + $FixtureUtf8.GetBytes($BeforeText))
    $FixtureCandidate = [byte[]]($Bom + $FixtureUtf8.GetBytes($CandidateText))
    $SyntheticHostPath = Join-Path $Root 'AGENTS.md'
    $SyntheticCandidatePath = Join-Path $Root 'candidate.md'
    [IO.File]::WriteAllBytes($SyntheticHostPath, $FixtureBefore)
    [IO.File]::WriteAllBytes($SyntheticCandidatePath, $FixtureCandidate)
__TASK12_BLOCK__
    if (-not $Committed -or
        -not (Test-BytesEqual `
            ([IO.File]::ReadAllBytes($SyntheticHostPath)) $FixtureCandidate)) {
        throw 'synthetic removal failed'
    }
    if ([IO.File]::Exists($SyntheticCandidatePath)) {
        throw 'successful removal did not clean candidate'
    }
    if ([IO.Directory]::GetFiles(
        $Root, 'AGENTS.host.backup.*.bin'
    ).Count -ne 0) { throw 'success backup was not removed' }

    [IO.File]::WriteAllBytes($SyntheticHostPath, $FixtureBefore)
    $Stale = $Utf8.GetBytes('stale reviewed bytes')
    $Caught = $false
    try {
        $Ignored = Invoke-HostAgentsSameHandleCas `
            -HostPath $SyntheticHostPath `
            -ExpectedBefore $Stale `
            -Candidate $FixtureCandidate `
            -BackupDirectory $Root `
            -ExpectedBeforeBeginCount 1 `
            -ExpectedBeforeEndCount 1 `
            -ExpectedCandidateBeginCount 0 `
            -ExpectedCandidateEndCount 0
    } catch {
        if ($_.Exception.Message -notlike
            '*host changed since candidate review; no write performed*') { throw }
        $Caught = $true
    }
    if (-not $Caught -or
        -not (Test-BytesEqual `
            ([IO.File]::ReadAllBytes($SyntheticHostPath)) $FixtureBefore)) {
        throw 'synthetic stale no-op failed'
    }
    if ([IO.Directory]::GetFiles(
        $Root, 'AGENTS.host.backup.*.bin'
    ).Count -ne 0) { throw 'stale path created a backup' }

    [IO.File]::WriteAllBytes($SyntheticHostPath, $FixtureBefore)
    $Caught = $false
    try {
        $Ignored = Invoke-HostAgentsSameHandleCas `
            -HostPath $SyntheticHostPath `
            -ExpectedBefore $FixtureBefore `
            -Candidate $FixtureCandidate `
            -BackupDirectory $Root `
            -ExpectedBeforeBeginCount 1 `
            -ExpectedBeforeEndCount 1 `
            -ExpectedCandidateBeginCount 1 `
            -ExpectedCandidateEndCount 1
    } catch {
        if ($_.Exception.Message -notlike
            '*exact same-handle restore verified*') { throw }
        $Caught = $true
    }
    if (-not $Caught -or
        -not (Test-BytesEqual `
            ([IO.File]::ReadAllBytes($SyntheticHostPath)) $FixtureBefore)) {
        throw 'synthetic verified restore failed'
    }
    $Backups = [IO.Directory]::GetFiles(
        $Root, 'AGENTS.host.backup.*.bin'
    )
    if ($Backups.Count -ne 1 -or
        -not (Test-BytesEqual `
            ([IO.File]::ReadAllBytes($Backups[0])) $FixtureBefore)) {
        throw 'verified restore backup was not retained'
    }
} catch {
    $FixtureError = $_
} finally {
    [IO.Directory]::Delete($Root, $true)
}
if ($null -ne $FixtureError) { exit 23 }
Write-Output 'HOST_CAS_SYNTHETIC_PASS'
exit 0
'''.replace("__TASK12_BLOCK__", task12_block)
        script_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="ascii",
                newline="\r\n",
                suffix=".ps1",
                prefix=".host-cas-fixture-",
                dir=ROOT,
                delete=False,
            ) as script_file:
                script_file.write(harness)
                script_path = Path(script_file.name)
            script_argument = str(script_path)
            if powershell.lower().endswith(".exe"):
                converted = subprocess.run(
                    ["wslpath", "-w", script_argument],
                    text=True,
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
                if converted.returncode != 0:
                    self.fail("PowerShell fixture path conversion failed")
                script_argument = converted.stdout.strip()
            completed = subprocess.run(
                [
                    powershell,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    script_argument,
                ],
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
        finally:
            if script_path is not None:
                script_path.unlink(missing_ok=True)
        normalized_stdout = completed.stdout.replace("\x00", "")
        if (
            completed.returncode != 0
            or normalized_stdout.count("HOST_CAS_SYNTHETIC_PASS") != 1
        ):
            self.fail(
                "PowerShell synthetic host CAS fixture failed "
                f"(exit={completed.returncode})"
            )


if __name__ == "__main__":
    unittest.main()

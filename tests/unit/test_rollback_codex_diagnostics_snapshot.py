from __future__ import annotations

import concurrent.futures
import fcntl
import hashlib
import importlib.util
import io
import os
import stat
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

    def test_parent_swap_before_replace_refuses_and_cleans_pinned_directory(
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
            with self.assertRaises(self.module.RollbackRefused):
                self.rollback_paths(snapshot, target)
        self.assertEqual((moved / snapshot.name).read_bytes(), self.current_bytes)
        self.assertEqual((parent / snapshot.name).read_bytes(), decoy)
        self.assertEqual(
            list(moved.glob(".shogun-codex-diagnostics.rollback.*")), []
        )
        self.assertEqual(
            list(parent.glob(".shogun-codex-diagnostics.rollback.*")), []
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

    def test_replace_failure_preserves_current_and_removes_temp(self) -> None:
        with mock.patch.object(self.module.os, "replace", side_effect=OSError):
            with self.assertRaises(OSError):
                self.rollback()
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


if __name__ == "__main__":
    unittest.main()

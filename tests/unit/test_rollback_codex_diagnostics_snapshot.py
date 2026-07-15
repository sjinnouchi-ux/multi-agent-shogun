from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import os
import stat
import sys
import tempfile
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
        self.assertEqual(self.snapshot.stat().st_mode & 0o777, 0o555)
        self.assertEqual(
            list(self.root.glob(".shogun-codex-diagnostics.rollback.*")), []
        )

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

        for parent in (self.snapshot.parent, self.target.parent):
            matching = [item for item in calls if item[0] == os.fspath(parent)]
            self.assertTrue(matching)
            self.assertTrue(any(flags & os.O_DIRECTORY for _, flags, _ in matching))
            self.assertTrue(any(flags & os.O_NOFOLLOW for _, flags, _ in matching))
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
            "- [ ] **Step 5: Implement and test the atomic snapshot rollback primitive**",
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


if __name__ == "__main__":
    unittest.main()

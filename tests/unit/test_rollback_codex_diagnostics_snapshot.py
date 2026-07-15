from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts" / "rollback_codex_diagnostics_snapshot.py"


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
        self.module.atomic_rollback(
            snapshot=self.snapshot,
            target_blob=self.target,
            failing_sha256=sha(self.current_bytes),
            target_sha256=sha(self.target_bytes),
        )

    def test_success_uses_mode_0555_temp_in_same_directory_and_atomic_replace(self) -> None:
        real_replace = os.replace
        observed = {}

        def checked_replace(source, destination):
            source_path = Path(source)
            observed["parent"] = source_path.parent
            observed["mode"] = source_path.stat().st_mode & 0o777
            observed["destination"] = Path(destination)
            real_replace(source, destination)

        with mock.patch.object(self.module.os, "replace", side_effect=checked_replace):
            self.rollback()
        self.assertEqual(observed["parent"], self.snapshot.parent)
        self.assertEqual(observed["mode"], 0o555)
        self.assertEqual(observed["destination"], self.snapshot)
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

    def test_current_change_before_replace_is_not_overwritten(self) -> None:
        real_read = self.module._read_regular
        current_reads = 0
        changed = b"changed-by-another-process"

        def mutate_before_second_current_read(path, required_mode):
            nonlocal current_reads
            if Path(path) == self.snapshot:
                current_reads += 1
                if current_reads == 2:
                    self.snapshot.chmod(0o755)
                    self.snapshot.write_bytes(changed)
                    self.snapshot.chmod(0o555)
            return real_read(path, required_mode)

        with mock.patch.object(
            self.module, "_read_regular", side_effect=mutate_before_second_current_read
        ):
            with self.assertRaises(self.module.RollbackRefused):
                self.rollback()
        self.assertEqual(self.snapshot.read_bytes(), changed)

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

    def test_replace_failure_preserves_current_and_removes_temp(self) -> None:
        with mock.patch.object(self.module.os, "replace", side_effect=OSError):
            with self.assertRaises(OSError):
                self.rollback()
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)
        self.assertEqual(
            list(self.root.glob(".shogun-codex-diagnostics.rollback.*")), []
        )

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
            with self.assertRaises(self.module.RollbackCommittedIndeterminate):
                self.rollback()
        self.assertEqual(self.snapshot.read_bytes(), self.target_bytes)
        self.assertEqual(self.snapshot.stat().st_mode & 0o777, 0o555)

    def test_replace_error_after_visible_commit_is_indeterminate(self) -> None:
        real_replace = os.replace

        def replace_then_error(source, destination):
            real_replace(source, destination)
            raise OSError("rename result uncertain")

        with mock.patch.object(
            self.module.os, "replace", side_effect=replace_then_error
        ):
            with self.assertRaises(self.module.RollbackCommittedIndeterminate):
                self.rollback()
        self.assertEqual(self.snapshot.read_bytes(), self.target_bytes)

    def test_cli_maps_committed_indeterminate_to_exit_four(self) -> None:
        with mock.patch.object(
            self.module,
            "atomic_rollback",
            side_effect=self.module.RollbackCommittedIndeterminate,
        ):
            result = self.module.main((
                "--failing-sha256", sha(self.current_bytes),
                "--target-sha256", sha(self.target_bytes),
                "--target-blob", str(self.target),
            ))
        self.assertEqual(result, 4)


if __name__ == "__main__":
    unittest.main()

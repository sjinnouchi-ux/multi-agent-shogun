from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts" / "codex_diagnostics.py"
WORK_LOG = (
    ROOT
    / "docs"
    / "superpowers"
    / "plans"
    / "2026-07-14-codex-readonly-diagnostics-work-log.md"
)


def load_module():
    spec = importlib.util.spec_from_file_location("codex_diagnostics", SOURCE)
    if spec is None or spec.loader is None:
        raise AssertionError("diagnostics module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CliAndSourceHashTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def test_summary_is_the_only_accepted_argument_vector(self) -> None:
        self.assertIsNone(self.module.parse_argv(("summary",)))
        for argv in ((), ("status",), ("summary", "extra"), ("summary", "--raw")):
            with self.subTest(argv=argv), self.assertRaises(
                self.module.ArgumentRejected
            ):
                self.module.parse_argv(argv)

    def test_source_hash_accepts_only_fixed_mode_regular_bounded_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "snapshot"
            source.write_bytes(b"#!/usr/bin/python3 -I\nprint('safe')\n")
            source.chmod(0o555)
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(self.module.calculate_source_sha256(source), expected)

            source.chmod(0o755)
            with self.assertRaises(self.module.InternalFailure):
                self.module.calculate_source_sha256(source)

            source.chmod(0o555)
            link = root / "link"
            link.symlink_to(source)
            with self.assertRaises(self.module.InternalFailure):
                self.module.calculate_source_sha256(link)

            large = root / "large"
            large.write_bytes(b"x" * (1_048_576 + 1))
            large.chmod(0o555)
            with self.assertRaises(self.module.InternalFailure):
                self.module.calculate_source_sha256(large)

    def test_source_hash_rejects_metadata_change_during_read(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "snapshot"
            source.write_bytes(b"#!/usr/bin/python3 -I\n")
            source.chmod(0o555)
            fd = os.open(source, os.O_RDONLY)
            try:
                before = os.fstat(fd)
            finally:
                os.close(fd)
            changed_values = list(before)
            changed_values[8] = before.st_mtime + 1
            changed = os.stat_result(changed_values)
            with mock.patch.object(
                self.module.os, "fstat", side_effect=(before, changed)
            ):
                with self.assertRaises(self.module.InternalFailure):
                    self.module.calculate_source_sha256(source)

    def test_default_source_hash_rejects_repo_or_renamed_execution_path(self) -> None:
        with self.assertRaises(self.module.InternalFailure):
            self.module.calculate_source_sha256()

    def test_failure_document_and_literal_fallback_are_exact(self) -> None:
        document = self.module.build_failure_document("argument_rejected")
        self.assertEqual(
            tuple(document),
            (
                "schema_version",
                "generated_at",
                "ok",
                "overall",
                "tool",
                "repository",
                "sessions",
                "processes",
                "global_sources",
                "agents",
                "errors",
                "warnings",
            ),
        )
        self.assertFalse(document["ok"])
        self.assertEqual(document["tool"]["source_sha256"], None)
        self.assertEqual(document["errors"][0]["code"], "argument_rejected")
        fallback = json.loads(self.module.FALLBACK_INTERNAL_ERROR)
        self.assertEqual(fallback["tool"]["source_sha256"], None)
        self.assertEqual(fallback["errors"][0]["code"], "internal_error")

    def test_issue_arrays_are_deduplicated_sorted_and_bounded(self) -> None:
        issue = self.module.Issue("watcher_missing", "process", "ashigaru1")
        many = [issue, issue]
        for code in self.module.ERROR_CODES:
            for component in self.module.COMPONENTS:
                for agent in (None, *self.module.AGENT_IDS):
                    many.append(self.module.Issue(code, component, agent))
                    if len(many) >= 72:
                        break
                if len(many) >= 72:
                    break
            if len(many) >= 72:
                break
        errors, warnings = self.module.normalize_issues(many, ())
        self.assertEqual(len(errors), 64)
        self.assertIn("result_truncated", {item["code"] for item in errors})
        self.assertEqual(warnings, [])
        self.assertEqual(errors, sorted(errors, key=lambda item: (
            item["code"], item["component"], item["agent"] or ""
        )))

        warning_errors, bounded_warnings = self.module.normalize_issues((), many)
        self.assertEqual(len(bounded_warnings), 64)
        self.assertIn("result_truncated", {item["code"] for item in warning_errors})

    def test_deployment_work_log_has_one_marker_pair_and_at_most_one_active(self) -> None:
        text = WORK_LOG.read_text(encoding="utf-8")
        begin = "<!-- BEGIN CODEX_DIAGNOSTICS_DEPLOYMENTS_V1 -->"
        end = "<!-- END CODEX_DIAGNOSTICS_DEPLOYMENTS_V1 -->"
        self.assertEqual(text.count(begin), 1)
        self.assertEqual(text.count(end), 1)
        payload = text.split(begin, 1)[1].split(end, 1)[0].strip()
        self.assertNotIn("\n", payload)
        value = json.loads(payload)
        self.assertEqual(set(value), {"schema_version", "deployments"})
        self.assertEqual(value["schema_version"], 1)
        self.assertIsInstance(value["deployments"], list)
        self.assertLessEqual(
            sum(item.get("status") == "active" for item in value["deployments"]), 1
        )


if __name__ == "__main__":
    unittest.main()

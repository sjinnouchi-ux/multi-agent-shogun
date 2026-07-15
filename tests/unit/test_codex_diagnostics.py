from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
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


class ScriptedRunner:
    def __init__(self, results):
        self.results = dict(results)
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        if argv not in self.results:
            raise AssertionError(f"unexpected command: {argv!r}")
        return self.results[argv]


class CommandRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def test_stream_budget_enforces_bytes_and_records_without_partial_result(self) -> None:
        budget = self.module._StreamBudget(max_bytes=8, max_records=2)
        self.assertFalse(budget.feed(b"one\n"))
        self.assertFalse(budget.feed(b"two"))
        self.assertTrue(budget.feed(b"\nX"))
        self.assertTrue(budget.limited)
        self.assertLessEqual(len(budget.data), 9)

        bytes_budget = self.module._StreamBudget(max_bytes=4, max_records=128)
        self.assertTrue(bytes_budget.feed(b"12345"))
        self.assertTrue(bytes_budget.limited)

        nul_budget = self.module._StreamBudget(max_bytes=1_024, max_records=2)
        self.assertTrue(nul_budget.feed(b"one\0two\0three\0"))
        self.assertTrue(nul_budget.limited)

    def test_drain_discards_partial_output_after_nul_record_limit(self) -> None:
        stdout_read, stdout_write = os.pipe()
        stderr_read, stderr_write = os.pipe()
        os.write(stdout_write, b"\0".join([b"record"] * 129) + b"\0")
        os.close(stdout_write)
        os.close(stderr_write)
        stdout = os.fdopen(stdout_read, "rb", buffering=0)
        stderr = os.fdopen(stderr_read, "rb", buffering=0)
        process = mock.Mock(pid=42, stdout=stdout, stderr=stderr)
        try:
            with mock.patch.object(self.module, "_terminate_and_reap") as terminate:
                result = self.module.drain_process(
                    process,
                    command_deadline=2.0,
                    overall_deadline=10.0,
                    monotonic=lambda: 0.0,
                )
        finally:
            stdout.close()
            stderr.close()
        self.assertEqual(
            result,
            self.module.CommandResult("output_limited", None, b""),
        )
        terminate.assert_called_once()

    def test_terminate_does_not_wait_after_overall_deadline_is_exhausted(self) -> None:
        process = mock.Mock(pid=42)
        with mock.patch.object(self.module.os, "killpg"):
            self.module._terminate_and_reap(
                process,
                deadline=10.0,
                monotonic=lambda: 10.0,
            )
        process.wait.assert_not_called()
        process.poll.assert_called_once_with()

    def test_runner_rejects_non_allowlisted_executable_without_spawning(self) -> None:
        factory = mock.Mock()
        runner = self.module.CommandRunner(popen_factory=factory)
        result = runner(("/bin/sh", "-c", "id"))
        self.assertEqual(result, self.module.CommandResult("failed", None, b""))
        factory.assert_not_called()

    def test_runner_uses_fixed_process_boundary_and_discards_stderr(self) -> None:
        process = mock.Mock()
        drain = mock.Mock(
            return_value=self.module.CommandResult("ok", 0, b"main\n")
        )
        factory = mock.Mock(return_value=process)
        runner = self.module.CommandRunner(
            popen_factory=factory,
            drain=drain,
            monotonic=lambda: 100.0,
        )
        result = runner(("/usr/bin/git", "branch", "--show-current"))
        self.assertEqual(result.stdout, b"main\n")
        _, kwargs = factory.call_args
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["cwd"], ".")
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], subprocess.PIPE)
        self.assertIs(kwargs["stderr"], subprocess.PIPE)
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(
            kwargs["env"],
            {
                "PATH": "/usr/bin:/bin",
                "LANG": "C",
                "LC_ALL": "C",
                "HOME": "/nonexistent",
                "XDG_CONFIG_HOME": "/nonexistent",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_PAGER": "cat",
            },
        )
        drain.assert_called_once()

    def test_runner_honors_shared_ten_second_deadline_before_spawn(self) -> None:
        ticks = iter((0.0, 10.01))
        factory = mock.Mock()
        runner = self.module.CommandRunner(
            popen_factory=factory,
            monotonic=lambda: next(ticks),
        )
        result = runner(("/usr/bin/git", "status"))
        self.assertEqual(result.status, "timeout")
        factory.assert_not_called()

    def test_real_runner_accepts_only_bounded_git_output(self) -> None:
        runner = self.module.CommandRunner()
        result = runner(("/usr/bin/git", "--version"))
        self.assertEqual(result.status, "ok")
        self.assertLessEqual(len(result.stdout), 65_536)
        self.assertNotIn(b"traceback", result.stdout.lower())

        failure = runner(("/usr/bin/git", "--definitely-invalid-diagnostics-option"))
        self.assertEqual(failure.status, "nonzero")
        self.assertFalse(hasattr(failure, "stderr"))
        self.assertNotIn(b"usage:", failure.stdout.lower())

    def test_real_runner_closes_stdout_and_stderr_pipe_readers(self) -> None:
        processes = []

        def retain_process(*args, **kwargs):
            process = subprocess.Popen(*args, **kwargs)
            processes.append(process)
            return process

        runner = self.module.CommandRunner(popen_factory=retain_process)
        result = runner(("/usr/bin/git", "--version"))
        self.assertEqual(result.status, "ok")
        self.assertEqual(len(processes), 1)
        stdout = processes[0].stdout
        stderr = processes[0].stderr
        if stdout is None or stderr is None:
            self.fail("runner did not create both pipe readers")
        self.addCleanup(stdout.close)
        self.addCleanup(stderr.close)
        self.assertEqual((stdout.closed, stderr.closed), (True, True))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import datetime as dt
import errno
import hashlib
import importlib.util
import json
import os
import re
import socket
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
WORK_LOG_BEGIN = b"<!-- BEGIN CODEX_DIAGNOSTICS_DEPLOYMENTS_V1 -->"
WORK_LOG_END = b"<!-- END CODEX_DIAGNOSTICS_DEPLOYMENTS_V1 -->"
WORK_LOG_RECORD_KEYS = (
    "status", "source_repo", "source_commit", "source_path", "source_sha256",
    "deployed_at", "snapshot_path", "snapshot_mode", "contract_schema_version",
)


def load_module():
    spec = importlib.util.spec_from_file_location("codex_diagnostics", SOURCE)
    if spec is None or spec.loader is None:
        raise AssertionError("diagnostics module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def validate_work_log_registry(raw: bytes) -> list[dict[str, object]]:
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise AssertionError("duplicate registry key")
            value[key] = item
        return value

    def reject_constant(_value):
        raise AssertionError("non-finite registry number")

    if not isinstance(raw, bytes) or not raw or len(raw) > 1_048_576:
        raise AssertionError("registry byte boundary")
    if raw.count(WORK_LOG_BEGIN) != 1 or raw.count(WORK_LOG_END) != 1:
        raise AssertionError("registry marker cardinality")
    begin = raw.index(WORK_LOG_BEGIN) + len(WORK_LOG_BEGIN)
    end = raw.index(WORK_LOG_END)
    if end <= begin:
        raise AssertionError("registry marker order")
    payload = raw[begin:end].strip()
    if not payload or b"\n" in payload or b"\r" in payload:
        raise AssertionError("registry must be one line")
    try:
        value = json.loads(
            payload.decode("ascii", errors="strict"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise AssertionError("invalid registry JSON") from exc
    if not isinstance(value, dict) or tuple(value) != (
        "schema_version", "deployments"
    ):
        raise AssertionError("registry top-level schema")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise AssertionError("registry schema version")
    records = value["deployments"]
    if not isinstance(records, list):
        raise AssertionError("registry deployments type")
    validated: list[dict[str, object]] = []
    for record in records:
        if not isinstance(record, dict) or tuple(record) != WORK_LOG_RECORD_KEYS:
            raise AssertionError("registry record keys")
        if record["status"] not in ("active", "superseded"):
            raise AssertionError("registry status")
        if record["source_repo"] != (
            "https://github.com/sjinnouchi-ux/multi-agent-shogun"
        ):
            raise AssertionError("registry source repo")
        if not isinstance(record["source_commit"], str) or re.fullmatch(
            r"[0-9a-f]{40}", record["source_commit"]
        ) is None:
            raise AssertionError("registry source commit")
        if record["source_path"] != "scripts/codex_diagnostics.py":
            raise AssertionError("registry source path")
        if not isinstance(record["source_sha256"], str) or re.fullmatch(
            r"[0-9a-f]{64}", record["source_sha256"]
        ) is None:
            raise AssertionError("registry source SHA-256")
        timestamp = record["deployed_at"]
        if not isinstance(timestamp, str) or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", timestamp
        ) is None:
            raise AssertionError("registry deployment timestamp")
        try:
            dt.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as exc:
            raise AssertionError("registry deployment timestamp") from exc
        if record["snapshot_path"] != (
            "/home/jinnouchi/.local/libexec/shogun-codex-diagnostics"
        ):
            raise AssertionError("registry snapshot path")
        if record["snapshot_mode"] != "0555":
            raise AssertionError("registry snapshot mode")
        if type(record["contract_schema_version"]) is not int or (
            record["contract_schema_version"] != 1
        ):
            raise AssertionError("registry contract schema")
        validated.append(record)
    if sum(record["status"] == "active" for record in validated) > 1:
        raise AssertionError("multiple active deployment records")
    return validated


def work_log_record(status: str = "active") -> dict[str, object]:
    return {
        "status": status,
        "source_repo": "https://github.com/sjinnouchi-ux/multi-agent-shogun",
        "source_commit": "1" * 40,
        "source_path": "scripts/codex_diagnostics.py",
        "source_sha256": "a" * 64,
        "deployed_at": "2026-07-14T00:00:00Z",
        "snapshot_path": "/home/jinnouchi/.local/libexec/shogun-codex-diagnostics",
        "snapshot_mode": "0555",
        "contract_schema_version": 1,
    }


def work_log_registry(records: list[dict[str, object]], schema=1) -> bytes:
    payload = json.dumps(
        {"schema_version": schema, "deployments": records},
        separators=(",", ":"),
    ).encode("ascii")
    return WORK_LOG_BEGIN + b"\n" + payload + b"\n" + WORK_LOG_END


def bounded_issue_fixture(module, *, severity: str, count: int):
    if severity == "errors":
        codes = tuple(
            code for code in module.CLI_ERROR_CODES
            if code != "result_truncated"
        )
    elif severity == "warnings":
        codes = module.CLI_WARNING_CODES
    else:
        raise AssertionError("unsupported severity")
    values = sorted(
        (
            (code, component, agent)
            for code in codes
            for component in ("diagnostic", "source")
            for agent in (None, *module.AGENT_IDS)
        ),
        key=lambda item: (item[0], item[1], item[2] or ""),
    )[:count]
    return [
        {"code": code, "component": component, "agent": agent}
        for code, component, agent in values
    ]


def truncated_error_fixture(module):
    values = bounded_issue_fixture(module, severity="errors", count=63)
    values.append({
        "code": "result_truncated",
        "component": "diagnostic",
        "agent": None,
    })
    return sorted(
        values,
        key=lambda item: (item["code"], item["component"], item["agent"] or ""),
    )


def clear_log_events(module, document, agent_index):
    events = document["agents"][agent_index]["log_events"]
    events["modified_at"] = None
    for key in module.LOG_EVENT_KEYS[2:]:
        events[key] = None


def log_issue(code, agent):
    return {"code": code, "component": "log", "agent": agent}


def truncated_errors_with_log_issues(module, *issues):
    base = [
        issue for issue in truncated_error_fixture(module)
        if issue["code"] != "result_truncated"
    ]
    values = base[: 63 - len(issues)] + list(issues) + [{
        "code": "result_truncated",
        "component": "diagnostic",
        "agent": None,
    }]
    return sorted(
        values,
        key=lambda item: (item["code"], item["component"], item["agent"] or ""),
    )


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
        for code in self.module.CLI_ERROR_CODES:
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

        warning_many = []
        for code in self.module.CLI_WARNING_CODES:
            for component in self.module.COMPONENTS:
                for agent in (None, *self.module.AGENT_IDS):
                    warning_many.append(self.module.Issue(code, component, agent))
                    if len(warning_many) >= 72:
                        break
                if len(warning_many) >= 72:
                    break
            if len(warning_many) >= 72:
                break
        warning_errors, bounded_warnings = self.module.normalize_issues(
            (), warning_many
        )
        self.assertEqual(len(bounded_warnings), 64)
        self.assertIn("result_truncated", {item["code"] for item in warning_errors})

    def test_issue_normalization_rejects_wrong_severity_and_consumer_codes(self) -> None:
        m = self.module
        invalid = (
            ((m.Issue("unknown_cli_observed", "tmux", "shogun"),), ()),
            ((), (m.Issue("watcher_missing", "process", "shogun"),)),
            ((m.Issue("diagnostic_process_failed", "diagnostic", None),), ()),
            ((), (m.Issue("diagnostic_provenance_untrusted", "diagnostic", None),)),
        )
        for errors, warnings in invalid:
            with self.subTest(errors=errors, warnings=warnings), self.assertRaises(
                m.InternalFailure
            ):
                m.normalize_issues(errors, warnings)

    def test_deployment_work_log_has_one_marker_pair_and_at_most_one_active(self) -> None:
        records = validate_work_log_registry(WORK_LOG.read_bytes())
        self.assertLessEqual(
            sum(item["status"] == "active" for item in records), 1
        )

    def test_work_log_validator_exercises_nonempty_hostile_records(self) -> None:
        self.assertEqual(
            validate_work_log_registry(work_log_registry([work_log_record()])),
            [work_log_record()],
        )
        self.assertEqual(validate_work_log_registry(work_log_registry([])), [])

        reordered = work_log_record()
        reordered = {
            key: reordered[key]
            for key in (
                WORK_LOG_RECORD_KEYS[1],
                WORK_LOG_RECORD_KEYS[0],
                *WORK_LOG_RECORD_KEYS[2:],
            )
        }
        impossible_date = work_log_record()
        impossible_date["deployed_at"] = "2026-02-30T12:00:00Z"
        contract_bool = work_log_record()
        contract_bool["contract_schema_version"] = True
        wrong_mode = work_log_record()
        wrong_mode["snapshot_mode"] = "0755"
        missing_key = work_log_record()
        missing_key.pop("snapshot_mode")
        cases = {
            "schema_bool": work_log_registry([work_log_record()], schema=True),
            "record_key_order": work_log_registry([reordered]),
            "record_missing_key": work_log_registry([missing_key]),
            "contract_schema_bool": work_log_registry([contract_bool]),
            "impossible_utc_second": work_log_registry([impossible_date]),
            "fixed_snapshot_mode": work_log_registry([wrong_mode]),
            "active_multiple": work_log_registry(
                [work_log_record(), work_log_record()]
            ),
        }
        for name, raw in cases.items():
            with self.subTest(name=name), self.assertRaises(AssertionError):
                validate_work_log_registry(raw)


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

    def test_terminate_uses_bounded_reap_grace_after_overall_deadline(self) -> None:
        process = mock.Mock(pid=42)
        with mock.patch.object(self.module.os, "killpg"):
            self.module._terminate_and_reap(
                process,
                deadline=10.0,
                monotonic=lambda: 10.0,
            )
        process.wait.assert_called_once_with(
            timeout=self.module.REAP_GRACE_SECONDS
        )
        process.poll.assert_not_called()

    def test_terminate_never_uses_unbounded_wait_when_reap_grace_expires(self) -> None:
        process = mock.Mock(pid=42)
        process.wait.side_effect = subprocess.TimeoutExpired("child", 0.1)
        with mock.patch.object(self.module.os, "killpg"):
            self.module._terminate_and_reap(
                process,
                deadline=10.0,
                monotonic=lambda: 10.0,
            )
        process.wait.assert_called_once_with(
            timeout=self.module.REAP_GRACE_SECONDS
        )
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


class SafePathAndLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def test_size_class_boundaries_and_timestamp_are_exact(self) -> None:
        m = self.module
        self.assertEqual(m.size_class(0), "empty")
        self.assertEqual(m.size_class(1), "small")
        self.assertEqual(m.size_class(65_536), "small")
        self.assertEqual(m.size_class(65_537), "medium")
        self.assertEqual(m.size_class(1_048_576), "medium")
        self.assertEqual(m.size_class(1_048_577), "large")
        self.assertRegex(m.rfc3339_seconds(0), r"^1970-01-01T00:00:00Z$")

    def test_dir_fd_rejects_leaf_and_parent_symlinks_and_nonregular_files(self) -> None:
        m = self.module
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "safe").mkdir()
            (root / "safe" / "file").write_text("secret", encoding="utf-8")
            (root / "leaf-link").symlink_to(root / "safe" / "file")
            (root / "parent-link").symlink_to(root / "safe", target_is_directory=True)
            os.mkfifo(root / "fifo")
            sock = socket.socket(socket.AF_UNIX)
            sock.bind(str(root / "socket"))
            root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                fd, _ = m.open_regular_beneath(root_fd, ("safe", "file"), readable=False)
                os.close(fd)
                for parts in (("leaf-link",), ("parent-link", "file"), ("fifo",), ("socket",), ("..", "file")):
                    with self.subTest(parts=parts), self.assertRaises(m.SourceRejected):
                        m.open_regular_beneath(root_fd, parts, readable=False)
            finally:
                os.close(root_fd)
                sock.close()

    def test_metadata_collection_never_calls_read_and_preserves_applicability(self) -> None:
        m = self.module
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "queue" / "inbox").mkdir(parents=True)
            (root / "queue" / "inbox" / "shogun.yaml").write_text(
                "oauth: must-not-be-read", encoding="utf-8"
            )
            root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                spec = m.SourceSpec("inbox", ("queue", "inbox", "shogun.yaml"), "required")
                with mock.patch.object(m.os, "read", side_effect=AssertionError("content read")):
                    value, errors, warnings = m.collect_source_metadata(
                        root_fd, spec, agent="shogun"
                    )
                self.assertEqual(value["state"], "present")
                self.assertEqual(value["applicability"], "required")
                self.assertEqual(errors, ())
                self.assertEqual(warnings, ())
                self.assertNotIn("oauth", json.dumps(value))
            finally:
                os.close(root_fd)

    def test_missing_required_optional_and_not_applicable_are_distinct(self) -> None:
        m = self.module
        with tempfile.TemporaryDirectory() as raw:
            root_fd = os.open(raw, os.O_RDONLY | os.O_DIRECTORY)
            try:
                required = m.SourceSpec("inbox", ("queue", "inbox", "ashigaru1.yaml"), "required")
                optional = m.SourceSpec("report", ("queue", "reports", "ashigaru1_report.yaml"), "optional")
                na = m.SourceSpec("task", (), "not_applicable")
                req_value, req_errors, _ = m.collect_source_metadata(root_fd, required, agent="ashigaru1")
                opt_value, opt_errors, opt_warnings = m.collect_source_metadata(root_fd, optional, agent="ashigaru1")
                na_value, na_errors, na_warnings = m.collect_source_metadata(root_fd, na, agent="shogun")
                self.assertEqual(req_value["state"], "missing")
                self.assertEqual(req_errors[0].code, "required_source_missing")
                self.assertEqual(opt_value["state"], "missing")
                self.assertEqual((opt_errors, opt_warnings), ((), ()))
                self.assertEqual(na_value["state"], "not_applicable")
                self.assertEqual((na_errors, na_warnings), ((), ()))
            finally:
                os.close(root_fd)

    def test_missing_observed_log_is_required_error_but_optional_missing_is_silent(
        self,
    ) -> None:
        m = self.module
        with tempfile.TemporaryDirectory() as raw:
            root_fd = os.open(raw, os.O_RDONLY | os.O_DIRECTORY)
            try:
                collection = m.collect_log_aggregates(
                    root_fd, frozenset({"shogun"})
                )
            finally:
                os.close(root_fd)

        self.assertEqual(
            collection.errors,
            (m.Issue("required_source_missing", "log", "shogun"),),
        )
        self.assertEqual(collection.warnings, ())
        for agent, events in collection.events.items():
            with self.subTest(agent=agent):
                self.assertIsNone(events["modified_at"])
                self.assertTrue(
                    all(events[key] is None for key in m.LOG_EVENT_KEYS[2:])
                )

    def test_log_reader_uses_only_last_1048576_bytes_and_fixed_markers(self) -> None:
        m = self.module
        prefix = b"send-keys nudge failed\n" + b"x" * 64
        tail = (
            b"Wake-up sent to safe-agent\n"
            b"send-keys nudge failed token-value\n"
            b"nudge text still visible in pane\n"
            b"send-keys failed after 3 tries\n"
            b"WARNING: new unknown condition customer-name\n"
            b"normal customer-name line\n"
        )
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "watcher.log"
            padding = b"p" * (1_048_576 - len(tail))
            path.write_bytes(prefix + padding + tail)
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            try:
                before = os.fstat(fd)
                bounded = m.read_bounded_tail(fd, before)
            finally:
                os.close(fd)
        self.assertEqual(len(bounded), 1_048_576)
        events = m.aggregate_log_tail(bounded, "2026-07-14T00:00:00Z")
        self.assertEqual(events["send_keys_failed_attempt"], 1)
        self.assertEqual(events["nudge_still_visible"], 1)
        self.assertEqual(events["wakeup_retry_exhausted"], 1)
        self.assertEqual(events["wakeup_success_logged"], 1)
        self.assertEqual(events["unclassified_error_candidate"], 1)
        rendered = json.dumps(events)
        self.assertNotIn("token-value", rendered)
        self.assertNotIn("customer-name", rendered)


class InboxRootTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        self.repo_temp = tempfile.TemporaryDirectory()
        self.target_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.repo_temp.cleanup)
        self.addCleanup(self.target_temp.cleanup)
        self.repo = Path(self.repo_temp.name)
        self.anchor = Path(self.target_temp.name)
        os.chmod(self.anchor, 0o700)
        (self.repo / "queue").mkdir(mode=0o700)
        (self.anchor / "fixed" / "inbox").mkdir(parents=True, mode=0o700)
        os.chmod(self.anchor / "fixed", 0o700)
        os.chmod(self.anchor / "fixed" / "inbox", 0o700)
        self.repo_fd = os.open(self.repo, os.O_RDONLY | os.O_DIRECTORY)
        self.anchor_fd = os.open(self.anchor, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.anchor_fd)
        self.addCleanup(os.close, self.repo_fd)

    def open_binding(self, *, target_parts=("fixed", "inbox")):
        return self.module.open_inbox_root(
            self.repo_fd,
            traversal_root_fd=self.anchor_fd,
            target_parts=target_parts,
        )

    def test_exact_canonical_link_opens_isolated_fixed_root(self) -> None:
        m = self.module
        (self.repo / "queue" / "inbox").symlink_to(m.INBOX_LINK_TARGET)
        binding = self.open_binding()
        try:
            opened = os.fstat(binding.inbox_fd)
            expected = os.stat(self.anchor / "fixed" / "inbox")
            self.assertEqual(
                (opened.st_dev, opened.st_ino),
                (expected.st_dev, expected.st_ino),
            )
        finally:
            m.close_inbox_root(binding)

    def test_regular_repository_inbox_remains_supported(self) -> None:
        m = self.module
        (self.repo / "queue" / "inbox").mkdir(mode=0o700)
        binding = self.open_binding()
        try:
            opened = os.fstat(binding.inbox_fd)
            expected = os.stat(self.repo / "queue" / "inbox")
            self.assertEqual(
                (opened.st_dev, opened.st_ino),
                (expected.st_dev, expected.st_ino),
            )
        finally:
            m.close_inbox_root(binding)

    def test_wrong_relative_or_normalized_link_target_is_rejected(self) -> None:
        m = self.module
        for target in (
            "/tmp/not-allowed",
            "fixed/inbox",
            m.INBOX_LINK_TARGET + "/",
        ):
            link = self.repo / "queue" / "inbox"
            if link.is_symlink():
                link.unlink()
            link.symlink_to(target)
            with self.subTest(target=target), self.assertRaises(m.SourceRejected):
                self.open_binding()

    def test_missing_fixed_target_is_missing(self) -> None:
        m = self.module
        (self.repo / "queue" / "inbox").symlink_to(m.INBOX_LINK_TARGET)
        with self.assertRaises(m.SourceMissing):
            self.open_binding(target_parts=("missing", "inbox"))

    def test_symlinked_fixed_target_component_is_rejected(self) -> None:
        m = self.module
        (self.repo / "queue" / "inbox").symlink_to(m.INBOX_LINK_TARGET)
        (self.anchor / "real" / "inbox").mkdir(parents=True, mode=0o700)
        os.chmod(self.anchor / "real", 0o700)
        (self.anchor / "fixed-link").symlink_to(
            self.anchor / "real", target_is_directory=True
        )
        with self.assertRaises(m.SourceRejected):
            self.open_binding(target_parts=("fixed-link", "inbox"))

    def test_group_writable_fixed_target_component_is_rejected(self) -> None:
        m = self.module
        (self.repo / "queue" / "inbox").symlink_to(m.INBOX_LINK_TARGET)
        os.chmod(self.anchor / "fixed", 0o770)
        with self.assertRaises(m.SourceRejected):
            self.open_binding()

    def test_non_directory_fixed_target_component_is_rejected(self) -> None:
        m = self.module
        (self.repo / "queue" / "inbox").symlink_to(m.INBOX_LINK_TARGET)
        (self.anchor / "blocked").write_text("sanitized", encoding="utf-8")
        with self.assertRaises(m.SourceRejected):
            self.open_binding(target_parts=("blocked", "inbox"))

    def test_missing_nofollow_support_is_rejected(self) -> None:
        m = self.module
        (self.repo / "queue" / "inbox").symlink_to(m.INBOX_LINK_TARGET)
        with mock.patch.object(m.os, "O_NOFOLLOW", None):
            with self.assertRaises(m.SourceRejected):
                self.open_binding()


class TmuxAndProcessCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def test_fixed_argv_projects_tmux_fields_and_supervisor_pattern_is_exact(self) -> None:
        m = self.module

        def projection(variable, values):
            return "".join(
                f"#{{?#{{==:#{{{variable}}},{value}}},{value},}}"
                for value in values
            )

        self.assertEqual(
            m.TMUX_SESSIONS_ARGV,
            ("/usr/bin/tmux", "list-sessions", "-F", "#{session_name}"),
        )
        self.assertEqual(
            m.TMUX_PANES_ARGV,
            (
                "/usr/bin/tmux",
                "list-panes",
                "-a",
                "-F",
                "|".join((
                    projection("session_name", m.SESSION_NAMES),
                    "#{pane_dead}",
                    projection("@agent_id", m.AGENT_IDS),
                    projection("@agent_cli", m.CLI_NAMES),
                )),
            ),
        )
        self.assertEqual(
            m.PGREP_SUPERVISOR_ARGV,
            (
                "/usr/bin/pgrep",
                "-f",
                "--",
                r"(^|/)scripts/watcher_supervisor\.sh([[:space:]]|$)",
            ),
        )

    def test_one_ashigaru_formation_keeps_other_agents_not_observed(self) -> None:
        m = self.module
        runner = ScriptedRunner({
            m.TMUX_SESSIONS_ARGV: m.CommandResult("ok", 0, b"shogun\nmultiagent\n"),
            m.TMUX_PANES_ARGV: m.CommandResult(
                "ok", 0,
                b"shogun|0|shogun|claude\n"
                b"multiagent|0|karo|codex\n"
                b"multiagent|0|ashigaru1|claude\n",
            ),
        })
        collection = m.collect_tmux(runner)
        self.assertEqual(collection.observed_agents, frozenset(("shogun", "karo", "ashigaru1")))
        self.assertEqual(collection.observations["ashigaru2"].pane_state, "not_observed")
        self.assertNotIn("ashigaru2", {issue.agent for issue in collection.errors})
        self.assertEqual(len(collection.sessions), 2)
        self.assertNotIn("capture-pane", SOURCE.read_text(encoding="utf-8"))

    def test_overflowing_session_discards_partial_panes_and_warnings(self) -> None:
        m = self.module
        pane_output = (
            b"shogun|0|shogun|claude\n"
            + b"shogun|0||claude\n" * 64
        )
        runner = ScriptedRunner({
            m.TMUX_SESSIONS_ARGV: m.CommandResult("ok", 0, b"shogun\n"),
            m.TMUX_PANES_ARGV: m.CommandResult("ok", 0, pane_output),
        })

        collection = m.collect_tmux(runner)

        self.assertEqual(
            collection.sessions[0],
            {
                "name": "shogun",
                "state": "error",
                "pane_count": None,
                "dead_pane_count": None,
                "unknown_agent_count": None,
            },
        )
        self.assertEqual(collection.observed_agents, frozenset())
        self.assertEqual(collection.warnings, ())
        self.assertIn("result_truncated", {issue.code for issue in collection.errors})
        parts = list(sample_collections(m, both_sessions_missing=True))
        parts[1] = collection
        document = m.build_success_document("a" * 64, *parts)
        m.validate_document(document)

    def test_unknown_duplicate_wrong_session_dead_and_hostile_cli_are_sanitized(self) -> None:
        m = self.module
        secret = "oauth-secret-customer"
        runner = ScriptedRunner({
            m.TMUX_SESSIONS_ARGV: m.CommandResult("ok", 0, b"shogun\nmultiagent\n"),
            m.TMUX_PANES_ARGV: m.CommandResult(
                "ok", 0,
                b"shogun|0|unknown-" + secret.encode() + b"|claude\n"
                b"multiagent|0|shogun|bad-cli\n"
                b"multiagent|1|ashigaru1|claude\n"
                b"multiagent|0|ashigaru1|claude\n",
            ),
        })
        collection = m.collect_tmux(runner)
        codes = {issue.code for issue in collection.errors}
        self.assertIn("agent_session_mismatch", codes)
        self.assertIn("duplicate_agent_pane", codes)
        self.assertEqual(collection.sessions[0]["unknown_agent_count"], 1)
        self.assertEqual(collection.observations["shogun"].cli, "unknown")
        self.assertNotIn(secret, repr(collection))

    def test_all_lines_valid_option_injection_has_no_raw_output_path(self) -> None:
        m = self.module
        injection = "unknown|claude\nmultiagent|0|ashigaru2"
        session_field, dead_field, agent_field, cli_field = m.TMUX_PANES_ARGV[-1].split(
            "|"
        )
        self.assertEqual(dead_field, "#{pane_dead}")
        self.assertNotIn("#{q:", m.TMUX_PANES_ARGV[-1])
        self.assertNotIn(injection, m.TMUX_PANES_ARGV[-1])
        for variable, values, field in (
            ("session_name", m.SESSION_NAMES, session_field),
            ("@agent_id", m.AGENT_IDS, agent_field),
            ("@agent_cli", m.CLI_NAMES, cli_field),
        ):
            self.assertEqual(
                field,
                "".join(
                    f"#{{?#{{==:#{{{variable}}},{value}}},{value},}}"
                    for value in values
                ),
            )

        runner = ScriptedRunner({
            m.TMUX_SESSIONS_ARGV: m.CommandResult("ok", 0, b"shogun\n"),
            m.TMUX_PANES_ARGV: m.CommandResult(
                "ok",
                0,
                b"shogun|0||claude\n",
            ),
        })
        collection = m.collect_tmux(runner)
        self.assertEqual(collection.sessions[0]["unknown_agent_count"], 1)
        self.assertEqual(collection.observed_agents, frozenset())
        self.assertEqual(collection.observations["ashigaru2"].pane_state, "not_observed")
        self.assertNotIn("ashigaru2", repr(collection.errors))

    def test_raw_newline_or_separator_injection_discards_all_pane_rows(self) -> None:
        m = self.module
        secret = b"oauth-secret-customer"
        pane_outputs = (
            (
                b"shogun|0|unknown-" + secret + b"\n"
                b"multiagent|0|ashigaru2|claude\n"
            ),
            (
                b"shogun|0|unknown-" + secret
                + b"|multiagent|0|ashigaru2|claude\n"
            ),
        )
        for pane_output in pane_outputs:
            with self.subTest(pane_output=pane_output):
                runner = ScriptedRunner({
                    m.TMUX_SESSIONS_ARGV: m.CommandResult(
                        "ok", 0, b"shogun\nmultiagent\n"
                    ),
                    m.TMUX_PANES_ARGV: m.CommandResult("ok", 0, pane_output),
                })
                collection = m.collect_tmux(runner)
                self.assertEqual(collection.observed_agents, frozenset())
                self.assertEqual(
                    [item["state"] for item in collection.sessions],
                    ["error", "error"],
                )
                self.assertIn("command_failed", {issue.code for issue in collection.errors})
                self.assertNotIn(secret.decode(), repr(collection))

    def test_malformed_pane_batch_discards_provisional_unknown_warnings(self) -> None:
        m = self.module
        runner = ScriptedRunner({
            m.TMUX_SESSIONS_ARGV: m.CommandResult(
                "ok", 0, b"shogun\nmultiagent\n"
            ),
            m.TMUX_PANES_ARGV: m.CommandResult(
                "ok",
                0,
                b"shogun|0||claude\n"
                b"multiagent|not-a-dead-flag|ashigaru1|codex\n",
            ),
        })
        collection = m.collect_tmux(runner)
        self.assertEqual(
            [item["state"] for item in collection.sessions],
            ["error", "error"],
        )
        self.assertEqual(collection.warnings, ())

    def test_missing_sessions_have_fixed_shape_without_polling_absent_agents(self) -> None:
        m = self.module
        runner = ScriptedRunner({
            m.TMUX_SESSIONS_ARGV: m.CommandResult("nonzero", 1, b""),
            m.TMUX_PANES_ARGV: m.CommandResult("nonzero", 1, b""),
        })
        collection = m.collect_tmux(runner)
        self.assertEqual([item["state"] for item in collection.sessions], ["missing", "missing"])
        self.assertEqual(collection.observed_agents, frozenset())
        self.assertEqual({item.pane_state for item in collection.observations.values()}, {"not_observed"})

    def test_present_sessions_fail_closed_when_pane_result_is_missing_or_empty(self) -> None:
        m = self.module
        pane_results = (
            m.CommandResult("nonzero", 1, b""),
            m.CommandResult("ok", 0, b""),
        )
        for pane_result in pane_results:
            with self.subTest(pane_result=pane_result):
                runner = ScriptedRunner({
                    m.TMUX_SESSIONS_ARGV: m.CommandResult(
                        "ok", 0, b"shogun\nmultiagent\n"
                    ),
                    m.TMUX_PANES_ARGV: pane_result,
                })
                collection = m.collect_tmux(runner)
                self.assertEqual(
                    [item["state"] for item in collection.sessions],
                    ["error", "error"],
                )
                self.assertEqual(collection.observed_agents, frozenset())
                self.assertIn("command_failed", {issue.code for issue in collection.errors})

    def test_unique_dead_pane_has_fixed_state_and_error(self) -> None:
        m = self.module
        runner = ScriptedRunner({
            m.TMUX_SESSIONS_ARGV: m.CommandResult(
                "ok", 0, b"shogun\nmultiagent\n"
            ),
            m.TMUX_PANES_ARGV: m.CommandResult(
                "ok",
                0,
                b"shogun|0|shogun|claude\n"
                b"multiagent|1|ashigaru1|codex\n",
            ),
        })
        collection = m.collect_tmux(runner)
        self.assertEqual(collection.observations["ashigaru1"].pane_state, "dead")
        self.assertIn(
            ("pane_dead", "ashigaru1"),
            {(issue.code, issue.agent) for issue in collection.errors},
        )

    def test_process_queries_only_observed_agents_and_never_returns_pids(self) -> None:
        m = self.module
        results = {
            m.PGREP_SUPERVISOR_ARGV: m.CommandResult("ok", 0, b"101\n"),
            m.PGREP_AGENT_ARGV["shogun"]: m.CommandResult("ok", 0, b"201\n"),
            m.PGREP_AGENT_ARGV["ashigaru1"]: m.CommandResult("nonzero", 1, b""),
        }
        runner = ScriptedRunner(results)
        collection = m.collect_processes(frozenset(("shogun", "ashigaru1")), runner)
        self.assertEqual(collection.processes["watcher_supervisor_state"], "healthy")
        self.assertEqual(collection.agent_watchers["shogun"], (1, "healthy"))
        self.assertEqual(collection.agent_watchers["ashigaru1"], (0, "missing"))
        self.assertEqual(collection.agent_watchers["ashigaru2"], (None, "not_observed"))
        self.assertNotIn(m.PGREP_AGENT_ARGV["ashigaru2"], runner.calls)
        self.assertNotIn("101", json.dumps(collection.processes))
        self.assertIn("watcher_missing", {issue.code for issue in collection.errors})

    def test_missing_optional_supervisor_is_observed_without_health_error(self) -> None:
        m = self.module
        runner = ScriptedRunner({
            m.PGREP_SUPERVISOR_ARGV: m.CommandResult("nonzero", 1, b""),
            m.PGREP_AGENT_ARGV["shogun"]: m.CommandResult("ok", 0, b"201\n"),
        })
        collection = m.collect_processes(frozenset(("shogun",)), runner)
        self.assertEqual(
            collection.processes,
            {
                "watcher_supervisor_count": 0,
                "watcher_supervisor_state": "missing",
            },
        )
        self.assertNotIn(
            ("watcher_missing", "process", None),
            {(issue.code, issue.component, issue.agent) for issue in collection.errors},
        )

    def test_duplicate_and_timeout_process_results_have_fixed_states_and_issues(self) -> None:
        m = self.module
        runner = ScriptedRunner({
            m.PGREP_SUPERVISOR_ARGV: m.CommandResult("ok", 0, b"101\n102\n"),
            m.PGREP_AGENT_ARGV["shogun"]: m.CommandResult("timeout", None, b""),
            m.PGREP_AGENT_ARGV["ashigaru1"]: m.CommandResult(
                "ok", 0, b"201\n202\n"
            ),
        })
        collection = m.collect_processes(
            frozenset(("shogun", "ashigaru1")), runner
        )
        self.assertEqual(
            collection.processes,
            {
                "watcher_supervisor_count": 2,
                "watcher_supervisor_state": "duplicate",
            },
        )
        self.assertEqual(collection.agent_watchers["shogun"], (None, "unknown"))
        self.assertEqual(collection.agent_watchers["ashigaru1"], (2, "duplicate"))
        self.assertIn(
            ("duplicate_process", None),
            {(issue.code, issue.agent) for issue in collection.errors},
        )
        self.assertIn(
            ("command_timeout", "shogun"),
            {(issue.code, issue.agent) for issue in collection.errors},
        )
        self.assertIn(
            ("duplicate_process", "ashigaru1"),
            {(issue.code, issue.agent) for issue in collection.errors},
        )

    def test_pgrep_invalid_pid_timeout_and_duplicates_map_to_fixed_states(self) -> None:
        m = self.module
        self.assertEqual(m.count_pgrep(m.CommandResult("nonzero", 1, b"")), 0)
        self.assertEqual(m.count_pgrep(m.CommandResult("ok", 0, b"1\n2\n")), 2)
        self.assertIsNone(m.count_pgrep(m.CommandResult("ok", 0, b"1\nsecret\n")))
        self.assertIsNone(m.count_pgrep(m.CommandResult("timeout", None, b"")))
        for argv in m.PGREP_AGENT_ARGV.values():
            self.assertEqual(argv[:3], ("/usr/bin/pgrep", "-f", "--"))


class RepositoryCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def _collect_counts(
        self,
        tracked_stdout: bytes,
        untracked_stdout: bytes,
        *,
        branch_stdout: bytes = b"main\n",
    ):
        m = self.module
        results = {
            m.git_argv("rev-parse", "--show-toplevel"): m.CommandResult(
                "ok", 0, (os.getcwd() + "\n").encode()
            ),
            m.git_argv("remote", "-v"): m.CommandResult(
                "ok",
                0,
                b"origin\thttps://github.com/sjinnouchi-ux/multi-agent-shogun.git (fetch)\n",
            ),
            m.git_argv("symbolic-ref", "--quiet", "--short", "HEAD"): m.CommandResult(
                "ok", 0, branch_stdout
            ),
            m.git_argv("rev-parse", "--verify", "HEAD"): m.CommandResult(
                "ok", 0, b"2" * 40 + b"\n"
            ),
            m.git_argv("status", "--porcelain=v1", "-z", "--untracked-files=no"): m.CommandResult(
                "ok", 0, tracked_stdout
            ),
            m.git_argv("ls-files", "--others", "--exclude-standard", "-z"): m.CommandResult(
                "ok", 0, untracked_stdout
            ),
        }
        return m.collect_repository(ScriptedRunner(results))

    def test_branch_classifier_covers_valid_and_hostile_values(self) -> None:
        cases = {
            b"main\n": "main",
            b"shogun/cmd-1\n": "shogun_namespace",
            b"codex/diagnostics\n": "codex_namespace",
            b"feature/safe-1\n": "other",
            b"": "detached",
            b"bad branch\n": "invalid",
            b"bad..branch\n": "invalid",
            b"/leading\n": "invalid",
            b"trailing/\n": "invalid",
            b"refs.lock\n": "invalid",
            "顧客名\n".encode(): "invalid",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(self.module.classify_branch(raw), expected)

    def test_invalid_successful_branch_output_adds_fixed_repository_error(self) -> None:
        collection = self._collect_counts(
            b"", b"", branch_stdout=b"bad branch with secret\n"
        )
        self.assertEqual(collection.value["branch_class"], "invalid")
        self.assertFalse(collection.available)
        self.assertIn(
            ("command_failed", "repository", None),
            {(issue.code, issue.component, issue.agent) for issue in collection.errors},
        )

    def test_canonical_remote_accepts_only_fixed_https_or_ssh_repo(self) -> None:
        for raw in (
            b"origin\thttps://github.com/sjinnouchi-ux/multi-agent-shogun.git (fetch)\n",
            b"upstream\tgit@github.com:sjinnouchi-ux/multi-agent-shogun.git (fetch)\n",
        ):
            self.assertTrue(self.module.is_canonical_remote(raw))
        self.assertFalse(
            self.module.is_canonical_remote(
                b"origin\thttps://github.com/attacker/multi-agent-shogun.git (fetch)\n"
            )
        )

    def test_canonical_remote_requires_an_exact_fetch_line(self) -> None:
        invalid = (
            b"origin\thttps://github.com/sjinnouchi-ux/multi-agent-shogun.git (push)\n",
            b"origin\thttps://github.com/sjinnouchi-ux/multi-agent-shogun.git\n",
            b"origin\thttps://github.com/sjinnouchi-ux/multi-agent-shogun.git (FETCH)\n",
            b"origin\thttps://github.com/sjinnouchi-ux/multi-agent-shogun.git (fetch) trailing\n",
            b"origin\thttps://github.com/sjinnouchi-ux/multi-agent-shogun.git (fetch)\textra\n",
            b"\thttps://github.com/sjinnouchi-ux/multi-agent-shogun.git (fetch)\n",
        )
        for raw in invalid:
            with self.subTest(raw=raw):
                self.assertFalse(self.module.is_canonical_remote(raw))

    def test_porcelain_counts_rename_and_copy_continuations_once(self) -> None:
        tracked = (
            b"R  rename-secret-target\0rename-secret-source\0"
            b" C copy-secret-target\0copy-secret-source\0"
            b" M ordinary-secret-name\0"
        )
        collection = self._collect_counts(tracked, b"")
        self.assertEqual(collection.value["tracked_changes"], 3)
        self.assertTrue(collection.value["dirty"])
        self.assertTrue(collection.available)
        self.assertNotIn("secret", repr(collection))

    def test_porcelain_rejects_empty_malformed_and_truncated_records(self) -> None:
        malformed = (
            b"\0",
            b" M valid\0\0",
            b"M missing-separator\0",
            b"ZZ invalid-status\0",
            b" M truncated",
            b"R  rename-target\0",
            b"R  rename-target\0\0",
        )
        for tracked in malformed:
            with self.subTest(tracked=tracked):
                collection = self._collect_counts(tracked, b"")
                self.assertIsNone(collection.value["tracked_changes"])
                self.assertIsNone(collection.value["dirty"])
                self.assertFalse(collection.available)
                self.assertIn(
                    "command_failed", {item.code for item in collection.errors}
                )

    def test_ls_files_counts_only_nonempty_complete_path_records(self) -> None:
        valid = self._collect_counts(b"", b"first-secret\0second-secret\0")
        self.assertEqual(valid.value["untracked_changes"], 2)
        self.assertTrue(valid.value["dirty"])
        self.assertNotIn("secret", repr(valid))

        for untracked in (b"\0", b"first\0\0second\0", b"truncated"):
            with self.subTest(untracked=untracked):
                collection = self._collect_counts(b"", untracked)
                self.assertIsNone(collection.value["untracked_changes"])
                self.assertIsNone(collection.value["dirty"])
                self.assertFalse(collection.available)
                self.assertIn(
                    "command_failed", {item.code for item in collection.errors}
                )

    def test_repository_returns_only_class_count_hash_and_boolean(self) -> None:
        m = self.module
        results = {
            m.git_argv("rev-parse", "--show-toplevel"): m.CommandResult(
                "ok", 0, (os.getcwd() + "\n").encode()
            ),
            m.git_argv("remote", "-v"): m.CommandResult(
                "ok", 0,
                b"origin\thttps://github.com/sjinnouchi-ux/multi-agent-shogun.git (fetch)\n",
            ),
            m.git_argv("symbolic-ref", "--quiet", "--short", "HEAD"): m.CommandResult(
                "ok", 0, b"codex/secret-customer-name\n"
            ),
            m.git_argv("rev-parse", "--verify", "HEAD"): m.CommandResult(
                "ok", 0, b"0" * 40 + b"\n"
            ),
            m.git_argv("status", "--porcelain=v1", "-z", "--untracked-files=no"): m.CommandResult(
                "ok", 0, b" M token-looking-name.txt\0"
            ),
            m.git_argv("ls-files", "--others", "--exclude-standard", "-z"): m.CommandResult(
                "ok", 0, b"oauth-code.json\0"
            ),
        }
        collection = m.collect_repository(ScriptedRunner(results))
        self.assertTrue(collection.boundary_accepted)
        self.assertTrue(collection.available)
        self.assertEqual(
            collection.value,
            {
                "branch_class": "codex_namespace",
                "head": "0" * 40,
                "dirty": True,
                "tracked_changes": 1,
                "untracked_changes": 1,
                "canonical_remote_present": True,
            },
        )
        serialized = json.dumps(collection.value)
        self.assertNotIn("secret-customer-name", serialized)
        self.assertNotIn("oauth-code", serialized)
        self.assertNotIn("github.com", serialized)

    def test_missing_or_unreadable_canonical_boundary_raises_before_runtime(self) -> None:
        m = self.module
        base = {
            m.git_argv("rev-parse", "--show-toplevel"): m.CommandResult(
                "ok", 0, (os.getcwd() + "\n").encode()
            )
        }
        for remote_result, code in (
            (m.CommandResult("ok", 0, b"origin\thttps://example.invalid/repo (fetch)\n"),
             "canonical_remote_missing"),
            (m.CommandResult("timeout", None, b""), "boundary_rejected"),
        ):
            with self.subTest(code=code):
                results = dict(base)
                results[m.git_argv("remote", "-v")] = remote_result
                with self.assertRaises(m.BoundaryRejected) as caught:
                    m.collect_repository(ScriptedRunner(results))
                self.assertEqual(caught.exception.code, code)

    def test_post_boundary_command_limit_returns_null_not_partial_count(self) -> None:
        m = self.module
        results = {
            m.git_argv("rev-parse", "--show-toplevel"): m.CommandResult(
                "ok", 0, (os.getcwd() + "\n").encode()
            ),
            m.git_argv("remote", "-v"): m.CommandResult(
                "ok", 0,
                b"origin\tgit@github.com:sjinnouchi-ux/multi-agent-shogun.git (fetch)\n",
            ),
            m.git_argv("symbolic-ref", "--quiet", "--short", "HEAD"): m.CommandResult(
                "ok", 0, b"main\n"
            ),
            m.git_argv("rev-parse", "--verify", "HEAD"): m.CommandResult(
                "ok", 0, b"1" * 40 + b"\n"
            ),
            m.git_argv("status", "--porcelain=v1", "-z", "--untracked-files=no"): m.CommandResult(
                "output_limited", None, b""
            ),
            m.git_argv("ls-files", "--others", "--exclude-standard", "-z"): m.CommandResult(
                "ok", 0, b""
            ),
        }
        collection = m.collect_repository(ScriptedRunner(results))
        self.assertFalse(collection.available)
        self.assertIsNone(collection.value["tracked_changes"])
        self.assertIsNone(collection.value["dirty"])
        self.assertIn("command_output_limited", {item.code for item in collection.errors})


def sample_collections(
    module, *, both_sessions_missing=False, one_session_missing=False
):
    repository = module.RepositoryCollection(
        {
            "branch_class": "main",
            "head": "0" * 40,
            "dirty": False,
            "tracked_changes": 0,
            "untracked_changes": 0,
            "canonical_remote_present": True,
        },
        True,
        True,
        (),
        (),
    )
    if both_sessions_missing:
        states = ("missing", "missing")
    elif one_session_missing:
        states = ("present", "missing")
    else:
        states = ("present", "present")
    observed_ids = set()
    if states[0] == "present":
        observed_ids.add("shogun")
    if states[1] == "present":
        observed_ids.update(("karo", "ashigaru1"))
    sessions = tuple(
        {
            "name": name,
            "state": state,
            "pane_count": (
                0
                if state == "missing"
                else sum(
                    agent in observed_ids
                    and ("shogun" if agent == "shogun" else "multiagent") == name
                    for agent in module.AGENT_IDS
                )
            ),
            "dead_pane_count": 0,
            "unknown_agent_count": 0,
        }
        for name, state in zip(module.SESSION_NAMES, states)
    )
    observations = {
        agent: module.PaneObservation(
            agent in observed_ids,
            "shogun"
            if agent == "shogun" and agent in observed_ids
            else (
                "multiagent" if agent in observed_ids else None
            ),
            "alive"
            if agent in observed_ids
            else "not_observed",
            "claude"
            if agent in observed_ids
            else "unknown",
        )
        for agent in module.AGENT_IDS
    }
    tmux_errors = (
        ()
        if states == ("present", "present")
        else (module.Issue("session_missing", "tmux", None),)
    )
    tmux = module.TmuxCollection(
        sessions,
        observations,
        frozenset(observed_ids),
        tmux_errors,
        (),
    )
    watchers = {
        agent: (
            (1, "healthy")
            if observations[agent].observed
            else (None, "not_observed")
        )
        for agent in module.AGENT_IDS
    }
    processes = module.ProcessCollection(
        {"watcher_supervisor_count": 1, "watcher_supervisor_state": "healthy"},
        watchers,
        (),
        (),
    )
    def present(applicability):
        return {
            "applicability": applicability,
            "state": "present",
            "modified_at": "2026-07-14T00:00:00Z",
            "size_class": "small",
        }
    na = {
        "applicability": "not_applicable",
        "state": "not_applicable",
        "modified_at": None,
        "size_class": None,
    }
    agent_sources = {}
    for agent in module.AGENT_IDS:
        task_report = agent not in ("shogun", "karo")
        observed = observations[agent].observed
        agent_sources[agent] = {
            "inbox": present("required" if observed else "optional"),
            "task": (
                present("required" if observed else "optional")
                if task_report else dict(na)
            ),
            "report": present("optional") if task_report else dict(na),
            "handoff_status": present("optional"),
            "watcher_log": present("required" if observed else "optional"),
        }
    sources = module.SourceCollection(
        {
            "command_queue": present("required"),
            "dashboard": present("optional"),
        },
        agent_sources,
        (),
        (),
    )
    event = {
        "window": "tail_1048576_bytes",
        "modified_at": "2026-07-14T00:00:00Z",
        "send_keys_failed_attempt": 0,
        "nudge_still_visible": 0,
        "wakeup_retry_exhausted": 0,
        "wakeup_success_logged": 0,
        "unclassified_error_candidate": 0,
    }
    logs = module.LogCollection(
        {agent: dict(event) for agent in module.AGENT_IDS}, (), ()
    )
    return repository, tmux, processes, sources, logs


class SummaryAndSerializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def test_success_document_has_exact_shape_order_and_cardinality(self) -> None:
        m = self.module
        document = m.build_success_document("a" * 64, *sample_collections(m))
        m.validate_document(document)
        self.assertTrue(document["ok"])
        self.assertEqual(document["overall"], "healthy")
        self.assertEqual(len(document["sessions"]), 2)
        self.assertEqual(len(document["agents"]), 11)
        self.assertEqual(
            [item["id"] for item in document["agents"]], list(m.AGENT_IDS)
        )
        self.assertEqual(
            tuple(document["global_sources"]), ("command_queue", "dashboard")
        )
        self.assertEqual(tuple(document["agents"][0]["sources"]), m.SOURCE_KEYS)

    def test_overall_distinguishes_degraded_unavailable_and_optional_warning(
        self,
    ) -> None:
        m = self.module
        degraded = m.build_success_document(
            "a" * 64, *sample_collections(m, one_session_missing=True)
        )
        unavailable = m.build_success_document(
            "a" * 64, *sample_collections(m, both_sessions_missing=True)
        )
        healthy_parts = list(sample_collections(m))
        healthy_parts[3] = m.SourceCollection(
            healthy_parts[3].global_sources,
            healthy_parts[3].agent_sources,
            (),
            (m.Issue("source_rejected", "source", "ashigaru2"),),
        )
        healthy_warning = m.build_success_document("a" * 64, *healthy_parts)
        self.assertEqual(degraded["overall"], "degraded")
        self.assertEqual(unavailable["overall"], "unavailable")
        self.assertEqual(healthy_warning["overall"], "healthy")
        for document in (degraded, unavailable, healthy_warning):
            m.validate_document(document)

    def test_optional_missing_supervisor_keeps_success_document_healthy(self) -> None:
        m = self.module
        parts = list(sample_collections(m))
        watchers = parts[2].agent_watchers
        parts[2] = m.ProcessCollection(
            {
                "watcher_supervisor_count": 0,
                "watcher_supervisor_state": "missing",
            },
            watchers,
            (),
            (),
        )
        document = m.build_success_document("a" * 64, *parts)
        self.assertEqual(document["overall"], "healthy")
        m.validate_document(document)

    def test_validator_accepts_log_unavailability_only_with_matching_issue(
        self,
    ) -> None:
        m = self.module
        for code in (
            "required_source_missing",
            "source_rejected",
            "command_failed",
        ):
            with self.subTest(observed_error=code):
                document = m.build_success_document(
                    "a" * 64, *sample_collections(m)
                )
                clear_log_events(m, document, 0)
                document["errors"] = [log_issue(code, "shogun")]
                document["overall"] = "degraded"
                m.validate_document(document)

        document = m.build_success_document(
            "a" * 64, *sample_collections(m)
        )
        clear_log_events(m, document, 3)
        m.validate_document(document)

        for code in ("source_rejected", "command_failed"):
            with self.subTest(unobserved_warning=code):
                document = m.build_success_document(
                    "a" * 64, *sample_collections(m)
                )
                clear_log_events(m, document, 3)
                document["warnings"] = [log_issue(code, "ashigaru2")]
                m.validate_document(document)

    def test_validator_rejects_log_event_issue_contradictions(self) -> None:
        m = self.module
        cases = (
            ("observed_missing_without_issue", 0, False, (), ()),
            (
                "observed_missing_with_warning", 0, False, (),
                (log_issue("source_rejected", "shogun"),),
            ),
            (
                "observed_missing_with_two_errors", 0, False,
                (
                    log_issue("command_failed", "shogun"),
                    log_issue("required_source_missing", "shogun"),
                ),
                (),
            ),
            (
                "observed_missing_with_wrong_error", 0, False,
                (log_issue("command_timeout", "shogun"),), (),
            ),
            (
                "observed_complete_with_error", 0, True,
                (log_issue("command_failed", "shogun"),), (),
            ),
            (
                "unobserved_missing_with_error", 3, False,
                (log_issue("command_failed", "ashigaru2"),), (),
            ),
            (
                "unobserved_missing_with_two_warnings", 3, False, (),
                (
                    log_issue("command_failed", "ashigaru2"),
                    log_issue("source_rejected", "ashigaru2"),
                ),
            ),
            (
                "unobserved_missing_with_wrong_warning", 3, False, (),
                (log_issue("unknown_cli_observed", "ashigaru2"),),
            ),
            (
                "unobserved_complete_with_warning", 3, True, (),
                (log_issue("source_rejected", "ashigaru2"),),
            ),
            (
                "global_log_issue", 0, True,
                (log_issue("command_failed", None),), (),
            ),
        )
        for name, agent_index, log_available, errors, warnings in cases:
            with self.subTest(name=name):
                document = m.build_success_document(
                    "a" * 64, *sample_collections(m)
                )
                if not log_available:
                    clear_log_events(m, document, agent_index)
                document["errors"] = list(errors)
                document["warnings"] = list(warnings)
                if errors:
                    document["overall"] = "degraded"
                with self.assertRaises(m.InternalFailure):
                    m.validate_document(document)

    def test_validator_allows_omitted_observed_log_issue_only_when_errors_truncated(
        self,
    ) -> None:
        m = self.module
        document = m.build_success_document(
            "a" * 64, *sample_collections(m)
        )
        clear_log_events(m, document, 0)
        document["errors"] = truncated_error_fixture(m)
        document["overall"] = "degraded"
        m.validate_document(document)

    def test_validator_rejects_retained_log_contradictions_when_errors_truncated(
        self,
    ) -> None:
        m = self.module

        missing_with_two = m.build_success_document(
            "a" * 64, *sample_collections(m)
        )
        clear_log_events(m, missing_with_two, 0)
        missing_with_two["errors"] = truncated_errors_with_log_issues(
            m,
            log_issue("command_failed", "shogun"),
            log_issue("required_source_missing", "shogun"),
        )
        missing_with_two["overall"] = "degraded"

        complete_with_one = m.build_success_document(
            "a" * 64, *sample_collections(m)
        )
        complete_with_one["errors"] = truncated_errors_with_log_issues(
            m, log_issue("command_failed", "shogun")
        )
        complete_with_one["overall"] = "degraded"

        for name, document in (
            ("missing_with_two", missing_with_two),
            ("complete_with_one", complete_with_one),
        ):
            with self.subTest(name=name), self.assertRaises(m.InternalFailure):
                m.validate_document(document)

    def test_supervisor_duplicate_and_unknown_remain_valid_degraded_states(self) -> None:
        m = self.module
        cases = (
            (
                2,
                "duplicate",
                m.Issue("duplicate_process", "process", None),
            ),
            (
                None,
                "unknown",
                m.Issue("command_timeout", "process", None),
            ),
        )
        for count, state, issue in cases:
            with self.subTest(state=state):
                parts = list(sample_collections(m))
                parts[2] = m.ProcessCollection(
                    {
                        "watcher_supervisor_count": count,
                        "watcher_supervisor_state": state,
                    },
                    parts[2].agent_watchers,
                    (issue,),
                    (),
                )
                document = m.build_success_document("a" * 64, *parts)
                self.assertEqual(document["overall"], "degraded")
                m.validate_document(document)

    def test_validator_rejects_cross_field_semantic_contradictions(self) -> None:
        m = self.module

        def mutate_overall(document):
            document["overall"] = "degraded"

        def mutate_error_without_overall(document):
            document["errors"] = [{
                "code": "command_failed",
                "component": "log",
                "agent": "ashigaru1",
            }]

        def mutate_canonical_remote(document):
            document["repository"]["canonical_remote_present"] = False

        def mutate_missing_session_counts(document):
            document["sessions"][0].update(
                state="missing",
                pane_count=1,
                dead_pane_count=0,
                unknown_agent_count=0,
            )
            document["overall"] = "degraded"
            document["errors"] = [{
                "code": "session_missing",
                "component": "tmux",
                "agent": None,
            }]

        def mutate_source_state(document):
            document["global_sources"]["command_queue"] = {
                "applicability": "required",
                "state": "not_applicable",
                "modified_at": None,
                "size_class": None,
            }
            document["overall"] = "degraded"

        def mutate_unobserved_agent(document):
            document["agents"][3]["session"] = "multiagent"

        def mutate_observed_watcher(document):
            document["agents"][0]["watcher_count"] = 0

        def mutate_supervisor_pair(document):
            document["processes"]["watcher_supervisor_count"] = 0

        def mutate_mismatch_with_expected_session(document):
            document["agents"][0]["pane_state"] = "error"
            document["overall"] = "degraded"
            document["errors"] = [{
                "code": "agent_session_mismatch",
                "component": "tmux",
                "agent": "shogun",
            }]

        def mutate_mismatch_without_session(document):
            mutate_mismatch_with_expected_session(document)
            document["agents"][0]["session"] = None

        def mutate_duplicate_with_nonunknown_cli(document):
            document["agents"][0]["pane_state"] = "error"
            document["agents"][0]["session"] = None
            document["overall"] = "degraded"
            document["errors"] = [{
                "code": "duplicate_agent_pane",
                "component": "tmux",
                "agent": "shogun",
            }]

        for name, mutate in (
            ("overall_recalculation", mutate_overall),
            ("error_requires_degraded", mutate_error_without_overall),
            ("canonical_remote_true", mutate_canonical_remote),
            ("missing_session_zero_counts", mutate_missing_session_counts),
            ("source_applicability_state", mutate_source_state),
            ("unobserved_agent_shape", mutate_unobserved_agent),
            ("observed_watcher_pair", mutate_observed_watcher),
            ("supervisor_count_state_pair", mutate_supervisor_pair),
            ("mismatch_requires_unexpected_session", mutate_mismatch_with_expected_session),
            ("mismatch_requires_nonnull_session", mutate_mismatch_without_session),
            ("duplicate_requires_unknown_cli", mutate_duplicate_with_nonunknown_cli),
        ):
            with self.subTest(name=name):
                document = m.build_success_document(
                    "a" * 64, *sample_collections(m)
                )
                mutate(document)
                with self.assertRaises(m.InternalFailure):
                    m.validate_document(document)

    def test_validator_accepts_omitted_correlation_only_with_truncation_marker(
        self,
    ) -> None:
        m = self.module
        document = m.build_success_document(
            "a" * 64, *sample_collections(m)
        )
        document["agents"][0]["watcher_count"] = 0
        document["agents"][0]["watcher_state"] = "missing"
        document["errors"] = truncated_error_fixture(m)
        document["overall"] = "degraded"
        m.validate_document(document)

        document = m.build_success_document(
            "a" * 64, *sample_collections(m)
        )
        document["sessions"][0]["pane_count"] = 2
        document["sessions"][0]["unknown_agent_count"] = 1
        document["errors"] = [{
            "code": "result_truncated",
            "component": "diagnostic",
            "agent": None,
        }]
        document["warnings"] = bounded_issue_fixture(
            m, severity="warnings", count=64
        )
        document["overall"] = "degraded"
        m.validate_document(document)

    def test_truncation_marker_requires_full_corresponding_issue_array(
        self,
    ) -> None:
        m = self.module

        def missing_watcher(document):
            document["agents"][0]["watcher_count"] = 0
            document["agents"][0]["watcher_state"] = "missing"
            document["errors"] = [{
                "code": "result_truncated",
                "component": "diagnostic",
                "agent": None,
            }]
            document["overall"] = "degraded"

        short_marker = m.build_success_document(
            "a" * 64, *sample_collections(m)
        )
        missing_watcher(short_marker)

        warnings_only = m.build_success_document(
            "a" * 64, *sample_collections(m)
        )
        missing_watcher(warnings_only)
        warnings_only["warnings"] = bounded_issue_fixture(
            m, severity="warnings", count=64
        )

        errors_only = m.build_success_document(
            "a" * 64, *sample_collections(m)
        )
        errors_only["sessions"][0]["pane_count"] = 2
        errors_only["sessions"][0]["unknown_agent_count"] = 1
        errors_only["errors"] = truncated_error_fixture(m)
        errors_only["overall"] = "degraded"

        for name, document in (
            ("short_marker", short_marker),
            ("warnings_do_not_truncate_errors", warnings_only),
            ("errors_do_not_truncate_warnings", errors_only),
        ):
            with self.subTest(name=name), self.assertRaises(m.InternalFailure):
                m.validate_document(document)

    def test_validator_rejects_issue_codes_at_the_wrong_severity(self) -> None:
        m = self.module
        cases = (
            ("errors", "unknown_cli_observed", "tmux", "shogun"),
            ("warnings", "watcher_missing", "process", "shogun"),
            ("errors", "diagnostic_process_failed", "diagnostic", None),
            ("warnings", "diagnostic_provenance_untrusted", "diagnostic", None),
        )
        for array_name, code, component, agent in cases:
            with self.subTest(array=array_name, code=code):
                document = m.build_success_document(
                    "a" * 64, *sample_collections(m)
                )
                document[array_name] = [{
                    "code": code,
                    "component": component,
                    "agent": agent,
                }]
                if array_name == "errors":
                    document["overall"] = "degraded"
                with self.assertRaises(m.InternalFailure):
                    m.validate_document(document)

    def test_validator_rejects_unknown_keys_and_free_text(self) -> None:
        m = self.module
        document = m.build_success_document("a" * 64, *sample_collections(m))
        document["raw_message"] = "secret"
        with self.assertRaises(m.InternalFailure):
            m.validate_document(document)

    def test_validator_requires_integer_schema_version_not_boolean(self) -> None:
        m = self.module
        document = m.build_success_document("a" * 64, *sample_collections(m))
        document["schema_version"] = True
        with self.assertRaises(m.InternalFailure):
            m.validate_document(document)

    def test_validator_rejects_unsorted_or_duplicate_issue_arrays(self) -> None:
        m = self.module
        session_issue = {
            "code": "session_missing",
            "component": "tmux",
            "agent": None,
        }
        watcher_issue = {
            "code": "watcher_missing",
            "component": "process",
            "agent": "ashigaru1",
        }
        invalid_arrays = (
            [watcher_issue, session_issue],
            [session_issue, session_issue],
        )
        for errors in invalid_arrays:
            with self.subTest(errors=errors):
                document = m.build_success_document(
                    "a" * 64, *sample_collections(m)
                )
                document["overall"] = "degraded"
                document["errors"] = errors
                with self.assertRaises(m.InternalFailure):
                    m.validate_document(document)

        document = m.build_success_document("a" * 64, *sample_collections(m))
        document["generated_at"] = None
        with self.assertRaises(m.InternalFailure):
            m.validate_document(document)

    def test_validator_rejects_nonexistent_rfc3339_utc_seconds(self) -> None:
        m = self.module

        def generated_at(document):
            document["generated_at"] = "2026-02-30T12:00:00Z"

        def source_modified_at(document):
            document["global_sources"]["command_queue"]["modified_at"] = (
                "2026-02-30T12:00:00Z"
            )

        def log_modified_at(document):
            document["agents"][0]["log_events"]["modified_at"] = (
                "2026-02-30T12:00:00Z"
            )

        for name, mutate in (
            ("generated_at", generated_at),
            ("source_modified_at", source_modified_at),
            ("log_modified_at", log_modified_at),
        ):
            with self.subTest(name=name):
                document = m.build_success_document(
                    "a" * 64, *sample_collections(m)
                )
                mutate(document)
                with self.assertRaises(m.InternalFailure):
                    m.validate_document(document)

    def test_boundary_failure_occurs_before_runtime_root_open(self) -> None:
        m = self.module
        runner = ScriptedRunner(
            {
                m.git_argv("rev-parse", "--show-toplevel"): m.CommandResult(
                    "ok", 0, (os.getcwd() + "\n").encode()
                ),
                m.git_argv("remote", "-v"): m.CommandResult(
                    "ok", 0, b"origin\thttps://example.invalid/repo (fetch)\n"
                ),
            }
        )
        opened = mock.Mock(side_effect=AssertionError("runtime opened"))
        with self.assertRaises(m.BoundaryRejected):
            m.collect_summary(runner, source_hash="a" * 64, open_root=opened)
        opened.assert_not_called()

    def test_run_cli_hash_failure_and_argument_rejection_do_not_call_collector(
        self,
    ) -> None:
        m = self.module
        collector = mock.Mock()
        with mock.patch.object(
            m, "calculate_source_sha256", side_effect=m.InternalFailure
        ):
            code, document = m.run_cli(("summary",), collector)
        self.assertEqual(code, 3)
        self.assertEqual(document["tool"]["source_sha256"], None)
        collector.assert_not_called()
        code, document = m.run_cli(("summary", "extra"), collector)
        self.assertEqual(code, 2)
        self.assertEqual(document["errors"][0]["code"], "argument_rejected")
        collector.assert_not_called()

    def test_serialization_failure_uses_literal_without_exception_text(self) -> None:
        m = self.module
        document = m.build_success_document("a" * 64, *sample_collections(m))
        with mock.patch.object(
            m.json, "dumps", side_effect=ValueError("token-secret")
        ):
            payload, code = m.safe_render_document(document, 0)
        self.assertEqual((payload, code), (m.FALLBACK_INTERNAL_ERROR, 3))
        self.assertNotIn(b"token-secret", payload)

    def test_main_uses_literal_when_failure_document_construction_fails(self) -> None:
        m = self.module
        with mock.patch.object(m.signal, "signal"), mock.patch.object(
            m, "_timestamp", side_effect=RuntimeError("token-secret")
        ), mock.patch.object(m, "emit_bytes") as emit:
            code = m.main(("unexpected",))
        self.assertEqual(code, 3)
        emit.assert_called_once_with(m.FALLBACK_INTERNAL_ERROR)

    def test_main_uses_signal_barrier_around_first_output(self) -> None:
        m = self.module
        events = []

        def mask(how, signals):
            events.append(("mask", how, frozenset(signals), m._OUTPUT_STARTED))
            return frozenset()

        def emit(payload):
            events.append(("emit", payload, m._OUTPUT_STARTED))

        with mock.patch.object(m.signal, "signal"), mock.patch.object(
            m.signal, "pthread_sigmask", side_effect=mask
        ), mock.patch.object(
            m.signal, "sigpending", return_value=frozenset()
        ), mock.patch.object(m, "emit_bytes", side_effect=emit):
            code = m.main(("unexpected",))

        self.assertEqual(code, 2)
        self.assertEqual(
            [event[0] for event in events],
            ["mask", "mask", "mask", "emit", "mask"],
        )
        self.assertEqual(events[0][1], m.signal.SIG_BLOCK)
        self.assertFalse(events[0][3])
        self.assertEqual(events[1][1], m.signal.SIG_SETMASK)
        self.assertEqual(events[2][1], m.signal.SIG_BLOCK)
        self.assertFalse(events[2][3])
        self.assertTrue(events[3][2])
        self.assertEqual(events[4][1], m.signal.SIG_SETMASK)

    def test_signal_fallback_ignores_cross_signal_reentry(self) -> None:
        m = self.module
        emitted = []
        events = []

        def emit(payload):
            events.append("outer-emit-started")
            emitted.append(payload)
            m._signal_before_output(m.signal.SIGTERM, None)
            events.append("nested-handler-returned")
            events.append("outer-emit-completed")

        def exit_process(code):
            events.append(f"exit-{code}")
            raise SystemExit(code)

        with mock.patch.object(
            m.signal, "pthread_sigmask", return_value=frozenset()
        ), mock.patch.object(m, "emit_bytes", side_effect=emit), mock.patch.object(
            m.os, "_exit", side_effect=exit_process
        ):
            with self.assertRaisesRegex(SystemExit, "3"):
                m._signal_before_output(m.signal.SIGINT, None)
        self.assertEqual(emitted, [m.FALLBACK_INTERNAL_ERROR])
        self.assertEqual(
            events,
            [
                "outer-emit-started",
                "nested-handler-returned",
                "outer-emit-completed",
                "exit-3",
            ],
        )

    def test_main_blocks_handler_installation_with_a_pending_signal(self) -> None:
        m = self.module
        termination_signals = frozenset((m.signal.SIGINT, m.signal.SIGTERM))
        previous_mask = frozenset((m.signal.SIGHUP,))
        blocked = set(previous_mask)
        handlers = {}
        pending = set()
        events = []

        def mask(how, signals):
            requested = frozenset(signals)
            if how == m.signal.SIG_BLOCK:
                previous = frozenset(blocked)
                blocked.update(requested)
                events.append(("block", requested, previous))
                return previous
            self.assertEqual(how, m.signal.SIG_SETMASK)
            self.assertEqual(requested, previous_mask)
            self.assertEqual(frozenset(handlers), termination_signals)
            self.assertIn(m.signal.SIGTERM, pending)
            blocked.clear()
            blocked.update(requested)
            events.append(("restore", requested))
            signum = pending.pop()
            events.append(("deliver", signum))
            handlers[signum](signum, None)
            self.fail("pending termination handler returned past os._exit")

        def install(signum, handler):
            self.assertTrue(termination_signals.issubset(blocked))
            self.assertIs(handler, m._signal_before_output)
            handlers[signum] = handler
            events.append(("install", signum))
            if len(handlers) == 1:
                pending.add(m.signal.SIGTERM)
                events.append(("pending", m.signal.SIGTERM))

        def emit(payload):
            events.append(("emit", payload))

        def exit_process(code):
            events.append(("exit", code))
            raise SystemExit(code)

        with mock.patch.object(
            m.signal, "pthread_sigmask", side_effect=mask
        ), mock.patch.object(m.signal, "signal", side_effect=install), mock.patch.object(
            m, "emit_bytes", side_effect=emit
        ), mock.patch.object(
            m.os, "_exit", side_effect=exit_process
        ):
            with self.assertRaisesRegex(SystemExit, "3"):
                m._install_signal_handlers()

        self.assertEqual(
            events,
            [
                ("block", termination_signals, previous_mask),
                ("install", m.signal.SIGINT),
                ("pending", m.signal.SIGTERM),
                ("install", m.signal.SIGTERM),
                ("restore", previous_mask),
                ("deliver", m.signal.SIGTERM),
                ("block", termination_signals, previous_mask),
                ("emit", m.FALLBACK_INTERNAL_ERROR),
                ("exit", 3),
            ],
        )

    def test_handler_installation_failure_exits_with_fallback_while_blocked(
        self,
    ) -> None:
        m = self.module
        termination_signals = frozenset((m.signal.SIGINT, m.signal.SIGTERM))
        previous_mask = frozenset((m.signal.SIGHUP,))
        blocked = set(previous_mask)
        events = []

        def mask(how, signals):
            self.assertEqual(how, m.signal.SIG_BLOCK)
            requested = frozenset(signals)
            prior = frozenset(blocked)
            blocked.update(requested)
            events.append(("block", requested, prior))
            return prior

        def install(signum, handler):
            self.assertTrue(termination_signals.issubset(blocked))
            self.assertIs(handler, m._signal_before_output)
            events.append(("install", signum))
            if signum == m.signal.SIGTERM:
                raise RuntimeError("second handler install failed")

        def exit_process(code):
            events.append(("exit", code))
            raise SystemExit(code)

        with mock.patch.object(
            m.signal, "pthread_sigmask", side_effect=mask
        ), mock.patch.object(m.signal, "signal", side_effect=install), mock.patch.object(
            m, "emit_bytes", side_effect=lambda payload: events.append(("emit", payload))
        ), mock.patch.object(m.os, "_exit", side_effect=exit_process):
            with self.assertRaisesRegex(SystemExit, "3"):
                m._install_signal_handlers()

        self.assertEqual(
            events,
            [
                ("block", termination_signals, previous_mask),
                ("install", m.signal.SIGINT),
                ("install", m.signal.SIGTERM),
                ("block", termination_signals, termination_signals | previous_mask),
                ("emit", m.FALLBACK_INTERNAL_ERROR),
                ("exit", 3),
            ],
        )

    def test_pending_signal_selects_fallback_at_first_output(self) -> None:
        m = self.module
        termination_signals = frozenset((m.signal.SIGINT, m.signal.SIGTERM))
        blocked = set()
        handlers = {}
        pending = set()
        events = []

        def mask(how, signals):
            requested = frozenset(signals)
            if how == m.signal.SIG_BLOCK:
                prior = frozenset(blocked)
                blocked.update(requested)
                events.append(("block", m._OUTPUT_STARTED))
                return prior
            self.assertEqual(how, m.signal.SIG_SETMASK)
            blocked.clear()
            blocked.update(requested)
            events.append(("restore", m._OUTPUT_STARTED))
            if m._OUTPUT_STARTED and pending:
                signum = pending.pop()
                events.append(("deliver", signum))
                handlers[signum](signum, None)
            return frozenset()

        def install(signum, handler):
            self.assertTrue(termination_signals.issubset(blocked))
            self.assertIs(handler, m._signal_before_output)
            handlers[signum] = handler

        def sample_pending():
            self.assertTrue(m._OUTPUT_STARTED)
            pending.add(m.signal.SIGTERM)
            events.append(("pending", m._OUTPUT_STARTED))
            return frozenset(pending)

        def emit(payload):
            events.append(("emit", payload, m._OUTPUT_STARTED))

        def exit_process(code):
            events.append(("exit", code))
            raise SystemExit(code)

        with mock.patch.object(m.signal, "signal", side_effect=install), mock.patch.object(
            m.signal, "pthread_sigmask", side_effect=mask
        ), mock.patch.object(
            m.signal, "sigpending", side_effect=sample_pending
        ) as sigpending, mock.patch.object(
            m, "emit_bytes", side_effect=emit
        ), mock.patch.object(
            m.os, "_exit", side_effect=exit_process
        ):
            code = m.main(("unexpected",))

        self.assertEqual(code, 3)
        sigpending.assert_called_once_with()
        emit_events = [event for event in events if event[0] == "emit"]
        self.assertEqual(len(emit_events), 1)
        self.assertIs(emit_events[0][1], m.FALLBACK_INTERNAL_ERROR)
        self.assertTrue(emit_events[0][2])
        self.assertEqual(
            [event[0] for event in events],
            [
                "block",
                "restore",
                "block",
                "pending",
                "emit",
                "restore",
                "deliver",
                "block",
                "exit",
            ],
        )

    def test_signal_before_output_emits_exact_literal_and_exits_three(self) -> None:
        m = self.module
        with mock.patch.object(
            m.signal, "pthread_sigmask", return_value=frozenset()
        ), mock.patch.object(m, "emit_bytes") as emit, mock.patch.object(
            m.os, "_exit", side_effect=SystemExit(3)
        ):
            with self.assertRaisesRegex(SystemExit, "3"):
                m._signal_before_output(15, None)
        emit.assert_called_once_with(m.FALLBACK_INTERNAL_ERROR)

    def test_agent_order_matches_tracked_status_helper(self) -> None:
        helper = (
            ROOT
            / "skills"
            / "shogun-agent-status"
            / "scripts"
            / "agent_status.sh"
        )
        text = helper.read_text(encoding="utf-8")
        positions = [text.index(agent) for agent in self.module.AGENT_IDS]
        self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main()

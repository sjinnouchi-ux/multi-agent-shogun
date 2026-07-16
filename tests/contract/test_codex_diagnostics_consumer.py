from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tests.contract.codex_diagnostics_consumer as consumer

SOURCE_SHA = "a" * 64


class ExplodingBoundary:
    def __bool__(self):
        raise RuntimeError("boundary coercion must not run")

    def __len__(self):
        raise RuntimeError("boundary length must not run")


class ExplodingElapsed(float):
    def __ge__(self, _other):
        raise RuntimeError("elapsed subclass comparison must not run")


def record(status: str = "active") -> dict[str, object]:
    return {
        "status": status,
        "source_repo": "https://github.com/sjinnouchi-ux/multi-agent-shogun",
        "source_commit": "1" * 40,
        "source_path": "scripts/codex_diagnostics.py",
        "source_sha256": SOURCE_SHA,
        "deployed_at": "2026-07-14T00:00:00Z",
        "snapshot_path": "/home/jinnouchi/.local/libexec/shogun-codex-diagnostics",
        "snapshot_mode": "0555",
        "contract_schema_version": 1,
    }


def registry(records: list[dict[str, object]], schema: int = 1) -> bytes:
    body = json.dumps(
        {"schema_version": schema, "deployments": records},
        separators=(",", ":"),
    ).encode()
    return consumer.BEGIN + b"\n" + body + b"\n" + consumer.END


def source_value(applicability: str = "optional") -> dict[str, object]:
    return {
        "applicability": applicability,
        "state": "present",
        "modified_at": "2026-07-14T00:00:00Z",
        "size_class": "small",
    }


def not_applicable_source() -> dict[str, object]:
    return {
        "applicability": "not_applicable",
        "state": "not_applicable",
        "modified_at": None,
        "size_class": None,
    }


def log_events() -> dict[str, object]:
    return {
        "window": "tail_1048576_bytes",
        "modified_at": "2026-07-14T00:00:00Z",
        "send_keys_failed_attempt": 0,
        "nudge_still_visible": 0,
        "wakeup_retry_exhausted": 0,
        "wakeup_success_logged": 0,
        "unclassified_error_candidate": 0,
    }


def output_value(source_hash: str = SOURCE_SHA) -> dict[str, object]:
    agents = []
    for index, agent_id in enumerate(consumer.AGENT_IDS):
        task_agent = agent_id not in ("shogun", "karo")
        agents.append({
            "id": agent_id,
            "observed": True,
            "session": "shogun" if index == 0 else "multiagent",
            "pane_state": "alive",
            "cli": "codex",
            "watcher_count": 1,
            "watcher_state": "healthy",
            "sources": {
                "inbox": source_value("required"),
                "task": (
                    source_value("required")
                    if task_agent else not_applicable_source()
                ),
                "report": (
                    source_value("optional")
                    if task_agent else not_applicable_source()
                ),
                "handoff_status": source_value("optional"),
                "watcher_log": source_value("required"),
            },
            "log_events": log_events(),
        })
    return {
        "schema_version": 1,
        "generated_at": "2026-07-14T00:00:01Z",
        "ok": True,
        "overall": "healthy",
        "tool": {
            "version": "1.0.0",
            "deployment": "user_local_snapshot",
            "source_sha256": source_hash,
        },
        "repository": {
            "branch_class": "main",
            "head": "2" * 40,
            "dirty": False,
            "tracked_changes": 0,
            "untracked_changes": 0,
            "canonical_remote_present": True,
        },
        "sessions": [
            {
                "name": "shogun", "state": "present", "pane_count": 1,
                "dead_pane_count": 0, "unknown_agent_count": 0,
            },
            {
                "name": "multiagent", "state": "present", "pane_count": 10,
                "dead_pane_count": 0, "unknown_agent_count": 0,
            },
        ],
        "processes": {
            "watcher_supervisor_count": 1,
            "watcher_supervisor_state": "healthy",
        },
        "global_sources": {
            "command_queue": source_value("required"),
            "dashboard": source_value("optional"),
        },
        "agents": agents,
        "errors": [],
        "warnings": [],
    }


def output(source_hash: str = SOURCE_SHA) -> bytes:
    return json.dumps(
        output_value(source_hash), separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def changed_output(change, *, ensure_ascii: bool = True) -> bytes:
    value = output_value()
    change(value)
    return json.dumps(
        value, separators=(",", ":"), ensure_ascii=ensure_ascii
    ).encode("utf-8")


def bounded_issue_fixture(*, severity: str, count: int):
    if severity == "errors":
        codes = tuple(
            code for code in consumer.CLI_ERROR_CODES
            if code != "result_truncated"
        )
    elif severity == "warnings":
        codes = consumer.CLI_WARNING_CODES
    else:
        raise AssertionError("unsupported severity")
    values = sorted(
        (
            (code, component, agent)
            for code in codes
            for component in ("diagnostic", "source")
            for agent in (None, *consumer.AGENT_IDS)
        ),
        key=lambda item: (item[0], item[1], item[2] or ""),
    )[:count]
    return [
        {"code": code, "component": component, "agent": agent}
        for code, component, agent in values
    ]


def truncated_error_fixture():
    values = bounded_issue_fixture(severity="errors", count=63)
    values.append({
        "code": "result_truncated",
        "component": "diagnostic",
        "agent": None,
    })
    return sorted(
        values,
        key=lambda item: (item["code"], item["component"], item["agent"] or ""),
    )


def clear_log_events(value, agent_index):
    events = value["agents"][agent_index]["log_events"]
    events["modified_at"] = None
    for key in consumer.LOG_EVENT_KEYS[2:]:
        events[key] = None


def make_agent_unobserved(value, agent_index):
    agent = value["agents"][agent_index]
    agent.update(
        observed=False,
        session=None,
        pane_state="not_observed",
        cli="unknown",
        watcher_count=None,
        watcher_state="not_observed",
    )
    for source in ("inbox", "task", "watcher_log"):
        agent["sources"][source]["applicability"] = "optional"


def log_issue(code, agent):
    return {"code": code, "component": "log", "agent": agent}


def truncated_errors_with_log_issues(*issues):
    base = [
        issue for issue in truncated_error_fixture()
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


def changed_log_output(
    *, agent_index, log_available, errors=(), warnings=(), unobserved=False
):
    def change(value):
        if unobserved:
            make_agent_unobserved(value, agent_index)
        if not log_available:
            clear_log_events(value, agent_index)
        value["errors"] = list(errors)
        value["warnings"] = list(warnings)
        if errors:
            value["overall"] = "degraded"

    return changed_output(change)


class ConsumerContractTests(unittest.TestCase):
    def evaluate(self, **overrides):
        values = {
            "fetch_ok": True,
            "registry": registry([record()]),
            "stdout": output(),
            "stderr": b"",
            "exit_code": 0,
            "elapsed_seconds": 0.1,
        }
        values.update(overrides)
        return consumer.evaluate_consumer(**values)

    def assert_registry_cli_rejects_silently(self, path: Path) -> None:
        with mock.patch("builtins.print") as output_capture:
            result = consumer.registry_cli(
                ("validate-active-registry", str(path))
            )
        self.assertEqual(result, 1)
        output_capture.assert_not_called()

    def test_valid_envelope_is_the_only_trusted_decision(self) -> None:
        decision = self.evaluate()
        self.assertTrue(decision.trusted)
        self.assertIsNone(decision.code)
        self.assertEqual(decision.action, "use_sanitized_diagnostic")
        self.assertFalse(decision.fallback_allowed)

    def test_registry_boundary_requires_exact_bytes_and_never_raises(self) -> None:
        for name, value in (
            ("none", None),
            ("text", registry([record()]).decode("ascii")),
            ("bytearray", bytearray(registry([record()]))),
            ("memoryview", memoryview(registry([record()]))),
            ("hostile", ExplodingBoundary()),
        ):
            with self.subTest(name=name):
                try:
                    decision = self.evaluate(registry=value)
                except BaseException as exc:  # pragma: no cover - regression guard
                    self.fail(f"registry boundary leaked {type(exc).__name__}")
                self.assertFalse(decision.trusted)
                self.assertEqual(
                    decision.code, "diagnostic_provenance_untrusted"
                )
                self.assertEqual(decision.action, "stop_without_fallback")
                self.assertFalse(decision.fallback_allowed)

    def test_process_stream_boundaries_require_exact_bytes_and_never_raise(
        self,
    ) -> None:
        cases = (
            ("stdout_none", {"stdout": None}),
            ("stdout_bytearray", {"stdout": bytearray(output())}),
            ("stdout_memoryview", {"stdout": memoryview(output())}),
            ("stdout_hostile", {"stdout": ExplodingBoundary()}),
            ("stderr_none", {"stderr": None}),
            ("stderr_bytearray", {"stderr": bytearray()}),
            ("stderr_memoryview", {"stderr": memoryview(b"")}),
            ("stderr_hostile", {"stderr": ExplodingBoundary()}),
            ("elapsed_subclass", {"elapsed_seconds": ExplodingElapsed(0.1)}),
        )
        for name, overrides in cases:
            with self.subTest(name=name):
                try:
                    decision = self.evaluate(**overrides)
                except BaseException as exc:  # pragma: no cover - regression guard
                    self.fail(f"process boundary leaked {type(exc).__name__}")
                self.assertFalse(decision.trusted)
                self.assertEqual(decision.code, "diagnostic_process_failed")
                self.assertEqual(decision.action, "stop_without_fallback")
                self.assertFalse(decision.fallback_allowed)

    def test_missing_optional_supervisor_is_trusted_when_everything_else_is_healthy(
        self,
    ) -> None:
        decision = self.evaluate(stdout=changed_output(
            lambda value: value["processes"].update(
                watcher_supervisor_count=0,
                watcher_supervisor_state="missing",
            )
        ))
        self.assertTrue(decision.trusted)
        self.assertIsNone(decision.code)

    def test_log_unavailability_is_trusted_only_with_matching_issue(self) -> None:
        for code in (
            "required_source_missing",
            "source_rejected",
            "command_failed",
        ):
            with self.subTest(observed_error=code):
                decision = self.evaluate(stdout=changed_log_output(
                    agent_index=0,
                    log_available=False,
                    errors=(log_issue(code, "shogun"),),
                ))
                self.assertTrue(decision.trusted)
                self.assertIsNone(decision.code)

        decision = self.evaluate(stdout=changed_log_output(
            agent_index=3,
            log_available=False,
            unobserved=True,
        ))
        self.assertTrue(decision.trusted)
        self.assertIsNone(decision.code)

        for code in ("source_rejected", "command_failed"):
            with self.subTest(unobserved_warning=code):
                decision = self.evaluate(stdout=changed_log_output(
                    agent_index=3,
                    log_available=False,
                    warnings=(log_issue(code, "ashigaru2"),),
                    unobserved=True,
                ))
                self.assertTrue(decision.trusted)
                self.assertIsNone(decision.code)

    def test_log_event_issue_contradictions_fail_closed(self) -> None:
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
                decision = self.evaluate(stdout=changed_log_output(
                    agent_index=agent_index,
                    log_available=log_available,
                    errors=errors,
                    warnings=warnings,
                    unobserved=agent_index == 3,
                ))
                self.assertFalse(decision.trusted)
                self.assertEqual(decision.code, "diagnostic_process_failed")
                self.assertEqual(decision.action, "stop_without_fallback")
                self.assertFalse(decision.fallback_allowed)

    def test_observed_missing_log_issue_may_be_omitted_only_when_errors_truncated(
        self,
    ) -> None:
        decision = self.evaluate(stdout=changed_log_output(
            agent_index=0,
            log_available=False,
            errors=tuple(truncated_error_fixture()),
        ))
        self.assertTrue(decision.trusted)
        self.assertIsNone(decision.code)

    def test_retained_log_contradictions_fail_closed_when_errors_truncated(
        self,
    ) -> None:
        cases = (
            (
                "missing_with_two", False,
                truncated_errors_with_log_issues(
                    log_issue("command_failed", "shogun"),
                    log_issue("required_source_missing", "shogun"),
                ),
            ),
            (
                "complete_with_one", True,
                truncated_errors_with_log_issues(
                    log_issue("command_failed", "shogun")
                ),
            ),
        )
        for name, log_available, errors in cases:
            with self.subTest(name=name):
                decision = self.evaluate(stdout=changed_log_output(
                    agent_index=0,
                    log_available=log_available,
                    errors=tuple(errors),
                ))
                self.assertFalse(decision.trusted)
                self.assertEqual(decision.code, "diagnostic_process_failed")
                self.assertEqual(decision.action, "stop_without_fallback")
                self.assertFalse(decision.fallback_allowed)

    def test_truncation_marker_allows_only_omitted_correlation_issue(self) -> None:
        def truncated_missing_watcher(value):
            value["agents"][0].update(
                watcher_count=0,
                watcher_state="missing",
            )
            value["errors"] = truncated_error_fixture()
            value["overall"] = "degraded"

        decision = self.evaluate(stdout=changed_output(truncated_missing_watcher))
        self.assertTrue(decision.trusted)
        self.assertIsNone(decision.code)

        def truncated_unknown_agent_warning(value):
            value["sessions"][0].update(
                pane_count=2,
                unknown_agent_count=1,
            )
            value["errors"] = [{
                "code": "result_truncated",
                "component": "diagnostic",
                "agent": None,
            }]
            value["warnings"] = bounded_issue_fixture(
                severity="warnings", count=64
            )
            value["overall"] = "degraded"

        decision = self.evaluate(
            stdout=changed_output(truncated_unknown_agent_warning)
        )
        self.assertTrue(decision.trusted)
        self.assertIsNone(decision.code)

    def test_truncation_marker_requires_full_corresponding_issue_array(
        self,
    ) -> None:
        def short_marker(value):
            value["agents"][0].update(
                watcher_count=0,
                watcher_state="missing",
            )
            value["errors"] = [{
                "code": "result_truncated",
                "component": "diagnostic",
                "agent": None,
            }]
            value["overall"] = "degraded"

        def warnings_do_not_truncate_errors(value):
            short_marker(value)
            value["warnings"] = bounded_issue_fixture(
                severity="warnings", count=64
            )

        def errors_do_not_truncate_warnings(value):
            value["sessions"][0].update(
                pane_count=2,
                unknown_agent_count=1,
            )
            value["errors"] = truncated_error_fixture()
            value["overall"] = "degraded"

        for name, change in (
            ("short_marker", short_marker),
            ("warnings_do_not_truncate_errors", warnings_do_not_truncate_errors),
            ("errors_do_not_truncate_warnings", errors_do_not_truncate_warnings),
        ):
            with self.subTest(name=name):
                decision = self.evaluate(stdout=changed_output(change))
                self.assertFalse(decision.trusted)
                self.assertEqual(decision.code, "diagnostic_process_failed")

    def test_every_provenance_failure_stops_without_fallback(self) -> None:
        valid = registry([record()])
        impossible_date_record = record()
        impossible_date_record["deployed_at"] = "2026-02-30T12:00:00Z"
        cases = {
            "github_fetch_failed": self.evaluate(fetch_ok=False),
            "fetch_integer_is_not_boolean_success": self.evaluate(fetch_ok=1),
            "fetch_truthy_string_is_not_boolean_success": self.evaluate(
                fetch_ok="fetch failed"
            ),
            "marker_missing": self.evaluate(registry=b"{}"),
            "marker_duplicate": self.evaluate(registry=valid + b"\n" + valid),
            "marker_reversed": self.evaluate(
                registry=consumer.END + b"\n{}\n" + consumer.BEGIN
            ),
            "registry_deep_nesting": self.evaluate(
                registry=(
                    consumer.BEGIN + b"\n" + b"[" * 1_500 + b"]" * 1_500
                    + b"\n" + consumer.END
                )
            ),
            "registry_oversized": self.evaluate(
                registry=valid + b" " * consumer.MAX_CONSUMER_BYTES
            ),
            "schema_invalid": self.evaluate(registry=registry([record()], schema=2)),
            "deployed_at_is_not_a_real_utc_second": self.evaluate(
                registry=registry([impossible_date_record])
            ),
            "active_zero": self.evaluate(registry=registry([record("superseded")])),
            "active_multiple": self.evaluate(registry=registry([record(), record()])),
            "source_hash_mismatch": self.evaluate(stdout=output("b" * 64)),
        }
        for name, decision in cases.items():
            with self.subTest(name=name):
                self.assertFalse(decision.trusted)
                self.assertEqual(decision.code, "diagnostic_provenance_untrusted")
                self.assertEqual(decision.action, "stop_without_fallback")
                self.assertFalse(decision.fallback_allowed)

    def test_registry_validator_enforces_exact_record_contract(self) -> None:
        valid_record = record()
        self.assertEqual(
            consumer.validate_registry(
                registry([valid_record]), require_active=True
            ),
            [valid_record],
        )
        self.assertEqual(
            consumer.validate_registry(registry([]), require_active=False),
            [],
        )
        self.assertEqual(
            consumer.validate_registry(
                registry([record("superseded")]), require_active=False
            )[0]["status"],
            "superseded",
        )

        reordered = record()
        reordered = {
            key: reordered[key]
            for key in (
                consumer.RECORD_KEYS[1],
                consumer.RECORD_KEYS[0],
                *consumer.RECORD_KEYS[2:],
            )
        }
        missing_key = record()
        missing_key.pop("snapshot_mode")
        extra_key = record()
        extra_key["unexpected"] = False
        impossible_date = record()
        impossible_date["deployed_at"] = "2026-02-30T12:00:00Z"
        fraction = record()
        fraction["deployed_at"] = "2026-07-14T00:00:00.0Z"
        offset = record()
        offset["deployed_at"] = "2026-07-14T00:00:00+00:00"
        schema_bool = registry([record()]).replace(
            b'"schema_version":1', b'"schema_version":true', 1
        )
        contract_bool = registry([record()]).replace(
            b'"contract_schema_version":1',
            b'"contract_schema_version":true',
            1,
        )
        duplicate_key = registry([record()]).replace(
            b'{"schema_version":1',
            b'{"schema_version":1,"schema_version":1',
            1,
        )
        top_level_reordered = consumer.BEGIN + b"\n" + json.dumps(
            {"deployments": [record()], "schema_version": 1},
            separators=(",", ":"),
        ).encode("ascii") + b"\n" + consumer.END
        deployments_not_list = consumer.BEGIN + b"\n" + json.dumps(
            {"schema_version": 1, "deployments": {}},
            separators=(",", ":"),
        ).encode("ascii") + b"\n" + consumer.END

        mutations = {
            "record_key_order": registry([reordered]),
            "record_missing_key": registry([missing_key]),
            "record_extra_key": registry([extra_key]),
            "impossible_utc_second": registry([impossible_date]),
            "fractional_second": registry([fraction]),
            "utc_offset": registry([offset]),
            "schema_bool": schema_bool,
            "contract_schema_bool": contract_bool,
            "duplicate_key": duplicate_key,
            "top_level_key_order": top_level_reordered,
            "deployments_not_list": deployments_not_list,
        }
        fixed_fields = {
            "status": "pending",
            "source_repo": "https://example.invalid/repo",
            "source_commit": "A" * 40,
            "source_path": "scripts/other.py",
            "source_sha256": "A" * 64,
            "snapshot_path": "/tmp/snapshot",
            "snapshot_mode": "0755",
        }
        for field, value in fixed_fields.items():
            changed = record()
            changed[field] = value
            mutations[f"fixed_{field}"] = registry([changed])

        for name, raw in mutations.items():
            with self.subTest(name=name), self.assertRaises(consumer.ContractRejected):
                consumer.validate_registry(raw, require_active=True)

        for require_active, records in (
            (True, []),
            (True, [record(), record()]),
            (False, [record(), record()]),
        ):
            with self.subTest(
                require_active=require_active, count=len(records)
            ), self.assertRaises(consumer.ContractRejected):
                consumer.validate_registry(
                    registry(records), require_active=require_active
                )

    def test_registry_validator_cli_is_fixed_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "work-log.md"
            path.write_bytes(registry([record()]))
            with mock.patch("builtins.print") as output:
                self.assertEqual(
                    consumer.registry_cli(
                        ("validate-active-registry", str(path))
                    ),
                    0,
                )
            output.assert_called_once_with("deployment_registry=pass")

            path.write_bytes(registry([record()]))
            completed = subprocess.run(
                (
                    sys.executable,
                    "-I",
                    str(Path(consumer.__file__).resolve()),
                    "validate-active-registry",
                    str(path),
                ),
                check=False,
                capture_output=True,
                timeout=5,
            )
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(completed.stdout, b"deployment_registry=pass\n")
            self.assertEqual(completed.stderr, b"")

            path.write_bytes(registry([]))
            self.assertEqual(
                consumer.registry_cli(("validate-active-registry", str(path))),
                1,
            )
            self.assertEqual(consumer.registry_cli(("other", str(path))), 2)

    def test_registry_cli_rejects_leaf_and_parent_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            real_parent = root / "real"
            real_parent.mkdir()
            real_leaf = real_parent / "work-log.md"
            real_leaf.write_bytes(registry([record()]))

            leaf_link = real_parent / "leaf-link.md"
            leaf_link.symlink_to(real_leaf)
            self.assert_registry_cli_rejects_silently(leaf_link)

            parent_link = root / "parent-link"
            parent_link.symlink_to(real_parent, target_is_directory=True)
            self.assert_registry_cli_rejects_silently(
                parent_link / real_leaf.name
            )

    def test_registry_cli_rejects_fifo_device_and_oversized_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fifo = root / "registry.fifo"
            os.mkfifo(fifo)
            try:
                completed = subprocess.run(
                    (
                        sys.executable,
                        "-I",
                        str(Path(consumer.__file__).resolve()),
                        "validate-active-registry",
                        str(fifo),
                    ),
                    check=False,
                    capture_output=True,
                    timeout=2,
                )
            except subprocess.TimeoutExpired:
                self.fail("FIFO registry read blocked instead of failing closed")
            self.assertEqual(completed.returncode, 1)
            self.assertEqual(completed.stdout, b"")
            self.assertEqual(completed.stderr, b"")

            self.assert_registry_cli_rejects_silently(Path("/dev/null"))

            oversized = root / "oversized.md"
            valid = registry([record()])
            oversized.write_bytes(
                valid + b" " * (consumer.MAX_CONSUMER_BYTES - len(valid) + 1)
            )
            self.assert_registry_cli_rejects_silently(oversized)

    def test_registry_cli_rejects_parent_traversal_component(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            child = root / "child"
            child.mkdir()
            path = root / "work-log.md"
            path.write_bytes(registry([record()]))
            self.assert_registry_cli_rejects_silently(
                Path(f"{child}/../{path.name}")
            )

    def test_registry_cli_rejects_overlong_encoded_path_before_opening(
        self,
    ) -> None:
        path = Path("x" * 4_097)
        self.assertEqual(len(os.fsencode(str(path))), 4_097)
        with mock.patch.object(
            os, "open", side_effect=OSError("path limit must run first")
        ) as open_file, mock.patch.object(
            os, "supports_dir_fd", os.supports_dir_fd | {open_file}
        ):
            self.assert_registry_cli_rejects_silently(path)
        open_file.assert_not_called()

    def test_registry_cli_rejects_too_many_components_before_opening(
        self,
    ) -> None:
        path = Path(*(["x"] * 65))
        self.assertEqual(len(str(path).split(os.sep)), 65)
        with mock.patch.object(
            os, "open", side_effect=OSError("component limit must run first")
        ) as open_file, mock.patch.object(
            os, "supports_dir_fd", os.supports_dir_fd | {open_file}
        ):
            self.assert_registry_cli_rejects_silently(path)
        open_file.assert_not_called()

    def test_registry_cli_rejects_leaf_swap_after_read(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "work-log.md"
            moved = root / "moved.md"
            replacement = root / "replacement.md"
            path.write_bytes(registry([record()]))
            replacement.write_bytes(registry([record()]))
            original_read = os.read
            swapped = False

            def read_then_swap(fd, count):
                nonlocal swapped
                data = original_read(fd, count)
                if not swapped:
                    swapped = True
                    path.rename(moved)
                    replacement.rename(path)
                return data

            with mock.patch.object(os, "read", side_effect=read_then_swap):
                self.assert_registry_cli_rejects_silently(path)
            self.assertTrue(swapped)

    def test_registry_cli_rejects_parent_swap_after_read(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            parent = root / "parent"
            moved = root / "moved-parent"
            replacement = root / "replacement-parent"
            parent.mkdir()
            replacement.mkdir()
            path = parent / "work-log.md"
            path.write_bytes(registry([record()]))
            (replacement / path.name).write_bytes(registry([record()]))
            original_read = os.read
            swapped = False

            def read_then_swap(fd, count):
                nonlocal swapped
                data = original_read(fd, count)
                if not swapped:
                    swapped = True
                    parent.rename(moved)
                    replacement.rename(parent)
                return data

            with mock.patch.object(os, "read", side_effect=read_then_swap):
                self.assert_registry_cli_rejects_silently(path)
            self.assertTrue(swapped)

    def test_registry_cli_rejects_in_place_metadata_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "work-log.md"
            path.write_bytes(registry([record()]))
            path.chmod(0o640)
            original_read = os.read
            mutated = False

            def read_then_mutate(fd, count):
                nonlocal mutated
                data = original_read(fd, count)
                if not mutated:
                    mutated = True
                    path.chmod(0o600)
                return data

            with mock.patch.object(os, "read", side_effect=read_then_mutate):
                self.assert_registry_cli_rejects_silently(path)
            self.assertTrue(mutated)

    def test_registry_cli_rejects_same_size_rewrite_with_restored_metadata(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "work-log.md"
            expected = registry([record()])
            replacement = b"!" + expected[1:]
            self.assertEqual(len(replacement), len(expected))
            path.write_bytes(expected)
            original = path.stat()
            original_read = os.read
            rewritten = False

            def read_then_rewrite(fd, count):
                nonlocal rewritten
                data = original_read(fd, count)
                if not rewritten:
                    rewritten = True
                    path.write_bytes(replacement)
                path.chmod(original.st_mode & 0o7777)
                os.utime(
                    path,
                    ns=(original.st_atime_ns, original.st_mtime_ns),
                    follow_symlinks=False,
                )
                return data

            with mock.patch.object(os, "read", side_effect=read_then_rewrite):
                self.assert_registry_cli_rejects_silently(path)
            self.assertTrue(rewritten)
            final = path.stat()
            self.assertEqual(final.st_size, original.st_size)
            self.assertEqual(final.st_atime_ns, original.st_atime_ns)
            self.assertEqual(final.st_mtime_ns, original.st_mtime_ns)
            self.assertEqual(final.st_mode, original.st_mode)
            self.assertNotEqual(final.st_ctime_ns, original.st_ctime_ns)

    def test_registry_cli_accepts_exact_stable_bounded_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "work-log.md"
            expected = registry([record()])
            path.write_bytes(expected)
            with mock.patch("builtins.print") as output_capture:
                self.assertEqual(
                    consumer.registry_cli(
                        ("validate-active-registry", str(path))
                    ),
                    0,
                )
            output_capture.assert_called_once_with("deployment_registry=pass")

    def test_every_process_failure_stops_without_fallback(self) -> None:
        def missing_session_with_nonzero_counts(value):
            value["sessions"][0].update(state="missing", pane_count=1)
            value["overall"] = "degraded"
            value["errors"] = [{
                "code": "session_missing",
                "component": "tmux",
                "agent": None,
            }]

        def required_source_not_applicable(value):
            value["global_sources"]["command_queue"] = {
                "applicability": "required",
                "state": "not_applicable",
                "modified_at": None,
                "size_class": None,
            }
            value["overall"] = "degraded"

        def mismatch_with_expected_session(value):
            value["agents"][0]["pane_state"] = "error"
            value["errors"] = [{
                "code": "agent_session_mismatch",
                "component": "tmux",
                "agent": "shogun",
            }]
            value["overall"] = "degraded"

        def mismatch_without_session(value):
            mismatch_with_expected_session(value)
            value["agents"][0]["session"] = None

        def duplicate_with_nonunknown_cli(value):
            value["agents"][0]["pane_state"] = "error"
            value["agents"][0]["session"] = None
            value["errors"] = [{
                "code": "duplicate_agent_pane",
                "component": "tmux",
                "agent": "shogun",
            }]
            value["overall"] = "degraded"

        cases = {
            "empty_stdout": self.evaluate(stdout=b""),
            "partial_json": self.evaluate(stdout=b'{"schema_version":1'),
            "second_json": self.evaluate(stdout=output() + b"{}"),
            "duplicate_json_key": self.evaluate(
                stdout=output().replace(
                    b'{"schema_version":1',
                    b'{"schema_version":1,"schema_version":1',
                    1,
                )
            ),
            "stdout_oversized": self.evaluate(
                stdout=output() + b" " * consumer.MAX_CONSUMER_BYTES
            ),
            "output_schema_invalid": self.evaluate(
                stdout=output().replace(b'"schema_version":1', b'"schema_version":2', 1)
            ),
            "generated_at_null": self.evaluate(
                stdout=changed_output(lambda value: value.update(generated_at=None))
            ),
            "generated_at_is_not_a_real_utc_second": self.evaluate(
                stdout=changed_output(
                    lambda value: value.update(
                        generated_at="2026-02-30T12:00:00Z"
                    )
                )
            ),
            "source_modified_at_is_not_a_real_utc_second": self.evaluate(
                stdout=changed_output(
                    lambda value: value["global_sources"]["command_queue"].update(
                        modified_at="2026-02-30T12:00:00Z"
                    )
                )
            ),
            "log_modified_at_is_not_a_real_utc_second": self.evaluate(
                stdout=changed_output(
                    lambda value: value["agents"][0]["log_events"].update(
                        modified_at="2026-02-30T12:00:00Z"
                    )
                )
            ),
            "nested_free_text": self.evaluate(
                stdout=changed_output(
                    lambda value: value["repository"].update(
                        raw_message="secret-free-text"
                    )
                )
            ),
            "session_cardinality": self.evaluate(
                stdout=changed_output(lambda value: value["sessions"].clear())
            ),
            "agent_cardinality": self.evaluate(
                stdout=changed_output(lambda value: value["agents"].pop())
            ),
            "literal_non_ascii": self.evaluate(
                stdout=changed_output(
                    lambda value: value["repository"].update(branch_class="秘密"),
                    ensure_ascii=False,
                )
            ),
            "output_deep_nesting": self.evaluate(
                stdout=b"[" * 1_500 + b"]" * 1_500
            ),
            "healthy_overall_cannot_be_declared_degraded": self.evaluate(
                stdout=changed_output(
                    lambda value: value.update(overall="degraded")
                )
            ),
            "error_requires_recomputed_overall": self.evaluate(
                stdout=changed_output(
                    lambda value: value.update(errors=[{
                        "code": "command_failed",
                        "component": "log",
                        "agent": "ashigaru1",
                    }])
                )
            ),
            "canonical_remote_cannot_be_false": self.evaluate(
                stdout=changed_output(
                    lambda value: value["repository"].update(
                        canonical_remote_present=False
                    )
                )
            ),
            "missing_session_requires_zero_counts": self.evaluate(
                stdout=changed_output(missing_session_with_nonzero_counts)
            ),
            "source_applicability_must_match_state": self.evaluate(
                stdout=changed_output(required_source_not_applicable)
            ),
            "unobserved_agent_cannot_keep_observed_fields": self.evaluate(
                stdout=changed_output(
                    lambda value: value["agents"][2].update(observed=False)
                )
            ),
            "watcher_count_must_match_state": self.evaluate(
                stdout=changed_output(
                    lambda value: value["agents"][0].update(watcher_count=0)
                )
            ),
            "supervisor_count_must_match_state": self.evaluate(
                stdout=changed_output(
                    lambda value: value["processes"].update(
                        watcher_supervisor_count=0
                    )
                )
            ),
            "mismatch_requires_unexpected_session": self.evaluate(
                stdout=changed_output(mismatch_with_expected_session)
            ),
            "mismatch_requires_nonnull_session": self.evaluate(
                stdout=changed_output(mismatch_without_session)
            ),
            "duplicate_requires_unknown_cli": self.evaluate(
                stdout=changed_output(duplicate_with_nonunknown_cli)
            ),
            "error_rejects_warning_only_code": self.evaluate(
                stdout=changed_output(
                    lambda value: value.update(
                        overall="degraded",
                        errors=[{
                            "code": "unknown_cli_observed",
                            "component": "tmux",
                            "agent": "shogun",
                        }],
                    )
                )
            ),
            "warning_rejects_error_only_code": self.evaluate(
                stdout=changed_output(
                    lambda value: value.update(warnings=[{
                        "code": "watcher_missing",
                        "component": "process",
                        "agent": "shogun",
                    }])
                )
            ),
            "cli_rejects_consumer_process_code": self.evaluate(
                stdout=changed_output(
                    lambda value: value.update(
                        overall="degraded",
                        errors=[{
                            "code": "diagnostic_process_failed",
                            "component": "diagnostic",
                            "agent": None,
                        }],
                    )
                )
            ),
            "cli_rejects_consumer_provenance_code": self.evaluate(
                stdout=changed_output(
                    lambda value: value.update(warnings=[{
                        "code": "diagnostic_provenance_untrusted",
                        "component": "diagnostic",
                        "agent": None,
                    }])
                )
            ),
            "nonempty_stderr": self.evaluate(stderr=b"unexpected"),
            "exit_two": self.evaluate(exit_code=2),
            "exit_three": self.evaluate(exit_code=3),
            "elapsed_nan": self.evaluate(elapsed_seconds=float("nan")),
            "elapsed_positive_infinity": self.evaluate(
                elapsed_seconds=float("inf")
            ),
            "elapsed_negative_infinity": self.evaluate(
                elapsed_seconds=float("-inf")
            ),
            "elapsed_exactly_10_seconds": self.evaluate(elapsed_seconds=10.0),
            "elapsed_over_10_seconds": self.evaluate(elapsed_seconds=10.001),
        }
        for name, decision in cases.items():
            with self.subTest(name=name):
                self.assertFalse(decision.trusted)
                self.assertEqual(decision.code, "diagnostic_process_failed")
                self.assertEqual(decision.action, "stop_without_fallback")
                self.assertFalse(decision.fallback_allowed)

    def test_huge_integer_elapsed_values_do_not_escape_fail_closed_decision(
        self,
    ) -> None:
        for elapsed in (10**10_000, -(10**10_000)):
            with self.subTest(sign="negative" if elapsed < 0 else "positive"):
                try:
                    decision = self.evaluate(elapsed_seconds=elapsed)
                except Exception as exc:  # pragma: no cover - regression assertion
                    self.fail(f"elapsed validation leaked {type(exc).__name__}")
                self.assertFalse(decision.trusted)
                self.assertEqual(decision.code, "diagnostic_process_failed")
                self.assertEqual(decision.action, "stop_without_fallback")
                self.assertFalse(decision.fallback_allowed)

    def test_issue_arrays_must_be_strictly_sorted_and_unique(self) -> None:
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
        invalid_arrays = {
            "reversed": [watcher_issue, session_issue],
            "duplicate": [session_issue, session_issue],
        }
        for array_name in ("errors", "warnings"):
            for case_name, issues in invalid_arrays.items():
                with self.subTest(array=array_name, case=case_name):
                    decision = self.evaluate(
                        stdout=changed_output(
                            lambda value, name=array_name, values=issues: value.update(
                                {name: values}
                            )
                        )
                    )
                    self.assertFalse(decision.trusted)
                    self.assertEqual(decision.code, "diagnostic_process_failed")
                    self.assertEqual(decision.action, "stop_without_fallback")
                    self.assertFalse(decision.fallback_allowed)


if __name__ == "__main__":
    unittest.main()

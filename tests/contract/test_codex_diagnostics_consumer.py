from __future__ import annotations

import json
import unittest

import tests.contract.codex_diagnostics_consumer as consumer

SOURCE_SHA = "a" * 64


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
        codes = ("command_failed", "source_rejected")
    else:
        raise AssertionError("unsupported severity")
    values = sorted(
        (
            (code, component, agent)
            for code in codes
            for component in ("diagnostic", "log", "source")
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

    def test_valid_envelope_is_the_only_trusted_decision(self) -> None:
        decision = self.evaluate()
        self.assertTrue(decision.trusted)
        self.assertIsNone(decision.code)
        self.assertEqual(decision.action, "use_sanitized_diagnostic")
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

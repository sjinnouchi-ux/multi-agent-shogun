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


def source_value() -> dict[str, object]:
    return {
        "applicability": "optional",
        "state": "present",
        "modified_at": "2026-07-14T00:00:00Z",
        "size_class": "small",
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
        agents.append({
            "id": agent_id,
            "observed": True,
            "session": "shogun" if index == 0 else "multiagent",
            "pane_state": "alive",
            "cli": "codex",
            "watcher_count": 1,
            "watcher_state": "healthy",
            "sources": {key: source_value() for key in consumer.SOURCE_KEYS},
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
            "command_queue": source_value(),
            "dashboard": source_value(),
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

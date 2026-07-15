from __future__ import annotations

import datetime as dt
import json
import math
import re
from dataclasses import dataclass

BEGIN = b"<!-- BEGIN CODEX_DIAGNOSTICS_DEPLOYMENTS_V1 -->"
END = b"<!-- END CODEX_DIAGNOSTICS_DEPLOYMENTS_V1 -->"
RECORD_KEYS = (
    "status", "source_repo", "source_commit", "source_path", "source_sha256",
    "deployed_at", "snapshot_path", "snapshot_mode", "contract_schema_version",
)
TOP_LEVEL_KEYS = (
    "schema_version", "generated_at", "ok", "overall", "tool", "repository",
    "sessions", "processes", "global_sources", "agents", "errors", "warnings",
)
TOOL_KEYS = ("version", "deployment", "source_sha256")
REPOSITORY_KEYS = (
    "branch_class", "head", "dirty", "tracked_changes",
    "untracked_changes", "canonical_remote_present",
)
SESSION_KEYS = ("name", "state", "pane_count", "dead_pane_count", "unknown_agent_count")
AGENT_KEYS = (
    "id", "observed", "session", "pane_state", "cli", "watcher_count",
    "watcher_state", "sources", "log_events",
)
SOURCE_KEYS = ("inbox", "task", "report", "handoff_status", "watcher_log")
SOURCE_VALUE_KEYS = ("applicability", "state", "modified_at", "size_class")
LOG_EVENT_KEYS = (
    "window", "modified_at", "send_keys_failed_attempt", "nudge_still_visible",
    "wakeup_retry_exhausted", "wakeup_success_logged",
    "unclassified_error_candidate",
)
ISSUE_KEYS = ("code", "component", "agent")
AGENT_IDS = (
    "shogun", "karo", "ashigaru1", "ashigaru2", "ashigaru3", "ashigaru4",
    "ashigaru5", "ashigaru6", "ashigaru7", "gunshi", "oometsuke",
)
SESSION_NAMES = ("shogun", "multiagent")
CLI_NAMES = (
    "claude", "codex", "copilot", "kimi", "opencode", "cursor",
    "antigravity", "unknown",
)
COMPONENTS = ("repository", "tmux", "process", "source", "log", "diagnostic")
ERROR_CODES = (
    "argument_rejected", "agent_session_mismatch", "boundary_rejected",
    "canonical_remote_missing", "command_failed", "command_output_limited",
    "command_timeout", "diagnostic_process_failed",
    "diagnostic_provenance_untrusted", "duplicate_agent_pane",
    "duplicate_process", "internal_error", "pane_dead", "required_source_missing",
    "result_truncated", "session_missing", "source_rejected",
    "unknown_agent_observed", "unknown_cli_observed", "watcher_missing",
)
SHA40 = re.compile(r"[0-9a-f]{40}")
SHA64 = re.compile(r"[0-9a-f]{64}")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
MAX_CONSUMER_BYTES = 1_048_576


class ContractRejected(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ConsumerDecision:
    trusted: bool
    code: str | None
    action: str

    @property
    def fallback_allowed(self) -> bool:
        return False


def _failure(code: str) -> ConsumerDecision:
    return ConsumerDecision(False, code, "stop_without_fallback")


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ContractRejected
        value[key] = item
    return value


def _reject_constant(_value: str):
    raise ContractRejected


def _json_object(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(
            raw.decode("ascii", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ContractRejected from exc
    if not isinstance(value, dict):
        raise ContractRejected
    return value


def _active_record(raw: bytes) -> dict[str, object]:
    if raw.count(BEGIN) != 1 or raw.count(END) != 1:
        raise ContractRejected
    begin_marker = raw.index(BEGIN)
    end_marker = raw.index(END)
    if end_marker <= begin_marker:
        raise ContractRejected
    begin = begin_marker + len(BEGIN)
    end = end_marker
    body = raw[begin:end].strip()
    if not body or b"\n" in body or b"\r" in body:
        raise ContractRejected
    value = _json_object(body)
    if tuple(value) != ("schema_version", "deployments"):
        raise ContractRejected
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ContractRejected
    records = value["deployments"]
    if not isinstance(records, list) or not records:
        raise ContractRejected
    active: list[dict[str, object]] = []
    for record in records:
        if not isinstance(record, dict) or tuple(record) != RECORD_KEYS:
            raise ContractRejected
        if record["status"] not in ("active", "superseded"):
            raise ContractRejected
        if record["source_repo"] != (
            "https://github.com/sjinnouchi-ux/multi-agent-shogun"
        ):
            raise ContractRejected
        if not isinstance(record["source_commit"], str) or SHA40.fullmatch(
            record["source_commit"]
        ) is None:
            raise ContractRejected
        if record["source_path"] != "scripts/codex_diagnostics.py":
            raise ContractRejected
        if not isinstance(record["source_sha256"], str) or SHA64.fullmatch(
            record["source_sha256"]
        ) is None:
            raise ContractRejected
        _timestamp(record["deployed_at"], nullable=False)
        if record["snapshot_path"] != (
            "/home/jinnouchi/.local/libexec/shogun-codex-diagnostics"
        ):
            raise ContractRejected
        if record["snapshot_mode"] != "0555":
            raise ContractRejected
        if type(record["contract_schema_version"]) is not int or (
            record["contract_schema_version"] != 1
        ):
            raise ContractRejected
        if record["status"] == "active":
            active.append(record)
    if len(active) != 1:
        raise ContractRejected
    return active[0]


def _exact_keys(value: object, keys: tuple[str, ...]) -> dict[str, object]:
    if not isinstance(value, dict) or tuple(value) != keys:
        raise ContractRejected
    return value


def _nullable_count(value: object, maximum: int | None = None) -> None:
    if value is None:
        return
    if type(value) is not int or value < 0 or (
        maximum is not None and value > maximum
    ):
        raise ContractRejected


def _timestamp(value: object, *, nullable: bool) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str) or TIMESTAMP.fullmatch(value) is None:
        raise ContractRejected
    try:
        dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ContractRejected from exc


def _source_value(raw: object) -> None:
    value = _exact_keys(raw, SOURCE_VALUE_KEYS)
    if value["applicability"] not in ("required", "optional", "not_applicable"):
        raise ContractRejected
    if value["state"] not in (
        "present", "missing", "rejected", "not_applicable", "error"
    ):
        raise ContractRejected
    _timestamp(value["modified_at"], nullable=True)
    if value["size_class"] not in ("empty", "small", "medium", "large", None):
        raise ContractRejected
    if value["state"] == "not_applicable" and (
        value["applicability"] != "not_applicable"
        or value["modified_at"] is not None
        or value["size_class"] is not None
    ):
        raise ContractRejected


def _output_source_hash(raw: bytes) -> str:
    top = _exact_keys(_json_object(raw), TOP_LEVEL_KEYS)
    if type(top["schema_version"]) is not int or top["schema_version"] != 1:
        raise ContractRejected
    _timestamp(top["generated_at"], nullable=False)
    if top["ok"] is not True or top["overall"] not in (
        "healthy", "degraded", "unavailable"
    ):
        raise ContractRejected
    tool = _exact_keys(top["tool"], TOOL_KEYS)
    if tool["version"] != "1.0.0" or tool["deployment"] != "user_local_snapshot":
        raise ContractRejected
    source_hash = tool["source_sha256"]
    if not isinstance(source_hash, str) or SHA64.fullmatch(source_hash) is None:
        raise ContractRejected

    repository = _exact_keys(top["repository"], REPOSITORY_KEYS)
    if repository["branch_class"] not in (
        "main", "shogun_namespace", "codex_namespace", "other", "detached", "invalid"
    ):
        raise ContractRejected
    head = repository["head"]
    if head is not None and (
        not isinstance(head, str) or SHA40.fullmatch(head) is None
    ):
        raise ContractRejected
    if repository["dirty"] is not None and type(repository["dirty"]) is not bool:
        raise ContractRejected
    _nullable_count(repository["tracked_changes"], 10_000)
    _nullable_count(repository["untracked_changes"], 10_000)
    if repository["canonical_remote_present"] is not None and type(
        repository["canonical_remote_present"]
    ) is not bool:
        raise ContractRejected

    sessions = top["sessions"]
    if not isinstance(sessions, list) or len(sessions) != len(SESSION_NAMES):
        raise ContractRejected
    for expected, raw_session in zip(SESSION_NAMES, sessions):
        session = _exact_keys(raw_session, SESSION_KEYS)
        if session["name"] != expected or session["state"] not in (
            "present", "missing", "error"
        ):
            raise ContractRejected
        for key in SESSION_KEYS[2:]:
            _nullable_count(session[key], 64)

    processes = _exact_keys(
        top["processes"], ("watcher_supervisor_count", "watcher_supervisor_state")
    )
    _nullable_count(processes["watcher_supervisor_count"])
    if processes["watcher_supervisor_state"] not in (
        "healthy", "missing", "duplicate", "unknown"
    ):
        raise ContractRejected

    global_sources = _exact_keys(top["global_sources"], ("command_queue", "dashboard"))
    for source in global_sources.values():
        _source_value(source)

    agents = top["agents"]
    if not isinstance(agents, list) or len(agents) != len(AGENT_IDS):
        raise ContractRejected
    for expected, raw_agent in zip(AGENT_IDS, agents):
        agent = _exact_keys(raw_agent, AGENT_KEYS)
        if agent["id"] != expected or type(agent["observed"]) is not bool:
            raise ContractRejected
        if agent["session"] not in (*SESSION_NAMES, None):
            raise ContractRejected
        if agent["pane_state"] not in ("alive", "dead", "not_observed", "error"):
            raise ContractRejected
        if agent["cli"] not in CLI_NAMES:
            raise ContractRejected
        _nullable_count(agent["watcher_count"])
        if agent["watcher_state"] not in (
            "healthy", "missing", "duplicate", "unknown", "not_observed"
        ):
            raise ContractRejected
        sources = _exact_keys(agent["sources"], SOURCE_KEYS)
        for source in sources.values():
            _source_value(source)
        events = _exact_keys(agent["log_events"], LOG_EVENT_KEYS)
        if events["window"] != "tail_1048576_bytes":
            raise ContractRejected
        _timestamp(events["modified_at"], nullable=True)
        for key in LOG_EVENT_KEYS[2:]:
            _nullable_count(events[key])

    for array_name in ("errors", "warnings"):
        issues = top[array_name]
        if not isinstance(issues, list) or len(issues) > 64:
            raise ContractRejected
        previous: tuple[str, str, str] | None = None
        for raw_issue in issues:
            issue = _exact_keys(raw_issue, ISSUE_KEYS)
            if issue["code"] not in ERROR_CODES or issue["component"] not in COMPONENTS:
                raise ContractRejected
            if issue["agent"] not in (*AGENT_IDS, None):
                raise ContractRejected
            current = (
                issue["code"],
                issue["component"],
                issue["agent"] or "",
            )
            if previous is not None and current <= previous:
                raise ContractRejected
            previous = current
    return source_hash


def _valid_elapsed_seconds(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and 0 <= value < 10.0
    except (OverflowError, TypeError, ValueError):
        return False


def evaluate_consumer(
    *,
    fetch_ok: bool,
    registry: bytes,
    stdout: bytes,
    stderr: bytes,
    exit_code: int,
    elapsed_seconds: float,
) -> ConsumerDecision:
    if fetch_ok is not True:
        return _failure("diagnostic_provenance_untrusted")
    if not registry or len(registry) > MAX_CONSUMER_BYTES:
        return _failure("diagnostic_provenance_untrusted")
    try:
        active = _active_record(registry)
    except Exception:
        return _failure("diagnostic_provenance_untrusted")
    if (
        stderr
        or not stdout
        or len(stdout) > MAX_CONSUMER_BYTES
        or type(exit_code) is not int
        or exit_code != 0
        or not _valid_elapsed_seconds(elapsed_seconds)
    ):
        return _failure("diagnostic_process_failed")
    try:
        source_hash = _output_source_hash(stdout)
    except Exception:
        return _failure("diagnostic_process_failed")
    if source_hash != active["source_sha256"]:
        return _failure("diagnostic_provenance_untrusted")
    return ConsumerDecision(True, None, "use_sanitized_diagnostic")

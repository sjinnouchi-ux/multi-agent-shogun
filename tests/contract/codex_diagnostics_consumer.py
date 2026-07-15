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
MAX_ISSUES = 64
ALL_ISSUE_CODES = (
    "argument_rejected", "agent_session_mismatch", "boundary_rejected",
    "canonical_remote_missing", "command_failed", "command_output_limited",
    "command_timeout", "diagnostic_process_failed",
    "diagnostic_provenance_untrusted", "duplicate_agent_pane",
    "duplicate_process", "internal_error", "pane_dead", "required_source_missing",
    "result_truncated", "session_missing", "source_rejected",
    "unknown_agent_observed", "unknown_cli_observed", "watcher_missing",
)
CONSUMER_DECISION_CODES = (
    "diagnostic_process_failed",
    "diagnostic_provenance_untrusted",
)
CLI_ERROR_CODES = (
    "argument_rejected", "agent_session_mismatch", "boundary_rejected",
    "canonical_remote_missing", "command_failed", "command_output_limited",
    "command_timeout", "duplicate_agent_pane", "duplicate_process",
    "internal_error", "pane_dead", "required_source_missing",
    "result_truncated", "session_missing", "source_rejected",
    "watcher_missing",
)
CLI_WARNING_CODES = (
    "command_failed", "source_rejected", "unknown_agent_observed",
    "unknown_cli_observed",
)
EXPECTED_SESSION = {
    agent: ("shogun" if agent == "shogun" else "multiagent")
    for agent in AGENT_IDS
}
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


def _source_value(
    raw: object, *, expected_applicability: str | None = None
) -> dict[str, object]:
    value = _exact_keys(raw, SOURCE_VALUE_KEYS)
    if value["applicability"] not in ("required", "optional", "not_applicable"):
        raise ContractRejected
    if value["state"] not in (
        "present", "missing", "rejected", "not_applicable", "error"
    ):
        raise ContractRejected
    if (
        expected_applicability is not None
        and value["applicability"] != expected_applicability
    ):
        raise ContractRejected
    _timestamp(value["modified_at"], nullable=True)
    if value["size_class"] not in ("empty", "small", "medium", "large", None):
        raise ContractRejected
    if value["applicability"] == "not_applicable":
        if value != {
            "applicability": "not_applicable",
            "state": "not_applicable",
            "modified_at": None,
            "size_class": None,
        }:
            raise ContractRejected
    elif value["state"] == "not_applicable":
        raise ContractRejected
    elif value["state"] == "present":
        if value["modified_at"] is None or value["size_class"] is None:
            raise ContractRejected
    elif value["modified_at"] is not None or value["size_class"] is not None:
        raise ContractRejected
    return value


def _watcher_pair(count: object, state: object, *, observed: bool) -> None:
    _nullable_count(count)
    if not observed:
        if count is not None or state != "not_observed":
            raise ContractRejected
        return
    valid = (
        (state == "healthy" and count == 1)
        or (state == "missing" and count == 0)
        or (state == "duplicate" and type(count) is int and count >= 2)
        or (state == "unknown" and count is None)
    )
    if not valid:
        raise ContractRejected


def _agent_source_applicability(
    agent: str, observed: bool
) -> dict[str, str]:
    task_agent = agent not in ("shogun", "karo")
    required_or_optional = "required" if observed else "optional"
    return {
        "inbox": required_or_optional,
        "task": required_or_optional if task_agent else "not_applicable",
        "report": "optional" if task_agent else "not_applicable",
        "handoff_status": "optional",
        "watcher_log": required_or_optional,
    }


def _expected_overall(
    top: dict[str, object], *, repository_available: bool
) -> str:
    sessions = top["sessions"]
    if not isinstance(sessions, list):
        raise ContractRejected
    states = [item["state"] for item in sessions]
    if not repository_available or states == ["missing", "missing"]:
        return "unavailable"
    if top["errors"] or any(state != "present" for state in states):
        return "degraded"
    processes = top["processes"]
    if not isinstance(processes, dict):
        raise ContractRejected
    if processes["watcher_supervisor_state"] in ("duplicate", "unknown"):
        return "degraded"
    global_sources = top["global_sources"]
    if not isinstance(global_sources, dict):
        raise ContractRejected
    if global_sources["command_queue"]["state"] != "present":
        return "degraded"
    agents = top["agents"]
    if not isinstance(agents, list):
        raise ContractRejected
    for agent in agents:
        if not agent["observed"]:
            continue
        if agent["pane_state"] in ("dead", "error"):
            return "degraded"
        if agent["watcher_state"] != "healthy":
            return "degraded"
        if any(
            source["applicability"] == "required"
            and source["state"] != "present"
            for source in agent["sources"].values()
        ):
            return "degraded"
    return "healthy"


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
    if repository["canonical_remote_present"] is not True:
        raise ContractRejected
    if repository["tracked_changes"] is None or repository["untracked_changes"] is None:
        if repository["dirty"] is not None:
            raise ContractRejected
    elif repository["dirty"] is not bool(
        repository["tracked_changes"] or repository["untracked_changes"]
    ):
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
        counts = tuple(session[key] for key in SESSION_KEYS[2:])
        if session["state"] == "missing" and counts != (0, 0, 0):
            raise ContractRejected
        if session["state"] == "error" and counts != (None, None, None):
            raise ContractRejected
        if session["state"] == "present":
            pane_count, dead_count, unknown_count = counts
            if (
                type(pane_count) is not int
                or type(dead_count) is not int
                or type(unknown_count) is not int
                or pane_count < 1
                or dead_count > pane_count
                or unknown_count > pane_count
            ):
                raise ContractRejected

    processes = _exact_keys(
        top["processes"], ("watcher_supervisor_count", "watcher_supervisor_state")
    )
    if processes["watcher_supervisor_state"] not in (
        "healthy", "missing", "duplicate", "unknown"
    ):
        raise ContractRejected
    _watcher_pair(
        processes["watcher_supervisor_count"],
        processes["watcher_supervisor_state"],
        observed=True,
    )

    global_sources = _exact_keys(top["global_sources"], ("command_queue", "dashboard"))
    _source_value(
        global_sources["command_queue"], expected_applicability="required"
    )
    _source_value(
        global_sources["dashboard"], expected_applicability="optional"
    )

    agents = top["agents"]
    if not isinstance(agents, list) or len(agents) != len(AGENT_IDS):
        raise ContractRejected
    validated_agents: list[dict[str, object]] = []
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
        if agent["watcher_state"] not in (
            "healthy", "missing", "duplicate", "unknown", "not_observed"
        ):
            raise ContractRejected
        observed = agent["observed"]
        if not observed:
            if (
                agent["session"] is not None
                or agent["pane_state"] != "not_observed"
                or agent["cli"] != "unknown"
            ):
                raise ContractRejected
        else:
            if agent["pane_state"] == "not_observed":
                raise ContractRejected
            if agent["pane_state"] in ("alive", "dead") and (
                agent["session"] != EXPECTED_SESSION[expected]
            ):
                raise ContractRejected
            if agent["session"] is not None:
                session_index = SESSION_NAMES.index(agent["session"])
                if sessions[session_index]["state"] != "present":
                    raise ContractRejected
        _watcher_pair(
            agent["watcher_count"], agent["watcher_state"], observed=observed
        )
        sources = _exact_keys(agent["sources"], SOURCE_KEYS)
        expected_sources = _agent_source_applicability(expected, observed)
        for key, source in sources.items():
            _source_value(
                source, expected_applicability=expected_sources[key]
            )
        events = _exact_keys(agent["log_events"], LOG_EVENT_KEYS)
        if events["window"] != "tail_1048576_bytes":
            raise ContractRejected
        _timestamp(events["modified_at"], nullable=True)
        event_counts = []
        for key in LOG_EVENT_KEYS[2:]:
            _nullable_count(events[key])
            event_counts.append(events[key])
        if any(value is None for value in event_counts):
            if any(value is not None for value in event_counts) or (
                events["modified_at"] is not None
            ):
                raise ContractRejected
        elif events["modified_at"] is None:
            raise ContractRejected
        validated_agents.append(agent)

    for index, session in enumerate(sessions):
        name = SESSION_NAMES[index]
        assigned = [agent for agent in validated_agents if agent["session"] == name]
        if session["state"] == "missing" and assigned:
            raise ContractRejected
        if session["state"] == "present":
            if session["pane_count"] < len(assigned) + session["unknown_agent_count"]:
                raise ContractRejected
            dead = sum(agent["pane_state"] == "dead" for agent in assigned)
            if session["dead_pane_count"] < dead:
                raise ContractRejected

    issue_sets: dict[str, set[tuple[str, str, str | None]]] = {}
    for array_name, allowed_codes in (
        ("errors", CLI_ERROR_CODES),
        ("warnings", CLI_WARNING_CODES),
    ):
        issues = top[array_name]
        if not isinstance(issues, list) or len(issues) > 64:
            raise ContractRejected
        previous: tuple[str, str, str] | None = None
        for raw_issue in issues:
            issue = _exact_keys(raw_issue, ISSUE_KEYS)
            if issue["code"] not in allowed_codes or issue["component"] not in COMPONENTS:
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
        issue_sets[array_name] = {
            (issue["code"], issue["component"], issue["agent"])
            for issue in issues
        }

    errors = issue_sets["errors"]
    warnings = issue_sets["warnings"]
    truncation_reported = ("result_truncated", "diagnostic", None) in errors
    if truncation_reported and (
        len(top["errors"]) != MAX_ISSUES
        and len(top["warnings"]) != MAX_ISSUES
    ):
        raise ContractRejected
    errors_truncated = truncation_reported and len(top["errors"]) == MAX_ISSUES
    warnings_truncated = truncation_reported and len(top["warnings"]) == MAX_ISSUES
    missing_session = any(item["state"] == "missing" for item in sessions)
    session_missing_reported = ("session_missing", "tmux", None) in errors
    if session_missing_reported and not missing_session:
        raise ContractRejected
    if missing_session and not session_missing_reported and not errors_truncated:
        raise ContractRejected
    unknown_agents = any(item["unknown_agent_count"] for item in sessions)
    unknown_agents_reported = ("unknown_agent_observed", "tmux", None) in warnings
    if unknown_agents_reported and not unknown_agents:
        raise ContractRejected
    if unknown_agents and not unknown_agents_reported and not warnings_truncated:
        raise ContractRejected

    supervisor_state = processes["watcher_supervisor_state"]
    global_process_errors = {
        item for item in errors if item[1] == "process" and item[2] is None
    }
    if supervisor_state in ("healthy", "missing"):
        if global_process_errors:
            raise ContractRejected
    elif supervisor_state == "duplicate":
        if global_process_errors:
            if global_process_errors != {("duplicate_process", "process", None)}:
                raise ContractRejected
        elif not errors_truncated:
            raise ContractRejected
    elif global_process_errors:
        if any(
            code not in ("command_failed", "command_output_limited", "command_timeout")
            for code, _component, _agent in global_process_errors
        ):
            raise ContractRejected
    elif not errors_truncated:
        raise ContractRejected

    for agent in validated_agents:
        agent_id = agent["id"]
        pane_errors = {
            item for item in errors
            if item[1] == "tmux" and item[2] == agent_id
        }
        if agent["pane_state"] == "dead":
            expected_pane_errors = {("pane_dead", "tmux", agent_id)}
            if pane_errors:
                if pane_errors != expected_pane_errors:
                    raise ContractRejected
            elif not errors_truncated:
                raise ContractRejected
        elif agent["pane_state"] == "error":
            if agent["session"] is None:
                if agent["cli"] != "unknown":
                    raise ContractRejected
                expected_pane_errors = {
                    ("duplicate_agent_pane", "tmux", agent_id)
                }
            else:
                if agent["session"] == EXPECTED_SESSION[agent_id]:
                    raise ContractRejected
                expected_pane_errors = {
                    ("agent_session_mismatch", "tmux", agent_id)
                }
            if pane_errors:
                if pane_errors != expected_pane_errors:
                    raise ContractRejected
            elif not errors_truncated:
                raise ContractRejected
        elif pane_errors.intersection({
            ("pane_dead", "tmux", agent_id),
            ("duplicate_agent_pane", "tmux", agent_id),
            ("agent_session_mismatch", "tmux", agent_id),
        }):
            raise ContractRejected

        watcher_state = agent["watcher_state"]
        process_errors = {
            item for item in errors
            if item[1] == "process" and item[2] == agent_id
        }
        if watcher_state in ("healthy", "not_observed"):
            if process_errors:
                raise ContractRejected
        elif watcher_state == "missing":
            if process_errors:
                if process_errors != {("watcher_missing", "process", agent_id)}:
                    raise ContractRejected
            elif not errors_truncated:
                raise ContractRejected
        elif watcher_state == "duplicate":
            if process_errors:
                if process_errors != {("duplicate_process", "process", agent_id)}:
                    raise ContractRejected
            elif not errors_truncated:
                raise ContractRejected
        elif process_errors:
            if any(
                code not in ("command_failed", "command_output_limited", "command_timeout")
                for code, _component, _agent in process_errors
            ):
                raise ContractRejected
        elif not errors_truncated:
            raise ContractRejected

        if (
            agent["observed"]
            and agent["pane_state"] != "error"
            and agent["cli"] == "unknown"
            and ("unknown_cli_observed", "tmux", agent_id) not in warnings
            and not warnings_truncated
        ):
            raise ContractRejected

    repository_complete = (
        repository["branch_class"] != "invalid"
        and repository["head"] is not None
        and repository["dirty"] is not None
        and repository["tracked_changes"] is not None
        and repository["untracked_changes"] is not None
    )
    repository_errors = any(item[1] == "repository" for item in errors)
    repository_available = repository_complete and not repository_errors
    if (
        not repository_available
        and not repository_errors
        and not errors_truncated
    ):
        raise ContractRejected
    if top["overall"] != _expected_overall(
        top, repository_available=repository_available
    ):
        raise ContractRejected
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

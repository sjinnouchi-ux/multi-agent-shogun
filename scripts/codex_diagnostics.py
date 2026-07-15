#!/usr/bin/python3 -I
from __future__ import annotations

import datetime as dt
import errno
import hashlib
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

SCHEMA_VERSION = 1
TOOL_VERSION = "1.0.0"
DEPLOYMENT = "user_local_snapshot"
SNAPSHOT_PATH = Path("/home/jinnouchi/.local/libexec/shogun-codex-diagnostics")
MAX_SOURCE_BYTES = 1_048_576
MAX_ISSUES = 64

AGENT_IDS = (
    "shogun", "karo", "ashigaru1", "ashigaru2", "ashigaru3",
    "ashigaru4", "ashigaru5", "ashigaru6", "ashigaru7",
    "gunshi", "oometsuke",
)
SESSION_NAMES = ("shogun", "multiagent")
CLI_NAMES = (
    "claude", "codex", "copilot", "kimi", "opencode",
    "cursor", "antigravity", "unknown",
)
COMPONENTS = ("repository", "tmux", "process", "source", "log", "diagnostic")
ERROR_CODES = (
    "argument_rejected", "agent_session_mismatch", "boundary_rejected",
    "canonical_remote_missing", "command_failed", "command_output_limited",
    "command_timeout", "diagnostic_process_failed",
    "diagnostic_provenance_untrusted", "duplicate_agent_pane",
    "duplicate_process", "internal_error", "pane_dead",
    "required_source_missing", "result_truncated", "session_missing",
    "source_rejected", "unknown_agent_observed", "unknown_cli_observed",
    "watcher_missing",
)

FALLBACK_INTERNAL_ERROR = (
    b'{"schema_version":1,"generated_at":null,"ok":false,'
    b'"overall":"unavailable","tool":{"version":"1.0.0",'
    b'"deployment":"user_local_snapshot","source_sha256":null},'
    b'"repository":null,"sessions":[],"processes":null,'
    b'"global_sources":{},"agents":[],"errors":[{"code":'
    b'"internal_error","component":"diagnostic","agent":null}],'
    b'"warnings":[]}'
)


class ArgumentRejected(Exception):
    pass


class BoundaryRejected(Exception):
    def __init__(self, code: str = "boundary_rejected") -> None:
        self.code = code if code in ERROR_CODES else "boundary_rejected"


class InternalFailure(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    component: str
    agent: str | None = None


@dataclass(frozen=True, slots=True)
class CommandResult:
    status: str
    returncode: int | None
    stdout: bytes


def parse_argv(argv: Sequence[str]) -> None:
    if tuple(argv) != ("summary",):
        raise ArgumentRejected


def _source_stat_key(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        stat.S_IMODE(value.st_mode),
    )


def calculate_source_sha256(path: Path | None = None) -> str:
    if path is None:
        executing = Path(os.path.abspath(__file__))
        if executing != SNAPSHOT_PATH:
            raise InternalFailure
        path = SNAPSHOT_PATH
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise InternalFailure
    fd = -1
    try:
        fd = os.open(os.fspath(path), flags | nofollow)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise InternalFailure
        if stat.S_IMODE(before.st_mode) != 0o555:
            raise InternalFailure
        if before.st_size > MAX_SOURCE_BYTES:
            raise InternalFailure
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(fd, min(65_536, MAX_SOURCE_BYTES + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_SOURCE_BYTES:
                raise InternalFailure
            digest.update(chunk)
        after = os.fstat(fd)
        if _source_stat_key(before) != _source_stat_key(after) or total != before.st_size:
            raise InternalFailure
        return digest.hexdigest()
    except (OSError, ValueError) as exc:
        raise InternalFailure from None
    finally:
        if fd >= 0:
            os.close(fd)


def _timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def build_failure_document(code: str) -> dict[str, object]:
    safe_code = code if code in ERROR_CODES else "internal_error"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _timestamp(),
        "ok": False,
        "overall": "unavailable",
        "tool": {
            "version": TOOL_VERSION,
            "deployment": DEPLOYMENT,
            "source_sha256": None,
        },
        "repository": None,
        "sessions": [],
        "processes": None,
        "global_sources": {},
        "agents": [],
        "errors": [{"code": safe_code, "component": "diagnostic", "agent": None}],
        "warnings": [],
    }


def _issue_json(issue: Issue) -> dict[str, object]:
    return {"code": issue.code, "component": issue.component, "agent": issue.agent}


def normalize_issues(
    errors: Iterable[Issue], warnings: Iterable[Issue]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    def one(values: Iterable[Issue]) -> tuple[list[dict[str, object]], bool]:
        unique = {
            (item.code, item.component, item.agent)
            for item in values
            if item.code in ERROR_CODES
            and item.component in COMPONENTS
            and (item.agent is None or item.agent in AGENT_IDS)
        }
        ordered = sorted(unique, key=lambda item: (item[0], item[1], item[2] or ""))
        truncated = len(ordered) > MAX_ISSUES
        ordered = ordered[:MAX_ISSUES]
        return [_issue_json(Issue(*item)) for item in ordered], truncated

    error_values, error_truncated = one(errors)
    warning_values, warning_truncated = one(warnings)
    if error_truncated or warning_truncated:
        marker = _issue_json(Issue("result_truncated", "diagnostic", None))
        error_values = [item for item in error_values if item != marker][: MAX_ISSUES - 1]
        error_values.append(marker)
        error_values.sort(key=lambda item: (
            item["code"], item["component"], item["agent"] or ""
        ))
    return error_values, warning_values


def render_document(document: dict[str, object]) -> bytes:
    return json.dumps(
        document, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).encode("ascii")


def emit_bytes(payload: bytes, fd: int = 1) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise InternalFailure
        view = view[written:]


def run_cli(argv: Sequence[str], collector) -> tuple[int, dict[str, object]]:
    try:
        parse_argv(argv)
    except ArgumentRejected:
        return 2, build_failure_document("argument_rejected")
    try:
        source_hash = calculate_source_sha256()
        return 0, collector(source_hash)
    except BoundaryRejected as exc:
        return 2, build_failure_document(exc.code)
    except BaseException:
        return 3, build_failure_document("internal_error")


MAX_COMMAND_BYTES = 65_536
MAX_COMMAND_RECORDS = 128
COMMAND_TIMEOUT_SECONDS = 2.0
OVERALL_TIMEOUT_SECONDS = 10.0
ALLOWED_EXECUTABLES = frozenset(("/usr/bin/git", "/usr/bin/tmux", "/usr/bin/pgrep"))
SAFE_ENV = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
    "HOME": "/nonexistent",
    "XDG_CONFIG_HOME": "/nonexistent",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_PAGER": "cat",
}


@dataclass(slots=True)
class _StreamBudget:
    max_bytes: int = MAX_COMMAND_BYTES
    max_records: int = MAX_COMMAND_RECORDS
    data: bytearray = field(default_factory=bytearray)
    limited: bool = False

    def feed(self, chunk: bytes) -> bool:
        if self.limited:
            return True
        remaining_probe = self.max_bytes + 1 - len(self.data)
        if remaining_probe > 0:
            self.data.extend(chunk[:remaining_probe])
        delimiters = self.data.count(b"\n") + self.data.count(b"\0")
        terminated = self.data.endswith((b"\n", b"\0"))
        records = delimiters + (1 if self.data and not terminated else 0)
        self.limited = len(self.data) > self.max_bytes or records > self.max_records
        return self.limited


def _remaining(deadline: float, monotonic: Callable[[], float]) -> float:
    return max(0.0, deadline - monotonic())


def _terminate_and_reap(
    process: subprocess.Popen[bytes],
    *,
    deadline: float,
    monotonic: Callable[[], float],
) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    remaining = _remaining(deadline, monotonic)
    if remaining <= 0:
        try:
            process.poll()
        except OSError:
            pass
        return
    try:
        process.wait(timeout=min(0.1, remaining))
    except (OSError, subprocess.TimeoutExpired):
        pass


def drain_process(
    process: subprocess.Popen[bytes],
    *,
    command_deadline: float,
    overall_deadline: float,
    monotonic: Callable[[], float],
) -> CommandResult:
    deadline = min(command_deadline, overall_deadline)
    stdout_budget = _StreamBudget()
    stderr_budget = _StreamBudget()
    selector = selectors.DefaultSelector()
    try:
        if process.stdout is None or process.stderr is None:
            _terminate_and_reap(process, deadline=deadline, monotonic=monotonic)
            return CommandResult("failed", None, b"")
        os.set_blocking(process.stdout.fileno(), False)
        os.set_blocking(process.stderr.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ, stdout_budget)
        selector.register(process.stderr, selectors.EVENT_READ, stderr_budget)
        while selector.get_map():
            remaining = _remaining(deadline, monotonic)
            if remaining <= 0:
                _terminate_and_reap(process, deadline=deadline, monotonic=monotonic)
                return CommandResult("timeout", None, b"")
            events = selector.select(timeout=min(remaining, 0.05))
            for key, _ in events:
                stream = key.fileobj
                budget = key.data
                try:
                    chunk = os.read(stream.fileno(), 4_096)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(stream)
                    continue
                if budget.feed(chunk):
                    _terminate_and_reap(
                        process,
                        deadline=deadline,
                        monotonic=monotonic,
                    )
                    return CommandResult("output_limited", None, b"")
        remaining = _remaining(deadline, monotonic)
        if remaining <= 0:
            _terminate_and_reap(process, deadline=deadline, monotonic=monotonic)
            return CommandResult("timeout", None, b"")
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            _terminate_and_reap(process, deadline=deadline, monotonic=monotonic)
            return CommandResult("timeout", None, b"")
        status_name = "ok" if returncode == 0 else "nonzero"
        return CommandResult(status_name, returncode, bytes(stdout_budget.data))
    except (OSError, ValueError):
        _terminate_and_reap(process, deadline=deadline, monotonic=monotonic)
        return CommandResult("failed", None, b"")
    finally:
        selector.close()
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


class CommandRunner:
    def __init__(
        self,
        *,
        popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        drain: Callable[..., CommandResult] = drain_process,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._popen_factory = popen_factory
        self._drain = drain
        self._monotonic = monotonic
        self._overall_deadline = monotonic() + OVERALL_TIMEOUT_SECONDS

    def __call__(self, argv: tuple[str, ...]) -> CommandResult:
        now = self._monotonic()
        if not argv or argv[0] not in ALLOWED_EXECUTABLES:
            return CommandResult("failed", None, b"")
        if now >= self._overall_deadline:
            return CommandResult("timeout", None, b"")
        try:
            process = self._popen_factory(
                argv,
                shell=False,
                cwd=".",
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=SAFE_ENV,
                start_new_session=True,
            )
        except (OSError, ValueError):
            return CommandResult("failed", None, b"")
        return self._drain(
            process,
            command_deadline=now + COMMAND_TIMEOUT_SECONDS,
            overall_deadline=self._overall_deadline,
            monotonic=self._monotonic,
        )


def _command_issue(result: CommandResult, component: str) -> Issue:
    code = {
        "timeout": "command_timeout",
        "output_limited": "command_output_limited",
    }.get(result.status, "command_failed")
    return Issue(code, component, None)


SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]+$")
SOURCE_KEYS = ("inbox", "task", "report", "handoff_status", "watcher_log")


class SourceMissing(Exception):
    pass


class SourceRejected(Exception):
    pass


class SourceIOError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SourceSpec:
    key: str
    parts: tuple[str, ...]
    applicability: str


@dataclass(frozen=True, slots=True)
class SourceCollection:
    global_sources: dict[str, dict[str, object]]
    agent_sources: dict[str, dict[str, dict[str, object]]]
    errors: tuple[Issue, ...]
    warnings: tuple[Issue, ...]


def open_runtime_root() -> int:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise InternalFailure
    try:
        return os.open(".", flags | nofollow)
    except OSError:
        raise InternalFailure from None


def _validate_parts(parts: tuple[str, ...]) -> None:
    if not parts:
        raise SourceRejected
    for part in parts:
        if part in ("", ".", "..") or "/" in part or "\\" in part:
            raise SourceRejected
        if SAFE_COMPONENT.fullmatch(part) is None:
            raise SourceRejected


def open_regular_beneath(
    root_fd: int, parts: tuple[str, ...], *, readable: bool
) -> tuple[int, os.stat_result]:
    _validate_parts(parts)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    path_only = getattr(os, "O_PATH", None)
    if nofollow is None or path_only is None:
        raise SourceRejected
    current = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = os.open(
                part,
                path_only | os.O_DIRECTORY | os.O_CLOEXEC | nofollow,
                dir_fd=current,
            )
            os.close(current)
            current = next_fd
        leaf_flags = os.O_CLOEXEC | nofollow
        if readable:
            leaf_flags |= os.O_RDONLY | os.O_NONBLOCK
        else:
            leaf_flags |= path_only
        leaf = os.open(parts[-1], leaf_flags, dir_fd=current)
        metadata = os.fstat(leaf)
        if not stat.S_ISREG(metadata.st_mode):
            os.close(leaf)
            raise SourceRejected
        return leaf, metadata
    except FileNotFoundError:
        raise SourceMissing from None
    except SourceRejected:
        raise
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR, errno.EINVAL):
            raise SourceRejected from None
        raise SourceIOError from None
    finally:
        os.close(current)


def size_class(size: int) -> str:
    if size == 0:
        return "empty"
    if size <= 65_536:
        return "small"
    if size <= 1_048_576:
        return "medium"
    return "large"


def rfc3339_seconds(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")


def _source_value(applicability: str, state: str, metadata=None) -> dict[str, object]:
    return {
        "applicability": applicability,
        "state": state,
        "modified_at": rfc3339_seconds(metadata.st_mtime) if metadata is not None else None,
        "size_class": size_class(metadata.st_size) if metadata is not None else None,
    }


def collect_source_metadata(
    root_fd: int, spec: SourceSpec, *, agent: str | None
) -> tuple[dict[str, object], tuple[Issue, ...], tuple[Issue, ...]]:
    if spec.applicability == "not_applicable":
        return _source_value("not_applicable", "not_applicable"), (), ()
    try:
        fd, metadata = open_regular_beneath(root_fd, spec.parts, readable=False)
        os.close(fd)
        return _source_value(spec.applicability, "present", metadata), (), ()
    except SourceMissing:
        value = _source_value(spec.applicability, "missing")
        if spec.applicability == "required":
            return value, (Issue("required_source_missing", "source", agent),), ()
        return value, (), ()
    except SourceRejected:
        value = _source_value(spec.applicability, "rejected")
        issue = Issue("source_rejected", "source", agent)
        if spec.applicability == "required":
            return value, (issue,), ()
        return value, (), (issue,)
    except SourceIOError:
        value = _source_value(spec.applicability, "error")
        issue = Issue("command_failed", "source", agent)
        if spec.applicability == "required":
            return value, (issue,), ()
        return value, (), (issue,)


def _agent_specs(agent: str, observed: bool) -> tuple[SourceSpec, ...]:
    required_or_optional = "required" if observed else "optional"
    task_agent = agent not in ("shogun", "karo")
    report_path = ("queue", "reports", f"{agent}_report.yaml") if task_agent else ()
    return (
        SourceSpec("inbox", ("queue", "inbox", f"{agent}.yaml"), required_or_optional),
        SourceSpec(
            "task",
            ("queue", "tasks", f"{agent}.yaml") if task_agent else (),
            required_or_optional if task_agent else "not_applicable",
        ),
        SourceSpec("report", report_path, "optional" if task_agent else "not_applicable"),
        SourceSpec(
            "handoff_status",
            ("status", "handoff_watchdog", f"{agent}.yaml"),
            "optional",
        ),
        SourceSpec(
            "watcher_log",
            ("logs", f"inbox_watcher_{agent}.log"),
            required_or_optional,
        ),
    )


def collect_runtime_sources(
    root_fd: int, observed_agents: frozenset[str]
) -> SourceCollection:
    errors: list[Issue] = []
    warnings: list[Issue] = []
    global_sources: dict[str, dict[str, object]] = {}
    for spec in (
        SourceSpec("command_queue", ("queue", "shogun_to_karo.yaml"), "required"),
        SourceSpec("dashboard", ("dashboard.md",), "optional"),
    ):
        value, found_errors, found_warnings = collect_source_metadata(
            root_fd, spec, agent=None
        )
        global_sources[spec.key] = value
        errors.extend(found_errors)
        warnings.extend(found_warnings)

    agent_sources: dict[str, dict[str, dict[str, object]]] = {}
    for agent in AGENT_IDS:
        values: dict[str, dict[str, object]] = {}
        for spec in _agent_specs(agent, agent in observed_agents):
            value, found_errors, found_warnings = collect_source_metadata(
                root_fd, spec, agent=agent
            )
            values[spec.key] = value
            errors.extend(found_errors)
            warnings.extend(found_warnings)
        agent_sources[agent] = values
    return SourceCollection(global_sources, agent_sources, tuple(errors), tuple(warnings))


LOG_LIMIT = 1_048_576
LOG_MARKERS = {
    "send_keys_failed_attempt": b"send-keys nudge failed",
    "nudge_still_visible": b"nudge text still visible in pane",
    "wakeup_retry_exhausted": b"send-keys failed after",
    "wakeup_success_logged": b"Wake-up sent to",
}


@dataclass(frozen=True, slots=True)
class LogCollection:
    events: dict[str, dict[str, object]]
    errors: tuple[Issue, ...]
    warnings: tuple[Issue, ...]


def _empty_log_events(modified_at: str | None = None) -> dict[str, object]:
    value: dict[str, object] = {
        "window": "tail_1048576_bytes",
        "modified_at": modified_at,
    }
    value.update({key: None for key in LOG_MARKERS})
    value["unclassified_error_candidate"] = None
    return value


def read_bounded_tail(fd: int, before: os.stat_result) -> bytes:
    if not stat.S_ISREG(before.st_mode):
        raise SourceRejected
    offset = max(0, before.st_size - LOG_LIMIT)
    os.lseek(fd, offset, os.SEEK_SET)
    remaining = min(before.st_size, LOG_LIMIT)
    chunks: list[bytes] = []
    while remaining:
        chunk = os.read(fd, min(65_536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    after = os.fstat(fd)
    if _source_stat_key(before) != _source_stat_key(after):
        raise SourceRejected
    result = b"".join(chunks)
    if len(result) != min(before.st_size, LOG_LIMIT):
        raise SourceRejected
    return result


def aggregate_log_tail(tail: bytes, modified_at: str | None) -> dict[str, object]:
    value: dict[str, object] = {
        "window": "tail_1048576_bytes",
        "modified_at": modified_at,
    }
    for code, marker in LOG_MARKERS.items():
        value[code] = tail.count(marker)
    unclassified = 0
    for line in tail.splitlines():
        candidate = b"WARNING:" in line or b"[ERROR]" in line
        known = any(marker in line for marker in LOG_MARKERS.values())
        if candidate and not known:
            unclassified += 1
    value["unclassified_error_candidate"] = unclassified
    return value


def collect_log_aggregates(
    root_fd: int, observed_agents: frozenset[str]
) -> LogCollection:
    events: dict[str, dict[str, object]] = {}
    errors: list[Issue] = []
    warnings: list[Issue] = []
    for agent in AGENT_IDS:
        parts = ("logs", f"inbox_watcher_{agent}.log")
        try:
            fd, metadata = open_regular_beneath(root_fd, parts, readable=True)
            try:
                tail = read_bounded_tail(fd, metadata)
            finally:
                os.close(fd)
            events[agent] = aggregate_log_tail(tail, rfc3339_seconds(metadata.st_mtime))
        except SourceMissing:
            events[agent] = _empty_log_events()
        except SourceRejected:
            events[agent] = _empty_log_events()
            issue = Issue("source_rejected", "log", agent)
            (errors if agent in observed_agents else warnings).append(issue)
        except SourceIOError:
            events[agent] = _empty_log_events()
            issue = Issue("command_failed", "log", agent)
            (errors if agent in observed_agents else warnings).append(issue)
        except OSError:
            events[agent] = _empty_log_events()
            issue = Issue("command_failed", "log", agent)
            (errors if agent in observed_agents else warnings).append(issue)
    return LogCollection(events, tuple(errors), tuple(warnings))


def _tmux_enum_projection(variable: str, values: tuple[str, ...]) -> str:
    return "".join(
        f"#{{?#{{==:#{{{variable}}},{value}}},{value},}}"
        for value in values
    )


TMUX_SESSIONS_ARGV = ("/usr/bin/tmux", "list-sessions", "-F", "#{session_name}")
TMUX_PANES_ARGV = (
    "/usr/bin/tmux", "list-panes", "-a", "-F",
    "|".join((
        _tmux_enum_projection("session_name", SESSION_NAMES),
        "#{pane_dead}",
        _tmux_enum_projection("@agent_id", AGENT_IDS),
        _tmux_enum_projection("@agent_cli", CLI_NAMES),
    )),
)
EXPECTED_SESSION = {
    agent: ("shogun" if agent == "shogun" else "multiagent")
    for agent in AGENT_IDS
}


@dataclass(frozen=True, slots=True)
class PaneObservation:
    observed: bool
    session: str | None
    pane_state: str
    cli: str


@dataclass(frozen=True, slots=True)
class TmuxCollection:
    sessions: tuple[dict[str, object], dict[str, object]]
    observations: dict[str, PaneObservation]
    observed_agents: frozenset[str]
    errors: tuple[Issue, ...]
    warnings: tuple[Issue, ...]


def _empty_observations() -> dict[str, PaneObservation]:
    return {
        agent: PaneObservation(False, None, "not_observed", "unknown")
        for agent in AGENT_IDS
    }


def _session_json(
    name: str,
    state: str,
    panes: int | None,
    dead: int | None,
    unknown: int | None,
) -> dict[str, object]:
    return {
        "name": name,
        "state": state,
        "pane_count": panes,
        "dead_pane_count": dead,
        "unknown_agent_count": unknown,
    }


def collect_tmux(run) -> TmuxCollection:
    errors: list[Issue] = []
    warnings: list[Issue] = []
    sessions_result = run(TMUX_SESSIONS_ARGV)
    present: set[str] = set()
    session_error = False
    if sessions_result.status == "ok":
        present = {
            line.decode("ascii")
            for line in sessions_result.stdout.splitlines()
            if line in {b"shogun", b"multiagent"}
        }
    elif sessions_result.status == "nonzero" and sessions_result.returncode == 1:
        present = set()
    else:
        session_error = True
        errors.append(_command_issue(sessions_result, "tmux"))

    panes_result = run(TMUX_PANES_ARGV)
    rows: dict[str, list[tuple[str, str, str]]] = {
        name: [] for name in SESSION_NAMES
    }
    pane_counts = {name: 0 for name in SESSION_NAMES}
    dead_counts = {name: 0 for name in SESSION_NAMES}
    unknown_counts = {name: 0 for name in SESSION_NAMES}
    pane_error_sessions: set[str] = set()
    if panes_result.status == "ok":
        malformed = False
        for raw_line in panes_result.stdout.splitlines():
            fields = raw_line.split(b"|")
            if len(fields) != 4:
                malformed = True
                continue
            if fields[0] not in {b"shogun", b"multiagent"}:
                continue
            session = fields[0].decode("ascii")
            if fields[1] not in {b"0", b"1"} or session not in present:
                malformed = True
                pane_error_sessions.add(session)
                continue
            pane_counts[session] += 1
            dead = fields[1] == b"1"
            if dead:
                dead_counts[session] += 1
            if fields[2] not in {item.encode() for item in AGENT_IDS}:
                unknown_counts[session] += 1
                warnings.append(Issue("unknown_agent_observed", "tmux", None))
                continue
            agent = fields[2].decode("ascii")
            cli = (
                fields[3].decode("ascii")
                if fields[3] in {item.encode() for item in CLI_NAMES}
                else "unknown"
            )
            if cli == "unknown":
                warnings.append(Issue("unknown_cli_observed", "tmux", agent))
            rows[session].append((agent, "dead" if dead else "alive", cli))
        if malformed:
            pane_error_sessions.update(present)
            errors.append(Issue("command_failed", "tmux", None))
            rows = {name: [] for name in SESSION_NAMES}
            pane_counts = {name: 0 for name in SESSION_NAMES}
            dead_counts = {name: 0 for name in SESSION_NAMES}
            unknown_counts = {name: 0 for name in SESSION_NAMES}
        else:
            empty_present = {name for name in present if pane_counts[name] == 0}
            if empty_present:
                pane_error_sessions.update(empty_present)
                errors.append(Issue("command_failed", "tmux", None))
    elif panes_result.status == "nonzero" and panes_result.returncode == 1:
        if present:
            pane_error_sessions.update(present)
            errors.append(_command_issue(panes_result, "tmux"))
    else:
        pane_error_sessions.update(present)
        errors.append(_command_issue(panes_result, "tmux"))

    sessions: list[dict[str, object]] = []
    for name in SESSION_NAMES:
        if session_error:
            sessions.append(_session_json(name, "error", None, None, None))
        elif name in pane_error_sessions:
            sessions.append(_session_json(name, "error", None, None, None))
        elif name not in present:
            sessions.append(_session_json(name, "missing", 0, 0, 0))
            errors.append(Issue("session_missing", "tmux", None))
        elif pane_counts[name] > 64:
            sessions.append(_session_json(name, "error", None, None, None))
            errors.append(Issue("result_truncated", "tmux", None))
        else:
            sessions.append(_session_json(
                name,
                "present",
                pane_counts[name],
                dead_counts[name],
                unknown_counts[name],
            ))

    by_agent: dict[str, list[tuple[str, str, str]]] = {
        agent: [] for agent in AGENT_IDS
    }
    for session, values in rows.items():
        for agent, pane_state, cli in values:
            by_agent[agent].append((session, pane_state, cli))

    observations = _empty_observations()
    for agent in AGENT_IDS:
        values = by_agent[agent]
        if not values:
            continue
        if len(values) != 1:
            observations[agent] = PaneObservation(True, None, "error", "unknown")
            errors.append(Issue("duplicate_agent_pane", "tmux", agent))
            continue
        session, pane_state, cli = values[0]
        if session != EXPECTED_SESSION[agent]:
            observations[agent] = PaneObservation(True, session, "error", cli)
            errors.append(Issue("agent_session_mismatch", "tmux", agent))
        else:
            observations[agent] = PaneObservation(True, session, pane_state, cli)
            if pane_state == "dead":
                errors.append(Issue("pane_dead", "tmux", agent))
    observed = frozenset(
        agent for agent, value in observations.items() if value.observed
    )
    return TmuxCollection(
        tuple(sessions), observations, observed, tuple(errors), tuple(warnings)
    )


PGREP_SUPERVISOR_ARGV = (
    "/usr/bin/pgrep", "-f", "--",
    r"(^|/)scripts/watcher_supervisor\.sh([[:space:]]|$)",
)
PGREP_AGENT_ARGV = {
    agent: (
        "/usr/bin/pgrep", "-f", "--",
        rf"(^|/)scripts/inbox_watcher\.sh[[:space:]]+{agent}[[:space:]]",
    )
    for agent in AGENT_IDS
}


@dataclass(frozen=True, slots=True)
class ProcessCollection:
    processes: dict[str, object]
    agent_watchers: dict[str, tuple[int | None, str]]
    errors: tuple[Issue, ...]
    warnings: tuple[Issue, ...]


def count_pgrep(result: CommandResult) -> int | None:
    if result.status == "nonzero" and result.returncode == 1:
        return 0
    if result.status != "ok":
        return None
    lines = result.stdout.splitlines()
    if any(not line.isdigit() for line in lines):
        return None
    return len(lines)


def _watcher_state(count: int | None) -> str:
    if count is None:
        return "unknown"
    if count == 0:
        return "missing"
    if count == 1:
        return "healthy"
    return "duplicate"


def collect_processes(
    observed_agents: frozenset[str], run
) -> ProcessCollection:
    errors: list[Issue] = []
    supervisor_result = run(PGREP_SUPERVISOR_ARGV)
    supervisor_count = count_pgrep(supervisor_result)
    supervisor_state = _watcher_state(supervisor_count)
    if supervisor_state == "missing":
        errors.append(Issue("watcher_missing", "process", None))
    elif supervisor_state == "duplicate":
        errors.append(Issue("duplicate_process", "process", None))
    elif supervisor_state == "unknown":
        errors.append(_command_issue(supervisor_result, "process"))

    agent_watchers: dict[str, tuple[int | None, str]] = {}
    for agent in AGENT_IDS:
        if agent not in observed_agents:
            agent_watchers[agent] = (None, "not_observed")
            continue
        result = run(PGREP_AGENT_ARGV[agent])
        count = count_pgrep(result)
        state = _watcher_state(count)
        agent_watchers[agent] = (count, state)
        if state == "missing":
            errors.append(Issue("watcher_missing", "process", agent))
        elif state == "duplicate":
            errors.append(Issue("duplicate_process", "process", agent))
        elif state == "unknown":
            issue = _command_issue(result, "process")
            errors.append(Issue(issue.code, issue.component, agent))
    return ProcessCollection(
        {
            "watcher_supervisor_count": supervisor_count,
            "watcher_supervisor_state": supervisor_state,
        },
        agent_watchers,
        tuple(errors),
        (),
    )


GIT_PREFIX = (
    "/usr/bin/git",
    "-c", "core.fsmonitor=false",
    "-c", "color.ui=false",
    "-c", "core.pager=cat",
)
SAFE_BRANCH = re.compile(rb"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
SAFE_SHA = re.compile(rb"^[0-9a-f]{40}$")
CANONICAL_REMOTE = re.compile(
    rb"^(?:https://github\.com/sjinnouchi-ux/multi-agent-shogun(?:\.git)?|"
    rb"git@github\.com:sjinnouchi-ux/multi-agent-shogun(?:\.git)?)$"
)


@dataclass(frozen=True, slots=True)
class RepositoryCollection:
    value: dict[str, object]
    boundary_accepted: bool
    available: bool
    errors: tuple[Issue, ...]
    warnings: tuple[Issue, ...]


def git_argv(*parts: str) -> tuple[str, ...]:
    return GIT_PREFIX + tuple(parts)


def _single_line(raw: bytes) -> bytes | None:
    if b"\x00" in raw or raw.count(b"\n") > 1:
        return None
    return raw.rstrip(b"\n")


def classify_branch(raw: bytes) -> str:
    value = _single_line(raw)
    if value == b"":
        return "detached"
    if value is None or not SAFE_BRANCH.fullmatch(value):
        return "invalid"
    if b".." in value or value.endswith(b".lock") or value.startswith(b"/") or value.endswith(b"/"):
        return "invalid"
    if value == b"main":
        return "main"
    if value.startswith(b"shogun/"):
        return "shogun_namespace"
    if value.startswith(b"codex/"):
        return "codex_namespace"
    return "other"


def is_canonical_remote(raw: bytes) -> bool:
    for line in raw.splitlines():
        fields = line.split(b"\t")
        if len(fields) != 2 or not fields[0]:
            continue
        marker = b" (fetch)"
        if not fields[1].endswith(marker):
            continue
        url = fields[1][:-len(marker)]
        if url and CANONICAL_REMOTE.fullmatch(url):
            return True
    return False


def _malformed_repository_result() -> tuple[None, Issue]:
    return None, Issue("command_failed", "repository", None)


def _porcelain_v1_z_count(
    result: CommandResult,
) -> tuple[int | None, Issue | None]:
    if result.status != "ok":
        return None, _command_issue(result, "repository")
    if not result.stdout:
        return 0, None
    if not result.stdout.endswith(b"\x00"):
        return _malformed_repository_result()

    fields = result.stdout.split(b"\x00")[:-1]
    count = 0
    index = 0
    valid_status = b" MTADRCU"
    while index < len(fields):
        record = fields[index]
        if (
            len(record) < 4
            or record[2:3] != b" "
            or record[0] not in valid_status
            or record[1] not in valid_status
            or record[:2] == b"  "
        ):
            return _malformed_repository_result()
        index += 1
        if record[0:1] in (b"R", b"C") or record[1:2] in (b"R", b"C"):
            if index >= len(fields) or not fields[index]:
                return _malformed_repository_result()
            index += 1
        count += 1
        if count > 10_000:
            return None, Issue("result_truncated", "repository", None)
    return count, None


def _ls_files_z_count(
    result: CommandResult,
) -> tuple[int | None, Issue | None]:
    if result.status != "ok":
        return None, _command_issue(result, "repository")
    if not result.stdout:
        return 0, None
    if not result.stdout.endswith(b"\x00"):
        return _malformed_repository_result()

    records = result.stdout.split(b"\x00")[:-1]
    if not records or any(not record for record in records):
        return _malformed_repository_result()
    count = len(records)
    if count > 10_000:
        return None, Issue("result_truncated", "repository", None)
    return count, None


def collect_repository(run) -> RepositoryCollection:
    top = run(git_argv("rev-parse", "--show-toplevel"))
    if top.status != "ok":
        raise BoundaryRejected("boundary_rejected")
    top_line = _single_line(top.stdout)
    if top_line is None:
        raise BoundaryRejected("boundary_rejected")
    try:
        if not os.path.samefile(os.fsdecode(top_line), "."):
            raise BoundaryRejected("boundary_rejected")
    except OSError:
        raise BoundaryRejected("boundary_rejected") from None

    remote = run(git_argv("remote", "-v"))
    if remote.status != "ok":
        raise BoundaryRejected("boundary_rejected")
    if not is_canonical_remote(remote.stdout):
        raise BoundaryRejected("canonical_remote_missing")

    errors: list[Issue] = []
    branch_result = run(git_argv("symbolic-ref", "--quiet", "--short", "HEAD"))
    if branch_result.status == "ok":
        branch_class = classify_branch(branch_result.stdout)
    elif branch_result.status == "nonzero" and branch_result.returncode == 1:
        branch_class = "detached"
    else:
        branch_class = "invalid"
        errors.append(_command_issue(branch_result, "repository"))

    head_result = run(git_argv("rev-parse", "--verify", "HEAD"))
    head_line = _single_line(head_result.stdout) if head_result.status == "ok" else None
    head = head_line.decode("ascii") if head_line and SAFE_SHA.fullmatch(head_line) else None
    if head is None:
        errors.append(_command_issue(head_result, "repository"))

    tracked, tracked_issue = _porcelain_v1_z_count(
        run(git_argv("status", "--porcelain=v1", "-z", "--untracked-files=no"))
    )
    untracked, untracked_issue = _ls_files_z_count(
        run(git_argv("ls-files", "--others", "--exclude-standard", "-z"))
    )
    for issue in (tracked_issue, untracked_issue):
        if issue is not None:
            errors.append(issue)
    dirty = None if tracked is None or untracked is None else bool(tracked or untracked)
    available = not errors and branch_class != "invalid" and head is not None
    return RepositoryCollection(
        value={
            "branch_class": branch_class,
            "head": head,
            "dirty": dirty,
            "tracked_changes": tracked,
            "untracked_changes": untracked,
            "canonical_remote_present": True,
        },
        boundary_accepted=True,
        available=available,
        errors=tuple(errors),
        warnings=(),
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
SESSION_KEYS = (
    "name", "state", "pane_count", "dead_pane_count", "unknown_agent_count",
)
AGENT_KEYS = (
    "id", "observed", "session", "pane_state", "cli", "watcher_count",
    "watcher_state", "sources", "log_events",
)
SOURCE_VALUE_KEYS = ("applicability", "state", "modified_at", "size_class")
LOG_EVENT_KEYS = (
    "window", "modified_at", "send_keys_failed_attempt", "nudge_still_visible",
    "wakeup_retry_exhausted", "wakeup_success_logged",
    "unclassified_error_candidate",
)
ISSUE_KEYS = ("code", "component", "agent")


def calculate_overall(
    repository_available: bool,
    sessions: Sequence[dict[str, object]],
    errors: Sequence[dict[str, object]],
) -> str:
    states = [item["state"] for item in sessions]
    if not repository_available or states == ["missing", "missing"]:
        return "unavailable"
    if errors or "missing" in states or "error" in states:
        return "degraded"
    return "healthy"


def build_success_document(
    source_hash: str,
    repository: RepositoryCollection,
    tmux: TmuxCollection,
    processes: ProcessCollection,
    sources: SourceCollection,
    logs: LogCollection,
) -> dict[str, object]:
    errors, warnings = normalize_issues(
        repository.errors
        + tmux.errors
        + processes.errors
        + sources.errors
        + logs.errors,
        repository.warnings
        + tmux.warnings
        + processes.warnings
        + sources.warnings
        + logs.warnings,
    )
    agents: list[dict[str, object]] = []
    for agent in AGENT_IDS:
        observation = tmux.observations[agent]
        watcher_count, watcher_state = processes.agent_watchers[agent]
        agents.append(
            {
                "id": agent,
                "observed": observation.observed,
                "session": observation.session,
                "pane_state": observation.pane_state,
                "cli": observation.cli,
                "watcher_count": watcher_count,
                "watcher_state": watcher_state,
                "sources": sources.agent_sources[agent],
                "log_events": logs.events[agent],
            }
        )
    document: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _timestamp(),
        "ok": True,
        "overall": calculate_overall(repository.available, tmux.sessions, errors),
        "tool": {
            "version": TOOL_VERSION,
            "deployment": DEPLOYMENT,
            "source_sha256": source_hash,
        },
        "repository": repository.value,
        "sessions": list(tmux.sessions),
        "processes": processes.processes,
        "global_sources": sources.global_sources,
        "agents": agents,
        "errors": errors,
        "warnings": warnings,
    }
    return document


def _exact_keys(value: object, keys: tuple[str, ...]) -> dict[str, object]:
    if not isinstance(value, dict) or tuple(value) != keys:
        raise InternalFailure
    return value


def _nullable_count(value: object, maximum: int | None = None) -> None:
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise InternalFailure
    if maximum is not None and value > maximum:
        raise InternalFailure


def _nullable_timestamp(value: object) -> None:
    if value is None:
        return
    if (
        not isinstance(value, str)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value) is None
    ):
        raise InternalFailure
    try:
        dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise InternalFailure from exc


def _validate_source_value(raw: object) -> None:
    value = _exact_keys(raw, SOURCE_VALUE_KEYS)
    if value["state"] not in (
        "present", "missing", "rejected", "not_applicable", "error"
    ):
        raise InternalFailure
    if value["applicability"] not in ("required", "optional", "not_applicable"):
        raise InternalFailure
    _nullable_timestamp(value["modified_at"])
    if value["size_class"] not in ("empty", "small", "medium", "large", None):
        raise InternalFailure
    if value["state"] == "not_applicable" and (
        value["applicability"] != "not_applicable"
        or value["modified_at"] is not None
        or value["size_class"] is not None
    ):
        raise InternalFailure


def validate_document(document: dict[str, object]) -> None:
    top = _exact_keys(document, TOP_LEVEL_KEYS)
    if (
        type(top["schema_version"]) is not int
        or top["schema_version"] != SCHEMA_VERSION
        or top["ok"] is not True
    ):
        raise InternalFailure
    if not isinstance(top["generated_at"], str):
        raise InternalFailure
    _nullable_timestamp(top["generated_at"])
    if top["overall"] not in ("healthy", "degraded", "unavailable"):
        raise InternalFailure
    tool = _exact_keys(top["tool"], TOOL_KEYS)
    if tool["version"] != TOOL_VERSION or tool["deployment"] != DEPLOYMENT:
        raise InternalFailure
    if not isinstance(tool["source_sha256"], str) or re.fullmatch(
        r"[0-9a-f]{64}", tool["source_sha256"]
    ) is None:
        raise InternalFailure
    repository = _exact_keys(top["repository"], REPOSITORY_KEYS)
    if repository["branch_class"] not in (
        "main", "shogun_namespace", "codex_namespace", "other", "detached", "invalid"
    ):
        raise InternalFailure
    if repository["head"] is not None and (
        not isinstance(repository["head"], str)
        or re.fullmatch(r"[0-9a-f]{40}", repository["head"]) is None
    ):
        raise InternalFailure
    if repository["dirty"] is not None and not isinstance(
        repository["dirty"], bool
    ):
        raise InternalFailure
    _nullable_count(repository["tracked_changes"], 10_000)
    _nullable_count(repository["untracked_changes"], 10_000)
    if repository["canonical_remote_present"] is not None and not isinstance(
        repository["canonical_remote_present"], bool
    ):
        raise InternalFailure

    sessions = top["sessions"]
    agents = top["agents"]
    if not isinstance(sessions, list) or len(sessions) != 2:
        raise InternalFailure
    if not isinstance(agents, list) or len(agents) != 11:
        raise InternalFailure
    for expected, raw in zip(SESSION_NAMES, sessions):
        item = _exact_keys(raw, SESSION_KEYS)
        if item["name"] != expected or item["state"] not in (
            "present", "missing", "error"
        ):
            raise InternalFailure
        for key in ("pane_count", "dead_pane_count", "unknown_agent_count"):
            _nullable_count(item[key], 64)
    processes_value = _exact_keys(
        top["processes"],
        ("watcher_supervisor_count", "watcher_supervisor_state"),
    )
    _nullable_count(processes_value["watcher_supervisor_count"])
    if processes_value["watcher_supervisor_state"] not in (
        "healthy", "missing", "duplicate", "unknown"
    ):
        raise InternalFailure

    global_sources = _exact_keys(
        top["global_sources"], ("command_queue", "dashboard")
    )
    for raw in global_sources.values():
        _validate_source_value(raw)
    for expected, raw in zip(AGENT_IDS, agents):
        item = _exact_keys(raw, AGENT_KEYS)
        if item["id"] != expected or not isinstance(item["observed"], bool):
            raise InternalFailure
        if item["session"] not in (*SESSION_NAMES, None):
            raise InternalFailure
        if item["pane_state"] not in ("alive", "dead", "not_observed", "error"):
            raise InternalFailure
        if item["cli"] not in CLI_NAMES:
            raise InternalFailure
        _nullable_count(item["watcher_count"])
        if item["watcher_state"] not in (
            "healthy", "missing", "duplicate", "unknown", "not_observed"
        ):
            raise InternalFailure
        sources_value = _exact_keys(item["sources"], SOURCE_KEYS)
        for raw_source in sources_value.values():
            _validate_source_value(raw_source)
        events = _exact_keys(item["log_events"], LOG_EVENT_KEYS)
        if events["window"] != "tail_1048576_bytes":
            raise InternalFailure
        _nullable_timestamp(events["modified_at"])
        for key in LOG_EVENT_KEYS[2:]:
            _nullable_count(events[key])
    for array_name in ("errors", "warnings"):
        values = top[array_name]
        if not isinstance(values, list) or len(values) > 64:
            raise InternalFailure
        previous: tuple[str, str, str] | None = None
        for raw in values:
            issue = _exact_keys(raw, ISSUE_KEYS)
            if issue["code"] not in ERROR_CODES or issue["component"] not in COMPONENTS:
                raise InternalFailure
            if issue["agent"] not in (*AGENT_IDS, None):
                raise InternalFailure
            current = (
                issue["code"],
                issue["component"],
                issue["agent"] or "",
            )
            if previous is not None and current <= previous:
                raise InternalFailure
            previous = current


def collect_summary(
    run,
    *,
    source_hash: str,
    open_root: Callable[[], int] = open_runtime_root,
) -> dict[str, object]:
    repository = collect_repository(run)
    tmux = collect_tmux(run)
    processes = collect_processes(tmux.observed_agents, run)
    root_fd = open_root()
    try:
        sources = collect_runtime_sources(root_fd, tmux.observed_agents)
        logs = collect_log_aggregates(root_fd, tmux.observed_agents)
    finally:
        os.close(root_fd)
    document = build_success_document(
        source_hash, repository, tmux, processes, sources, logs
    )
    validate_document(document)
    return document


def safe_render_document(
    document: dict[str, object], intended_code: int
) -> tuple[bytes, int]:
    try:
        if document.get("ok") is True:
            validate_document(document)
        return render_document(document), intended_code
    except BaseException:
        return FALLBACK_INTERNAL_ERROR, 3


TERMINATION_SIGNALS = (signal.SIGINT, signal.SIGTERM)
_OUTPUT_STARTED = False
_FALLBACK_EMITTING = False


def _signal_before_output(_signum, _frame) -> None:
    global _FALLBACK_EMITTING
    try:
        signal.pthread_sigmask(signal.SIG_BLOCK, TERMINATION_SIGNALS)
    except BaseException:
        os._exit(3)
    if _OUTPUT_STARTED:
        os._exit(3)
    if _FALLBACK_EMITTING:
        return
    _FALLBACK_EMITTING = True
    try:
        emit_bytes(FALLBACK_INTERNAL_ERROR)
    finally:
        os._exit(3)


def _install_signal_handlers() -> None:
    global _FALLBACK_EMITTING, _OUTPUT_STARTED
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, TERMINATION_SIGNALS)
    try:
        _OUTPUT_STARTED = False
        _FALLBACK_EMITTING = False
        for signum in TERMINATION_SIGNALS:
            signal.signal(signum, _signal_before_output)
    except BaseException:
        _signal_before_output(0, None)
        os._exit(3)
    signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def _emit_final(payload: bytes) -> bool:
    global _OUTPUT_STARTED
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, TERMINATION_SIGNALS)
    pending = False
    try:
        _OUTPUT_STARTED = True
        pending_signals = signal.sigpending()
        pending = any(signum in pending_signals for signum in TERMINATION_SIGNALS)
        emit_bytes(FALLBACK_INTERNAL_ERROR if pending else payload)
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    return pending


def main(argv: Sequence[str] | None = None) -> int:
    try:
        _install_signal_handlers()
        runner = CommandRunner()
        code, document = run_cli(
            tuple(sys.argv[1:] if argv is None else argv),
            lambda source_hash: collect_summary(runner, source_hash=source_hash),
        )
        payload, code = safe_render_document(document, code)
    except BaseException:
        payload, code = FALLBACK_INTERNAL_ERROR, 3
    try:
        if _emit_final(payload):
            code = 3
    except BaseException:
        return 3
    return code


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/python3 -I
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import selectors
import signal
import stat
import subprocess
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
    pass


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
    except BoundaryRejected:
        return 2, build_failure_document("boundary_rejected")
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

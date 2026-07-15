# Codex Read-Only Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Codex DesktopがShogunの制御系へ結合せず、固定snapshot一つからallowlist済みmetadataと固定log集計だけを安全なJSONで診断できるようにする。

**Architecture:** Shogun repositoryにはself-containedなPython CLIとtest/docsだけを追加し、既存watcher、queue writer、launcher、agent status、WebUI、runtime schemaは変更しない。review済みmain sourceをrepo外のmode `0555` snapshotへ明示配置し、各実行直前にGitHub mainの唯一のactive deployment recordと`tool.source_sha256`を照合する。Workspace policyとhost `AGENTS.md`はdeployment記録がmainへ入った後に別PR・marker付きblockとして有効化する。

**Tech Stack:** Python 3 standard library、`unittest`、Bats、GNU Make、Git/GitHub、tmux、PowerShell、WSL2 Ubuntu、Gitleaks v8.30.1。

## Global Constraints

- 実装開始時にオンライン `workspace/main/codex/CODEX_DESKTOP_STARTUP.md`、`workspace/main/PROJECTS.md`、対象repositoryのdefault branch、`AGENTS.md`、Primary Docsを再取得し、Canonical Entryを再確認する。
- 実装worktreeは`superpowers:using-git-worktrees`で作る。live path `/home/jinnouchi/multi-agent-shogun`、tmux session、queue/report/log本文を実装workspaceとして使わない。
- Canonical repoは`https://github.com/sjinnouchi-ux/multi-agent-shogun`、baseは実行時の最新`origin/main`、実装branchは`codex/add-readonly-diagnostics`である。
- production sourceは`scripts/codex_diagnostics.py`一fileで、repository内module、plugin、base class、dynamic registryをimportしない。
- Python runtimeは3.10以上とし、deployment preflightで不足をskipせず拒否する。
- production executableは`/usr/bin/git`、`/usr/bin/tmux`、`/usr/bin/pgrep`だけ、`shell=False`、command timeout 2秒、overall deadline 10秒、各stream 65,536 byte・128 recordである。
- production CLIは`summary`だけを受理する。追加argument、別subcommand、environment overrideはcollector起動前にexit 2とする。
- stdoutはASCII JSON一件、stderrは空。controlled failureはexit 2または3で固定JSON、serialization failureは固定literal bytesを返す。
- pane本文、queue/task/report/status本文、log行、秘密値、OAuth/token/認証JSON、path、PID、command line、remote名/URL、正確なfile size、runtime data hashを出力しない。
- source hashだけは固定snapshot pathを`O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK`で開き、regular file、mode `0555`、最大1,048,576 byte、read前後metadata一致を検証して出力できる。
- runtime source traversalはdir-FDと`O_NOFOLLOW`だけを使う。`Path.resolve()` fallback、glob、任意path、任意regex、任意session/socketをproductionへ追加しない。
- fixed agentsは`shogun, karo, ashigaru1..7, gunshi, oometsuke`、sessionsは`shogun, multiagent`、CLI enumは`claude, codex, copilot, kimi, opencode, cursor, antigravity, unknown`である。
- 1足軽編成を正常に扱い、未観測agentだけを理由に`degraded`にしない。
- local manifest/cache、`sudo`、system directory、`/mnt/c`経由のdeploymentを使わない。
- existing EOL-only instruction diffsをstageしない。各commitは列挙したfileだけをpathspecでstageする。
- Shogun source PR、post-deployment work-log PR、Workspace policy PRを分離する。各mergeとlive deploymentの前にユーザーcheckpointを置く。
- 完了根拠は実WSL deployment hostで`make test-no-skip`がexit 0、test count > 0、skip 0であること。GitHub CIの既知skip除外は代用しない。
- raw JSON、tmux pane、生queue、生report、生logをwork log、PR、chatへ保存・表示しない。記録するのはexit、count、enum、hash一致、commitだけである。

- Rollback is never automatic: revoke the persistent command permission first, require an explicit user-selected superseded record, and keep policy disabled after restoration.
- `tests/contract/codex_diagnostics_consumer.py` is test/deployment-verification-only; `scripts/rollback_codex_diagnostics_snapshot.py` is offline maintenance-only. Neither is imported into, installed with, or persistently approved as part of the one-file diagnostic production snapshot.

## File Structure

### Shogun source PR

- Create `scripts/codex_diagnostics.py`: fixed CLI、bounded runner、collector、schema、serialization。
- Create `tests/unit/test_codex_diagnostics.py`: pure/unit/security/contract tests。
- Create `tests/unit/test_codex_diagnostics.bats`: unittest、compile、suffix rejection wrapper。
- Create `tests/integration/test_codex_diagnostics_tmux.py`: unique socket tmux integration harness。
- Create `tests/integration/test_codex_diagnostics_tmux.bats`: deployment-host-only wrapper。
- Create `docs/codex-diagnostics.md`: operator contract、output、deployment、rollback。
- Create `docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics-work-log.md`: fixed marked deployment JSON and sanitized evidence。
- Modify `docs/github-boundary-operation.md`: trusted-gate限定例外とfail-closed provenance rule。
- Modify `Makefile`: deployment-host-only`test-no-skip` target。既存`test`の意味は変えない。
- Modify `.gitignore`: 上記exact filesだけをallowlist。

- Create `tests/contract/__init__.py`: consumer contract package marker.
- Create `tests/contract/codex_diagnostics_consumer.py`: executable fail-closed consumer contract.
- Create `tests/contract/test_codex_diagnostics_consumer.py`: hostile registry/output/no-fallback fixtures.
- Create `scripts/rollback_codex_diagnostics_snapshot.py`: hash-gated atomic snapshot rollback primitive.
- Create `tests/unit/test_rollback_codex_diagnostics_snapshot.py`: pre/post-commit and TOCTOU rollback tests.

### Workspace policy PR（Shogun deployment record main反映後）

- Modify `codex/CODEX_DESKTOP_STARTUP.md`: marker付き限定例外。
- Modify `codex/CODEX_DESKTOP_CUSTOM_INSTRUCTIONS.md`: `Paste This Text`内の同一blockとverification。
- Modify `codex/work_log.md`: sanitized enablement evidence。

### Host-only state（Workspace main反映後）

- Modify `C:\Users\jinnouchi\.codex\AGENTS.md`: marker blockだけ。marker外bytesとhost固有の厳しい規則は保持する。
- Install `/home/jinnouchi/.local/libexec/shogun-codex-diagnostics`: reviewed Git blobのmode `0555` snapshot一file。

---

### Task 1: Freeze the CLI, Source-Hash, and Deployment-Record Contracts

**Files:**

- Create: `scripts/codex_diagnostics.py`
- Create: `tests/unit/test_codex_diagnostics.py`
- Create: `docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics-work-log.md`
- Modify: `.gitignore` after the existing Scripts, Docs, and Tests allowlists

**Interfaces:**

- Consumes: no production code; only Python standard library and the approved design spec.
- Produces: `Issue`, `CommandResult`, `parse_argv()`, `calculate_source_sha256()`, `build_failure_document()`, `normalize_issues()`, `render_document()`, `emit_bytes()`, `run_cli()`; later tasks must use these exact names.

- [ ] **Step 1: Add exact allowlist entries before creating ignored files**

Apply this `.gitignore` delta; do not broaden to `scripts/*.py` or `tests/unit/*.py`:

```gitignore
!scripts/codex_diagnostics.py
!scripts/rollback_codex_diagnostics_snapshot.py
!docs/codex-diagnostics.md
!tests/unit/test_codex_diagnostics.py
!tests/unit/test_rollback_codex_diagnostics_snapshot.py
!tests/integration/test_codex_diagnostics_tmux.py
!tests/contract/
!tests/contract/__init__.py
!tests/contract/codex_diagnostics_consumer.py
!tests/contract/test_codex_diagnostics_consumer.py
```

Run:

```bash
git check-ignore -v \
  scripts/codex_diagnostics.py \
  scripts/rollback_codex_diagnostics_snapshot.py \
  tests/unit/test_codex_diagnostics.py \
  tests/unit/test_rollback_codex_diagnostics_snapshot.py \
  tests/integration/test_codex_diagnostics_tmux.py \
  tests/contract/__init__.py \
  tests/contract/codex_diagnostics_consumer.py \
  tests/contract/test_codex_diagnostics_consumer.py \
  docs/codex-diagnostics.md
```

Expected: exit 1 and no output, meaning all nine exact paths are trackable.

- [ ] **Step 2: Write RED contract tests**

Create `tests/unit/test_codex_diagnostics.py` with this loader, test helper, and first test class. The local `validate_work_log_registry()` helper must validate marker order/cardinality, duplicate JSON keys, exact top-level and nine-record key order, strict integer/string types, lowercase commit/hash formats, all fixed values, real UTC seconds, and at most one active record. Exercise it with non-empty valid and hostile synthetic records so the initial empty registry cannot make the record loop vacuous:

```python
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
        records = validate_work_log_registry(WORK_LOG.read_bytes())
        self.assertLessEqual(
            sum(item["status"] == "active" for item in records), 1
        )

    def test_work_log_validator_exercises_nonempty_hostile_records(self) -> None:
        # Use fixed nine-field records. Valid empty/one-active inputs pass;
        # reordered/missing/extra keys, bool versions, impossible UTC seconds,
        # wrong fixed values, uppercase hashes, and two active records fail.
        ...


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run RED tests**

Run:

```bash
python3 -m unittest -v tests.unit.test_codex_diagnostics.CliAndSourceHashTests
```

Expected: FAIL because `scripts/codex_diagnostics.py` and the deployment work log do not exist.

- [ ] **Step 4: Implement the minimal fixed contract**

Create `scripts/codex_diagnostics.py` with this complete first block. Later tasks append collectors; do not change these public names:

```python
#!/usr/bin/python3 -I
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import stat
from dataclasses import dataclass
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
```

Create the initial work log exactly as follows:

```markdown
# Codex Read-Only Diagnostics Work Log

- State: source implementation not yet deployed
- Evidence boundary: no raw diagnostic JSON, pane, queue, report, log, or secret is recorded here

<!-- BEGIN CODEX_DIAGNOSTICS_DEPLOYMENTS_V1 -->
{"schema_version":1,"deployments":[]}
<!-- END CODEX_DIAGNOSTICS_DEPLOYMENTS_V1 -->
```

- [ ] **Step 5: Run GREEN tests and source guard checks**

Run:

```bash
python3 -m unittest -v tests.unit.test_codex_diagnostics.CliAndSourceHashTests
python3 -m py_compile scripts/codex_diagnostics.py tests/unit/test_codex_diagnostics.py
git check-ignore -v scripts/codex_diagnostics.py tests/unit/test_codex_diagnostics.py docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics-work-log.md
```

Expected: all tests PASS, compile exit 0, `git check-ignore` exit 1 with no output.

- [ ] **Step 6: Commit only Task 1 files**

```bash
git add -- .gitignore scripts/codex_diagnostics.py tests/unit/test_codex_diagnostics.py docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics-work-log.md
git diff --cached --name-only
git commit -m "test: define diagnostics safety contract"
```

Expected staged paths: exactly the four paths listed in `git add`; commit succeeds.

### Task 2: Add the Allowlisted Bounded Command Runner

**Files:**

- Modify: `scripts/codex_diagnostics.py` imports and append runner code
- Modify: `tests/unit/test_codex_diagnostics.py` imports and append `CommandRunnerTests`

**Interfaces:**

- Consumes: `CommandResult` from Task 1.
- Produces: `_StreamBudget.feed(bytes) -> bool`, `drain_process(...) -> CommandResult`, and `CommandRunner.__call__(tuple[str, ...]) -> CommandResult`.

- [ ] **Step 1: Write RED runner tests**

Add `import subprocess` and `import time` to the test imports, then add:

```python
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
```

- [ ] **Step 2: Run the runner tests RED**

```bash
python3 -m unittest -v tests.unit.test_codex_diagnostics.CommandRunnerTests
```

Expected: FAIL because `_StreamBudget` and `CommandRunner` are undefined.

- [ ] **Step 3: Implement bounded drain and runner**

Add these imports to `scripts/codex_diagnostics.py`, and extend the existing dataclasses import to `from dataclasses import dataclass, field`:

```python
import selectors
import signal
import subprocess
import time
from collections.abc import Callable
```

Append this complete runner block:

```python
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
```

- [ ] **Step 4: Run GREEN runner and regression tests**

```bash
python3 -m unittest -v tests.unit.test_codex_diagnostics.CommandRunnerTests
python3 -m unittest -v tests.unit.test_codex_diagnostics
```

Expected: all tests PASS; the real runner returns bounded `/usr/bin/git --version` output.

- [ ] **Step 5: Commit the runner slice**

```bash
git add -- scripts/codex_diagnostics.py tests/unit/test_codex_diagnostics.py
git diff --cached --name-only
git commit -m "feat: add bounded diagnostics command runner"
```

Expected staged paths: the two listed files only.

### Task 3: Add dir-FD Source Metadata and Bounded Log Aggregates

**Files:**

- Modify: `scripts/codex_diagnostics.py` append safe path, source, and log collectors
- Modify: `tests/unit/test_codex_diagnostics.py` append safe path/log tests

**Interfaces:**

- Consumes: fixed `AGENT_IDS`, `Issue`, `_source_stat_key()`.
- Produces: `SourceSpec`, `SourceCollection`, `LogCollection`, `open_runtime_root()`, `open_regular_beneath()`, `collect_runtime_sources()`, `read_bounded_tail()`, `aggregate_log_tail()`, `collect_log_aggregates()`.

- [ ] **Step 1: Write RED safe-path and aggregate tests**

Add `import errno`, `import re`, and `import socket`, then append:

```python
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
```

- [ ] **Step 2: Run safe-path/log tests RED**

```bash
python3 -m unittest -v tests.unit.test_codex_diagnostics.SafePathAndLogTests
```

Expected: FAIL because source/path/log interfaces are undefined.

- [ ] **Step 3: Implement dir-FD traversal and source metadata**

Append:

```python
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
```

- [ ] **Step 4: Implement bounded log-tail aggregation**

Append:

```python
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
```

- [ ] **Step 5: Run GREEN safe-path/log and full unit tests**

```bash
python3 -m unittest -v tests.unit.test_codex_diagnostics.SafePathAndLogTests
python3 -m unittest -v tests.unit.test_codex_diagnostics
```

Expected on Linux/WSL: all tests PASS. On a platform without `O_PATH`, the real traversal is deliberately rejected; do not add a `Path.resolve()` fallback or skip to claim deployment readiness.

- [ ] **Step 6: Commit the source/log slice**

```bash
git add -- scripts/codex_diagnostics.py tests/unit/test_codex_diagnostics.py
git diff --cached --name-only
git commit -m "feat: add dir-fd runtime diagnostics collectors"
```

Expected staged paths: the two listed files only.


### Task 4: Collect Fixed tmux Metadata and Watcher Process Counts

**Files:**

- Modify: `scripts/codex_diagnostics.py` append tmux/process collectors
- Modify: `tests/unit/test_codex_diagnostics.py` append tmux/process tests

**Interfaces:**

- Consumes: `CommandResult`, `Issue`, `_command_issue()`.
- Produces: `PaneObservation`, `TmuxCollection`, `ProcessCollection`, `collect_tmux()`, `count_pgrep()`, `collect_processes()`.

- [ ] **Step 1: Write RED tmux and process tests**

Append:

```python
class TmuxAndProcessCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def test_one_ashigaru_formation_keeps_other_agents_not_observed(self) -> None:
        m = self.module
        runner = ScriptedRunner({
            m.TMUX_SESSIONS_ARGV: m.CommandResult("ok", 0, b"shogun\nmultiagent\n"),
            m.TMUX_PANES_ARGV: m.CommandResult(
                "ok", 0,
                b"shogun\t0\tshogun\tclaude\n"
                b"multiagent\t0\tkaro\tcodex\n"
                b"multiagent\t0\tashigaru1\tclaude\n",
            ),
        })
        collection = m.collect_tmux(runner)
        self.assertEqual(collection.observed_agents, frozenset(("shogun", "karo", "ashigaru1")))
        self.assertEqual(collection.observations["ashigaru2"].pane_state, "not_observed")
        self.assertNotIn("ashigaru2", {issue.agent for issue in collection.errors})
        self.assertEqual(len(collection.sessions), 2)
        self.assertNotIn("capture-pane", SOURCE.read_text(encoding="utf-8"))

    def test_unknown_duplicate_wrong_session_dead_and_hostile_cli_are_sanitized(self) -> None:
        m = self.module
        secret = "oauth-secret-customer"
        runner = ScriptedRunner({
            m.TMUX_SESSIONS_ARGV: m.CommandResult("ok", 0, b"shogun\nmultiagent\n"),
            m.TMUX_PANES_ARGV: m.CommandResult(
                "ok", 0,
                b"shogun\t0\tunknown-" + secret.encode() + b"\tclaude\n"
                b"multiagent\t0\tshogun\tbad-cli\n"
                b"multiagent\t1\tashigaru1\tclaude\n"
                b"multiagent\t0\tashigaru1\tclaude\n",
            ),
        })
        collection = m.collect_tmux(runner)
        codes = {issue.code for issue in collection.errors}
        self.assertIn("agent_session_mismatch", codes)
        self.assertIn("duplicate_agent_pane", codes)
        self.assertEqual(collection.sessions[0]["unknown_agent_count"], 1)
        self.assertEqual(collection.observations["shogun"].cli, "unknown")
        self.assertNotIn(secret, repr(collection))

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

    def test_pgrep_invalid_pid_timeout_and_duplicates_map_to_fixed_states(self) -> None:
        m = self.module
        self.assertEqual(m.count_pgrep(m.CommandResult("nonzero", 1, b"")), 0)
        self.assertEqual(m.count_pgrep(m.CommandResult("ok", 0, b"1\n2\n")), 2)
        self.assertIsNone(m.count_pgrep(m.CommandResult("ok", 0, b"1\nsecret\n")))
        self.assertIsNone(m.count_pgrep(m.CommandResult("timeout", None, b"")))
        for argv in m.PGREP_AGENT_ARGV.values():
            self.assertEqual(argv[:3], ("/usr/bin/pgrep", "-f", "--"))
```

- [ ] **Step 2: Run tmux/process tests RED**

```bash
python3 -m unittest -v tests.unit.test_codex_diagnostics.TmuxAndProcessCollectorTests
```

Expected: FAIL because collector constants and functions are undefined.

- [ ] **Step 3: Implement tmux metadata parsing**

Append:

```python
TMUX_SESSIONS_ARGV = ("/usr/bin/tmux", "list-sessions", "-F", "#{session_name}")
TMUX_PANES_ARGV = (
    "/usr/bin/tmux", "list-panes", "-a", "-F",
    "#{session_name}\t#{pane_dead}\t#{@agent_id}\t#{@agent_cli}",
)
EXPECTED_SESSION = {agent: ("shogun" if agent == "shogun" else "multiagent") for agent in AGENT_IDS}


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


def _session_json(name: str, state: str, panes: int | None, dead: int | None, unknown: int | None):
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
    rows: dict[str, list[tuple[str, str, str]]] = {name: [] for name in SESSION_NAMES}
    pane_counts = {name: 0 for name in SESSION_NAMES}
    dead_counts = {name: 0 for name in SESSION_NAMES}
    unknown_counts = {name: 0 for name in SESSION_NAMES}
    if panes_result.status == "ok":
        for raw_line in panes_result.stdout.splitlines():
            fields = raw_line.split(b"\t")
            if len(fields) != 4 or fields[0] not in {b"shogun", b"multiagent"}:
                continue
            session = fields[0].decode("ascii")
            pane_counts[session] += 1
            dead = fields[1] == b"1"
            if dead:
                dead_counts[session] += 1
            if fields[2] not in {item.encode() for item in AGENT_IDS}:
                unknown_counts[session] += 1
                warnings.append(Issue("unknown_agent_observed", "tmux", None))
                continue
            agent = fields[2].decode("ascii")
            cli = fields[3].decode("ascii") if fields[3] in {item.encode() for item in CLI_NAMES} else "unknown"
            if cli == "unknown":
                warnings.append(Issue("unknown_cli_observed", "tmux", agent))
            rows[session].append((agent, "dead" if dead else "alive", cli))
    elif not (panes_result.status == "nonzero" and panes_result.returncode == 1):
        errors.append(_command_issue(panes_result, "tmux"))

    sessions: list[dict[str, object]] = []
    for name in SESSION_NAMES:
        if session_error:
            sessions.append(_session_json(name, "error", None, None, None))
        elif name not in present:
            sessions.append(_session_json(name, "missing", 0, 0, 0))
            errors.append(Issue("session_missing", "tmux", None))
        elif pane_counts[name] > 64:
            sessions.append(_session_json(name, "error", None, None, None))
            errors.append(Issue("result_truncated", "tmux", None))
        else:
            sessions.append(_session_json(
                name, "present", pane_counts[name], dead_counts[name], unknown_counts[name]
            ))

    by_agent: dict[str, list[tuple[str, str, str]]] = {agent: [] for agent in AGENT_IDS}
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
    observed = frozenset(agent for agent, value in observations.items() if value.observed)
    return TmuxCollection(tuple(sessions), observations, observed, tuple(errors), tuple(warnings))
```

- [ ] **Step 4: Implement fixed pgrep counts**

Append:

```python
PGREP_SUPERVISOR_ARGV = (
    "/usr/bin/pgrep", "-f", "--", r"(^|/)scripts/watcher_supervisor\.sh([[:space:]]|$)"
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


def collect_processes(observed_agents: frozenset[str], run) -> ProcessCollection:
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
```

- [ ] **Step 5: Run GREEN tmux/process and regression tests**

```bash
python3 -m unittest -v tests.unit.test_codex_diagnostics.TmuxAndProcessCollectorTests
python3 -m unittest -v tests.unit.test_codex_diagnostics
```

Expected: all tests PASS; only the three observed agents are queried; no PID or unknown raw value is serialized.

- [ ] **Step 6: Commit the tmux/process slice**

```bash
git add -- scripts/codex_diagnostics.py tests/unit/test_codex_diagnostics.py
git diff --cached --name-only
git commit -m "feat: collect tmux and watcher process metadata"
```

Expected staged paths: the two listed files only.


### Task 5: Collect Sanitized Canonical Repository Metadata

**Files:**

- Modify: `scripts/codex_diagnostics.py` boundary exception and append repository collector
- Modify: `tests/unit/test_codex_diagnostics.py` append scripted runner and repository tests

**Interfaces:**

- Consumes: `CommandRunner`, `CommandResult`, `Issue`, `BoundaryRejected`.
- Produces: `RepositoryCollection`, `git_argv()`, `classify_branch()`, `is_canonical_remote()`, `collect_repository()`.

- [ ] **Step 1: Write RED repository tests**

Add this reusable fake and test class before the module trailer:

```python
class RepositoryCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

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
```

- [ ] **Step 2: Run repository tests RED**

```bash
python3 -m unittest -v tests.unit.test_codex_diagnostics.RepositoryCollectorTests
```

Expected: FAIL because repository functions and `BoundaryRejected.code` do not exist.

- [ ] **Step 3: Make boundary rejection carry a fixed code**

Replace the Task 1 `BoundaryRejected` class and its `run_cli` handler with:

```python
class BoundaryRejected(Exception):
    def __init__(self, code: str = "boundary_rejected") -> None:
        self.code = code if code in ERROR_CODES else "boundary_rejected"


# inside run_cli
    except BoundaryRejected as exc:
        return 2, build_failure_document(exc.code)
```

- [ ] **Step 4: Implement the repository collector**

Add `import re` and append:

```python
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
        fields = line.split(b"\t", 1)
        if len(fields) != 2:
            continue
        url = fields[1].split(b" ", 1)[0]
        if CANONICAL_REMOTE.fullmatch(url):
            return True
    return False


def _nul_count(result: CommandResult) -> tuple[int | None, Issue | None]:
    if result.status != "ok":
        return None, _command_issue(result, "repository")
    if not result.stdout:
        return 0, None
    if not result.stdout.endswith(b"\x00"):
        return None, Issue("command_failed", "repository", None)
    count = result.stdout.count(b"\x00")
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

    tracked, tracked_issue = _nul_count(
        run(git_argv("status", "--porcelain=v1", "-z", "--untracked-files=no"))
    )
    untracked, untracked_issue = _nul_count(
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
```

- [ ] **Step 5: Run GREEN repository and full unit tests**

```bash
python3 -m unittest -v tests.unit.test_codex_diagnostics.RepositoryCollectorTests
python3 -m unittest -v tests.unit.test_codex_diagnostics
```

Expected: all tests PASS; no raw branch, remote URL, or filename appears in collection JSON.

- [ ] **Step 6: Commit the repository slice**

```bash
git add -- scripts/codex_diagnostics.py tests/unit/test_codex_diagnostics.py
git diff --cached --name-only
git commit -m "feat: collect sanitized repository metadata"
```

Expected staged paths: the two listed files only.

### Task 6: Assemble, Validate, and Serialize the Fixed JSON Document

**Files:**

- Modify: `scripts/codex_diagnostics.py` imports, schema assembly, CLI entrypoint
- Modify: `tests/unit/test_codex_diagnostics.py` append summary/serialization tests

**Interfaces:**

- Consumes: all five collection dataclasses from Tasks 3-5 and `CommandRunner`.
- Produces: `calculate_overall()`, `build_success_document()`, `validate_document()`, `collect_summary()`, `main()`.

- [ ] **Step 1: Write RED document and orchestration tests**

Append these fixture builders and tests:

```python
def sample_collections(module, *, both_sessions_missing=False, one_session_missing=False):
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
    sessions = tuple(
        {
            "name": name,
            "state": state,
            "pane_count": 0 if state == "missing" else 1,
            "dead_pane_count": 0,
            "unknown_agent_count": 0,
        }
        for name, state in zip(module.SESSION_NAMES, states)
    )
    observations = {
        agent: module.PaneObservation(
            agent in ("shogun", "karo", "ashigaru1"),
            "shogun" if agent == "shogun" else (
                "multiagent" if agent in ("karo", "ashigaru1") else None
            ),
            "alive" if agent in ("shogun", "karo", "ashigaru1") else "not_observed",
            "claude" if agent in ("shogun", "karo", "ashigaru1") else "unknown",
        )
        for agent in module.AGENT_IDS
    }
    tmux_errors = () if states == ("present", "present") else (
        module.Issue("session_missing", "tmux", None),
    )
    tmux = module.TmuxCollection(
        sessions,
        observations,
        frozenset(("shogun", "karo", "ashigaru1")),
        tmux_errors,
        (),
    )
    watchers = {
        agent: ((1, "healthy") if observations[agent].observed else (None, "not_observed"))
        for agent in module.AGENT_IDS
    }
    processes = module.ProcessCollection(
        {"watcher_supervisor_count": 1, "watcher_supervisor_state": "healthy"},
        watchers,
        (),
        (),
    )
    present = {
        "applicability": "optional",
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
        agent_sources[agent] = {
            "inbox": dict(present),
            "task": dict(present if task_report else na),
            "report": dict(present if task_report else na),
            "handoff_status": dict(present),
            "watcher_log": dict(present),
        }
    sources = module.SourceCollection(
        {"command_queue": dict(present), "dashboard": dict(present)},
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
        self.assertEqual([item["id"] for item in document["agents"]], list(m.AGENT_IDS))
        self.assertEqual(tuple(document["global_sources"]), ("command_queue", "dashboard"))
        self.assertEqual(tuple(document["agents"][0]["sources"]), m.SOURCE_KEYS)

    def test_overall_distinguishes_degraded_unavailable_and_optional_warning(self) -> None:
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

    def test_validator_rejects_unknown_keys_and_free_text(self) -> None:
        m = self.module
        document = m.build_success_document("a" * 64, *sample_collections(m))
        document["raw_message"] = "secret"
        with self.assertRaises(m.InternalFailure):
            m.validate_document(document)

        document = m.build_success_document("a" * 64, *sample_collections(m))
        document["generated_at"] = None
        with self.assertRaises(m.InternalFailure):
            m.validate_document(document)

    def test_boundary_failure_occurs_before_runtime_root_open(self) -> None:
        m = self.module
        runner = ScriptedRunner({
            m.git_argv("rev-parse", "--show-toplevel"): m.CommandResult(
                "ok", 0, (os.getcwd() + "\n").encode()
            ),
            m.git_argv("remote", "-v"): m.CommandResult(
                "ok", 0, b"origin\thttps://example.invalid/repo (fetch)\n"
            ),
        })
        opened = mock.Mock(side_effect=AssertionError("runtime opened"))
        with self.assertRaises(m.BoundaryRejected):
            m.collect_summary(runner, source_hash="a" * 64, open_root=opened)
        opened.assert_not_called()

    def test_run_cli_hash_failure_and_argument_rejection_do_not_call_collector(self) -> None:
        m = self.module
        collector = mock.Mock()
        with mock.patch.object(m, "calculate_source_sha256", side_effect=m.InternalFailure):
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
        with mock.patch.object(m.json, "dumps", side_effect=ValueError("token-secret")):
            payload, code = m.safe_render_document(document, 0)
        self.assertEqual((payload, code), (m.FALLBACK_INTERNAL_ERROR, 3))
        self.assertNotIn(b"token-secret", payload)

    def test_signal_before_output_emits_exact_literal_and_exits_three(self) -> None:
        m = self.module
        with mock.patch.object(m, "emit_bytes") as emit, mock.patch.object(
            m.os, "_exit", side_effect=SystemExit(3)
        ):
            with self.assertRaisesRegex(SystemExit, "3"):
                m._signal_before_output(15, None)
        emit.assert_called_once_with(m.FALLBACK_INTERNAL_ERROR)

    def test_agent_order_matches_tracked_status_helper(self) -> None:
        helper = ROOT / "skills" / "shogun-agent-status" / "scripts" / "agent_status.sh"
        text = helper.read_text(encoding="utf-8")
        positions = [text.index(agent) for agent in self.module.AGENT_IDS]
        self.assertEqual(positions, sorted(positions))
```

- [ ] **Step 2: Run summary tests RED**

```bash
python3 -m unittest -v tests.unit.test_codex_diagnostics.SummaryAndSerializationTests
```

Expected: FAIL because document assembly, validation, orchestration, and safe serialization are undefined.

- [ ] **Step 3: Implement fixed document assembly and validation**

Append:

```python
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
        repository.errors + tmux.errors + processes.errors + sources.errors + logs.errors,
        repository.warnings + tmux.warnings + processes.warnings + sources.warnings + logs.warnings,
    )
    agents: list[dict[str, object]] = []
    for agent in AGENT_IDS:
        observation = tmux.observations[agent]
        watcher_count, watcher_state = processes.agent_watchers[agent]
        agents.append({
            "id": agent,
            "observed": observation.observed,
            "session": observation.session,
            "pane_state": observation.pane_state,
            "cli": observation.cli,
            "watcher_count": watcher_count,
            "watcher_state": watcher_state,
            "sources": sources.agent_sources[agent],
            "log_events": logs.events[agent],
        })
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
    if value is not None and (
        not isinstance(value, str)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value) is None
    ):
        raise InternalFailure


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
    if top["schema_version"] != 1 or top["ok"] is not True:
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
    if repository["head"] is not None and re.fullmatch(
        r"[0-9a-f]{40}", repository["head"]
    ) is None:
        raise InternalFailure
    if repository["dirty"] not in (True, False, None):
        raise InternalFailure
    _nullable_count(repository["tracked_changes"], 10_000)
    _nullable_count(repository["untracked_changes"], 10_000)
    if repository["canonical_remote_present"] not in (True, False, None):
        raise InternalFailure

    sessions = top["sessions"]
    agents = top["agents"]
    if not isinstance(sessions, list) or len(sessions) != 2:
        raise InternalFailure
    if not isinstance(agents, list) or len(agents) != 11:
        raise InternalFailure
    for expected, raw in zip(SESSION_NAMES, sessions):
        item = _exact_keys(raw, SESSION_KEYS)
        if item["name"] != expected or item["state"] not in ("present", "missing", "error"):
            raise InternalFailure
        for key in ("pane_count", "dead_pane_count", "unknown_agent_count"):
            _nullable_count(item[key], 64)
    processes = _exact_keys(
        top["processes"], ("watcher_supervisor_count", "watcher_supervisor_state")
    )
    _nullable_count(processes["watcher_supervisor_count"])
    if processes["watcher_supervisor_state"] not in ("healthy", "missing", "duplicate", "unknown"):
        raise InternalFailure

    global_sources = _exact_keys(top["global_sources"], ("command_queue", "dashboard"))
    for raw in global_sources.values():
        _validate_source_value(raw)
    for expected, raw in zip(AGENT_IDS, agents):
        item = _exact_keys(raw, AGENT_KEYS)
        if item["id"] != expected or item["observed"] not in (True, False):
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
        for raw in values:
            issue = _exact_keys(raw, ISSUE_KEYS)
            if issue["code"] not in ERROR_CODES or issue["component"] not in COMPONENTS:
                raise InternalFailure
            if issue["agent"] not in (*AGENT_IDS, None):
                raise InternalFailure
```

- [ ] **Step 4: Implement orchestration, fallback, signals, and executable entrypoint**

Add `import sys` and append:

```python
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


_OUTPUT_STARTED = False


def _signal_before_output(_signum, _frame) -> None:
    if not _OUTPUT_STARTED:
        try:
            emit_bytes(FALLBACK_INTERNAL_ERROR)
        finally:
            os._exit(3)
    os._exit(3)


def main(argv: Sequence[str] | None = None) -> int:
    global _OUTPUT_STARTED
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, _signal_before_output)
    try:
        runner = CommandRunner()
        code, document = run_cli(
            tuple(sys.argv[1:] if argv is None else argv),
            lambda source_hash: collect_summary(runner, source_hash=source_hash),
        )
    except BaseException:
        code, document = 3, build_failure_document("internal_error")
    payload, code = safe_render_document(document, code)
    _OUTPUT_STARTED = True
    try:
        emit_bytes(payload)
    except BaseException:
        return 3
    return code


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run GREEN summary and all unit tests**

```bash
python3 -m unittest -v tests.unit.test_codex_diagnostics.SummaryAndSerializationTests
python3 -m unittest -v tests.unit.test_codex_diagnostics
python3 -m py_compile scripts/codex_diagnostics.py tests/unit/test_codex_diagnostics.py
```

Expected: all tests PASS and compile exit 0. No test is skipped.

- [ ] **Step 6: Commit the fixed-document slice**

```bash
git add -- scripts/codex_diagnostics.py tests/unit/test_codex_diagnostics.py
git diff --cached --name-only
git commit -m "feat: finalize fail-closed diagnostics JSON"
```

Expected staged paths: the two listed files only.

### Task 7: Integrate Bats, Real tmux Isolation, Make Gate, and Operator Docs

**Files:**

- Create: `tests/unit/test_codex_diagnostics.bats`
- Create: `tests/contract/__init__.py`
- Create: `tests/contract/codex_diagnostics_consumer.py`
- Create: `tests/contract/test_codex_diagnostics_consumer.py`
- Create: `tests/integration/test_codex_diagnostics_tmux.py`
- Create: `tests/integration/test_codex_diagnostics_tmux.bats`
- Create: `scripts/rollback_codex_diagnostics_snapshot.py`
- Create: `tests/unit/test_rollback_codex_diagnostics_snapshot.py`
- Create: `docs/codex-diagnostics.md`
- Modify: `Makefile` `.PHONY`, help, and append `test-no-skip`
- Modify: `docs/github-boundary-operation.md` before `## Non-Goals`

**Interfaces:**

- Consumes: executable CLI and `collect_tmux()` from Task 6.
- Produces: standard `make test` coverage, executable fail-closed consumer fixtures, tested atomic snapshot rollback primitive, WSL-only real tmux coverage, deployment acceptance target, and the exact marker block later copied to Workspace.

- [ ] **Step 1: Write RED-first consumer contract tests and the unit Bats wrapper**

Create `tests/unit/test_codex_diagnostics.bats`:

```bash
#!/usr/bin/env bats

setup() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export SCRIPT="$PROJECT_ROOT/scripts/codex_diagnostics.py"
}

@test "codex diagnostics unittest suite passes with zero skips" {
    run python3 -m unittest -v tests.unit.test_codex_diagnostics
    [ "$status" -eq 0 ]
    [[ "$output" != *"skipped="* ]]
}

@test "codex diagnostics consumer contract rejects every untrusted fixture" {
    run python3 -m unittest -v \
        tests.contract.test_codex_diagnostics_consumer
    [ "$status" -eq 0 ]
    [[ "$output" != *"skipped="* ]]
}

@test "codex diagnostics source and tests compile" {
    run env PYTHONPYCACHEPREFIX="$BATS_TEST_TMPDIR/pycache" \
        python3 -m py_compile \
        "$SCRIPT" \
        "$PROJECT_ROOT/tests/unit/test_codex_diagnostics.py" \
        "$PROJECT_ROOT/tests/contract/codex_diagnostics_consumer.py" \
        "$PROJECT_ROOT/tests/contract/test_codex_diagnostics_consumer.py"
    [ "$status" -eq 0 ]
}

@test "codex diagnostics rejects suffix with one JSON and empty stderr" {
    stdout="$BATS_TEST_TMPDIR/stdout.json"
    stderr="$BATS_TEST_TMPDIR/stderr.txt"
    set +e
    /usr/bin/python3 -I "$SCRIPT" summary unexpected >"$stdout" 2>"$stderr"
    rc="$?"
    set -e
    [ "$rc" -eq 2 ]
    [ ! -s "$stderr" ]
    run python3 - "$stdout" <<'PY'
import json
import pathlib
import sys

raw = pathlib.Path(sys.argv[1]).read_bytes()
value = json.loads(raw)
assert value["ok"] is False
assert value["errors"] == [
    {"code": "argument_rejected", "component": "diagnostic", "agent": None}
]
assert value["tool"]["source_sha256"] is None
assert raw.count(b"{") >= 1
PY
    [ "$status" -eq 0 ]
}
```

Use this mandatory TDD execution order for the next two consumer listings:

1. Create `tests/contract/__init__.py` as an empty package marker.
2. Create `tests/contract/test_codex_diagnostics_consumer.py` from the second listing below while `codex_diagnostics_consumer.py` is still absent.
3. Run `python3 -m unittest -v tests.contract.test_codex_diagnostics_consumer` and require RED with `ModuleNotFoundError` for only the absent consumer module. Any syntax/collection failure is not the expected RED.
4. Only after that RED, create `tests/contract/codex_diagnostics_consumer.py` from the following GREEN listing.
5. Rerun the same command and require all consumer tests PASS with zero skips.

GREEN implementation listing for `tests/contract/codex_diagnostics_consumer.py` (do not create it before the RED run):

```python
from __future__ import annotations

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
        if not isinstance(record["deployed_at"], str) or TIMESTAMP.fullmatch(
            record["deployed_at"]
        ) is None:
            raise ContractRejected
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
        for raw_issue in issues:
            issue = _exact_keys(raw_issue, ISSUE_KEYS)
            if issue["code"] not in ERROR_CODES or issue["component"] not in COMPONENTS:
                raise ContractRejected
            if issue["agent"] not in (*AGENT_IDS, None):
                raise ContractRejected
    return source_hash


def evaluate_consumer(
    *,
    fetch_ok: bool,
    registry: bytes,
    stdout: bytes,
    stderr: bytes,
    exit_code: int,
    elapsed_seconds: float,
) -> ConsumerDecision:
    if not fetch_ok:
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
        or isinstance(elapsed_seconds, bool)
        or not isinstance(elapsed_seconds, (int, float))
        or not math.isfinite(elapsed_seconds)
        or elapsed_seconds < 0
        or elapsed_seconds >= 10.0
    ):
        return _failure("diagnostic_process_failed")
    try:
        source_hash = _output_source_hash(stdout)
    except Exception:
        return _failure("diagnostic_process_failed")
    if source_hash != active["source_sha256"]:
        return _failure("diagnostic_provenance_untrusted")
    return ConsumerDecision(True, None, "use_sanitized_diagnostic")
```

RED-first listing for `tests/contract/test_codex_diagnostics_consumer.py` (create this before the preceding implementation listing):

```python
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
        cases = {
            "github_fetch_failed": self.evaluate(fetch_ok=False),
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
            "elapsed_over_10_seconds": self.evaluate(elapsed_seconds=10.001),
        }
        for name, decision in cases.items():
            with self.subTest(name=name):
                self.assertFalse(decision.trusted)
                self.assertEqual(decision.code, "diagnostic_process_failed")
                self.assertEqual(decision.action, "stop_without_fallback")
                self.assertFalse(decision.fallback_allowed)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Write the WSL-only unique-socket integration**

Create `tests/integration/test_codex_diagnostics_tmux.py`:

```python
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts" / "codex_diagnostics.py"


def load_module():
    spec = importlib.util.spec_from_file_location("codex_diagnostics_integration", SOURCE)
    if spec is None or spec.loader is None:
        raise AssertionError("diagnostics module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SocketRunner:
    def __init__(self, module, socket_name: str) -> None:
        self.module = module
        self.socket_name = socket_name
        self.runner = module.CommandRunner()

    def __call__(self, argv):
        if argv[0] == "/usr/bin/tmux":
            argv = (argv[0], "-L", self.socket_name, *argv[1:])
        return self.runner(argv)


class UniqueTmuxSocketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        self.socket_name = os.environ["SHOGUN_DIAGNOSTIC_TEST_SOCKET"]
        self.fixture_dir = tempfile.TemporaryDirectory()
        self.fixture = Path(self.fixture_dir.name) / "bounded-pane-fixture"
        self.fixture.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' harmless-pane-sentinel\n"
            "exec /usr/bin/sleep 5\n",
            encoding="utf-8",
        )
        self.fixture.chmod(0o700)

    def tmux(self, *args: str) -> None:
        subprocess.run(
            ("/usr/bin/tmux", "-L", self.socket_name, *args),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=2,
        )

    def tearDown(self) -> None:
        deadline = time.monotonic() + 7.0
        try:
            while time.monotonic() < deadline:
                result = subprocess.run(
                    ("/usr/bin/tmux", "-L", self.socket_name, "has-session"),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=1,
                )
                if result.returncode != 0:
                    return
                time.sleep(0.05)
            self.fail("isolated tmux server did not exit after bounded fixtures")
        finally:
            self.fixture_dir.cleanup()

    def test_fixed_sessions_counts_and_pane_secrecy(self) -> None:
        self.tmux("new-session", "-d", "-s", "shogun", str(self.fixture))
        self.tmux("set-option", "-g", "exit-empty", "on")
        self.tmux("set-option", "-p", "-t", "shogun:0.0", "@agent_id", "shogun")
        self.tmux("set-option", "-p", "-t", "shogun:0.0", "@agent_cli", "claude")
        self.tmux("new-session", "-d", "-s", "multiagent", str(self.fixture))
        self.tmux("set-option", "-p", "-t", "multiagent:0.0", "@agent_id", "ashigaru1")
        self.tmux("set-option", "-p", "-t", "multiagent:0.0", "@agent_cli", "codex")

        value = self.module.collect_tmux(SocketRunner(self.module, self.socket_name))
        self.assertEqual([item["state"] for item in value.sessions], ["present", "present"])
        self.assertEqual([item["pane_count"] for item in value.sessions], [1, 1])
        self.assertEqual(value.observations["shogun"].pane_state, "alive")
        self.assertEqual(value.observations["ashigaru1"].cli, "codex")
        self.assertNotIn("harmless-pane-sentinel", repr(value))


if __name__ == "__main__":
    unittest.main()
```

Create `tests/integration/test_codex_diagnostics_tmux.bats`:

```bash
#!/usr/bin/env bats

@test "codex diagnostics uses an isolated tmux socket without pane capture" {
    export SHOGUN_DIAGNOSTIC_TEST_SOCKET="codex-diagnostics-${BATS_TEST_NUMBER}-$$"
    run python3 -m unittest -v \
        tests.integration.test_codex_diagnostics_tmux.UniqueTmuxSocketTests
    [ "$status" -eq 0 ]
    [[ "$output" != *"skipped="* ]]
}
```

- [ ] **Step 3: Run wrappers RED, then GREEN**

Run before adding the Make target:

```bash
bats tests/unit/test_codex_diagnostics.bats
bats tests/integration/test_codex_diagnostics_tmux.bats
```

Expected: unit wrapper PASS; integration PASS on WSL with `/usr/bin/tmux`. Any tmux absence is a failure, not a skip.

- [ ] **Step 4: Add the no-skip deployment target without changing `test`**

Change the first Makefile line to:

```make
.PHONY: test test-no-skip build lint check help install-deps clean skill-registry-check skill-registry-lock
```

Add this help line after the existing `make test` line:

```make
	@echo "  make test-no-skip  - Deployment-host tests; any skip or missing prerequisite fails"
```

Append this target immediately after the existing `test` recipe:

```make
test-no-skip:
	@set -eu; \
	for cmd in bats python3 tmux claude; do \
		command -v "$$cmd" >/dev/null 2>&1 || { \
			echo "ERROR: missing required command: $$cmd"; exit 1; \
		}; \
	done; \
	python3 -c 'import sys; assert sys.version_info >= (3, 10)' || { echo "ERROR: Python 3.10+ required"; exit 1; }; \
	test -x .venv/bin/python3 || { echo "ERROR: .venv/bin/python3 missing"; exit 1; }; \
	.venv/bin/python3 -c 'import yaml' || { echo "ERROR: PyYAML missing"; exit 1; }; \
	test -f tests/test_helper/bats-support/load.bash || { echo "ERROR: bats-support missing"; exit 1; }; \
	test -f tests/test_helper/bats-assert/load.bash || { echo "ERROR: bats-assert missing"; exit 1; }; \
	tap="$$(mktemp)"; \
	trap 'rm -f "$$tap"' EXIT; \
	set +e; \
	bats --formatter tap tests/*.bats tests/unit/ \
		tests/integration/test_codex_diagnostics_tmux.bats >"$$tap" 2>&1; \
	rc="$$?"; \
	set -e; \
	cat "$$tap"; \
	tests="$$(grep -Ec '^(ok|not ok) ' "$$tap" || true)"; \
	skips="$$(grep -Eic '^ok [0-9]+ .*# skip([[:space:]]|$$)' "$$tap" || true)"; \
	echo "tests=$$tests skips=$$skips exit=$$rc"; \
	test "$$tests" -gt 0; \
	test "$$rc" -eq 0; \
	test "$$skips" -eq 0
```

Run:

```bash
make -n test-no-skip
make test
```

Expected: dry-run shows the four command preflights and integration path; existing `make test` passes with unchanged scope.

- [ ] **Step 5: Implement and test the atomic snapshot rollback primitive**

Use this mandatory TDD execution order with the final tracked files. The actual
contents of `scripts/rollback_codex_diagnostics_snapshot.py` and
`tests/unit/test_rollback_codex_diagnostics_snapshot.py` are normative:

1. Create the final normative `tests/unit/test_rollback_codex_diagnostics_snapshot.py` while the rollback script is absent, including cleanup failure and temporary-name inode substitution hostile cases.
2. Run `python3 -m unittest -v tests.unit.test_rollback_codex_diagnostics_snapshot` and require RED with `FileNotFoundError` for only the absent rollback script. Any syntax/collection failure is not the expected RED.
3. Only after that RED, create the final dir-FD/exact-cleanup implementation and set mode `0755`.
4. Rerun the same test command and require all tests PASS with zero skips.

#### SUPERSEDED NON-EXECUTABLE ROLLBACK LISTINGS

The two historical sketches below are retained only for decision traceability.
They are not implementation instructions and must not be copied or executed.
They predate the final dir-FD identity checks, exact temporary cleanup, directory
fsync durability, and cleanup-indeterminate hostile cases. Use only the final
tracked files named above.

Superseded historical implementation sketch:

```text
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Sequence

SNAPSHOT_PATH = Path("/home/jinnouchi/.local/libexec/shogun-codex-diagnostics")
MAX_SOURCE_BYTES = 1_048_576
SHA256 = re.compile(r"[0-9a-f]{64}")


class RollbackRefused(Exception):
    pass


class RollbackCommitOrCleanupIndeterminate(Exception):
    pass


def _stat_key(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        stat.S_IMODE(value.st_mode),
    )


def _read_regular(path: Path, required_mode: int | None) -> bytes:
    if not hasattr(os, "O_NOFOLLOW"):
        raise RollbackRefused
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise RollbackRefused from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise RollbackRefused
        if required_mode is not None and stat.S_IMODE(before.st_mode) != required_mode:
            raise RollbackRefused
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_SOURCE_BYTES:
            chunk = os.read(fd, min(65_536, MAX_SOURCE_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > MAX_SOURCE_BYTES:
            raise RollbackRefused
        after = os.fstat(fd)
        if _stat_key(before) != _stat_key(after):
            raise RollbackRefused
        return b"".join(chunks)
    except OSError as exc:
        raise RollbackRefused from exc
    finally:
        os.close(fd)


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_rollback(
    *,
    snapshot: Path,
    target_blob: Path,
    failing_sha256: str,
    target_sha256: str,
) -> None:
    if SHA256.fullmatch(failing_sha256) is None or SHA256.fullmatch(
        target_sha256
    ) is None:
        raise RollbackRefused
    if failing_sha256 == target_sha256:
        raise RollbackRefused
    current = _read_regular(snapshot, 0o555)
    if _digest(current) != failing_sha256:
        raise RollbackRefused
    target = _read_regular(target_blob, None)
    if _digest(target) != target_sha256:
        raise RollbackRefused
    parent = snapshot.parent
    parent_before = os.lstat(parent)
    if not stat.S_ISDIR(parent_before.st_mode) or stat.S_ISLNK(parent_before.st_mode):
        raise RollbackRefused
    fd, raw_temp = tempfile.mkstemp(
        prefix=".shogun-codex-diagnostics.rollback.",
        dir=parent,
    )
    temp_path: Path | None = Path(raw_temp)
    try:
        view = memoryview(target)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise RollbackRefused
            view = view[written:]
        os.fchmod(fd, 0o555)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        if _digest(_read_regular(temp_path, 0o555)) != target_sha256:
            raise RollbackRefused
        if _digest(_read_regular(snapshot, 0o555)) != failing_sha256:
            raise RollbackRefused
        parent_after = os.lstat(parent)
        if (parent_before.st_dev, parent_before.st_ino) != (
            parent_after.st_dev,
            parent_after.st_ino,
        ):
            raise RollbackRefused
        try:
            os.replace(temp_path, snapshot)
        except OSError as exc:
            try:
                observed = _digest(_read_regular(snapshot, 0o555))
            except (OSError, RollbackRefused) as verify_exc:
                raise RollbackCommitOrCleanupIndeterminate from verify_exc
            if observed != failing_sha256:
                raise RollbackCommitOrCleanupIndeterminate from exc
            raise
        temp_path = None
        try:
            directory_fd = os.open(
                parent,
                os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            if _digest(_read_regular(snapshot, 0o555)) != target_sha256:
                raise RollbackRefused
        except (OSError, RollbackRefused) as exc:
            raise RollbackCommitOrCleanupIndeterminate from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise RollbackCommitOrCleanupIndeterminate from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--failing-sha256", required=True)
    parser.add_argument("--target-sha256", required=True)
    parser.add_argument("--target-blob", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        atomic_rollback(
            snapshot=SNAPSHOT_PATH,
            target_blob=args.target_blob,
            failing_sha256=args.failing_sha256,
            target_sha256=args.target_sha256,
        )
    except RollbackCommitOrCleanupIndeterminate:
        return 4
    except (OSError, RollbackRefused):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Superseded historical test sketch:

```text
from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts" / "rollback_codex_diagnostics_snapshot.py"


def load_module():
    spec = importlib.util.spec_from_file_location("rollback_diagnostics_test", SOURCE)
    if spec is None or spec.loader is None:
        raise AssertionError("rollback module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class AtomicRollbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.snapshot = self.root / "shogun-codex-diagnostics"
        self.target = self.root / "target.py"
        self.current_bytes = b"#!/usr/bin/python3\nprint('current')\n"
        self.target_bytes = b"#!/usr/bin/python3\nprint('target')\n"
        self.snapshot.write_bytes(self.current_bytes)
        self.snapshot.chmod(0o555)
        self.target.write_bytes(self.target_bytes)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def rollback(self) -> None:
        self.module.atomic_rollback(
            snapshot=self.snapshot,
            target_blob=self.target,
            failing_sha256=sha(self.current_bytes),
            target_sha256=sha(self.target_bytes),
        )

    def test_success_uses_mode_0555_temp_in_same_directory_and_atomic_replace(self) -> None:
        real_replace = os.replace
        observed = {}

        def checked_replace(source, destination):
            source_path = Path(source)
            observed["parent"] = source_path.parent
            observed["mode"] = source_path.stat().st_mode & 0o777
            observed["destination"] = Path(destination)
            real_replace(source, destination)

        with mock.patch.object(self.module.os, "replace", side_effect=checked_replace):
            self.rollback()
        self.assertEqual(observed["parent"], self.snapshot.parent)
        self.assertEqual(observed["mode"], 0o555)
        self.assertEqual(observed["destination"], self.snapshot)
        self.assertEqual(self.snapshot.read_bytes(), self.target_bytes)
        self.assertEqual(self.snapshot.stat().st_mode & 0o777, 0o555)
        self.assertEqual(
            list(self.root.glob(".shogun-codex-diagnostics.rollback.*")), []
        )

    def test_current_hash_mismatch_refuses_without_changing_snapshot(self) -> None:
        with self.assertRaises(self.module.RollbackRefused):
            self.module.atomic_rollback(
                snapshot=self.snapshot,
                target_blob=self.target,
                failing_sha256="f" * 64,
                target_sha256=sha(self.target_bytes),
            )
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)

    def test_target_hash_mismatch_refuses_without_changing_snapshot(self) -> None:
        with self.assertRaises(self.module.RollbackRefused):
            self.module.atomic_rollback(
                snapshot=self.snapshot,
                target_blob=self.target,
                failing_sha256=sha(self.current_bytes),
                target_sha256="e" * 64,
            )
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)

    def test_equal_failing_and_target_hash_is_rejected_as_noop(self) -> None:
        self.target.write_bytes(self.current_bytes)
        with self.assertRaises(self.module.RollbackRefused):
            self.module.atomic_rollback(
                snapshot=self.snapshot,
                target_blob=self.target,
                failing_sha256=sha(self.current_bytes),
                target_sha256=sha(self.current_bytes),
            )
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)

    def test_symlink_target_is_rejected(self) -> None:
        real_target = self.root / "real-target.py"
        real_target.write_bytes(self.target_bytes)
        self.target.unlink()
        self.target.symlink_to(real_target)
        with self.assertRaises(self.module.RollbackRefused):
            self.rollback()
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)

    def test_current_change_before_replace_is_not_overwritten(self) -> None:
        real_read = self.module._read_regular
        current_reads = 0
        changed = b"changed-by-another-process"

        def mutate_before_second_current_read(path, required_mode):
            nonlocal current_reads
            if Path(path) == self.snapshot:
                current_reads += 1
                if current_reads == 2:
                    self.snapshot.chmod(0o755)
                    self.snapshot.write_bytes(changed)
                    self.snapshot.chmod(0o555)
            return real_read(path, required_mode)

        with mock.patch.object(
            self.module, "_read_regular", side_effect=mutate_before_second_current_read
        ):
            with self.assertRaises(self.module.RollbackRefused):
                self.rollback()
        self.assertEqual(self.snapshot.read_bytes(), changed)

    def test_symlink_snapshot_is_rejected(self) -> None:
        real_snapshot = self.root / "real-snapshot"
        real_snapshot.write_bytes(self.current_bytes)
        real_snapshot.chmod(0o555)
        self.snapshot.unlink()
        self.snapshot.symlink_to(real_snapshot)
        with self.assertRaises(self.module.RollbackRefused):
            self.rollback()
        self.assertEqual(real_snapshot.read_bytes(), self.current_bytes)

    def test_missing_no_follow_support_fails_before_open(self) -> None:
        real_hasattr = hasattr

        def without_no_follow(value, name):
            if value is self.module.os and name == "O_NOFOLLOW":
                return False
            return real_hasattr(value, name)

        with mock.patch("builtins.hasattr", side_effect=without_no_follow):
            with self.assertRaises(self.module.RollbackRefused):
                self.rollback()
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)

    def test_replace_failure_preserves_current_and_removes_temp(self) -> None:
        with mock.patch.object(self.module.os, "replace", side_effect=OSError):
            with self.assertRaises(OSError):
                self.rollback()
        self.assertEqual(self.snapshot.read_bytes(), self.current_bytes)
        self.assertEqual(
            list(self.root.glob(".shogun-codex-diagnostics.rollback.*")), []
        )

    def test_post_replace_fsync_failure_is_distinct_and_requires_reconciliation(self) -> None:
        real_fsync = os.fsync
        calls = 0

        def fail_directory_fsync(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("directory fsync failed")
            return real_fsync(fd)

        with mock.patch.object(self.module.os, "fsync", side_effect=fail_directory_fsync):
            with self.assertRaises(
                self.module.RollbackCommitOrCleanupIndeterminate
            ):
                self.rollback()
        self.assertEqual(self.snapshot.read_bytes(), self.target_bytes)
        self.assertEqual(self.snapshot.stat().st_mode & 0o777, 0o555)

    def test_replace_error_after_visible_commit_is_indeterminate(self) -> None:
        real_replace = os.replace

        def replace_then_error(source, destination):
            real_replace(source, destination)
            raise OSError("rename result uncertain")

        with mock.patch.object(
            self.module.os, "replace", side_effect=replace_then_error
        ):
            with self.assertRaises(
                self.module.RollbackCommitOrCleanupIndeterminate
            ):
                self.rollback()
        self.assertEqual(self.snapshot.read_bytes(), self.target_bytes)

    def test_cli_maps_commit_or_cleanup_indeterminate_to_exit_four(self) -> None:
        with mock.patch.object(
            self.module,
            "atomic_rollback",
            side_effect=self.module.RollbackCommitOrCleanupIndeterminate,
        ):
            result = self.module.main((
                "--failing-sha256", sha(self.current_bytes),
                "--target-sha256", sha(self.target_bytes),
                "--target-blob", str(self.target),
            ))
        self.assertEqual(result, 4)


if __name__ == "__main__":
    unittest.main()
```

The normative final suite additionally requires pre-commit replace plus unlink
failure and temporary-name inode substitution cases. Both must raise
`RollbackCommitOrCleanupIndeterminate`; the former preserves the failing
snapshot and the latter preserves the unknown sentinel for explicit recovery.

Only after the rollback suite is GREEN, extend `tests/unit/test_codex_diagnostics.bats`. Insert this test after the consumer-contract test:

```bash
@test "codex diagnostics rollback primitive passes atomicity tests" {
    run python3 -m unittest -v \
        tests.unit.test_rollback_codex_diagnostics_snapshot
    [ "$status" -eq 0 ]
    [[ "$output" != *"skipped="* ]]
}
```

Then replace the final consumer-test argument of the existing `python3 -m py_compile` command with this exact three-line tail:

```bash
        "$PROJECT_ROOT/tests/contract/test_codex_diagnostics_consumer.py" \
        "$PROJECT_ROOT/scripts/rollback_codex_diagnostics_snapshot.py" \
        "$PROJECT_ROOT/tests/unit/test_rollback_codex_diagnostics_snapshot.py"
```

Run:

```bash
chmod 0755 scripts/rollback_codex_diagnostics_snapshot.py
python3 -m unittest -v tests.unit.test_rollback_codex_diagnostics_snapshot
python3 -m py_compile \
  scripts/rollback_codex_diagnostics_snapshot.py \
  tests/unit/test_rollback_codex_diagnostics_snapshot.py
bats tests/unit/test_codex_diagnostics.bats
make test
```

Expected: all rollback tests, the extended Bats wrapper, and `make test` PASS with no skip. Success replaces only through a same-directory mode-`0555` temporary file. Exit 3 proves both pre-commit refusal and exact cleanup; a post-`os.replace` fsync/verification failure or any unprovable temporary cleanup/durability state is the distinct `RollbackCommitOrCleanupIndeterminate` state and CLI exit 4.

- [ ] **Step 6: Write the operator contract**

Create `docs/codex-diagnostics.md` with these exact sections and values:

```markdown
# Codex Read-Only Diagnostics

## Boundary

This tool is an on-demand, read-only diagnostic gate for Codex Desktop. It does
not start, stop, restart, repair, enqueue, acknowledge, or alter Shogun. It does
not read tmux pane text or queue/task/report/status bodies. It reads only the
fixed metadata and watcher-log counters defined in the approved design.

## Installed command

`wsl.exe -d Ubuntu --cd /home/jinnouchi/multi-agent-shogun /home/jinnouchi/.local/libexec/shogun-codex-diagnostics summary`

No shorter prefix is approved. `summary` is the only subcommand. Any suffix is
rejected before source hashing and collectors run.

## Trust gate

Immediately before every invocation, read GitHub `main` raw
`docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics-work-log.md`.
Require one deployment marker pair, schema version 1, exactly one active record,
the fixed repository/source/snapshot paths, a 40-character source commit, a
64-character lowercase source SHA-256, UTC seconds, mode `0555`, and contract
schema version 1. Compare the command's `tool.source_sha256` with that record.

Missing/unreadable provenance, malformed markers/schema, zero or multiple
active records, or a hash mismatch is `diagnostic_provenance_untrusted`. A nonzero
exit, empty/non-JSON/partial JSON, nonempty stderr, or a run of 10 seconds or more is
`diagnostic_process_failed`. Neither case permits a raw fallback, repo source
execution, direct runtime reads, or a shorter WSL permission.
Before using any field, independently validate the complete nested schema,
exact key order/cardinality/enums/count limits, ASCII-only bytes, and exit 0.

## Output

Stdout is one ASCII JSON object and stderr is empty. Exit 0 means collection
completed; `overall=degraded` or `overall=unavailable` remains a valid result.
Exit 2 is a preflight/argument rejection. Exit 3 is a fail-closed internal or
serialization failure. The complete schema is fixed by
`docs/superpowers/specs/2026-07-14-codex-readonly-diagnostics-design.md`.

## Deployment and rollback

Deploy only a reviewed main Git blob to
`/home/jinnouchi/.local/libexec/shogun-codex-diagnostics` with mode `0555`.
Do not use sudo, a system directory, `/mnt/c`, a local manifest, or a cache.
Record each deployment through a separate Shogun work-log PR. Roll back by
revoking the full-command permission first, byte-safely removing the host marker,
and reverting the Workspace policy through a PR. Select an explicit superseded
GitHub record, extract its exact Git blob, and use the tested rollback primitive
only when the current bytes equal the failing active hash and the blob equals the
selected target hash. Record the restored deployment as the sole active record
through a separate Shogun work-log PR before any later re-enablement. The
rollback helper is never installed or persistently approved. Its exit 3 is a
verified pre-commit refusal only after exact cleanup succeeds. Exit 4 means
commit or exact temporary-artifact cleanup/durability is indeterminate and
requires external reconciliation plus a new explicit recovery task, with no
record update or automatic retry.
```

- [ ] **Step 7: Add the exact trusted-gate policy block to Shogun boundary docs**

Insert this block before `## Non-Goals` in `docs/github-boundary-operation.md`. Tasks 10 and 11 reuse the bytes between the markers exactly:

```markdown
<!-- BEGIN CODEX_SHOGUN_READONLY_DIAGNOSTICS_V1 -->
### Codex read-only diagnostics limited exception

The preceding prohibition remains in force. Immediately before each diagnostic
invocation, Codex must fetch GitHub `main` raw
`docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics-work-log.md`,
validate its single marked schema-version-1 JSON registry and exactly one active
deployment, then compare that record's source SHA-256 with the returned
`tool.source_sha256`.

Only this complete command is eligible for a persistent argv-prefix permission:

`wsl.exe -d Ubuntu --cd /home/jinnouchi/multi-agent-shogun /home/jinnouchi/.local/libexec/shogun-codex-diagnostics summary`

The installed mode-`0555` snapshot may locally aggregate only its fixed,
allowlisted Git/tmux/process/filesystem metadata and the counts of its four fixed
watcher-log substrings from at most the final 1,048,576 bytes. Codex receives
only schema-version-1 JSON. It does not directly read runtime files, logs, or
panes.

Before using any diagnostic field, Codex must require exit 0 and independently
validate ASCII-only bytes plus the complete nested schema, exact key order,
session/agent cardinality, enums, and count limits.

Do not persist a shorter `wsl.exe`, `bash -lc`, `python3`, or repo-script prefix.
`cat`, `grep`, YAML bodies, log lines, pane capture, arbitrary paths, sessions,
agents, regexes, shell commands, other scripts, suffix arguments, environment
overrides, starts, stops, restarts, repairs, and writes remain forbidden.

GitHub provenance retrieval or validation failure, no active deployment,
multiple active deployments, and source-hash mismatch are
`diagnostic_provenance_untrusted`. A nonzero exit, empty/non-JSON/partial output,
nonempty stderr, or execution of 10 seconds or more is `diagnostic_process_failed`. In both cases, do
not trust diagnostic fields and do not use any raw or direct-read fallback.
Snapshot placement or update is a separate, explicitly approved Shogun
deployment task and is not part of this exception.
<!-- END CODEX_SHOGUN_READONLY_DIAGNOSTICS_V1 -->
```

- [ ] **Step 8: Run GREEN integration and static boundary checks**

```bash
python3 -m unittest -v tests.unit.test_codex_diagnostics
python3 -m unittest -v tests.contract.test_codex_diagnostics_consumer
python3 -m unittest -v tests.unit.test_rollback_codex_diagnostics_snapshot
bats tests/unit/test_codex_diagnostics.bats
bats tests/integration/test_codex_diagnostics_tmux.bats
python3 -m py_compile \
  scripts/codex_diagnostics.py \
  scripts/rollback_codex_diagnostics_snapshot.py \
  tests/unit/test_codex_diagnostics.py \
  tests/unit/test_rollback_codex_diagnostics_snapshot.py \
  tests/contract/codex_diagnostics_consumer.py \
  tests/contract/test_codex_diagnostics_consumer.py \
  tests/integration/test_codex_diagnostics_tmux.py
python3 - <<'PY'
from pathlib import Path

source = Path("scripts/codex_diagnostics.py").read_text(encoding="utf-8")
boundary = Path("docs/github-boundary-operation.md").read_text(encoding="utf-8")
integration = Path(
    "tests/integration/test_codex_diagnostics_tmux.py"
).read_text(encoding="utf-8")
rollback = Path(
    "scripts/rollback_codex_diagnostics_snapshot.py"
).read_text(encoding="utf-8")
assert "capture-pane" not in source
assert "shell=True" not in source
assert "send-keys" not in integration
assert "kill-server" not in integration
assert "O_NOFOLLOW" in rollback
assert "RollbackCommitOrCleanupIndeterminate" in rollback
assert "complete nested schema" in boundary
assert boundary.count("<!-- BEGIN CODEX_SHOGUN_READONLY_DIAGNOSTICS_V1 -->") == 1
assert boundary.count("<!-- END CODEX_SHOGUN_READONLY_DIAGNOSTICS_V1 -->") == 1
PY
```

Expected: all tests PASS, compile exit 0, no skips, marker assertions pass.

- [ ] **Step 9: Commit the integration/docs slice**

```bash
git add -- \
  scripts/rollback_codex_diagnostics_snapshot.py \
  tests/unit/test_codex_diagnostics.bats \
  tests/unit/test_rollback_codex_diagnostics_snapshot.py \
  tests/contract/__init__.py \
  tests/contract/codex_diagnostics_consumer.py \
  tests/contract/test_codex_diagnostics_consumer.py \
  tests/integration/test_codex_diagnostics_tmux.py \
  tests/integration/test_codex_diagnostics_tmux.bats \
  docs/codex-diagnostics.md \
  docs/github-boundary-operation.md \
  Makefile
git diff --cached --name-only
git commit -m "feat: integrate readonly diagnostics safety gates"
```

Expected staged paths: exactly the eleven paths listed in `git add`.

### Task 8: Run the Frozen Source Verification and Open the Shogun PR

**Files:**

- Modify only when a test exposes a defect: files already listed in Tasks 1-7
- Verify: complete branch diff against the execution-time `origin/main`

**Interfaces:**

- Consumes: complete source branch.
- Produces: frozen reviewed commit, sanitized verification evidence, draft PR; no live deployment.

- [ ] **Step 1: Verify the exact branch scope**

Run:

```bash
git fetch origin --prune
git diff --name-only origin/main...HEAD | sort
git status --short --branch
git diff --check origin/main...HEAD
```

Expected diff paths are limited to:

```text
.gitignore
Makefile
docs/codex-diagnostics.md
docs/github-boundary-operation.md
docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics-work-log.md
docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics.md
docs/superpowers/specs/2026-07-14-codex-readonly-diagnostics-design.md
scripts/codex_diagnostics.py
scripts/rollback_codex_diagnostics_snapshot.py
tests/contract/__init__.py
tests/contract/codex_diagnostics_consumer.py
tests/contract/test_codex_diagnostics_consumer.py
tests/integration/test_codex_diagnostics_tmux.bats
tests/integration/test_codex_diagnostics_tmux.py
tests/unit/test_codex_diagnostics.bats
tests/unit/test_codex_diagnostics.py
tests/unit/test_rollback_codex_diagnostics_snapshot.py
```

Expected status: clean branch with no uncommitted/untracked files. Any instruction EOL-only path is a blocker and must not be staged.

- [ ] **Step 2: Run fresh functional and generated-output verification**

```bash
python3 -m unittest -v tests.unit.test_codex_diagnostics
python3 -m unittest -v tests.contract.test_codex_diagnostics_consumer
python3 -m unittest -v tests.unit.test_rollback_codex_diagnostics_snapshot
bats tests/unit/test_codex_diagnostics.bats
bats tests/integration/test_codex_diagnostics_tmux.bats
PYTHONPYCACHEPREFIX=/tmp/shogun-diagnostics-pycache \
  python3 -m py_compile \
  scripts/codex_diagnostics.py \
  scripts/rollback_codex_diagnostics_snapshot.py \
  tests/unit/test_codex_diagnostics.py \
  tests/unit/test_rollback_codex_diagnostics_snapshot.py \
  tests/contract/codex_diagnostics_consumer.py \
  tests/contract/test_codex_diagnostics_consumer.py \
  tests/integration/test_codex_diagnostics_tmux.py
make test
make lint
make build
git diff --exit-code -- instructions/generated/ .opencode/agents/ \
  instructions/shogun.md instructions/karo.md instructions/ashigaru.md \
  instructions/gunshi.md instructions/oometsuke.md AGENTS.md \
  .github/copilot-instructions.md agents/default/system.md agents/default/agent.yaml
```

Expected: every command exit 0; unittest/Bats report no skips; generated diff is empty.

- [ ] **Step 3: Verify tracking does not expand into runtime/private paths**

```bash
git check-ignore -q logs/inbox_watcher_ashigaru1.log
git check-ignore -q status/handoff_watchdog/ashigaru1.yaml
git check-ignore -q queue/shogun_to_karo.yaml
git check-ignore -q projects/private.yaml
git check-ignore -v \
  scripts/codex_diagnostics.py \
  scripts/rollback_codex_diagnostics_snapshot.py \
  tests/unit/test_codex_diagnostics.py \
  tests/unit/test_rollback_codex_diagnostics_snapshot.py \
  tests/contract/codex_diagnostics_consumer.py \
  tests/contract/test_codex_diagnostics_consumer.py \
  tests/integration/test_codex_diagnostics_tmux.py \
  docs/codex-diagnostics.md
```

Expected: first four commands exit 0; final command exits 1 with no output.

- [ ] **Step 4: Run pinned, redacted Gitleaks v8.30.1**

Use the [official Gitleaks v8.30.1 GitHub release](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1), Linux x64 asset, and its published SHA-256 `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb`. Download only to `/tmp`; do not install system-wide:

```bash
set -eu
archive=/tmp/gitleaks_8.30.1_linux_x64.tar.gz
tool_dir=/tmp/gitleaks-8.30.1
curl -fsSLo "$archive" \
  https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz
printf '%s  %s\n' \
  551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb \
  "$archive" | sha256sum -c -
mkdir -p "$tool_dir"
tar -xzf "$archive" -C "$tool_dir" gitleaks
"$tool_dir/gitleaks" version
"$tool_dir/gitleaks" git --redact --no-banner --config .gitleaks.toml .
"$tool_dir/gitleaks" dir --redact --no-banner --config .gitleaks.toml .
```

Expected: checksum `OK`, version `8.30.1`, both scans exit 0. Do not paste findings; any nonzero scan is a blocker.

- [ ] **Step 5: Obtain independent requirements and security/code-quality reviews**

Use `superpowers:requesting-code-review` twice on the frozen diff:

```text
Review A: compare every design-spec section with code/tests/docs; report missing behavior, schema drift, and unexpected coupling.
Review B: inspect source-hash boundary, dir-FD traversal, subprocess bounds, raw-data leakage, serialization fallback, consumer fail-closed fixtures, atomic rollback TOCTOU checks, and deployment policy; report exploitable or fail-open behavior.
```

Expected: both reviews return PASS. For any finding, use `superpowers:receiving-code-review`, reproduce it with a RED test, implement the smallest fix, rerun Steps 1-4, and create a focused commit.

- [ ] **Step 6: Push and open a draft PR without merging**

```bash
git status --short --branch
git push origin codex/add-readonly-diagnostics
pr="$(gh pr list --repo sjinnouchi-ux/multi-agent-shogun \
  --head codex/add-readonly-diagnostics --state open --json number --jq '.[0].number')"
if test -z "$pr"; then
  gh pr create \
    --repo sjinnouchi-ux/multi-agent-shogun \
    --base main \
    --head codex/add-readonly-diagnostics \
    --draft \
    --title "Add fail-closed Codex read-only diagnostics" \
    --body-file docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics-work-log.md
  pr="$(gh pr list --repo sjinnouchi-ux/multi-agent-shogun \
    --head codex/add-readonly-diagnostics --state open --json number --jq '.[0].number')"
fi
gh pr checks --watch --repo sjinnouchi-ux/multi-agent-shogun \
  "$pr"
```

Expected: branch push succeeds; draft PR targets `main`; all checks pass. The PR body contains only the initial sanitized work-log text and no runtime evidence.

- [ ] **Step 7: Stop for the source merge/deployment checkpoint**

Report the PR URL, head commit, check state, test counts, skip count, and review verdicts. Do not merge, touch the live WSL repo, place the snapshot, or relax Workspace/host policy until the user explicitly approves the next phase.

### Task 9: Merge the Approved Source and Deploy the Immutable WSL Snapshot

**Files:**

- Update through Git only: live WSL repo `/home/jinnouchi/multi-agent-shogun`
- Install atomically: `/home/jinnouchi/.local/libexec/shogun-codex-diagnostics`
- Create transient validation files under `/tmp`; remove them before handoff

**Interfaces:**

- Consumes: user-approved, reviewed, green Shogun PR.
- Produces: installed mode-`0555` snapshot and sanitized deployment facts; no deployment record or policy relaxation yet.

- [ ] **Step 1: Re-gate and merge the exact approved PR**

Derive the PR number from the branch, then verify it is approved and green:

```powershell
$Repo = 'sjinnouchi-ux/multi-agent-shogun'
$Pr = gh pr list --repo $Repo --head codex/add-readonly-diagnostics `
  --state open --json number --jq '.[0].number'
if (-not $Pr) { throw 'approved diagnostics PR not found' }
gh pr checks $Pr --repo $Repo
if ($LASTEXITCODE -ne 0) { throw 'PR checks are not green' }
$Meta = gh pr view $Pr --repo $Repo `
  --json isDraft,baseRefName,headRefName,reviewDecision | ConvertFrom-Json
if ($Meta.isDraft -or $Meta.baseRefName -ne 'main' -or
    $Meta.headRefName -ne 'codex/add-readonly-diagnostics' -or
    $Meta.reviewDecision -ne 'APPROVED') { throw 'PR approval gate failed' }
gh pr merge $Pr --repo $Repo --merge --delete-branch=false
if ($LASTEXITCODE -ne 0) { throw 'PR merge failed' }
$Merge = gh pr view $Pr --repo $Repo --json state,mergeCommit | ConvertFrom-Json
if ($Merge.state -ne 'MERGED' -or $Merge.mergeCommit.oid -notmatch '^[0-9a-f]{40}$') {
  throw 'merged commit unavailable'
}
$DeploySha = $Merge.mergeCommit.oid
```

Expected: merge succeeds through the PR; `$DeploySha` is a 40-character lowercase commit. Never push directly to `main`.

- [ ] **Step 2: Confirm the correct execution boundary without reading raw runtime state**

Request real-user execution approval, then run only:

```powershell
wsl.exe -d Ubuntu --cd /home/jinnouchi/multi-agent-shogun /usr/bin/id -un
wsl.exe -d Ubuntu --cd /home/jinnouchi/multi-agent-shogun /usr/bin/id -u
wsl.exe -d Ubuntu --cd /home/jinnouchi/multi-agent-shogun /usr/bin/pwd
```

Expected: user `jinnouchi`, UID is nonzero, cwd is `/home/jinnouchi/multi-agent-shogun`. An empty WSL list from the Codex isolation user remains `INCONCLUSIVE`; never use `ShogunUbuntu`.

- [ ] **Step 3: Fast-forward the clean stopped live repo**

Run each command separately through real-user WSL approval:

```powershell
wsl.exe -d Ubuntu --cd /home/jinnouchi/multi-agent-shogun /usr/bin/git diff --quiet
wsl.exe -d Ubuntu --cd /home/jinnouchi/multi-agent-shogun /usr/bin/git diff --cached --quiet
wsl.exe -d Ubuntu --cd /home/jinnouchi/multi-agent-shogun /usr/bin/git fetch origin --prune
wsl.exe -d Ubuntu --cd /home/jinnouchi/multi-agent-shogun /usr/bin/git switch main
wsl.exe -d Ubuntu --cd /home/jinnouchi/multi-agent-shogun /usr/bin/git merge --ff-only origin/main
wsl.exe -d Ubuntu --cd /home/jinnouchi/multi-agent-shogun /usr/bin/git rev-parse HEAD
```

Expected: clean gates and fast-forward exit 0; final SHA equals `$DeploySha`. If main moved, re-run the review/verification gate for the new main; do not reset or force.

- [ ] **Step 4: Run the deployment-host no-skip gate**

```powershell
wsl.exe -d Ubuntu --cd /home/jinnouchi/multi-agent-shogun `
  /usr/bin/timeout 1800 /usr/bin/make test-no-skip
```

Expected: exit 0, printed test count > 0, skips=0. Exit 124, missing dependency, any skip, or any test failure blocks deployment. Do not start Shogun or inspect panes/logs to make the test pass.

- [ ] **Step 5: Atomically install the first snapshot or prove it is already identical**

Run this one-time deployment script through an explicit, nonpersistent `bash -lc` approval. It never replaces a different existing file:

```bash
set -euo pipefail
umask 077
repo=/home/jinnouchi/multi-agent-shogun
source=scripts/codex_diagnostics.py
dest=/home/jinnouchi/.local/libexec/shogun-codex-diagnostics

test "$(id -un)" = jinnouchi
test "$(id -u)" -ne 0
test "$PWD" = "$repo"
test "$(git branch --show-current)" = main
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"
git diff --quiet
git diff --cached --quiet
case "$(git remote get-url origin)" in
  https://github.com/sjinnouchi-ux/multi-agent-shogun|\
  https://github.com/sjinnouchi-ux/multi-agent-shogun.git|\
  git@github.com:sjinnouchi-ux/multi-agent-shogun|\
  git@github.com:sjinnouchi-ux/multi-agent-shogun.git) ;;
  *) exit 1 ;;
esac
test "$(sed -n '1p' "$source")" = '#!/usr/bin/python3 -I'
python3 -I -c \
  'import pathlib,sys; compile(pathlib.Path(sys.argv[1]).read_bytes(), sys.argv[1], "exec")' \
  "$source"

if test -e /home/jinnouchi/.local || test -L /home/jinnouchi/.local; then
  test -d /home/jinnouchi/.local
  test ! -L /home/jinnouchi/.local
else
  /usr/bin/mkdir /home/jinnouchi/.local
fi
if test -e /home/jinnouchi/.local/libexec || test -L /home/jinnouchi/.local/libexec; then
  test -d /home/jinnouchi/.local/libexec
  test ! -L /home/jinnouchi/.local/libexec
else
  /usr/bin/mkdir /home/jinnouchi/.local/libexec
fi
test -d /home/jinnouchi/.local/libexec
source_sha="$(sha256sum "$source" | awk '{print $1}')"
test "${#source_sha}" -eq 64

if test -e "$dest" || test -L "$dest"; then
  test -f "$dest"
  test ! -L "$dest"
  test "$(stat -c '%U' "$dest")" = jinnouchi
  test "$(stat -c '%a' "$dest")" = 555
  test "$(sha256sum "$dest" | awk '{print $1}')" = "$source_sha"
  printf 'ALREADY_CURRENT %s\n' "$source_sha"
  exit 0
fi

tmp="$(mktemp /home/jinnouchi/.local/libexec/.shogun-codex-diagnostics.XXXXXXXX)"
cleanup() { test ! -e "$tmp" || /usr/bin/unlink "$tmp"; }
trap cleanup EXIT
/usr/bin/install -m 0555 -- "$source" "$tmp"
test "$(stat -c '%a' "$tmp")" = 555
test "$(sha256sum "$tmp" | awk '{print $1}')" = "$source_sha"
/usr/bin/mv -T -- "$tmp" "$dest"
tmp=''
test -f "$dest"
test ! -L "$dest"
test "$(stat -c '%U' "$dest")" = jinnouchi
test "$(stat -c '%a' "$dest")" = 555
test "$(sha256sum "$dest" | awk '{print $1}')" = "$source_sha"
printf 'DEPLOYED %s %s\n' "$(git rev-parse HEAD)" "$source_sha"
```

Expected: `DEPLOYED` or `ALREADY_CURRENT`, reviewed main commit, 64-character hash, mode `555`. A different pre-existing snapshot is a blocker; do not overwrite or delete it in this task.

- [ ] **Step 6: Validate fixed JSON and suffix rejection without exposing raw output**

Use transient files and print only safe verdicts:

```bash
set -euo pipefail
out="$(mktemp /tmp/shogun-diagnostics-out.XXXXXXXX)"
err="$(mktemp /tmp/shogun-diagnostics-err.XXXXXXXX)"
cleanup() { /usr/bin/unlink "$out" "$err" 2>/dev/null || true; }
trap cleanup EXIT
source_sha="$(sha256sum scripts/codex_diagnostics.py | awk '{print $1}')"

/home/jinnouchi/.local/libexec/shogun-codex-diagnostics summary >"$out" 2>"$err"
test ! -s "$err"
python3 -I - "$out" "$source_sha" <<'PY'
import json
import pathlib
import re
import sys

raw = pathlib.Path(sys.argv[1]).read_bytes()
value = json.loads(raw)
assert value["schema_version"] == 1
assert value["ok"] is True
assert value["overall"] in ("healthy", "degraded", "unavailable")
assert value["tool"] == {
    "version": "1.0.0",
    "deployment": "user_local_snapshot",
    "source_sha256": sys.argv[2],
}
assert len(value["sessions"]) == 2
assert len(value["agents"]) == 11
assert not re.search(rb"oauth|token|BEGIN [A-Z ]*PRIVATE KEY", raw, re.I)
print("diagnostic_contract=pass")
PY

set +e
/home/jinnouchi/.local/libexec/shogun-codex-diagnostics summary unexpected >"$out" 2>"$err"
rc="$?"
set -e
test "$rc" -eq 2
test ! -s "$err"
python3 -I - "$out" <<'PY'
import json
import pathlib
import sys
value = json.loads(pathlib.Path(sys.argv[1]).read_bytes())
assert value["errors"][0]["code"] == "argument_rejected"
assert value["tool"]["source_sha256"] is None
print("suffix_rejection=pass")
PY
test ! -e /home/jinnouchi/.local/share/shogun-codex-diagnostics/manifest.json
```

Expected safe stdout: `diagnostic_contract=pass` and `suffix_rejection=pass`; stderr files empty; transient files removed. `overall=unavailable` is valid while Shogun remains stopped.

- [ ] **Step 7: Stop before writing the GitHub deployment record**

Retain only these in-memory/sanitized facts: source merge commit, source SHA-256, UTC deployment time, mode `0555`, test count/pass/fail/skip counts, and contract verdicts. Do not persist raw diagnostic JSON. Continue immediately to Task 10; Workspace policy remains unchanged.

### Task 10: Record the Active Deployment in a Separate Shogun PR

**Files:**

- Modify only: `docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics-work-log.md`

**Interfaces:**

- Consumes: verified facts from Task 9.
- Produces: one active GitHub-main deployment record that Codex can trust per invocation.

- [ ] **Step 1: Create a fresh work-log branch from the new Shogun main**

```bash
git fetch origin --prune
git switch --create codex/record-readonly-diagnostics-deployment origin/main
git status --short --branch
```

Expected: clean dedicated branch based on the source merge commit or a reviewed descendant.

- [ ] **Step 2: Derive every record field from evidence, not memory**

Use these exact sources:

| Field | Source |
|---|---|
| `status` | literal `active` |
| `source_repo` | literal `https://github.com/sjinnouchi-ux/multi-agent-shogun` |
| `source_commit` | Task 9 merged source commit containing `scripts/codex_diagnostics.py` |
| `source_path` | literal `scripts/codex_diagnostics.py` |
| `source_sha256` | `sha256sum` of deployed bytes, already matched to source |
| `deployed_at` | `date -u +%Y-%m-%dT%H:%M:%SZ` captured immediately after install |
| `snapshot_path` | literal `/home/jinnouchi/.local/libexec/shogun-codex-diagnostics` |
| `snapshot_mode` | literal string `0555` after `stat` verification |
| `contract_schema_version` | integer `1` |

If the registry already has one active record, change its `status` to `superseded` in the same patch. Never create a second active record.

In the clean WSL work-log worktree, derive the three variable values with:

```bash
export SOURCE_COMMIT="$(gh pr list \
  --repo sjinnouchi-ux/multi-agent-shogun \
  --head codex/add-readonly-diagnostics \
  --state merged --json mergeCommit --jq '.[0].mergeCommit.oid')"
export SOURCE_SHA256="$(sha256sum scripts/codex_diagnostics.py | awk '{print $1}')"
git merge-base --is-ancestor "$SOURCE_COMMIT" origin/main
test "$(git show "$SOURCE_COMMIT:scripts/codex_diagnostics.py" | sha256sum | awk '{print $1}')" = "$SOURCE_SHA256"
snapshot=/home/jinnouchi/.local/libexec/shogun-codex-diagnostics
test "$(sha256sum "$snapshot" | awk '{print $1}')" = "$SOURCE_SHA256"
export DEPLOYED_AT="$(date -u -d "@$(stat -c %Y "$snapshot")" +%Y-%m-%dT%H:%M:%SZ)"
```

Expected: commit/hash regexes and snapshot equality pass; `DEPLOYED_AT` is UTC seconds.

- [ ] **Step 3: Update the marked one-line JSON and sanitized evidence with `apply_patch`**

Generate the exact one-line record from the observed values before using
`apply_patch`; never type a commit, hash, or timestamp from memory:

```python
import json
import os
import re

record = {
    "status": "active",
    "source_repo": "https://github.com/sjinnouchi-ux/multi-agent-shogun",
    "source_commit": os.environ["SOURCE_COMMIT"],
    "source_path": "scripts/codex_diagnostics.py",
    "source_sha256": os.environ["SOURCE_SHA256"],
    "deployed_at": os.environ["DEPLOYED_AT"],
    "snapshot_path": "/home/jinnouchi/.local/libexec/shogun-codex-diagnostics",
    "snapshot_mode": "0555",
    "contract_schema_version": 1,
}
assert re.fullmatch(r"[0-9a-f]{40}", record["source_commit"])
assert re.fullmatch(r"[0-9a-f]{64}", record["source_sha256"])
assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", record["deployed_at"])
print(json.dumps({"schema_version": 1, "deployments": [record]}, separators=(",", ":")))
```

The descriptive bullets may record only:

```markdown
- State: source implementation, deployment-host verification, and snapshot placement complete
- Deployment gate: `make test-no-skip` exit 0, test count greater than zero, skip 0
- Snapshot gate: source/deployed SHA-256 match, owner `jinnouchi`, mode `0555`
- Contract gate: schema 1 passed, suffix rejected, stderr empty
- Evidence boundary: no raw diagnostic JSON, pane, queue, report, log, or secret is recorded here
```

Before staging, parse the marked line and run the fixed registry validator in Step 4.

- [ ] **Step 4: Validate the fixed deployment registry**

```bash
python3 -I tests/contract/codex_diagnostics_consumer.py \
  validate-active-registry \
  docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics-work-log.md
python3 -W error -m unittest -v \
  tests.unit.test_codex_diagnostics \
  tests.contract.test_codex_diagnostics_consumer
git diff --check
git diff --name-only origin/main...HEAD
```

Expected: fixed `deployment_registry=pass`, all strict registry/work-log hostile
fixtures and unit tests pass without warnings/skips, diff check passes, and only
the work-log path changed. The shared validator rejects duplicate keys, wrong key
order/types/fixed values, non-real UTC seconds, and active zero/multiple.

- [ ] **Step 5: Commit, push, review, and stop for work-log merge approval**

```bash
git add -- docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics-work-log.md
git diff --cached --name-only
git commit -m "docs: record readonly diagnostics deployment"
git push origin codex/record-readonly-diagnostics-deployment
gh pr create \
  --repo sjinnouchi-ux/multi-agent-shogun \
  --base main \
  --head codex/record-readonly-diagnostics-deployment \
  --title "Record active Codex diagnostics deployment" \
  --body "Records sanitized immutable provenance only; no raw runtime evidence."
```

Expected: one-file PR. Obtain an independent schema/provenance review and explicit user approval before merging.

- [ ] **Step 6: Merge and verify the raw GitHub-main record**

After approval:

```bash
gh pr merge \
  --repo sjinnouchi-ux/multi-agent-shogun \
  "$(gh pr view --repo sjinnouchi-ux/multi-agent-shogun --json number --jq .number)" \
  --merge --delete-branch=false
```

Fetch the raw `main` work-log URL through the GitHub/web boundary into a bounded
transient file, repeat the Step 4 `validate-active-registry` command against those
exact raw bytes, and run the fixed installed command into a separate transient
file. Expected: exactly one active record and `tool.source_sha256` equals its
`source_sha256`. If any fetch/schema/hash check fails, classify
`diagnostic_provenance_untrusted`, remove transient output, and stop without fallback.

### Task 11: Enable the Workspace Policy and Preserve Host-Specific Rules

**Files:**

- Modify in a dedicated `workspace` clone: `codex/CODEX_DESKTOP_STARTUP.md`
- Modify: `codex/CODEX_DESKTOP_CUSTOM_INSTRUCTIONS.md`
- Modify: `codex/work_log.md`
- Modify after Workspace merge: `C:\Users\jinnouchi\.codex\AGENTS.md` marker block only

**Interfaces:**

- Consumes: raw GitHub-main active deployment record and hash match from Task 10.
- Produces: online canonical policy, host-local marker block, exact persistent argv prefix.

- [ ] **Step 1: Re-run Workspace canonical discovery and create a clean branch**

Fetch online Workspace startup and `PROJECTS.md` again. Verify default `main`, read its applicable instructions, then create a task-specific clone/branch:

```bash
git fetch origin --prune
git switch --create codex/shogun-readonly-diagnostics-policy origin/main
git status --short --branch
```

Expected: clean Workspace branch. Root `AGENTS.md` absence is acceptable only if confirmed online again; `PROJECTS.md` is not changed.

- [ ] **Step 2: Insert the exact Task 7 marker block in both canonical policy locations**

In `codex/CODEX_DESKTOP_STARTUP.md`, insert the exact bytes from Task 7 immediately after `## Shogun` → `### Runtime discovery` and its existing raw-state prohibition.

In `codex/CODEX_DESKTOP_CUSTOM_INSTRUCTIONS.md`, insert the same bytes inside `## Paste This Text`, immediately after the existing Shogun raw-state prohibition. Do not alter any existing prohibition.

Add these verification bullets to `CODEX_DESKTOP_CUSTOM_INSTRUCTIONS.md`:

```markdown
- Before every fixed diagnostic invocation, GitHub main has one valid active deployment and its source SHA-256 matches `tool.source_sha256`.
- The complete command exits 0, returns one fully schema-valid version-1 ASCII JSON object, has empty stderr, and finishes in under 10 seconds; `overall=degraded|unavailable` is not a process failure.
- Free text, pane/YAML/log bodies, paths, PID, command line, remote URL, exact runtime sizes, and runtime hashes are absent.
- Provenance/process failure never triggers a raw fallback, repo-script execution, shorter WSL permission, or direct runtime read.
```

- [ ] **Step 3: Add a sanitized Workspace work-log entry**

Append heading `## 2026-07-14｜Shogun読み取り専用診断ゲートの有効化` to `codex/work_log.md`. Under it, use `gh pr view --json url,mergeCommit` for the source PR and deployment-record PR and insert those actual public links/40-character commits with `apply_patch`. Then add these fixed evidence bullets:

```markdown
- Deployment: source/deployed SHA-256一致、mode `0555`、schema version 1
- Verification: deployment-host `make test-no-skip` exit 0、test count > 0、skip 0
- Policy: 固定command、実行直前のGitHub active record照合、raw fallback禁止だけを限定例外化
- Non-changes: Shogun watcher/queue/launcher/WebUI/runtime schema、credentials、raw runtime state
```

Do not record raw JSON or local paths beyond the fixed public command/snapshot path already in policy.

- [ ] **Step 4: Verify the Workspace three-file atomic diff**

```bash
python3 - <<'PY'
from pathlib import Path

begin = "<!-- BEGIN CODEX_SHOGUN_READONLY_DIAGNOSTICS_V1 -->"
end = "<!-- END CODEX_SHOGUN_READONLY_DIAGNOSTICS_V1 -->"
startup = Path("codex/CODEX_DESKTOP_STARTUP.md").read_text(encoding="utf-8")
custom = Path("codex/CODEX_DESKTOP_CUSTOM_INSTRUCTIONS.md").read_text(encoding="utf-8")
assert startup.count(begin) == startup.count(end) == 1
assert custom.count(begin) == custom.count(end) == 1
startup_block = begin + startup.split(begin, 1)[1].split(end, 1)[0] + end
custom_block = begin + custom.split(begin, 1)[1].split(end, 1)[0] + end
assert startup_block == custom_block
command = "wsl.exe -d Ubuntu --cd /home/jinnouchi/multi-agent-shogun /home/jinnouchi/.local/libexec/shogun-codex-diagnostics summary"
assert startup_block.count(command) == 1
assert "diagnostic_provenance_untrusted" in startup_block
assert "diagnostic_process_failed" in startup_block
PY
git diff --check
git diff --name-only origin/main...HEAD | sort
```

Expected changed files only:

```text
codex/CODEX_DESKTOP_CUSTOM_INSTRUCTIONS.md
codex/CODEX_DESKTOP_STARTUP.md
codex/work_log.md
```

- [ ] **Step 5: Commit, push, review, and stop for Workspace merge approval**

```bash
git add -- codex/CODEX_DESKTOP_STARTUP.md codex/CODEX_DESKTOP_CUSTOM_INSTRUCTIONS.md codex/work_log.md
git diff --cached --name-only
git commit -m "docs(codex): gate fixed Shogun diagnostics snapshot"
git push origin codex/shogun-readonly-diagnostics-policy
gh pr create \
  --repo sjinnouchi-ux/workspace \
  --base main \
  --head codex/shogun-readonly-diagnostics-policy \
  --title "Gate fixed Shogun diagnostics snapshot" \
  --body "Depends on the merged Shogun source and active deployment record; preserves all raw-state prohibitions."
```

Expected: three-file PR. Obtain independent policy review and explicit user approval before merge.

- [ ] **Step 6: Merge Workspace and verify raw main**

After approval, merge through the PR. Fetch raw GitHub main copies of all three files and rerun the marker/block equality assertions. If raw main differs, stop before changing host policy.

- [ ] **Step 7: Perform the one-time host marker insertion without replacing the file**

Read `C:\Users\jinnouchi\.codex\AGENTS.md` at the correct Codex host/credential boundary. Require marker count zero and exactly one copy of the existing Shogun raw-state prohibition anchor. Copy it to the task workspace, use `apply_patch` to insert the exact merged marker block after that anchor, then validate before requesting the single-file elevated copy:

```powershell
$Before = [IO.File]::ReadAllBytes('C:\Users\jinnouchi\.codex\AGENTS.md')
$CandidatePath = (Resolve-Path '.\AGENTS.host.candidate.md')
$Candidate = [IO.File]::ReadAllBytes($CandidatePath)
$Utf8 = [Text.UTF8Encoding]::new($false, $true)
$Begin = $Utf8.GetBytes('<!-- BEGIN CODEX_SHOGUN_READONLY_DIAGNOSTICS_V1 -->')
$End = $Utf8.GetBytes('<!-- END CODEX_SHOGUN_READONLY_DIAGNOSTICS_V1 -->')

function Find-ByteOffsets([byte[]]$Data, [byte[]]$Pattern) {
    $Offsets = @()
    for ($i = 0; $i -le $Data.Length - $Pattern.Length; $i++) {
        $Match = $true
        for ($j = 0; $j -lt $Pattern.Length; $j++) {
            if ($Data[$i + $j] -ne $Pattern[$j]) { $Match = $false; break }
        }
        if ($Match) { $Offsets += $i }
    }
    return $Offsets
}

$BeforeBegin = @(Find-ByteOffsets $Before $Begin)
$CandidateBegin = @(Find-ByteOffsets $Candidate $Begin)
$CandidateEnd = @(Find-ByteOffsets $Candidate $End)
if ($BeforeBegin.Count -ne 0) {
    throw 'host marker already exists; use reviewed block update flow'
}
if ($CandidateBegin.Count -ne 1 -or $CandidateEnd.Count -ne 1) {
    throw 'candidate marker count invalid'
}
$Start = [int]$CandidateBegin[0]
$EndStart = [int]$CandidateEnd[0]
if ($EndStart -le $Start) { throw 'candidate marker order invalid' }
$Finish = $EndStart + $End.Length
if ($Finish + 1 -lt $Candidate.Length -and
    $Candidate[$Finish] -eq 13 -and $Candidate[$Finish + 1] -eq 10) {
    $Finish += 2
} elseif ($Finish -lt $Candidate.Length -and $Candidate[$Finish] -eq 10) {
    $Finish += 1
}
$WithoutBlock = [byte[]]::new($Candidate.Length - ($Finish - $Start))
[Array]::Copy($Candidate, 0, $WithoutBlock, 0, $Start)
[Array]::Copy(
    $Candidate, $Finish, $WithoutBlock, $Start, $Candidate.Length - $Finish
)
if ([Convert]::ToBase64String($WithoutBlock) -ne
    [Convert]::ToBase64String($Before)) {
    throw 'bytes outside inserted block changed'
}
```

Expected: candidate minus the marker block is byte-identical to the original, including BOM and line endings. Request approval to copy the candidate to the host path, re-read it with `ReadAllBytes`, require exact byte equality with `$Candidate`, rerun the marker count, then delete the candidate. Do not replace the whole host file with `Paste This Text`; preserve stricter host-only authentication/surface rules.

After the approved copy, require this exact post-check before deleting the candidate:

```powershell
$Installed = [IO.File]::ReadAllBytes('C:\Users\jinnouchi\.codex\AGENTS.md')
if ([Convert]::ToBase64String($Installed) -ne
    [Convert]::ToBase64String($Candidate)) {
    throw 'installed host bytes differ from reviewed candidate'
}
$InstalledBegin = @(Find-ByteOffsets $Installed $Begin)
$InstalledEnd = @(Find-ByteOffsets $Installed $End)
if ($InstalledBegin.Count -ne 1 -or $InstalledEnd.Count -ne 1 -or
    $InstalledEnd[0] -le $InstalledBegin[0]) {
    throw 'installed host marker pair invalid'
}
```

- [ ] **Step 8: Request only the complete persistent argv prefix**

Use the command approval mechanism with this full token list and no shorter rule:

```text
wsl.exe
-d
Ubuntu
--cd
/home/jinnouchi/multi-agent-shogun
/home/jinnouchi/.local/libexec/shogun-codex-diagnostics
summary
```

The CLI's suffix rejection is the second boundary. Do not grant persistent approval to `wsl.exe`, `bash -lc`, `python3`, the repo source path, or the snapshot path without `summary`.

### Task 12: Smoke-Test Both Codex Task Boundaries, Record Completion, and Clean Up

**Files:**

- Modify only if recording final public evidence requires it: existing Shogun and Workspace work logs through separate reviewed PRs
- Remove: transient validation outputs and task-only host candidate copy

**Interfaces:**

- Consumes: merged Shogun record, merged Workspace policy, host marker, full argv prefix.
- Produces: current-task and fresh-task trust evidence, rollback readiness, pushed clean workspaces.

- [ ] **Step 1: Validate provenance immediately before the current-task smoke test**

Fetch the raw Shogun main work log, validate exactly one active record with the Task 10 validator, then invoke only:

```powershell
wsl.exe -d Ubuntu --cd /home/jinnouchi/multi-agent-shogun /home/jinnouchi/.local/libexec/shogun-codex-diagnostics summary
```

Capture exit code/stdout/stderr privately, require exit 0, validate the complete nested schema, require ASCII-only output, stderr empty, runtime under 10 seconds, and exact active-record hash match. Report only `provenance=pass`, `contract=pass`, `overall` enum, errors/warnings counts, and elapsed class; do not display raw JSON.

- [ ] **Step 2: Validate suffix rejection under the approved prefix**

Invoke the same command with one extra literal `unexpected`. Expected: exit 2, safe JSON, empty stderr, `argument_rejected`, `source_sha256=null`, and no collector side effect. This proves a prefix permission cannot be extended into a raw mode.

- [ ] **Step 3: Repeat from a fresh Codex task**

Ask the user to open one new Codex task on the same host. That task must follow online startup/PROJECTS discovery, fetch/validate the active deployment record, and run the same fixed command. Expected: the same provenance/contract verdicts without reauthorizing a shorter command. If the new task cannot execute, classify it as a permission/bootstrap failure and keep direct runtime reads forbidden.

- [ ] **Step 4: Exercise the fail-closed consumer cases without live runtime reads**

Run the committed reusable consumer harness against only its local synthetic registry/output fixtures:

```bash
python3 -m unittest -v tests.contract.test_codex_diagnostics_consumer
PYTHONPYCACHEPREFIX=/tmp/shogun-diagnostics-consumer-pycache \
  python3 -m py_compile \
  tests/contract/codex_diagnostics_consumer.py \
  tests/contract/test_codex_diagnostics_consumer.py
```

Expected: the harness parses real synthetic bytes and reports PASS for GitHub fetch failure, missing/duplicate/reversed marker, deep or bad registry/output schema, active zero/multiple, hash mismatch, empty/partial/multiple JSON, nested free text, wrong cardinality, literal non-ASCII, nonzero exit, nonempty stderr, and deadline expiry. Every rejected `ConsumerDecision` has `action=stop_without_fallback` and `fallback_allowed=False`; no case invokes a command or reads live runtime state.

- [ ] **Step 5: Prove rollback readiness and retain an explicit atomic procedure**

Run the atomic rollback tests again on the deployment host:

```bash
python3 -m unittest -v tests.unit.test_rollback_codex_diagnostics_snapshot
```

Expected: same-directory mode-`0555` atomic replacement passes; wrong current hash, wrong target hash, missing `O_NOFOLLOW`, symlink input, and a verified pre-commit replacement failure preserve the original bytes and remove the temporary file with exit 3. A post-commit fsync/verification failure or unprovable exact temporary cleanup/durability state returns exit 4 and requires external snapshot/artifact reconciliation before any work-log update.

Do not roll back during a healthy deployment. If a later failure requires rollback, stop Shogun and obtain explicit user approval for the exact failing active record and exact superseded target record. Then execute this fixed order; a failure at any gate stops the flow:

1. Revoke the persistent full-command approval before any file change and verify a fresh task no longer has that approval. Do not substitute a shorter prefix.
2. Copy host `AGENTS.md` to a task candidate, remove only the one marker block with `apply_patch`, and run the Task 11 raw-byte comparison in reverse: candidate bytes plus the removed marker/newline must equal the original bytes exactly, including BOM and line endings. After elevated replacement, `ReadAllBytes` must equal the candidate.
3. In a clean Workspace branch from current `origin/main`, revert only the diagnostics-policy merge commit, verify the three-file scope, open a PR, obtain review and user approval, merge it, and verify raw GitHub main before proceeding.
4. In a fresh clean Shogun worktree at current `origin/main`, fetch and validate the raw deployment registry with the Task 10 validator. The user selects one exact `superseded` record by its 40-character `source_commit` and UTC `deployed_at`; require exactly one matching record. Derive `FAILING_SHA256` from the sole active record and `TARGET_SHA256` from that selected record without printing either value.
5. Extract and verify the target Git blob, then run the tested primitive:

```bash
set -eu
git fetch origin --prune
git merge-base --is-ancestor "$TARGET_COMMIT" origin/main
target_blob="$(mktemp /tmp/shogun-codex-diagnostics-rollback.XXXXXX)"
trap 'rm -f "$target_blob"' EXIT
git show "$TARGET_COMMIT:scripts/codex_diagnostics.py" >"$target_blob"
test "$(sha256sum "$target_blob" | awk '{print $1}')" = "$TARGET_SHA256"
snapshot=/home/jinnouchi/.local/libexec/shogun-codex-diagnostics
test "$(stat -c %a "$snapshot")" = 555
test "$(sha256sum "$snapshot" | awk '{print $1}')" = "$FAILING_SHA256"
set +e
python3 -I scripts/rollback_codex_diagnostics_snapshot.py \
  --failing-sha256 "$FAILING_SHA256" \
  --target-sha256 "$TARGET_SHA256" \
  --target-blob "$target_blob"
rollback_rc="$?"
set -e
if [ "$rollback_rc" -eq 3 ]; then
  test "$(sha256sum "$snapshot" | awk '{print $1}')" = "$FAILING_SHA256"
  exit 3
fi
if [ "$rollback_rc" -eq 4 ]; then
  rollback_state=unreadable
  if [ -f "$snapshot" ] && [ ! -L "$snapshot" ]; then
    observed_mode="$(stat -c %a "$snapshot" 2>/dev/null || true)"
    observed_sha="$(sha256sum "$snapshot" 2>/dev/null | awk '{print $1}')"
    if printf '%s\n' "$observed_sha" | grep -Eq '^[0-9a-f]{64}$'; then
      if [ "$observed_mode" = 555 ] && [ "$observed_sha" = "$TARGET_SHA256" ]; then
        rollback_state=target
      elif [ "$observed_mode" = 555 ] && [ "$observed_sha" = "$FAILING_SHA256" ]; then
        rollback_state=failing
      else
        rollback_state=other
      fi
    fi
  fi
  echo "rollback_state=$rollback_state"
  exit 4
fi
test "$rollback_rc" -eq 0
test "$(stat -c %a "$snapshot")" = 555
test "$(sha256sum "$snapshot" | awk '{print $1}')" = "$TARGET_SHA256"
```

Expected: the current hash is rechecked inside the primitive immediately before a same-directory `os.replace`; exit 0 means the installed bytes exactly match the selected Git blob at mode `0555`. Exit 3 proves the failing bytes remain and exact cleanup completed, then stops. Exit 4 means commit state or exact temporary-artifact cleanup/durability state is indeterminate; the wrapper safely classifies the snapshot as only `target|failing|other|unreadable`, never prints the hash, always exits 4, and also reconciles any preserved temporary artifact only in a new explicit recovery task. Exit 4 must never be silently retried or recorded as active.

6. From a new Shogun work-log branch, change the failing record to `superseded` and append a new sole `active` record for the restored target commit/hash with the newly observed deployment timestamp. Run the Task 10 validator, commit only the work-log, open a PR, obtain independent review and explicit user approval, merge, and verify raw GitHub main.
7. Leave the host marker, Workspace exception, and command approval disabled. Re-enablement is a new reviewed deployment task. Never use `git reset --hard`, force push, an unverified local backup, Task 9's first-install helper, or a direct runtime-data fallback.

- [ ] **Step 6: Run final Git/GitHub cleanliness checks and remove task-local artifacts**

For every task clone/worktree:

```bash
git status --short --branch
git log --oneline --decorate -5
git branch -vv
```

Expected: no uncommitted/untracked work, every required commit pushed, no local-only report/evidence. Remove only verified task-specific clones/worktrees after their branches and PR/merge results are on GitHub. Do not clean the live WSL repo or unrelated user work.

- [ ] **Step 7: Hand off the completed result**

Report:

- Shogun source PR and merge commit;
- post-deployment work-log PR and merge commit;
- Workspace policy PR and merge commit;
- source/snapshot hash match and mode `0555` without printing raw output;
- `make test-no-skip` test/pass/fail/skip counts;
- current/new Codex task provenance/contract verdicts;
- unchanged existing Shogun control files/runtime schema count;
- rollback readiness and any explicitly deferred v2 items.

## Spec Coverage Map

| Design requirement | Implementation/verification task |
|---|---|
| Independent one-command CLI, suffix rejection, source hash, fixed failure JSON | Tasks 1, 6, 7 |
| Bounded absolute command execution and hostile-environment isolation | Task 2 |
| dir-FD/O_NOFOLLOW metadata, fixed source maps, no content read | Task 3 |
| bounded watcher-log tail and five count-only outputs | Task 3 |
| variable tmux formation, unknown/duplicate/dead/mismatch handling | Tasks 4, 7 |
| supervisor and observed-agent watcher counts without PID/command line | Task 4 |
| canonical Git boundary, branch class, SHA, dirty/counts without names/URLs | Task 5 |
| exact nested schema, issue caps/order, overall states, serialization/signal fallback | Task 6 |
| no-skip deployment gate, executable consumer fixtures, tested atomic rollback, real isolated tmux, docs and GitHub boundary exception | Task 7 |
| regression, generated diff, tracking negative tests, pinned secret scan, independent review | Task 8 |
| reviewed main merge, stopped-host test, atomic mode-0555 snapshot, no manifest/cache | Task 9 |
| unique active GitHub deployment provenance and raw-main revalidation | Task 10 |
| separate Workspace PR, marker-identical policy, host outside-byte preservation, full argv prefix | Task 11 |
| per-run provenance, current/new task smoke tests, executable fail-closed cases, ordered atomic rollback procedure, and cleanup | Task 12 |
| Existing watcher/queue/launcher/agent-status/WebUI/runtime-schema changes = 0 | Global Constraints and Tasks 8, 12 |
| Raw/YAML/pane/log content analysis and automatic repair remain deferred | Global Constraints, Tasks 7, 12 |

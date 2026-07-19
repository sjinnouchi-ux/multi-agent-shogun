# Codex Diagnostics Inbox Symlink Hotfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the immutable Codex diagnostics snapshot recognize Shogun's exact canonical inbox symlink without weakening its fail-closed no-follow boundary.

**Architecture:** Resolve `queue/inbox` once through a pinned directory-FD binding. A regular in-repository directory remains valid; the only accepted symlink string is `/home/jinnouchi/.local/share/multi-agent-shogun/inbox`, whose target is independently traversed component-by-component with `O_NOFOLLOW`, ownership and mode checks. Route only inbox leaves through that pinned FD, revalidate both repository and fixed-root bindings after collection, and keep schema-version-1 JSON unchanged.

**Tech Stack:** Python 3.10+, Linux directory-FD APIs, `unittest`, Bats, Make, tmux-isolated integration tests.

## Global Constraints

- Work only in the dedicated clone and branch `codex/diagnostics-source-rejected-hotfix` based on main `a3f21a6c62bc5b3c48f0b1501caff1ace5da5544`.
- Do not modify the live `/home/jinnouchi/multi-agent-shogun` checkout while implementing or testing.
- Do not read or copy live panes, queue bodies, reports or logs into fixtures or output.
- Keep schema version `1`, exact JSON key order, issue vocabulary and consumer validation unchanged.
- Accept no production CLI argument, environment variable, `HOME` value, repository setting or runtime file as an inbox-root override.
- Do not change watcher delivery, busy/idle semantics, WebUI, permission handling, startup behavior or P2 behavior.
- Use isolated temporary directories and sanitized file bodies only.
- Run `make test-no-skip` only on the deployment host; any test skip is a failure.
- Snapshot placement, registry mutation and live startup occur only after the reviewed code PR is merged.

## File Map

- Modify `scripts/codex_diagnostics.py`: fixed inbox binding, secure traversal, source-root routing and post-collection revalidation.
- Modify `.gitignore`: explicitly allow the isolated diagnostics-source integration file under the repository's deny-by-default policy.
- Modify `tests/unit/test_codex_diagnostics.py`: resolver, rejection, race, routing, leaf-state and FD-cleanup regressions.
- Create `tests/integration/test_codex_diagnostics_sources.py`: isolated launcher-shaped symlink fixture covering all eleven agents.
- Modify `tests/integration/test_codex_diagnostics_tmux.bats`: run the new source integration suite without changing the isolated tmux test.
- Modify `tests/unit/test_codex_diagnostics.bats`: compile the new integration source.
- Modify `docs/superpowers/specs/2026-07-19-codex-diagnostics-inbox-symlink-design.md`: mark the reviewed design approved when implementation starts.
- Later, in a separate deployment branch, modify `docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics-work-log.md`: supersede the active immutable-snapshot registry record and record sanitized acceptance results.

---

### Task 1: Establish the Resolver RED Tests

**Files:**
- Modify: `tests/unit/test_codex_diagnostics.py`

**Interfaces:**
- Consumes: existing `SourceMissing`, `SourceRejected`, `SourceIOError` and directory-FD helpers.
- Produces test contract for: `open_inbox_root(runtime_root_fd, *, expected_link=INBOX_LINK_TARGET, traversal_root_fd=None, target_parts=INBOX_TARGET_PARTS) -> InboxRootBinding` and `close_inbox_root(binding) -> None`.

- [x] **Step 1: Record the focused pre-change baseline**

Run on Linux/WSL from the dedicated clone:

```bash
python3 -m unittest -v tests.unit.test_codex_diagnostics.SafePathAndLogTests
```

Expected: current tests pass with `FAILED` absent and `skipped=` absent.

- [x] **Step 2: Add a real-filesystem fixture and exact-link tests**

Add `InboxRootTests` with a mode-`0700` traversal anchor and sanitized leaves. The fixture must create the repository link with the production string while redirecting only the internal helper traversal to the isolated target:

```python
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

    def open_binding(self):
        return self.module.open_inbox_root(
            self.repo_fd,
            traversal_root_fd=self.anchor_fd,
            target_parts=("fixed", "inbox"),
        )

    def test_exact_canonical_link_opens_isolated_fixed_root(self) -> None:
        m = self.module
        (self.repo / "queue" / "inbox").symlink_to(m.INBOX_LINK_TARGET)
        binding = self.open_binding()
        try:
            opened = os.fstat(binding.inbox_fd)
            expected = os.stat(self.anchor / "fixed" / "inbox")
            self.assertEqual((opened.st_dev, opened.st_ino), (expected.st_dev, expected.st_ino))
        finally:
            m.close_inbox_root(binding)

    def test_regular_repository_inbox_remains_supported(self) -> None:
        m = self.module
        (self.repo / "queue" / "inbox").mkdir(mode=0o700)
        binding = self.open_binding()
        try:
            opened = os.fstat(binding.inbox_fd)
            expected = os.stat(self.repo / "queue" / "inbox")
            self.assertEqual((opened.st_dev, opened.st_ino), (expected.st_dev, expected.st_ino))
        finally:
            m.close_inbox_root(binding)

    def test_wrong_or_relative_link_target_is_rejected(self) -> None:
        m = self.module
        for target in ("/tmp/not-allowed", "fixed/inbox", m.INBOX_LINK_TARGET + "/"):
            link = self.repo / "queue" / "inbox"
            if link.is_symlink():
                link.unlink()
            link.symlink_to(target)
            with self.subTest(target=target), self.assertRaises(m.SourceRejected):
                self.open_binding()
```

- [x] **Step 3: Add fail-closed traversal tests before production code**

Add tests that require `SourceMissing` for an absent fixed target and `SourceRejected` for a symlinked target component, mode `0770`, a non-directory target component and missing `O_NOFOLLOW`. Use `mock.patch.object(m.os, "O_NOFOLLOW", None)` only for the unsupported-platform case; all path cases use real files.

- [x] **Step 4: Run each new test and verify RED**

```bash
python3 -m unittest -v tests.unit.test_codex_diagnostics.InboxRootTests
```

Expected: fail because `INBOX_LINK_TARGET`, `open_inbox_root` and `InboxRootBinding` do not exist. A syntax error, fixture error or permission error is not an acceptable RED result.

- [x] **Step 5: Commit the RED tests**

```bash
git add tests/unit/test_codex_diagnostics.py
git commit -m "test: reproduce diagnostics inbox link rejection"
```

### Task 2: Implement the Fixed Root and Binding Verification

**Files:**
- Modify: `scripts/codex_diagnostics.py`
- Modify: `tests/unit/test_codex_diagnostics.py`

**Interfaces:**
- Consumes: Task 1 tests.
- Produces: `InboxRootBinding`, `open_inbox_root`, `verify_inbox_root`, `close_inbox_root`, fixed `INBOX_LINK_TARGET` and `INBOX_TARGET_PARTS`.

- [x] **Step 1: Add constants, binding data and source-error translation**

Add immutable production constants and an internal FD-owning record:

```python
INBOX_LINK_TARGET = "/home/jinnouchi/.local/share/multi-agent-shogun/inbox"
INBOX_TARGET_PARTS = (
    "home", "jinnouchi", ".local", "share", "multi-agent-shogun", "inbox"
)

@dataclass(slots=True)
class InboxRootBinding:
    inbox_fd: int
    queue_fd: int
    repository_kind: str
    repository_key: tuple[int, int, int, int, int, int]
    repository_target: str | None
    traversal_root_fd: int
    target_parts: tuple[str, ...]
    target_identity: tuple[int, int] | None
```

The repository key is `(st_dev, st_ino, stat.S_IFMT(st_mode), st_size, st_mtime_ns, st_ctime_ns)`. Convert `FileNotFoundError` to `SourceMissing`, `ELOOP`/`ENOTDIR`/`EINVAL` to `SourceRejected`, and other `OSError`, `TypeError` or `NotImplementedError` to `SourceIOError` without retaining exception text.

- [x] **Step 2: Implement component-by-component directory opening**

Add `_open_directory_beneath(root_fd, parts, *, trusted, require_final_euid)`. It must duplicate the supplied root, use `O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW` for every component, validate each trusted directory as root/effective-user owned and not group/world writable, require the final fixed inbox directory to be effective-user owned, and close every superseded or failing FD.

- [x] **Step 3: Implement `open_inbox_root` minimally to satisfy Task 1**

Open `queue` beneath the repository FD; inspect `inbox` with `os.stat(..., follow_symlinks=False)`. For a directory, open and pin it and compare device/inode with the inspected entry. For a symlink, require the exact stored string, duplicate the test traversal root or open `/`, traverse the immutable component tuple independently, and pin the target. Reject all other file types. Close all partially acquired FDs on every exception.

- [x] **Step 4: Run the resolver tests and verify GREEN**

```bash
python3 -m unittest -v tests.unit.test_codex_diagnostics.InboxRootTests
```

Expected: all resolver tests pass, with zero skips.

- [x] **Step 5: Add binding-swap RED tests**

Add two real-filesystem tests:

```python
def test_repository_symlink_swap_is_rejected_at_verification(self) -> None:
    m = self.module
    link = self.repo / "queue" / "inbox"
    link.symlink_to(m.INBOX_LINK_TARGET)
    binding = self.open_binding()
    self.addCleanup(m.close_inbox_root, binding)
    link.unlink()
    link.symlink_to(m.INBOX_LINK_TARGET)
    with self.assertRaises(m.SourceRejected):
        m.verify_inbox_root(binding)

def test_fixed_target_directory_swap_is_rejected_at_verification(self) -> None:
    m = self.module
    (self.repo / "queue" / "inbox").symlink_to(m.INBOX_LINK_TARGET)
    binding = self.open_binding()
    self.addCleanup(m.close_inbox_root, binding)
    original = self.anchor / "fixed" / "inbox"
    moved = self.anchor / "fixed" / "old-inbox"
    original.rename(moved)
    original.mkdir(mode=0o700)
    with self.assertRaises(m.SourceRejected):
        m.verify_inbox_root(binding)
```

Run both methods individually. Expected: fail because `verify_inbox_root` does not exist.

- [x] **Step 6: Implement post-collection binding verification**

For a repository directory, compare the current no-follow entry and pinned FD by type/device/inode. For a repository symlink, compare the complete recorded key and exact `readlink` value. Reopen the fixed target from the pinned traversal root with the same secure helper and require its device/inode to match `target_identity`. Convert every mismatch to `SourceRejected`; never emit path or exception text.

- [x] **Step 7: Verify GREEN and FD cleanup**

Run the full `InboxRootTests`, including a test that counts the FDs owned by the returned binding and confirms `close_inbox_root` closes each exactly once even after a verification failure.

- [x] **Step 8: Commit the secure resolver**

```bash
git add scripts/codex_diagnostics.py tests/unit/test_codex_diagnostics.py
git commit -m "fix: allow the canonical diagnostics inbox root"
```

### Task 3: Route Inbox Metadata Through the Pinned Root

**Files:**
- Modify: `scripts/codex_diagnostics.py`
- Modify: `tests/unit/test_codex_diagnostics.py`
- Create: `tests/integration/test_codex_diagnostics_sources.py`
- Modify: `tests/integration/test_codex_diagnostics_tmux.bats`
- Modify: `tests/unit/test_codex_diagnostics.bats`

**Interfaces:**
- Consumes: Task 2 `open_inbox_root`, `verify_inbox_root` and `close_inbox_root`.
- Produces: `SourceSpec.root` with values `runtime` or `inbox`, and `collect_runtime_sources(..., inbox_opener=open_inbox_root)`.

- [x] **Step 1: Add collection RED tests**

Add unit tests proving that all eleven canonical-link inbox leaves are `present`, a nonregular leaf alone is `rejected`, a missing leaf alone is `missing`, and a verification failure discards provisional leaf results and rejects every applicable inbox source. Assert issues contain only sanitized `Issue("source_rejected", "source", agent)` values and no path text.

Use an injected opener so the production default remains immutable:

```python
opener = lambda root_fd: m.open_inbox_root(
    root_fd,
    traversal_root_fd=self.anchor_fd,
    target_parts=("fixed", "inbox"),
)
collection = m.collect_runtime_sources(
    self.repo_fd,
    frozenset(m.AGENT_IDS),
    inbox_opener=opener,
)
for agent in m.AGENT_IDS:
    self.assertEqual(collection.agent_sources[agent]["inbox"]["state"], "present")
self.assertNotIn("source_rejected", {issue.code for issue in collection.errors})
```

Run the new collection methods individually. Expected: fail because `collect_runtime_sources` does not accept `inbox_opener` and current inbox parts still traverse `queue/inbox` under the runtime root.

- [x] **Step 2: Add the isolated integration RED test**

Create `tests/integration/test_codex_diagnostics_sources.py` with a mode-`0700` temporary repository, exact production link string, injected safe traversal root and eleven sanitized `messages:\n` leaves. Call the real collection path, assert eleven `present` states, exact source-value key order, and absence of `source_rejected` for inboxes. Do not access `/home/jinnouchi/.local/share/multi-agent-shogun/inbox`.

Add this Bats case to `tests/integration/test_codex_diagnostics_tmux.bats`:

```bash
@test "codex diagnostics accepts the isolated canonical inbox geometry" {
    run python3 -m unittest -v \
        tests.integration.test_codex_diagnostics_sources
    [ "$status" -eq 0 ]
    [[ "$output" != *"skipped="* ]]
}
```

Add the new Python file to the existing `py_compile` command in `tests/unit/test_codex_diagnostics.bats`. Run the integration method directly and confirm RED for the same missing routing API.

- [x] **Step 3: Implement root selection and atomic inbox result replacement**

Extend `SourceSpec` without breaking existing three-argument construction:

```python
@dataclass(frozen=True, slots=True)
class SourceSpec:
    key: str
    parts: tuple[str, ...]
    applicability: str
    root: str = "runtime"
```

Change only the inbox spec to `SourceSpec("inbox", (f"{agent}.yaml",), required_or_optional, "inbox")`. Add `_source_failure` to centralize current missing/rejected/error severity mapping. Acquire the inbox binding once, collect eleven leaves relative to `binding.inbox_fd`, verify after collection, then close it. If acquisition or final verification fails, replace every provisional applicable inbox value and issue with the single root failure classification at each agent's existing required/optional severity. Continue collecting task, report, handoff-status, watcher-log and global sources from `runtime` unchanged.

- [x] **Step 4: Verify focused GREEN and schema compatibility**

```bash
python3 -m unittest -v tests.unit.test_codex_diagnostics.InboxRootTests
python3 -m unittest -v tests.unit.test_codex_diagnostics.SafePathAndLogTests
python3 -m unittest -v tests.integration.test_codex_diagnostics_sources
python3 -m unittest -v tests.contract.test_codex_diagnostics_consumer
bats tests/unit/test_codex_diagnostics.bats
bats tests/integration/test_codex_diagnostics_tmux.bats
```

Expected: every command exits `0`; no output contains `FAILED`, `not ok` or `skipped=`. The consumer module and schema version remain unmodified.

- [x] **Step 5: Commit routing and integration coverage**

```bash
git add scripts/codex_diagnostics.py tests/unit/test_codex_diagnostics.py \
  tests/integration/test_codex_diagnostics_sources.py \
  tests/integration/test_codex_diagnostics_tmux.bats \
  tests/unit/test_codex_diagnostics.bats
git commit -m "test: cover canonical diagnostics inbox geometry"
```

### Task 4: Documentation, Full Regression and Independent Review

**Files:**
- Modify: `docs/superpowers/specs/2026-07-19-codex-diagnostics-inbox-symlink-design.md`
- Modify: `docs/superpowers/plans/2026-07-19-codex-diagnostics-inbox-symlink-hotfix.md`

**Interfaces:**
- Consumes: completed code and tests from Tasks 1-3.
- Produces: reviewable hotfix branch and exact verification evidence for the PR.

- [x] **Step 1: Mark the design implemented and record only sanitized evidence**

Change the design status to `Implemented; deployment pending`. Check completed plan boxes and add a results section containing command, tests/pass/fail/skip counts and no runtime content.

- [x] **Step 2: Run all required verification on the deployment host against the dedicated clone**

Use an isolated `IDLE_FLAG_DIR` for repository-wide tests:

```bash
SHOGUN_TEST_IDLE_DIR="$(mktemp -d)"
export IDLE_FLAG_DIR="$SHOGUN_TEST_IDLE_DIR"
make test
make test-int
make test-no-skip
make lint
make build
make check
```

Remove only that validated temporary directory after the commands. Expected: all commands exit `0`, fail count `0`, skip count `0`; `make check` reports generated outputs synchronized.

- [x] **Step 3: Verify diff hygiene and immutable-contract boundaries**

```bash
git diff --check a3f21a6c62bc5b3c48f0b1501caff1ace5da5544...HEAD
git status --short
git diff --name-only a3f21a6c62bc5b3c48f0b1501caff1ace5da5544...HEAD
git diff --binary a3f21a6c62bc5b3c48f0b1501caff1ace5da5544...HEAD | \
  python3 -c 'import re,sys; data=sys.stdin.buffer.read(); markers=[rb"BEGIN (?:RSA|OPENSSH|EC) PRIVATE KEY",b"gh"+b"p_",b"github"+b"_pat_",rb"token\s*[:=]"]; n=len(re.findall(b"|".join(markers),data,re.I)); print(f"secret_like_matches={n}"); raise SystemExit(n != 0)'
```

Expected: no whitespace errors, no uncommitted files, only planned paths, and no secret match introduced by the branch. Review the diff for live queue/report/log/pane content separately.

- [x] **Step 4: Request an independent requirements and security review**

Reviewer must check exact-link enforcement, no-follow traversal, ownership/mode validation, link and directory swap detection, FD closure, missing/rejected/error severity, unchanged JSON schema/consumer, isolated fixtures and deployment exclusions. Resolve findings with a new failing test before production changes.

- [x] **Step 5: Commit documentation evidence**

```bash
git add docs/superpowers/specs/2026-07-19-codex-diagnostics-inbox-symlink-design.md \
  docs/superpowers/plans/2026-07-19-codex-diagnostics-inbox-symlink-hotfix.md
git commit -m "docs: record diagnostics inbox hotfix verification"
```

## Implementation Results (2026-07-19)

Implementation and regression verification used the dedicated clone only. No
live pane, queue, report or log body was read or copied, and no production
deployment, startup, restart or WebUI action was performed.

### Test-first evidence

- Pre-change focused baseline: `SafePathAndLogTests`, 6 passed, 0 failed,
  0 skipped.
- Resolver RED: the first 8 new tests errored because `INBOX_LINK_TARGET` and
  `open_inbox_root` did not exist; the unsupported-directory-FD case also
  failed before the fail-closed implementation.
- Collection RED: 5 tests errored because the collector did not yet accept an
  `inbox_opener` and could not route fixed-root sources atomically.
- Integration RED: the launcher-shaped fixed-link scenario errored for the
  same missing routing seam.
- Focused GREEN before review: 18 source-collection unit tests and 1 isolated
  source integration test passed. After resolving review findings, the
  complete diagnostics unit module passed 97 tests, the consumer-contract
  suite passed 26 tests and the rollback-boundary suite passed 66 tests.

### Final verification

| Command | Passed | Failed | Skipped | Result |
|---|---:|---:|---:|---|
| `make test` | 882 | 0 | 0 | exit 0 |
| `make test-int` | 2 | 0 | 0 | exit 0 |
| `make test-no-skip` | 884 | 0 | 0 | exit 0; no-skip gate accepted 884 tests |
| `make lint` | n/a | 0 | 0 | exit 0; existing informational ShellCheck output only |
| `make build` | n/a | 0 | 0 | exit 0 |
| `make check` | n/a | 0 | 0 | exit 0; generated instructions synchronized |

The diagnostics Bats wrapper passed all 5 cases, including 97 diagnostics
unit tests, 26 consumer-contract tests and 66 rollback-boundary tests. The
integration Bats wrapper passed both cases.

### Setup failures resolved before the final run

The fresh dedicated clone initially lacked its ignored Python environment and
initialized Bats submodules. After those fixed dependencies were installed,
the first repository-wide unit run reported 867 passed, 15 failed and 0
skipped because four tracked skill-scenario YAML files had been checked out
with CRLF endings. Re-expanding those exact tracked fixtures from Git with LF
endings produced the final clean results above.

An intermediate rollback-boundary failure was initially misdiagnosed as a
stale documented SHA-256 because the Windows working-tree CRLF bytes produced
a different hash from the Git blob fetched by the deployment procedure. The
independent review identified the mismatch. A separate raw Git-blob
calculation confirmed the canonical hash remained `7f74246d...`; the
intermediate documentation change was reverted, and the regression test now
computes the expected remote-byte hash independently of checkout line endings.
All 66 rollback tests then passed. These environment and documentation
corrections did not read or change live runtime data.

The first post-review `make test` attempt used a 15-minute external command
limit and ended with exit 124 before Bats emitted its aggregate result. A
split run proved this was an observation timeout rather than a test failure:
the root group passed 33 tests in about 14 seconds, the first unit half passed
446 tests in about 7 minutes 23 seconds, and the second unit half passed 403
tests in about 9 minutes 29 seconds. The unchanged official target was then
rerun with a 30-minute limit and passed all 882 tests in about 17 minutes 11
seconds. The subsequent no-skip gate passed all 884 unit and integration
tests with `skips=0` and `exit=0`.

### Independent review

The read-only review reported 0 critical, 2 important and 2 minor findings.
Both important findings were reproduced before implementation: the
intermediate boundary hash did not match canonical GitHub bytes, and missing
`os.open(..., dir_fd=...)` capability was not classified as `SourceRejected`.
The minimal fixes restored the canonical hash, made the byte-level regression
line-ending independent and added the missing capability gate. Additional
ownership, world-writable-mode and descriptor-cleanup regressions cover the
minor test recommendations. The design-status/evidence recommendation is
addressed in this document and the linked design.

### Pending gates

- Push, draft PR, GitHub checks, merge, immutable snapshot installation,
  registry update and one approved production startup/acceptance sequence.

### Task 5: Publish, Deploy Once and Accept with Trusted Diagnostics

**Files:**
- Later modify in a separate branch: `docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics-work-log.md`

**Interfaces:**
- Consumes: reviewed hotfix PR and its merged Git blob.
- Produces: one active immutable-snapshot registry record, one official startup and trusted healthy acceptance.

- [ ] **Step 1: Push and open a draft hotfix PR**

Push `codex/diagnostics-source-rejected-hotfix` and create a draft PR against `main`. Include base SHA, purpose, changed files, new tests, every command, exact pass/fail/skip counts, constraints, rollback, dependency status and `production deployment not performed`.

- [ ] **Step 2: Make the PR ready only with all gates green**

Wait for GitHub checks and review threads. Do not mark ready while any failure, skip or unresolved review exists. Merge only with the user's merge authorization.

- [ ] **Step 3: Install the merged immutable snapshot atomically**

Fetch the merged `scripts/codex_diagnostics.py` Git blob by exact commit, verify its SHA-256, and use the existing atomic snapshot installer to replace the mode-`0555` user-local snapshot. Treat indeterminate installer status as failure and do not start Shogun.

- [ ] **Step 4: Update the registry in a separate reviewed PR**

Create a fresh branch from then-current main. Append a new exact schema-version-1 deployment record, mark the prior active record `superseded`, retain exactly one active record, and record only sanitized source commit/hash/path/mode/timestamp data. Push, review and merge it before diagnostic use.

- [ ] **Step 5: Revalidate provenance immediately before diagnostics**

Fetch the raw GitHub-main work log, validate its single marked registry and exactly one active deployment, then invoke only the fixed diagnostics command. Require ASCII-only schema-version-1 JSON, exact nested keys/order, exit `0`, empty stderr, runtime under 10 seconds and source hash equality. Any mismatch is `diagnostic_provenance_untrusted` or `diagnostic_process_failed`; use no direct-read fallback.

- [ ] **Step 6: Deploy main and run the official launcher exactly once**

After pre-start gates pass, update the live source to reviewed main and run the official launcher once. Do not auto-approve permission prompts, restart, retry or open WebUI. On failure, use recorded source/snapshot rollback and stop.

- [ ] **Step 7: Accept and record the final result**

Require a trusted diagnostic with repository main at the deployed SHA, both tmux sessions present, eleven agents observed, eleven watchers healthy, all eleven inbox sources `present`, no `source_rejected`, no errors or warnings, and recomputed `overall=healthy`. Add sanitized acceptance and rollback evidence to the work log PR/comment. Report branch/PR/merge/SHA/test/review/deployment state and confirm no uncommitted, unpushed or local-only changes remain.

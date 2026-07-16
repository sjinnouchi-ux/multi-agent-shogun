# Instruction Markdown EOL Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize every tracked instruction Markdown blob covered by the LF policy, prevent recurrence with an index-aware test, and produce a reviewed immutable tuple that allows the existing Task 9 deployment plan to resume without weakening its clean-tree gate.

**Architecture:** Add one Bats invariant to the existing build-system test file. Prove it fails against the current Git index, normalize only the ten known instruction blobs through the existing `.gitattributes` clean filter, and prove both index state and semantic content. Publish the narrowly scoped change as a separate PR; after approval and merge, resume Task 9 from its WSL clean-tree gate.

**Tech Stack:** Git, Git attributes, Bash, Bats, GNU awk, PowerShell, WSL2 Ubuntu, GitHub CLI.

## Global Constraints

- Work only in the linked worktree `C:\Users\jinnouchi\Documents\Codex\2026-07-12\new-chat\shogun-readonly-diagnostics-publication` on branch `codex/normalize-instruction-eol`.
- Base commit is `2e386673877d1181eec0f0589069cf24a3445c6a`; do not rewrite or force-update it.
- The only normalized instruction paths are the ten-path allowlist in Task 1.
- Do not change `.gitattributes`, instruction wording, file modes, Git remotes, Shogun runtime state, queues, reports, tmux panes, secrets, or WebUI state.
- Do not weaken clean checks with `--ignore-cr-at-eol`; that option is permitted only as a semantic-equivalence assertion for the ten staged normalization diffs.
- Required tests may not skip. A full-suite completion requires a positive test count, `skips=0`, and `exit=0`.
- Error handling is bounded: gather one sanitized evidence set, make one minimal correction, and verify once. Do not rerun an unchanged failing command more than once. A repeated identical failure stops the task for root-cause reporting.
- Do not rerun the 15–20 minute full suite unless the tree changed after its prior run or CI reports a materially different failure.

---

### Task 1: Add the index-EOL invariant and normalize the ten known blobs

**Files:**
- Modify: `tests/unit/test_build_system.bats` immediately after the existing `generated markdown is LF-only and has no trailing whitespace` test
- Normalize only:
  - `instructions/cli_specific/claude_tools.md`
  - `instructions/cli_specific/codex_tools.md`
  - `instructions/cli_specific/copilot_tools.md`
  - `instructions/cli_specific/kimi_tools.md`
  - `instructions/common/forbidden_actions.md`
  - `instructions/common/protocol.md`
  - `instructions/roles/ashigaru_role.md`
  - `instructions/roles/gunshi_role.md`
  - `instructions/roles/karo_role.md`
  - `instructions/roles/shogun_role.md`

**Interfaces:**
- Consumes: `.gitattributes` rule `instructions/**/*.md text eol=lf` and `PROJECT_ROOT` from the existing Bats setup.
- Produces: a Bats invariant requiring the first `git ls-files --eol` field to be exactly `i/lf` for all tracked instruction Markdown paths.

- [ ] **Step 1: Confirm the branch and clean starting state**

Run from the worktree:

```powershell
git branch --show-current
git rev-parse origin/main
git status --short
```

Expected: branch `codex/normalize-instruction-eol`, `origin/main` equals `2e386673877d1181eec0f0589069cf24a3445c6a`, and no output from `git status --short`.

- [ ] **Step 2: Add the failing Bats test**

Insert exactly this test after the existing LF/trailing-whitespace test:

```bash
@test "tracked instruction markdown is LF-normalized in the Git index" {
    local rows bad

    rows="$(git -C "$PROJECT_ROOT" ls-files --eol -- \
        'instructions/*.md' 'instructions/**/*.md')"
    [ -n "$rows" ]

    bad="$(printf '%s\n' "$rows" | awk '$1 != "i/lf" { print }')"
    if [ -n "$bad" ]; then
        printf 'Non-LF instruction blobs:\n%s\n' "$bad" >&2
        return 1
    fi
}
```

- [ ] **Step 3: Run the new test and verify RED**

Run:

```powershell
wsl.exe -d Ubuntu --cd /mnt/c/Users/jinnouchi/Documents/Codex/2026-07-12/new-chat/shogun-readonly-diagnostics-publication bash -lc "bats --filter 'tracked instruction markdown is LF-normalized in the Git index' tests/unit/test_build_system.bats"
```

Expected: one failing test whose sanitized failure names the ten known paths and reports `i/crlf` or `i/mixed`. If the failure contains any additional path, stop; do not broaden the allowlist automatically.

- [ ] **Step 4: Normalize only the paths governed by the existing policy**

Run:

```powershell
git add --renormalize -- 'instructions/*.md' 'instructions/**/*.md'
```

This uses the existing Git clean filter. It must not be run in the WSL live repository.

- [ ] **Step 5: Prove the staged normalization allowlist**

Run:

```powershell
$expected = @(
  'instructions/cli_specific/claude_tools.md',
  'instructions/cli_specific/codex_tools.md',
  'instructions/cli_specific/copilot_tools.md',
  'instructions/cli_specific/kimi_tools.md',
  'instructions/common/forbidden_actions.md',
  'instructions/common/protocol.md',
  'instructions/roles/ashigaru_role.md',
  'instructions/roles/gunshi_role.md',
  'instructions/roles/karo_role.md',
  'instructions/roles/shogun_role.md'
) | Sort-Object
$actual = @(git diff --cached --name-only --diff-filter=M -- instructions) | Sort-Object
$delta = Compare-Object $expected $actual
if ($delta) { $delta; throw 'normalization allowlist mismatch' }
```

Expected: no output and exit zero.

- [ ] **Step 6: Prove content and mode equivalence**

Run:

```powershell
git diff --cached --ignore-cr-at-eol --quiet -- instructions
if ($LASTEXITCODE -ne 0) { throw 'semantic content changed' }
$summary = git diff --cached --summary -- instructions
if ($summary) { $summary; throw 'file mode or path changed' }
git diff --cached --check
```

Expected: no output and exit zero. `--ignore-cr-at-eol` is an assertion here, not a deployment-gate bypass.

- [ ] **Step 7: Run the new test and verify GREEN**

Run:

```powershell
wsl.exe -d Ubuntu --cd /mnt/c/Users/jinnouchi/Documents/Codex/2026-07-12/new-chat/shogun-readonly-diagnostics-publication bash -lc "bats --filter 'tracked instruction markdown is LF-normalized in the Git index' tests/unit/test_build_system.bats"
```

Expected: one passing test and no skip.

- [ ] **Step 8: Stage the test and commit the minimal fix**

Run:

```powershell
git add -- tests/unit/test_build_system.bats
git diff --cached --check
git commit -m "fix: normalize instruction markdown EOLs"
```

Expected: one commit containing the Bats test and exactly ten line-ending-only instruction changes.

---

### Task 2: Verify the complete change and publish a reviewable PR

**Files:**
- Verify: all Task 1 paths
- Verify: `docs/superpowers/specs/2026-07-16-instruction-eol-normalization-design.md`
- Verify: `docs/superpowers/plans/2026-07-16-instruction-eol-normalization.md`

**Interfaces:**
- Consumes: the Task 1 commit and the clean isolated worktree.
- Produces: a GitHub PR with green CI and an immutable base/head/review-package tuple.

- [ ] **Step 1: Run the targeted build-system test file**

Run:

```powershell
wsl.exe -d Ubuntu --cd /mnt/c/Users/jinnouchi/Documents/Codex/2026-07-12/new-chat/shogun-readonly-diagnostics-publication bash -lc "bats tests/unit/test_build_system.bats"
```

Expected: every test passes and none is skipped.

- [ ] **Step 2: Run the full deployment-host suite once**

Run:

```powershell
wsl.exe -d Ubuntu --cd /mnt/c/Users/jinnouchi/Documents/Codex/2026-07-12/new-chat/shogun-readonly-diagnostics-publication bash -lc "/usr/bin/timeout 1800 /usr/bin/make test-no-skip"
```

Expected: at least 746 tests, `skips=0`, and `exit=0`.

- [ ] **Step 3: Recheck tree and index invariants**

Run:

```powershell
git status --short
git ls-files --eol -- 'instructions/*.md' 'instructions/**/*.md'
git diff origin/main...HEAD --check
```

Expected: clean status; every selected row starts with `i/lf`; no diff-check output.

- [ ] **Step 4: Push without force and open the PR**

Run:

```powershell
git push -u origin codex/normalize-instruction-eol
gh pr create --repo sjinnouchi-ux/multi-agent-shogun --base main --head codex/normalize-instruction-eol --title "Normalize instruction Markdown line endings" --body "Normalizes the ten instruction Markdown blobs governed by the existing LF policy and adds an index-aware Bats regression test. Verification includes RED/GREEN evidence, the targeted build-system suite, and make test-no-skip with zero skips." --draft
```

Expected: one draft PR against `main`; no temporary PR-body file is created.

- [ ] **Step 5: Wait for CI once**

Run:

```powershell
gh pr checks --watch --fail-fast
```

Expected: every required check passes. Do not restart unchanged CI failures. Capture one failing-check evidence set, fix only the identified cause, and rerun after a new commit.

- [ ] **Step 6: Generate the immutable review package**

Run:

```powershell
$base = gh pr view --repo sjinnouchi-ux/multi-agent-shogun --json baseRefOid --jq .baseRefOid
$head = gh pr view --repo sjinnouchi-ux/multi-agent-shogun --json headRefOid --jq .headRefOid
$package = ".superpowers/sdd/review-$($base.Substring(0,12))..$($head.Substring(0,12)).diff"
New-Item -ItemType Directory -Force .superpowers/sdd | Out-Null
git diff --binary --full-index "$base..$head" --output="$package"
$packageSha = (Get-FileHash -Algorithm SHA256 $package).Hash.ToLowerInvariant()
if ($packageSha -notmatch '^[0-9a-f]{64}$') { throw 'invalid review package hash' }
```

Expected: one review package derived from the exact PR base/head and one 64-character lowercase SHA-256. The package contains source diffs only and no secrets or runtime artifacts.

- [ ] **Step 7: Perform independent review, freeze, and present the new tuple**

Independent reviewers must confirm:

1. the base SHA is current `main` and the head SHA is immutable;
2. only the two approved docs, one Bats test, and ten normalized instruction files appear across the branch;
3. the ten instruction changes are semantically empty under `--ignore-cr-at-eol` and have no mode/path changes;
4. the index-EOL test fails before and passes after normalization;
5. the full suite reports zero failures and zero skips.

After both reviews pass, run:

```powershell
$base = gh pr view --repo sjinnouchi-ux/multi-agent-shogun --json baseRefOid --jq .baseRefOid
$head = gh pr view --repo sjinnouchi-ux/multi-agent-shogun --json headRefOid --jq .headRefOid
$package = ".superpowers/sdd/review-$($base.Substring(0,12))..$($head.Substring(0,12)).diff"
$packageSha = (Get-FileHash -Algorithm SHA256 $package).Hash.ToLowerInvariant()
"base_sha=$base"
"head_sha=$head"
"review_package_sha256=$packageSha"
```

Expected: the tuple exactly matches the reviewed PR and package. Present the exact tuple to the user before merge. Do not merge automatically at this gate.

---

### Task 3: Resume the existing immutable WSL deployment plan after tuple approval

**Files:**
- Execute from: `docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics.md`, Task 9
- Do not modify live runtime data files.

**Interfaces:**
- Consumes: the explicitly approved new tuple and its merged commit.
- Produces: a clean stopped WSL live repository and verified mode-`0555` read-only diagnostics snapshot.

- [ ] **Step 1: Merge only the approved immutable PR head**

Use GitHub's merge operation with head-SHA matching. Verify the merge tree equals the reviewed head tree and that the merge first parent equals the approved base. If `main` moved, stop and regenerate review evidence; do not force or rebase after approval.

- [ ] **Step 2: Re-enter Task 9 at the WSL preflight gate**

Use `Ubuntu`, real user `jinnouchi`, and `/home/jinnouchi/multi-agent-shogun`. Resolve the canonical remote by its URL `https://github.com/sjinnouchi-ux/multi-agent-shogun.git`; do not assume its name is `origin`. Verify both `shogun` and `multiagent` tmux sessions are absent without reading panes.

- [ ] **Step 3: Fast-forward and require an ordinary clean tree**

Fetch the canonical remote, require current `main` to be an ancestor of the approved merge, and use `git merge --ff-only`. Require both `git diff --quiet` and `git diff --cached --quiet` to return zero without ignore options.

- [ ] **Step 4: Complete the unchanged Task 9 deployment gates**

Run deployment-host `make test-no-skip` once, atomically install the source-identical snapshot with owner `jinnouchi` and mode `0555`, and validate contract and suffix rejection without printing raw diagnostic JSON. Continue to original Tasks 10–12 only after Task 9 records sanitized pass facts.

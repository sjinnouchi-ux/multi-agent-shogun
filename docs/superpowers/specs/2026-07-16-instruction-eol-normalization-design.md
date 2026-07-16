# Instruction Markdown EOL Normalization Design

**Status:** Approved in principle by the user on 2026-07-16; written-spec review pending.

## Context

PR #11 was merged as `2e386673877d1181eec0f0589069cf24a3445c6a`, and the stopped WSL live repository was fast-forwarded to that commit. The deployment gate then detected tracked working-tree differences.

Commit history already declares `instructions/**/*.md text eol=lf` in `.gitattributes`, but the Git index at the merged commit still contains ten instruction Markdown blobs that are either CRLF-only or mixed LF/CRLF:

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

The live differences disappear when carriage returns at line endings are ignored. The affected blob identities predate the deployment commit, so this is repository normalization debt exposed by Git index/stat-cache revalidation, not evidence of user-authored content changes. The isolated baseline remains healthy: `make test-no-skip` passes 745 tests with zero skips.

## Goals

1. Make every tracked instruction Markdown blob covered by the LF policy use LF in the Git index.
2. Add a regression test that checks the Git index rather than only the checked-out working tree.
3. Preserve all text content and avoid unrelated source, configuration, runtime, or generated-output changes.
4. Produce a separately reviewed PR and a new immutable deployment tuple.
5. Deploy only after the clean-repository, test, ownership, mode, hash, and contract gates pass.

## Non-goals

- Do not weaken the clean-repository gate with `--ignore-cr-at-eol`.
- Do not change `.gitattributes`, Git remote configuration, or local Git filters.
- Do not reset, restore, clean, or stage files in the WSL live repository to hide the condition.
- Do not read or modify Shogun secrets, tmux panes, queues, reports, runtime logs, or WebUI state.
- Do not refactor instruction content or build tooling.

## Approaches Considered

### 1. Normalize the canonical blobs and enforce the invariant — selected

Normalize all ten violating blobs to LF and add one Bats regression test. This repairs the source of the dirty state and keeps the existing deployment safety gate meaningful.

### 2. Ignore carriage-return-only differences during deployment — rejected

This would allow the current deployment to proceed faster, but it weakens the clean-tree invariant and can hide future line-ending drift.

### 3. Apply a local Git attribute or index workaround — rejected

This would create host-specific drift and would not repair the canonical Git tree used by other machines and CI.

## Test Design

Add one test to `tests/unit/test_build_system.bats`:

- Run `git ls-files --eol` for tracked `instructions/*.md` and `instructions/**/*.md` paths.
- Assert that the command returns at least one row.
- Reject any row whose index marker is not exactly `i/lf`.
- Print only violating tracked paths and EOL classifications on failure.

The test must be added and observed failing on the current merged tree before normalization. A working-tree-only grep is insufficient because checkout conversion can conceal a non-normalized Git blob.

## Minimal Remediation

After the failing test is established, normalize only the tracked instruction Markdown paths selected by the existing LF policy. The expected staged content changes are exactly the ten files listed in this design. No wording, whitespace other than carriage returns, file mode, or path changes are allowed.

The implementation must prove:

- the regression test changes from failing to passing;
- `git ls-files --eol` reports `i/lf` for every selected instruction Markdown path;
- the ten normalized files have no semantic diff when carriage returns at line endings are ignored;
- no unexpected file is included in the normalization change;
- `git diff --check` passes;
- `make test-no-skip` reports a positive test count, zero skips, and exit zero.

## Review and Publication

The change is committed on `codex/normalize-instruction-eol`, pushed without force, and opened as a separate PR against `main`. CI must pass with no skipped required test. Independent review must confirm the path allowlist, index-EOL invariant, absence of semantic content changes, and full-suite result.

The PR base SHA, head SHA, and review-package SHA-256 form a new immutable tuple. The exact tuple is presented to the user for approval before merge. If `main` moves, the review and tuple gates are repeated; no force update or direct push to `main` is permitted.

## WSL Deployment

After merge, deployment uses the real Windows user `jinnouchi`, WSL2 distribution `Ubuntu`, and `/home/jinnouchi/multi-agent-shogun`. The canonical remote is identified by URL (`sjinnouchi-ux/multi-agent-shogun`), not by assuming the remote name is `origin`.

Deployment proceeds only when both Shogun tmux sessions are absent, the tracked working tree and index are clean, and `main` can fast-forward to the approved merge SHA. The deployment host must pass `make test-no-skip` before the read-only diagnostics snapshot is installed atomically with owner `jinnouchi`, mode `0555`, and a source-identical hash. Contract and suffix-rejection checks must expose only pass/fail facts, never raw diagnostic JSON.

## Failure Handling

Stop before merge or deployment if any of the following occurs:

- normalization changes a path outside the ten-file allowlist;
- an ignored-carriage-return comparison still shows content differences;
- a required test fails or is skipped;
- CI or independent review is not green;
- the immutable tuple no longer matches the PR;
- canonical `main` moves after review;
- the WSL live repository has non-EOL user changes or a Shogun tmux session exists;
- snapshot ownership, mode, source hash, or contract verification is indeterminate.

## Acceptance Criteria

- A failing index-EOL regression test is captured before remediation.
- All tracked instruction Markdown covered by the LF policy reports `i/lf` after remediation.
- Exactly the ten known files change only by line-ending normalization, plus the test and approved documentation.
- Targeted and full tests pass with zero skips.
- A reviewed PR supplies an exact approved immutable tuple.
- The merged SHA is fast-forwarded to the stopped WSL live repository without local cleanup tricks.
- The fixed snapshot passes owner, mode, hash, contract, and suffix-rejection gates without exposing protected runtime data.

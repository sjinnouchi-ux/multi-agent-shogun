# Codex Readiness Marker Format Hotfix Plan

## Baseline and root cause

- Canonical repository: `sjinnouchi-ux/multi-agent-shogun`
- Base branch and SHA: `main` at
  `bdeb84bb8c4ccf9f359df488115bdbee9a948041`
- Follow-up branch: `fix/codex-readiness-marker-format`
- Codex CLI `0.144.1` renders the configured item as
  `Context 100% left`.
- The classifier currently searches for the contiguous text `context left`,
  while the fake E2E emits the non-production order `100% context left`.
  Consequently the fake passes and the real CLI remains `unknown`.

## Scope

Files expected to change:

- `lib/agent_status.sh`
- `tests/unit/test_agent_cli_state.bats`
- `tests/e2e/e2e_cli_readiness.bats`
- `docs/superpowers/specs/2026-07-19-codex-statusline-readiness-design.md`
- this plan and the existing handoff implementation log for final evidence

The implementation will accept the actual Codex ordering
`Context <percent>% left` as both a positive CLI marker and an explicit idle
marker. Compatibility with the existing legacy/mock ordering is retained.

## Test-first sequence

1. Add a unit case containing a stale busy line followed by
   `Context 100% left`; require `ready`.
2. Change the status-line E2E fake to emit the real Codex string and capture
   the focused RED result before modifying production code.
3. Update only the two Codex marker expressions in `lib/agent_status.sh`.
4. Run the focused unit and E2E tests, then the complete regression gates.
5. Obtain an independent review, scan the complete diff and commit history for
   secrets/runtime data, push the branch, and open a draft PR.

## Verification commands

```text
bats tests/unit/test_agent_cli_state.bats
bats tests/e2e/e2e_cli_readiness.bats
make test
make test-int
make lint
make build
make check
```

`make test-no-skip` is reserved for the approved deployment host and must use
an isolated `IDLE_FLAG_DIR`. Any failure or skip keeps the PR in draft.

## Rollback

- PR rollback: revert the hotfix commit; the readiness gate remains fail-closed
  and Codex roles return `unknown` rather than receiving input unsafely.
- Deployment rollback: restore only the live source branch/revision without
  `--clean`; do not restart automatically.
- No production startup, retry, stop, restart, or runtime inspection is part of
  this PR task. A later runtime attempt requires fresh explicit approval.

## Explicit exclusions

- No WebUI changes.
- No deployment or production runtime mutation.
- No P2 auto-restart behavior.
- No process-name readiness fallback.
- No capture-range, seven-state, busy/idle, idle-flag, watcher, ack/receipt, or
  delivery-semantics changes.
- No production pane, queue, report, dashboard, or log reads.

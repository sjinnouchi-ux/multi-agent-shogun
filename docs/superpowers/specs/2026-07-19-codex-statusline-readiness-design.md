# Codex Status-Line Readiness Design

## Context

The handoff-hardening changes through the detached-tmux geometry hotfix are on
GitHub `main` at `bc907ac20dc41b125a9eb2ca3de94066ba3e37bc`. Deployment-host
validation at that revision passed 878 tests with zero failures and zero skips;
`make lint`, `make build`, and `make check` also passed.

After the native WSL Claude CLI was repaired, the official launcher was run
once without `--clean`. The three Claude roles (`shogun`, `gunshi`, and
`oometsuke`) reached `ready`, while the eight Codex roles (`karo` and
`ashigaru1` through `ashigaru7`) remained `unknown`. Startup failed closed and
started no watchers. The trusted sanitized diagnostic confirmed that all eleven
panes were present and alive, that the expected Claude and Codex processes were
running, and that the watcher count was zero. No pane contents, queue/report
bodies, or log lines were read.

The deployment source was returned to the pre-geometry revision
`7994e57e392ce41a4b3e24a76dc88b65d0cc844f` without another startup attempt.
The existing runtime remains fail-closed with no watchers; there was no
automatic restart or data reset.

The deployment host runs Codex CLI `0.144.1`. The official Codex manual
documents that:

- `[tui].status_line` is an ordered list of footer item IDs, and
  `context-remaining` is a supported item;
- `-c` / `--config` accepts a one-run arbitrary configuration override;
- nested keys use dot notation and values are parsed as TOML; and
- CLI configuration overrides take precedence over project, profile, user,
  system, and built-in configuration.

The initial evidence supported a narrow root-cause inference: a user or host
Codex status-line choice could replace the normal shortcut/footer text, leaving
none of the existing Codex positive markers in the classifier's final five
visible lines. The global Codex configuration was not inspected and did not
need to be inspected to apply the one-run override.

## Post-merge runtime correction

PR #23 added the one-run override and merged at
`bdeb84bb8c4ccf9f359df488115bdbee9a948041`. All local and GitHub tests passed,
but the approved official startup still classified all eight Codex roles as
`unknown` and blocked watcher startup. The live source was restored to the
retained rollback revision without a second startup.

Official Codex `0.144.1` source and an isolated real-CLI probe established that
the override is valid and the marker is rendered in the final five lines as
`Context 100% left`. The remaining defect is the classifier grammar: it looks
for the contiguous words `context left`, while the fake E2E emitted the
non-production order `100% context left`. The fake therefore passed while the
real marker did not match.

The follow-up fix keeps the adapter override and all classifier boundaries. It
adds the actual `Context <percent>% left` ordering to the Codex positive and
idle marker checks, retains the previous ordering for compatibility, and makes
the E2E fake reproduce the real CLI text.

## Goal

Make every Codex process launched by Shogun render and recognize the
`Context <percent>% left` readiness marker within the final five visible lines,
independent of the user's global Codex status-line choice, while preserving the
fail-closed readiness classifier and all existing runtime semantics.

## Non-goals

- Do not modify `get_pane_cli_state`'s seven states, marker precedence, or
  five-line activity capture. The follow-up changes only the shared Codex
  context-remaining marker grammar used by its positive and idle checks.
- Do not use process names as readiness evidence.
- Do not modify the user's global or project Codex configuration.
- Do not change `agent_is_busy_check`, `agent_is_busy`, idle flags, watcher
  throttle, self-watch, ack, receipt, or delivery semantics.
- Do not auto-approve permission prompts, retry startup, or restart a CLI.
- Do not modify WebUI code or open WebUI.
- Do not read or reset production pane, queue, report, dashboard, or log data.
- Do not implement P2 behavior.

## Approaches considered

### 1. Shogun-scoped one-run Codex override (selected)

Append one Codex CLI override to the command assembled by the existing CLI
adapter:

```text
-c 'tui.status_line=["context-remaining"]'
```

This uses Codex's highest-precedence, one-run configuration surface and leaves
user configuration unchanged. It produces the real Codex status-line marker,
`Context <percent>% left`, which the shared Codex marker helper recognizes
without introducing a second readiness policy.

### 2. Widen the classifier capture range (rejected)

Scanning above the final five lines would violate the existing classifier
contract and increase the risk that stale output is treated as current CLI
readiness.

### 3. Accept the Codex process name as readiness (rejected)

A running process proves liveness, not input readiness. This would also violate
the explicit prohibition against process-name-only classification and would
reintroduce false positives during tool execution.

Changing global Codex configuration is also rejected because it would affect
non-Shogun sessions and create an unnecessary deployment side effect.

## Design

Define one fixed adapter constant in `lib/cli_adapter.sh`:

```bash
CODEX_READINESS_STATUSLINE_CONFIG='tui.status_line=["context-remaining"]'
```

In the `codex)` branch of `build_cli_command`, quote the constant with the
existing `_cli_adapter_shell_quote` helper and append it as exactly one `-c`
value before the existing Codex runtime flags. The resulting logical argv is:

```text
codex [--model MODEL] -c tui.status_line=["context-remaining"] \
  --search --dangerously-bypass-approvals-and-sandbox --no-alt-screen \
  [STARTUP_PROMPT]
```

The command remains a shell command string because that is the existing adapter
contract. Shell quoting must preserve the TOML expression as one argv element.
The override is added exactly once and only for `codex`; commands for Claude,
OpenCode, Copilot, Kimi, and Antigravity remain byte-for-byte unchanged.

Both official startup and `scripts/switch_cli.sh` already consume
`build_cli_command`, so they receive the same behavior without separate call-site
patches. No new setting, environment variable, or user-config migration is
introduced.

The runtime flow is:

```text
settings.yaml
  -> build_cli_command
  -> Codex one-run status-line override
  -> visible "Context <percent>% left" footer
  -> existing get_pane_cli_state
  -> existing aggregate readiness gate
  -> watcher startup only when every role is ready
```

## Failure handling

If the installed Codex rejects the override, exits, or still does not render a
recognized marker, the existing readiness gate remains authoritative. The pane
will classify as `shell_prompt`, `absent`, or `unknown`; aggregate startup will
exit nonzero and watchers will remain stopped. There is no fallback to process
names, a wider capture, an automatic approval, or a restart.

If any focused or regression test fails or skips, the PR remains draft. If live
acceptance fails after merge, restore the live source to the retained
`7994e57e392ce41a4b3e24a76dc88b65d0cc844f` rollback revision without
`--clean`, do not restart automatically, and report the sanitized failure.

## Test strategy

Implementation remains test-first.

1. Update the existing exact Codex command assertion in
   `tests/unit/test_cli_adapter.bats` so it fails before implementation and
   requires the one-run status-line override.
2. Add a unit test that shell-parses the assembled command and proves there is
   exactly one `-c`, its following argv is exactly
   `tui.status_line=["context-remaining"]`, and the existing model, runtime
   flags, and single startup-prompt argv are preserved.
3. Add a focused case to `tests/e2e/e2e_cli_readiness.bats`. The test creates an
   isolated temporary fake `codex` executable that emits `Context 100% left`
   only after receiving the exact override. It launches the command returned by
   `build_cli_command` in an isolated tmux pane, asks the real
   `get_pane_cli_state` for the Codex state, and requires `ready`. Before the
   adapter change the fake emits no marker, so this test is red. The fake process
   may appear as `bash`; readiness must still come from the positive marker.
4. The e2e case uses only sanitized generated text, a unique tmux session, and a
   temporary project/config directory, and removes all of them in teardown. It
   never reads production files or panes.
5. Run the focused unit and e2e files, followed by `make test`, `make test-int`,
   `make lint`, `make build`, and `make check`.
6. On the approved deployment host, run `make test-no-skip` with an isolated
   `IDLE_FLAG_DIR`. Any skip is a failure.

## Files in scope

- `lib/cli_adapter.sh`
- `lib/agent_status.sh` (follow-up marker-format correction only)
- `tests/unit/test_cli_adapter.bats`
- `tests/unit/test_agent_cli_state.bats` (follow-up regression only)
- `tests/e2e/e2e_cli_readiness.bats`
- `docs/superpowers/specs/2026-07-19-codex-statusline-readiness-design.md`
- `docs/superpowers/plans/2026-07-17-shogun-handoff-hardening-implementation.md`
  for sanitized implementation, review, PR, merge, deployment, and rollback
  evidence after the code is complete

No generated instruction output is expected to change.

## PR, review, and rollout

The initial hotfix is a single independent PR from branch
`fix/codex-statusline-readiness`, based on
`bc907ac20dc41b125a9eb2ca3de94066ba3e37bc`. It depends only on already-merged
PR #22 and does not alter the original PR dependency graph.

The marker-format correction is a second independent follow-up PR from branch
`fix/codex-readiness-marker-format`, based on merged main
`bdeb84bb8c4ccf9f359df488115bdbee9a948041`.

After the red-green implementation and all local gates pass, obtain an
independent code review, confirm that the diff contains no secrets or runtime
data, push the branch, and create a draft PR with exact pass/fail/skip counts.
Do not mark it ready or merge while any failure or skip remains. Merge requires
the user's existing explicit approval and a final current-main/review/check
audit.

Deployment occurs only from the merged GitHub `main`. Re-fetch the common
startup instructions, canonical entry, target `AGENTS.md`, and merged main SHA;
fast-forward the live source without `--clean`; run deployment-host gates; and
invoke the official launcher once. Do not modify global Codex configuration.

Acceptance requires all eleven roles to report `ready` and watchers to start.
Immediately before the post-start diagnostic, re-fetch and validate the
GitHub-main diagnostics registry and source hash, then run only the fixed
sanitized diagnostic command. The diagnostic must validate completely and
confirm the expected sessions, eleven live panes, and watcher state. Any
failure triggers the rollback behavior above, with no automatic retry.

## Acceptance criteria

- Every Shogun-built Codex command contains exactly one shell-safe
  `-c 'tui.status_line=["context-remaining"]'` override.
- Non-Codex commands and the Codex model, runtime flags, and startup prompt are
  unchanged.
- The existing classifier returns `ready` from the visible
  `Context <percent>% left` marker without using a process-name fallback or
  wider capture.
- Focused tests, unit regression, integration/e2e regression, lint, build, and
  check report zero failures and zero skips before the PR leaves draft.
- Independent review reports no blocking issue before merge.
- Deployment uses merged GitHub `main`, no `--clean`, no global Codex config
  edit, and no production data inspection.
- Official startup reports all eleven roles `ready`, or remains safely blocked
  with watchers absent and the live source rolled back.
- WebUI, P2, busy/idle, watcher, delivery, ack/receipt, permission, and restart
  behavior remain unchanged.

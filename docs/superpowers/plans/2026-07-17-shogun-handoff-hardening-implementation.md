# Shogun Handoff Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add fail-closed CLI liveness/readiness gates ahead of the existing handoff delivery state without replacing ack/receipt, watchdog, busy/idle, idle flags, throttle, or self-watch behavior.

**Architecture:** Keep the current state machine and delivery pipeline. Add `get_pane_cli_state <pane_target> [expected_cli]` as the sole seven-state classifier, apply it first to startup/CLI switching, then at the small number of aggregated delivery entrances, and finally harden clear-command and command-epoch closure semantics in ordered P1 pull requests.

**Tech Stack:** Bash 4+, tmux, Bats 1.13+, Python 3.10+ with PyYAML, shellcheck, Make.

## Global Constraints

- Baseline source is GitHub `main` commit `45b249edc03976a661d3b51dc516f3df3ea6d639`; re-read `main` before creating every PR.
- Use task-specific branches; never push directly to `main` and never merge without the Lord's approval.
- Do not modify WebUI or the live `/home/jinnouchi/multi-agent-shogun` deployment.
- Do not start, stop, restart, switch, or deploy the live Shogun runtime.
- Preserve ack/receipt, `agent_is_busy_check`, `agent_is_busy`, busy/idle meaning, idle flags, watcher throttle, and self-watch.
- Do not auto-approve permission prompts and do not add auto-restart behavior.
- Do not rename `notification_count`.
- Do not patch the approximately 83 raw `tmux send-keys` call sites individually; guard the aggregated entrances.
- Use an isolated task-only `IDLE_FLAG_DIR` for every test command.
- Treat any SKIP as FAIL. Keep every PR draft while a FAIL or SKIP remains.
- Deployment and P2 auto-restart are explicitly out of scope.

## Verified Baseline

- `make test`: 745 PASS, 0 FAIL, 0 SKIP.
- `make test-int`: 1 PASS, 0 FAIL, 0 SKIP.
- `bats tests/e2e/*.bats --timing`: 33 PASS, 0 FAIL, 6 SKIP.
- The six skipped Bloom tests require an existing live `multiagent` session. They remain FAIL for acceptance; this plan does not connect to the live session to clear them.
- `make test-no-skip` is reserved for an explicitly approved deployment-host validation and is not run during local implementation.

## PR Dependency Graph

```text
PR-1a (independent)          PR-1b
                                ├── PR-1c
                                └── PR-1d
PR-1d also records P0 docs only after PR-1a and PR-1c evidence exists.
PR-1d → P1-1 → P1-2 → P1-3
```

If PR-1b is not merged, PR-1c and PR-1d are opened as stacked draft PRs and their bases are set to the PR-1b branch. P1 PRs are stacked in the order above until their predecessors reach `main`.

---

### Task 1: PR-1a — Hook paths, Hook lint, and Oometsuke Phase-3 fallback

**Branch:** `codex/handoff-pr1a-hooks-oometsuke`

**Files:**
- Modify: `.gitignore`
- Modify: `.claude/settings.json`
- Modify: `Makefile`
- Create: `scripts/lint_hook_settings.py`
- Modify: `scripts/inbox_watcher.sh`
- Modify: `tests/unit/test_stop_hook.bats`
- Modify: `tests/unit/test_send_wakeup.bats`

**Interfaces:**
- Hook command contract: Stop uses `bash "${CLAUDE_PROJECT_DIR:-.}/scripts/stop_hook_inbox.sh"`, SessionStart uses `bash "${CLAUDE_PROJECT_DIR:-.}/scripts/session_start_hook.sh"`, and neither entry has an `args` key.
- Lint contract: `python3 scripts/lint_hook_settings.py .claude/settings.json` exits nonzero for bare relative hook paths or any hook `args` field.
- Phase-3 contract: `shogun|karo|gunshi|oometsuke` use Escape+nudge and never `/clear`.

- [ ] **Step 1: Write RED Hook contract tests.** Add tests that parse `.claude/settings.json`, assert exact shell-form commands for Stop and SessionStart, exercise the command with `CLAUDE_PROJECT_DIR` set and unset, and mutate a temporary settings file to prove lint rejects `bash scripts/...` and `args`.
- [ ] **Step 2: Run the focused Hook tests and record the expected failures.**

```bash
IDLE_FLAG_DIR="$TASK_IDLE" bats tests/unit/test_stop_hook.bats --filter 'settings|lint|CLAUDE_PROJECT_DIR'
```

- [ ] **Step 3: Write RED Phase-3 Oometsuke tests.** Source the watcher harness with `AGENT_ID=oometsuke`, a Phase-3 age, and Claude CLI; assert no `/clear`, assert Escape, and assert the nudge token.
- [ ] **Step 4: Run the focused watcher tests and record the expected `/clear` failure.**

```bash
IDLE_FLAG_DIR="$TASK_IDLE" bats tests/unit/test_send_wakeup.bats --filter 'oometsuke.*Phase 3|Phase 3.*oometsuke'
```

- [ ] **Step 5: Implement the minimum Hook and lint changes.** Keep both hook commands shell-form, load JSON with Python's standard library, inspect every hook entry recursively, reject `args`, and reject a command beginning with a bare `bash scripts/` path.
- [ ] **Step 6: Add `oometsuke` to the existing Phase-3 command-layer suppression branch only.** Do not add liveness classification or permission/login detection in this PR.
- [ ] **Step 7: Re-run focused tests, then PR gates.**

```bash
IDLE_FLAG_DIR="$TASK_IDLE" bats tests/unit/test_stop_hook.bats
IDLE_FLAG_DIR="$TASK_IDLE" bats tests/unit/test_send_wakeup.bats
IDLE_FLAG_DIR="$TASK_IDLE" bats tests/e2e/e2e_escalation.bats tests/e2e/e2e_clear_recovery.bats
make lint
make build
make check
IDLE_FLAG_DIR="$TASK_IDLE" make test
IDLE_FLAG_DIR="$TASK_IDLE" make test-int
IDLE_FLAG_DIR="$TASK_IDLE" bats tests/e2e/*.bats --timing
```

- [ ] **Step 8: Review, secret-scan, commit, push, and open a draft PR.** Roll back by reverting the PR commit; the previous Hook cwd behavior and previous Phase-3 role list are restored atomically.

### Task 2: PR-1b — Seven-state CLI classifier only

**Branch:** `codex/handoff-pr1b-cli-state`

**Files:**
- Modify: `lib/agent_status.sh`
- Create: `tests/unit/test_agent_status.bats`

**Interfaces:**
- Produces: `get_pane_cli_state <pane_target> [expected_cli]`.
- Returns one stdout token from `ready|busy|permission_prompt|login_prompt|shell_prompt|absent|unknown` and always exits 0.
- Consumes tmux `has-session`, `capture-pane`, `show-options`, and `display-message` through test-overridable command wrappers matching existing library patterns.

- [ ] **Step 1: Add RED table-driven tests for all seven tokens, exact stdout cardinality, and exit 0.** Include blocked-tail-15 and activity-tail-5 fixtures.
- [ ] **Step 2: Add RED precedence tests.** Blocked markers outrank positive CLI markers; positive markers outrank shell detection; process command alone never establishes state.
- [ ] **Step 3: Add RED false-positive tests.** Claude appearing as `node`, Bash tool execution appearing as `bash`, and `bash tests/e2e/mock_cli.sh` must not become `shell_prompt` when a positive CLI marker exists.
- [ ] **Step 4: Add RED override tests.** Accept `@pane_state_override` only with `SHOGUN_TEST_MODE=1`; otherwise emit a sanitized stderr warning and run normal classification with exactly one stdout token.
- [ ] **Step 5: Implement the classifier in `lib/agent_status.sh`.** Read pane existence first, then override, one tail capture, blocked patterns, CLI-positive markers, and finally the dual shell test (`prompt pattern` plus `bash|zsh|fish|sh`).
- [ ] **Step 6: Prove no existing call site changes.**

```bash
git diff -- lib/agent_status.sh tests/unit/test_agent_status.bats
rg -n 'get_pane_cli_state' --glob '!lib/agent_status.sh' --glob '!tests/unit/test_agent_status.bats'
```

- [ ] **Step 7: Run focused and full gates, review, push, and open an independent draft PR.** Roll back by reverting the classifier commit; no caller behavior has changed.

### Task 3: PR-1c — Startup and CLI-switch readiness

**Branch:** `codex/handoff-pr1c-readiness`

**Files:**
- Modify: `shutsujin_departure.sh`
- Modify: `scripts/switch_cli.sh`
- Modify: `tests/unit/test_switch_cli.bats`
- Create: `tests/unit/test_departure_readiness.bats`
- Modify: `tests/e2e/e2e_codex_startup.bats`
- Modify: `tests/e2e/mock_cli.sh`
- Modify: `tests/e2e/mock_behaviors/common.sh`

**Interfaces:**
- Consumes: `get_pane_cli_state` from PR-1b.
- Produces a sanitized per-role structured readiness summary with a nonzero aggregate result when any role is not `ready`.
- Commits CLI metadata only after the replacement CLI reaches `ready`.

- [ ] **Step 1: Add RED mixed-pane summary tests for ready, permission, shell, absent, unknown, and timeout.**
- [ ] **Step 2: Add RED no-send tests proving startup prompts and inbox numbers are withheld from every non-ready state.**
- [ ] **Step 3: Add RED switch rollback tests.** Preserve the old `settings.yaml` content and pane metadata when the new CLI never reaches ready.
- [ ] **Step 4: Add deterministic mock behaviors `never_ready`, `delay_ready`, and `normal_ready`; do not use live panes.**
- [ ] **Step 5: Implement bounded readiness polling and structured aggregation.** Never approve prompts and never restart automatically.
- [ ] **Step 6: Move metadata finalization after the ready result and restore the exact backup on failure.**
- [ ] **Step 7: Run focused unit/e2e and all PR gates.** Roll back by reverting PR-1c; the classifier remains unused by startup paths.

### Task 4: PR-1d — Delivery liveness guard and P0 documentation

**Branch:** `codex/handoff-pr1d-delivery-guard`

**Files:**
- Modify: `scripts/inbox_watcher.sh`
- Modify: `scripts/handoff_watchdog.py`
- Modify: `tests/unit/test_send_wakeup.bats`
- Modify: `tests/unit/test_handoff_watchdog.bats`
- Modify: `tests/e2e/mock_cli.sh`
- Modify: `tests/e2e/mock_behaviors/common.sh`
- Modify: `tests/e2e/e2e_inbox_delivery.bats`
- Modify: `tests/e2e/e2e_escalation.bats`
- Modify: `docs/known_issues.md`

**Interfaces:**
- Consumes: `get_pane_cli_state` from PR-1b.
- Adds only `cli_state_at_notify` and `delivery_blocked_reason` to delivery/report projections.
- Preserves `notification_count` and all existing ack/receipt fields.

- [ ] **Step 1: Inventory the aggregated send entrances and freeze the raw send-key count in a regression assertion.** Guard only `send_wakeup`, `send_wakeup_with_escape`, `send_cli_command`, `send_context_reset`, task-resume/startup send helpers, and watchdog notification entrances actually present in the current tree.
- [ ] **Step 2: Add RED tests for gate-first ordering.** Block permission, login, shell, absent, and unknown before busy/idle, throttle, or self-watch; let ready/busy continue to the existing busy/idle rules.
- [ ] **Step 3: Add RED watchdog projection tests for the two new fields and unchanged `notification_count`/receipt behavior.**
- [ ] **Step 4: Add sanitized mock behaviors for permission, login, shell-after-exit, never-ready, delay-ready, normal-ready, and busy.**
- [ ] **Step 5: Implement one liveness guard helper and call it at aggregated entrances.** Record a stable reason token; do not copy pane content into reports.
- [ ] **Step 6: Update `docs/known_issues.md` only for P0 items proven resolved.** Keep clear-command defer as unresolved P1, list remaining risk, six skipped Bloom tests, and no production deployment.
- [ ] **Step 7: Run focused tests and all PR gates.** Roll back by reverting PR-1d; existing busy/idle logic and classifier remain intact.

### Task 5: P1-1 — Explicit clear-command drop

**Branch:** `codex/handoff-p1-1-clear-drop`

**Files:**
- Modify: `scripts/inbox_watcher.sh`
- Modify: `scripts/handoff_watchdog.py`
- Modify: `tests/unit/test_send_wakeup.bats`
- Modify: `tests/unit/test_handoff_watchdog.bats`
- Modify: `tests/e2e/e2e_busy_clear_guard.bats`
- Modify: `tests/e2e/e2e_redo.bats`
- Modify: `docs/known_issues.md`

**Interfaces:**
- Consumes PR-1d liveness fields.
- A clear command observed in any non-ready delivery state, including busy, reaches terminal `dropped`; it is never deferred for later execution.
- Produces exactly one sanitized `watchdog_alert` to the source agent per dropped command.

- [ ] **Step 1: Add RED tests for busy, blocked, shell, absent, and unknown drop with no later retry.**
- [ ] **Step 2: Add RED alert deduplication and new-command independence tests.** A newly issued clear command may deliver later; redo/resend must not delete another command.
- [ ] **Step 3: Implement fail-closed drop and persisted alert deduplication using existing delivery identity.**
- [ ] **Step 4: Update the clear-command known issue from deferred bug to implemented drop semantics, retaining any verified residual risk.**
- [ ] **Step 5: Run gates, review, push, and open a stacked draft PR.** Roll back by reverting P1-1 to the P0 guard behavior; do not restore delayed execution in a partial state.

### Task 6: P1-2 — Formal command epoch and generated instructions

**Branch:** `codex/handoff-p1-2-cmd-epoch`

**Files:**
- Modify: `CLAUDE.md`
- Modify: `instructions/roles/shogun_role.md`
- Modify: `instructions/roles/karo_role.md`
- Modify: `instructions/roles/ashigaru_role.md`
- Modify: `instructions/roles/gunshi_role.md`
- Modify: `instructions/roles/oometsuke_role.md`
- Modify: `instructions/common/protocol.md`
- Modify: `instructions/common/task_flow.md`
- Modify only the relevant files under `instructions/cli_specific/`
- Modify: `scripts/handoff_watchdog.py`
- Modify: `tests/unit/test_handoff_watchdog.bats`
- Modify: `tests/unit/test_build_system.bats`
- Modify generated outputs only by running `scripts/build_instructions.sh`

**Interfaces:**
- Adds an optional formal `cmd:` epoch to new command/task/delivery data while accepting legacy data without it.
- Compares epoch plus task identity without replacing ack/receipt or creating a new transaction state machine.

- [ ] **Step 1: Add RED command-id generation/comparison/receipt tests, including redo, parallel tasks, and legacy YAML.**
- [ ] **Step 2: Add RED instruction-source tests requiring writers to emit and preserve `cmd:`.**
- [ ] **Step 3: Implement epoch parsing and comparison in the existing watchdog/delivery model.**
- [ ] **Step 4: Edit source instructions only, then run `bash scripts/build_instructions.sh`.** Never hand-edit `AGENTS.md` or `instructions/generated/`.
- [ ] **Step 5: Run `make build`, `make check`, inspect the complete generated diff, then run all gates.** Roll back by reverting P1-2; legacy parsing remains the compatibility floor.

### Task 7: P1-3 — Terminal command closure

**Branch:** `codex/handoff-p1-3-command-closure`

**Files:**
- Create: `scripts/verify_cmd_closed.sh`
- Create: `tests/unit/test_verify_cmd_closed.bats`
- Modify: `Makefile`
- Modify source instructions under `CLAUDE.md` and `instructions/common/task_flow.md` only if the verified workflow requires invoking the checker.
- Regenerate instruction outputs through `scripts/build_instructions.sh` when source instructions change.

**Interfaces:**
- Checks assigned/completed task files plus runtime `queue/tasks/pending.yaml` when present.
- Emits only a sanitized summary; legacy records are classified conservatively, not rejected wholesale.

- [ ] **Step 1: Add RED sanitized fixtures in a Bats temporary directory for terminal-in-pending, unclosed terminal command, valid parallel commands, and legacy YAML.**
- [ ] **Step 2: Implement the checker with an overridable queue root for tests and no direct live runtime reads.**
- [ ] **Step 3: Prevent terminal commands from promotion while allowing unrelated active epochs.**
- [ ] **Step 4: Add a Make target only after the script's unit contract is green.**
- [ ] **Step 5: Run focused tests, generation gates if needed, and full gates.** Roll back by reverting P1-3; no runtime file migration is required.

### Task 8: Per-PR review, publication, and final audit

**Files:**
- Update each draft PR body on GitHub.
- Update this plan's execution evidence only if the repository's established work-log pattern requires it.

- [ ] **Step 1: Re-fetch `main` and record starting/final SHA for each PR.** Rebase or rebuild the stacked base before publication; never force-push without `--force-with-lease`.
- [ ] **Step 2: Perform a cold independent review of the exact base/head diff.** Review requirements, safety boundaries, test quality, generated files, secret scan, and absence of runtime data.
- [ ] **Step 3: Run fresh verification after review fixes.** Do not reuse pre-fix results.
- [ ] **Step 4: Confirm tracked diff contains no `.env`, token, auth JSON, pane capture, live queue/report/log, or WebUI change.**
- [ ] **Step 5: Push the branch and create a draft PR with base SHA, purpose, files, tests, commands, exact pass/fail/skip counts, dependencies, constraints, rollback, and `production deployment not performed`.**
- [ ] **Step 6: Keep the PR draft while the six deployment-only Bloom SKIPs remain unresolved.** Do not merge.
- [ ] **Step 7: Final audit.** Report branches, PR URLs, dependency graph, changed files, known-issues changes, unresolved items, P2 not done, no deployment, and whether any local uncommitted/unpushed or task-only changes remain.

## 2026-07-18 Production Readiness Geometry Hotfix Addendum

This addendum implements the approved design in
`docs/superpowers/specs/2026-07-18-readiness-detached-tmux-geometry-design.md`.
It is based on GitHub `main` commit
`7994e57e392ce41a4b3e24a76dc88b65d0cc844f`. The Lord separately approved
production deployment, restart, rollback if required, and merge for this
hotfix. That approval overrides the original plan's deployment prohibition
only for the steps below. The WebUI, production data reset, permission
approval, automatic restart, and P2 prohibitions remain unchanged.

### Task 9: Detached multiagent startup geometry

**Branch:** `fix/readiness-detached-tmux-geometry`

**Files:**
- Modify: `shutsujin_departure.sh`
- Modify: `tests/unit/test_shutsujin_readiness.bats`
- Modify: `tests/e2e/e2e_cli_readiness.bats`
- Modify: `docs/superpowers/plans/2026-07-17-shogun-handoff-hardening-implementation.md`
- Already created: `docs/superpowers/specs/2026-07-18-readiness-detached-tmux-geometry-design.md`

**Interfaces:**
- Produces fixed shell constants `MULTIAGENT_DETACHED_WIDTH=300` and
  `MULTIAGENT_DETACHED_HEIGHT=120`.
- Passes those constants to `tmux new-session -d -x ... -y ...` only when
  creating the detached `multiagent` session.
- Preserves the existing split order, `window-size latest`,
  `aggressive-resize on`, seven-state classifier, readiness deadline, watcher
  gate, busy/idle behavior, queue/report data, and WebUI boundary.
- Baseline focused tests: unit 5 PASS, 0 FAIL, 0 SKIP; e2e 2 PASS, 0 FAIL,
  0 SKIP.

- [ ] **Step 1: Write the failing unit and isolated e2e tests.** Add the
  following unit contract to `tests/unit/test_shutsujin_readiness.bats`:

```bash
@test "departure gives detached multiagent panes explicit readiness geometry" {
    grep -q '^MULTIAGENT_DETACHED_WIDTH=300$' "$SCRIPT"
    grep -q '^MULTIAGENT_DETACHED_HEIGHT=120$' "$SCRIPT"
    run awk '
        /^MULTIAGENT_DETACHED_WIDTH=300$/ { geometry = 1 }
        geometry && /^if ! tmux new-session -d \\/ {
            capture = 1
            session_line = NR
        }
        capture {
            block = block $0 ORS
            if ($0 !~ /\\$/) {
                print session_line
                print block
                exit
            }
        }
    ' "$SCRIPT"
    [ "$status" -eq 0 ]
    session_line="${output%%$'\n'*}"
    command_block="${output#*$'\n'}"
    [[ "$command_block" == *'-x "$MULTIAGENT_DETACHED_WIDTH"'* ]]
    [[ "$command_block" == *'-y "$MULTIAGENT_DETACHED_HEIGHT"'* ]]
    [[ "$command_block" == *'-s multiagent -n "agents"'* ]]

    run grep -n 'tmux split-window -h -t "multiagent:agents"' "$SCRIPT"
    [ "$status" -eq 0 ]
    split_line="${output%%:*}"
    [ "$session_line" -lt "$split_line" ]
}
```

  Add this isolated fixture and e2e case to
  `tests/e2e/e2e_cli_readiness.bats`; never use the production tmux socket or
  session names:

```bash
GEOMETRY_SOCKET=""

teardown() {
    local attempt pane_id
    if [[ -n "${GEOMETRY_SOCKET:-}" ]]; then
        while read -r pane_id; do
            tmux -L "$GEOMETRY_SOCKET" send-keys -t "$pane_id" exit Enter \
                2>/dev/null || true
        done < <(
            tmux -L "$GEOMETRY_SOCKET" list-panes -a -F '#{pane_id}' \
                2>/dev/null || true
        )

        for attempt in {1..20}; do
            if ! tmux -L "$GEOMETRY_SOCKET" has-session 2>/dev/null; then
                GEOMETRY_SOCKET=""
                return 0
            fi
            sleep 0.05
        done

        echo "isolated geometry tmux cleanup did not complete" >&2
        return 1
    fi
}

@test "E2E readiness: detached multiagent geometry keeps ten tiled panes usable" {
    local width height pane_count=0 pane_width pane_height
    width=$(sed -n 's/^MULTIAGENT_DETACHED_WIDTH=\([0-9][0-9]*\)$/\1/p' \
        "$PROJECT_ROOT/shutsujin_departure.sh")
    height=$(sed -n 's/^MULTIAGENT_DETACHED_HEIGHT=\([0-9][0-9]*\)$/\1/p' \
        "$PROJECT_ROOT/shutsujin_departure.sh")
    [ "$width" -eq 300 ]
    [ "$height" -eq 120 ]

    GEOMETRY_SOCKET="shogun-geometry-${BATS_TEST_NUMBER}-${BASHPID}"
    tmux -L "$GEOMETRY_SOCKET" -f /dev/null new-session -d \
        -x "$width" -y "$height" -s geometry -n agents
    tmux -L "$GEOMETRY_SOCKET" split-window -h -t geometry:agents
    tmux -L "$GEOMETRY_SOCKET" split-window -h -t geometry:agents
    tmux -L "$GEOMETRY_SOCKET" select-pane -t geometry:agents.0
    tmux -L "$GEOMETRY_SOCKET" split-window -v
    tmux -L "$GEOMETRY_SOCKET" split-window -v
    tmux -L "$GEOMETRY_SOCKET" select-pane -t geometry:agents.3
    tmux -L "$GEOMETRY_SOCKET" split-window -v
    tmux -L "$GEOMETRY_SOCKET" split-window -v
    tmux -L "$GEOMETRY_SOCKET" select-pane -t geometry:agents.6
    tmux -L "$GEOMETRY_SOCKET" split-window -v
    tmux -L "$GEOMETRY_SOCKET" split-window -v
    tmux -L "$GEOMETRY_SOCKET" split-window -v -t geometry:agents.8
    tmux -L "$GEOMETRY_SOCKET" select-layout -t geometry:agents tiled

    while read -r pane_width pane_height; do
        ((pane_count += 1))
        [ "$pane_width" -ge 80 ]
        [ "$pane_height" -ge 24 ]
    done < <(
        tmux -L "$GEOMETRY_SOCKET" list-panes -t geometry:agents \
            -F '#{pane_width} #{pane_height}'
    )
    [ "$pane_count" -eq 10 ]
}
```

- [ ] **Step 2: Run RED and verify the expected failure.**

```bash
IDLE_FLAG_DIR="$TASK_IDLE" bats tests/unit/test_shutsujin_readiness.bats \
  --filter 'explicit readiness geometry'
IDLE_FLAG_DIR="$TASK_IDLE" bats tests/e2e/e2e_cli_readiness.bats \
  --filter 'detached multiagent geometry'
```

  Both commands must fail because the two constants and the `-x`/`-y`
  arguments do not exist. A collection error, missing helper, CRLF error, or
  live-session dependency is not an acceptable RED result.

- [ ] **Step 3: Implement the minimum production change.** Immediately before
  the existing `multiagent` `new-session` call, add:

```bash
MULTIAGENT_DETACHED_WIDTH=300
MULTIAGENT_DETACHED_HEIGHT=120
```

  Replace only that session-creation command with:

```bash
if ! tmux new-session -d \
    -x "$MULTIAGENT_DETACHED_WIDTH" \
    -y "$MULTIAGENT_DETACHED_HEIGHT" \
    -s multiagent -n "agents" 2>/dev/null; then
```

  Do not change the working `shogun` creation path, classifier patterns,
  timeout, CLI commands, split order, or watcher logic.

- [ ] **Step 4: Run focused GREEN verification.**

```bash
IDLE_FLAG_DIR="$TASK_IDLE" bats tests/unit/test_shutsujin_readiness.bats --timing
IDLE_FLAG_DIR="$TASK_IDLE" bats tests/e2e/e2e_cli_readiness.bats --timing
```

  Expected: unit 6 PASS, 0 FAIL, 0 SKIP; e2e 3 PASS, 0 FAIL, 0 SKIP. Confirm
  every isolated geometry socket is removed after the e2e process exits.

- [ ] **Step 5: Run local regression and generation gates.**

```bash
IDLE_FLAG_DIR="$TASK_IDLE" make test
IDLE_FLAG_DIR="$TASK_IDLE" make test-int
make lint
make build
make check
git diff --check
git status --short
```

  Record exact pass, fail, and skip totals. Any skip is a failed acceptance
  gate. Verify generated files remain unchanged and the diff contains no WebUI,
  runtime data, `.env`, token, auth JSON, pane content, queue/report body, or
  log content.

- [ ] **Step 6: Commit, independently review, publish, and merge.** Commit the
  test-first implementation, request a cold review of the exact
  `7994e57e...HEAD` diff, fix every blocking issue, and rerun all affected
  gates. Push `fix/readiness-detached-tmux-geometry`, open a draft PR with the
  complete command/count evidence and rollback instructions, then mark it
  ready and merge only after all GitHub checks pass. The Lord's merge approval
  is already recorded; do not bypass branch protection or failing checks.

- [ ] **Step 7: Create a live rollback ref and deploy without data reset.** In
  `/home/jinnouchi/multi-agent-shogun`, confirm branch `main`, zero tracked
  changes, the expected pre-hotfix SHA, and no untracked-name collision. Create
  `rollback/pre-readiness-geometry-20260718-7994e57e` at the deployed
  `7994e57e...` SHA. Fast-forward only from canonical `personal/main`. Never
  use the upstream `origin/main` remote and never pass `--clean`.

- [ ] **Step 8: Run deployment-host acceptance and official startup.** Create
  an isolated temporary `IDLE_FLAG_DIR`, run `make test-no-skip`, `make lint`,
  `make build`, and `make check`, then remove only that validated temporary
  directory. Run `bash shutsujin_departure.sh` without arguments. Require exit
  zero and a sanitized summary in which all eleven roles are `ready` before
  accepting watcher startup. Never approve a prompt or automatically retry a
  failed CLI.

- [ ] **Step 9: Run trusted post-start verification and close the hotfix.**
  Immediately re-fetch the GitHub `main` diagnostic registry, validate exactly
  one active schema-version-1 deployment, invoke only the fixed approved
  diagnostic command, and independently validate the complete sanitized JSON
  contract. Require the merged SHA, both expected sessions, eleven alive panes,
  and one healthy watcher per role. Report any remaining sanitized warning or
  error without a raw-data fallback. Roll back to the pre-hotfix ref if startup
  readiness or the trusted diagnostic fails.

## Rollback Conditions

Rollback the current PR rather than expanding scope when any of these occurs:

- A non-ready pane receives a startup prompt, inbox token, clear command, model switch, or automatic approval.
- `agent_is_busy_check`, `agent_is_busy`, idle-flag meaning, throttle, self-watch, ack, or receipt semantics change outside the explicit P1 contract.
- stdout from `get_pane_cli_state` contains anything except one state token or the function exits nonzero.
- `notification_count` is renamed or fields beyond the two approved P0 additions appear.
- More than the aggregated send entrances require changes, indicating the delivery boundary inventory is wrong.
- Instruction generation produces unexplained diffs or source/generated synchronization fails.
- A test fixture contains live pane, queue, report, log, secret, token, auth JSON, or `.env` content.
- Any PR gate adds a new FAIL or SKIP; the branch remains draft until corrected or explicitly documented as the pre-existing six Bloom deployment skips.

## Verification Command Set

```bash
export IDLE_FLAG_DIR="$TASK_IDLE"
bats tests/unit/test_stop_hook.bats tests/unit/test_send_wakeup.bats tests/unit/test_agent_status.bats tests/unit/test_switch_cli.bats tests/unit/test_departure_readiness.bats tests/unit/test_handoff_watchdog.bats tests/unit/test_verify_cmd_closed.bats --timing
bats tests/e2e/e2e_escalation.bats tests/e2e/e2e_clear_recovery.bats tests/e2e/e2e_codex_startup.bats tests/e2e/e2e_inbox_delivery.bats tests/e2e/e2e_busy_clear_guard.bats tests/e2e/e2e_redo.bats --timing
make lint
make build
make check
make test
make test-int
bats tests/e2e/*.bats --timing
git diff --check
git status --short
```

`make test-no-skip` is intentionally absent from the local command set. It is run only in a separately approved deployment-host validation with all prerequisites and without weakening the no-live-data fixture boundary.

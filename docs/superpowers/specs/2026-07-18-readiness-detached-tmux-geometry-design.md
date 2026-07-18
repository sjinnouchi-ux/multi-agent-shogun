# Detached tmux Readiness Geometry Design

## Context

Shogun handoff hardening was deployed from GitHub `main` at
`7994e57e392ce41a4b3e24a76dc88b65d0cc844f`. The deployment-host test suite
passed with 877 tests, zero failures, and zero skips, and `make lint`,
`make build`, and `make check` also passed.

The first production startup correctly failed closed at the CLI readiness
gate. `shogun` reported `ready`, while all ten roles in the detached
`multiagent` session reported `unknown`. Watchers were not started. The trusted
sanitized diagnostic confirmed that both tmux sessions and all eleven panes
were present, all panes were alive, and the expected CLI processes were
observed. It also confirmed zero watcher processes, which matches the guarded
startup result.

`shutsujin_departure.sh` creates `multiagent` without an explicit detached
window size and then divides the window into ten panes. A detached tmux window
therefore starts at a small default geometry. Current Codex and Claude TUIs do
not reliably render their positive readiness markers in those small panes.
The single-pane `shogun` session does render its marker, explaining the
role-specific result without using process names as readiness evidence.

An isolated tmux server reproduced the production split order. With an initial
geometry of `300x120`, nine panes measured approximately `99x29` and the tenth
measured `300x30` after `select-layout tiled`. The isolated server was removed
after measurement.

## Goal

Give the detached `multiagent` window enough initial terminal geometry for all
ten CLI TUIs to render their existing positive markers before the readiness
deadline, while preserving the fail-closed readiness classifier and all
existing runtime behavior after a client attaches.

## Non-goals

- Do not change `get_pane_cli_state`, its seven states, or marker precedence.
- Do not use process names to infer `ready`.
- Do not change `agent_is_busy_check`, `agent_is_busy`, idle flags, watcher
  throttle, self-watch, ack, or receipt handling.
- Do not extend the readiness timeout as a substitute for visible markers.
- Do not auto-approve permission prompts or auto-restart a CLI.
- Do not modify WebUI code or open WebUI automatically.
- Do not reset or rewrite production queue, report, dashboard, or log data.
- Do not implement P2 behavior.

## Design

Add two fixed startup constants to `shutsujin_departure.sh`:

```bash
MULTIAGENT_DETACHED_WIDTH=300
MULTIAGENT_DETACHED_HEIGHT=120
```

Use them only when the detached `multiagent` session is first created:

```bash
tmux new-session -d \
    -x "$MULTIAGENT_DETACHED_WIDTH" \
    -y "$MULTIAGENT_DETACHED_HEIGHT" \
    -s multiagent -n "agents"
```

The existing split order, pane metadata, CLI commands, readiness wait, and
watcher startup gate remain unchanged. The existing global tmux settings
`window-size latest` and `aggressive-resize on` remain authoritative after a
real client attaches, so the explicit geometry affects only detached startup.
The working `shogun` session creation is not changed.

No environment override is added. Fixed values keep production startup and
tests deterministic and avoid introducing a new unsupported configuration
surface.

## Failure handling

The current failure behavior remains intact. If any pane is not `ready` by the
shared deadline, startup exits nonzero, prints only the sanitized role summary,
and does not start watchers. Permission, login, shell, absent, and unknown
states remain non-ready. No automatic retry or restart is added.

## Test strategy

Testing remains test-first.

1. Add a failing unit test to
   `tests/unit/test_shutsujin_readiness.bats` that requires the two constants
   and requires the `multiagent` `new-session` command to use both `-x` and
   `-y` before any pane split.
2. Add an isolated tmux case to `tests/e2e/e2e_cli_readiness.bats`. It reads the
   committed dimensions, reproduces the ten-pane production split order on a
   unique tmux socket, applies `tiled`, and verifies that every pane is at least
   80 columns by 24 rows. The test always removes its isolated tmux server.
3. Run the focused unit and e2e tests, then `make test`, `make test-int`,
   `make lint`, `make build`, and `make check`.
4. After merge and deployment, run `make test-no-skip` with an isolated
   `IDLE_FLAG_DIR` on the deployment host. Any skip is a failure.
5. Start through `bash shutsujin_departure.sh` without `--clean`. Require an
   exit-zero aggregate readiness result before accepting watcher startup.
6. Fetch and validate the diagnostic registry again, then run only the fixed
   sanitized diagnostic command and require all sessions, panes, and watchers
   to satisfy the schema invariants.

No production pane content, queue/report bodies, or log lines are used as test
fixtures or verification output.

## PR and rollout

The hotfix is an independent PR based on
`7994e57e392ce41a4b3e24a76dc88b65d0cc844f`. It changes only startup geometry,
the focused tests, and the existing implementation record. It does not alter
the previously merged PR dependency graph.

Before deployment, create a rollback ref pointing to the current deployed SHA.
Fast-forward the live `main` only after all required checks and independent
review pass. Restart with the official launcher and without `--clean`.

Rollback to the pre-hotfix deployed SHA if focused tests, regression tests,
lint/build/check, aggregate startup readiness, or the trusted post-start
diagnostic fails. Rollback does not authorize queue/report cleanup or WebUI
changes.

## Acceptance criteria

- The detached `multiagent` session is created at exactly `300x120`.
- The production ten-pane tiled layout provides every pane at least `80x24`
  before a client attaches.
- All eleven roles report `ready` during official startup, or startup remains
  safely blocked with watchers absent.
- No classifier, busy/idle, watcher, WebUI, queue/report, permission, restart,
  or P2 behavior changes.
- Required tests report explicit pass, fail, and skip counts; skips are not
  accepted.
- Independent review finds no blocking issue before merge.
- Production deployment uses no `--clean` and exposes no secrets or runtime
  content.

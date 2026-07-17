#!/usr/bin/env bats

setup() {
    PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    # The readiness helper must consume the PR-1b classifier rather than
    # introducing a second pane-state detector.
    source "$PROJECT_ROOT/lib/agent_status.sh"
    source "$PROJECT_ROOT/lib/cli_readiness.sh"
}

@test "batch readiness reports every role and fails closed for mixed states" {
    get_pane_cli_state() {
        case "$1" in
            pane-ready) echo ready ;;
            pane-permission) echo permission_prompt ;;
            pane-login) echo login_prompt ;;
            pane-shell) echo shell_prompt ;;
            pane-absent) echo absent ;;
            *) echo unknown ;;
        esac
    }

    local roles=(shogun karo ashigaru1 ashigaru2 gunshi oometsuke)
    local panes=(pane-ready pane-permission pane-login pane-shell pane-absent pane-unknown)
    local clis=(claude claude codex codex claude claude)
    local states=()

    run cli_readiness_wait_all roles panes clis states 0 0

    [ "$status" -eq 1 ]
    [[ "$output" == *"cli_readiness role=shogun state=ready ready=true"* ]]
    [[ "$output" == *"cli_readiness role=karo state=permission_prompt ready=false"* ]]
    [[ "$output" == *"cli_readiness role=ashigaru1 state=login_prompt ready=false"* ]]
    [[ "$output" == *"cli_readiness role=ashigaru2 state=shell_prompt ready=false"* ]]
    [[ "$output" == *"cli_readiness role=gunshi state=absent ready=false"* ]]
    [[ "$output" == *"cli_readiness role=oometsuke state=unknown ready=false"* ]]
    [[ "$output" == *"cli_readiness overall=not_ready"* ]]
    [[ "$output" != *"pane-"* ]]
}

@test "batch readiness waits through busy and delayed startup until every role is ready" {
    export MOCK_DELAY_CALLS="$BATS_TEST_TMPDIR/delay-ready.calls"
    echo 0 > "$MOCK_DELAY_CALLS"
    get_pane_cli_state() {
        local pane="$1"
        if [[ "$pane" == "pane-delay" ]]; then
            local calls
            calls=$(<"$MOCK_DELAY_CALLS")
            calls=$((calls + 1))
            echo "$calls" > "$MOCK_DELAY_CALLS"
            if [[ "$calls" -eq 1 ]]; then
                echo busy
                return
            fi
        fi
        echo ready
    }

    local roles=(shogun karo)
    local panes=(pane-ready pane-delay)
    local clis=(claude codex)
    local states=()

    run cli_readiness_wait_all roles panes clis states 1 0

    [ "$status" -eq 0 ]
    [[ "$output" == *"cli_readiness role=shogun state=ready ready=true"* ]]
    [[ "$output" == *"cli_readiness role=karo state=ready ready=true"* ]]
    [[ "$output" == *"cli_readiness overall=ready"* ]]
}

@test "busy is liveness, not readiness, and times out as not ready" {
    get_pane_cli_state() { echo busy; }

    local roles=(ashigaru1)
    local panes=(pane-busy)
    local clis=(codex)
    local states=()

    run cli_readiness_wait_all roles panes clis states 0 0

    [ "$status" -eq 1 ]
    [[ "$output" == *"state=busy ready=false"* ]]
    [[ "$output" == *"cli_readiness overall=not_ready"* ]]
}

@test "summary rejects unsafe role labels without echoing them" {
    get_pane_cli_state() { echo ready; }

    local roles=('bad role=value')
    local panes=(pane-ready)
    local clis=(claude)
    local states=()

    run cli_readiness_wait_all roles panes clis states 0 0

    [ "$status" -eq 2 ]
    [[ "$output" == *"cli_readiness error=invalid_input"* ]]
    [[ "$output" != *"bad role=value"* ]]
}

@test "shared deadline bounds slow role probes and cannot report late success" {
    get_pane_cli_state() {
        sleep 2
        echo ready
    }

    local roles=(shogun karo ashigaru1)
    local panes=(pane-one pane-two pane-three)
    local clis=(claude claude codex)
    local states=()
    local started elapsed
    started=$SECONDS

    run cli_readiness_wait_all roles panes clis states 1 0.1
    elapsed=$((SECONDS - started))

    [ "$status" -eq 1 ]
    [ "$elapsed" -lt 3 ]
    [[ "$output" == *"cli_readiness overall=not_ready"* ]]
}

@test "watcher quiesce stops watcher and child wait processes" {
    export MOCK_PKILL_LOG="$BATS_TEST_TMPDIR/pkill.calls"
    export MOCK_NOHUP_LOG="$BATS_TEST_TMPDIR/nohup.calls"
    local supervisor_running=true
    : > "$MOCK_PKILL_LOG"
    : > "$MOCK_NOHUP_LOG"
    pgrep() {
        [[ "$*" == *watcher_supervisor.sh* && "$supervisor_running" == true ]]
    }
    pkill() {
        printf '%s\n' "$*" >> "$MOCK_PKILL_LOG"
        if [[ "$*" == *watcher_supervisor.sh* ]]; then
            supervisor_running=false
            return 0
        fi
        return 1
    }
    nohup() {
        printf '%s\n' "$*" >> "$MOCK_NOHUP_LOG"
        sleep 1
    }

    cli_readiness_quiesce_watchers

    [ "${CLI_READINESS_SUPERVISOR_WAS_RUNNING:-}" = true ]
    grep -Fq -- 'watcher_supervisor.sh' "$MOCK_PKILL_LOG"
    grep -Fxq -- '-f inbox_watcher.sh' "$MOCK_PKILL_LOG"
    grep -Fxq -- '-f inotifywait.*queue/inbox' "$MOCK_PKILL_LOG"
    grep -Fxq -- '-f fswatch.*queue/inbox' "$MOCK_PKILL_LOG"

    mkdir -p "$BATS_TEST_TMPDIR/project"/{scripts,logs}
    : > "$BATS_TEST_TMPDIR/project/scripts/watcher_supervisor.sh"
    cli_readiness_resume_watcher_supervisor "$BATS_TEST_TMPDIR/project"
    wait

    grep -Fq -- 'watcher_supervisor.sh' "$MOCK_NOHUP_LOG"
    [ "${CLI_READINESS_SUPERVISOR_WAS_RUNNING:-}" = false ]
}

@test "watcher supervisor resume fails closed and remains retryable after early exit" {
    mkdir -p "$BATS_TEST_TMPDIR/project"/{scripts,logs}
    : > "$BATS_TEST_TMPDIR/project/scripts/watcher_supervisor.sh"
    local runner="$BATS_TEST_TMPDIR/resume-failure-runner.sh"
    cat > "$runner" <<'RUNNER'
#!/usr/bin/env bash
project_root="$1"
fixture_root="$2"
source "$project_root/lib/cli_readiness.sh"
CLI_READINESS_SUPERVISOR_WAS_RUNNING=true
nohup() { return 1; }
cli_readiness_resume_watcher_supervisor "$fixture_root"
resume_status=$?
printf 'supervisor_retryable=%s\n' "$CLI_READINESS_SUPERVISOR_WAS_RUNNING"
exit "$resume_status"
RUNNER
    chmod +x "$runner"

    run bash "$runner" "$PROJECT_ROOT" "$BATS_TEST_TMPDIR/project"

    [ "$status" -eq 1 ]
    [[ "$output" == *"cli_readiness error=watcher_supervisor_resume_failed"* ]]
    [[ "$output" == *"supervisor_retryable=true"* ]]
}

@test "watcher quiesce fails closed when supervisor cannot be stopped" {
    pgrep() {
        [[ "$*" == *watcher_supervisor.sh* ]]
    }
    pkill() {
        return 1
    }

    run cli_readiness_quiesce_watchers

    [ "$status" -eq 1 ]
    [[ "$output" == *"cli_readiness error=watcher_supervisor_quiesce_failed"* ]]
}

@test "deadline cleanup terminates descendant probe processes" {
    export MOCK_DESCENDANT_PID="$BATS_TEST_TMPDIR/descendant.pid"
    get_pane_cli_state() {
        tail -f /dev/null >/dev/null 2>&1 3>&- &
        echo "$!" > "$MOCK_DESCENDANT_PID"
        wait "$!"
        echo ready
    }

    local roles=(shogun)
    local panes=(pane-slow)
    local clis=(claude)
    local states=()

    run cli_readiness_wait_all roles panes clis states 1 0.1
    [ "$status" -eq 1 ]

    local descendant_pid alive=false
    descendant_pid=$(<"$MOCK_DESCENDANT_PID")
    if kill -0 "$descendant_pid" 2>/dev/null; then
        alive=true
        kill "$descendant_pid" 2>/dev/null || true
        wait "$descendant_pid" 2>/dev/null || true
    fi
    [ "$alive" = false ]
}

@test "TERM cleanup terminates active probe descendants" {
    local runner="$BATS_TEST_TMPDIR/readiness-term-runner.sh"
    local pid_file="$BATS_TEST_TMPDIR/term-descendant.pid"
    local handler_file="$BATS_TEST_TMPDIR/prior-term-handler.called"
    cat > "$runner" <<'RUNNER'
#!/usr/bin/env bash
project_root="$1"
pid_file="$2"
handler_file="$3"
source "$project_root/lib/agent_status.sh"
source "$project_root/lib/cli_readiness.sh"
trap 'printf handled > "$handler_file"' TERM
get_pane_cli_state() {
    tail -f /dev/null >/dev/null 2>&1 3>&- &
    echo "$!" > "$pid_file"
    wait "$!"
    echo ready
}
roles=(shogun)
panes=(pane-slow)
clis=(claude)
states=()
cli_readiness_wait_all roles panes clis states 30 0.1
RUNNER
    chmod +x "$runner"

    bash "$runner" "$PROJECT_ROOT" "$pid_file" "$handler_file" >/dev/null 2>&1 3>&- &
    local runner_pid=$!
    local i
    for i in {1..50}; do
        [[ -s "$pid_file" ]] && break
        sleep 0.02
    done
    [ -s "$pid_file" ]
    kill -TERM "$runner_pid"
    wait "$runner_pid" 2>/dev/null || true
    [ -f "$handler_file" ]

    local descendant_pid alive=false
    descendant_pid=$(<"$pid_file")
    if kill -0 "$descendant_pid" 2>/dev/null; then
        alive=true
        kill "$descendant_pid" 2>/dev/null || true
        wait "$descendant_pid" 2>/dev/null || true
    fi
    [ "$alive" = false ]
}

@test "readiness wait preserves caller RETURN trap and works with functrace" {
    local runner="$BATS_TEST_TMPDIR/readiness-return-trap-runner.sh"
    cat > "$runner" <<'RUNNER'
#!/usr/bin/env bash
project_root="$1"
source "$project_root/lib/agent_status.sh"
source "$project_root/lib/cli_readiness.sh"
set -T
return_count=0
prior_return() { return_count=$((return_count + 1)); }
trap prior_return RETURN
before_trap=$(trap -p RETURN)
get_pane_cli_state() {
    echo ready
}
roles=(shogun)
panes=(pane-ready)
clis=(claude)
states=()
cli_readiness_wait_all roles panes clis states 2 0.1 >/dev/null
wait_status=$?
after_trap=$(trap -p RETURN)
[[ "$wait_status" -eq 0 && "$before_trap" == "$after_trap" ]]
RUNNER
    chmod +x "$runner"

    run bash "$runner" "$PROJECT_ROOT"

    [ "$status" -eq 0 ]
}

@test "readiness wait preserves caller RETURN trap without functrace" {
    local runner="$BATS_TEST_TMPDIR/readiness-existing-return-trap-runner.sh"
    cat > "$runner" <<'RUNNER'
#!/usr/bin/env bash
project_root="$1"
source "$project_root/lib/agent_status.sh"
source "$project_root/lib/cli_readiness.sh"
set +T
return_count=0
prior_return() { return_count=$((return_count + 1)); }
trap prior_return RETURN
before_trap=$(trap -p RETURN)
get_pane_cli_state() { echo ready; }
roles=(shogun)
panes=(pane-ready)
clis=(claude)
states=()
cli_readiness_wait_all roles panes clis states 2 0.1 >/dev/null
wait_status=$?
after_trap=$(trap -p RETURN)
[[ "$wait_status" -eq 0 && "$before_trap" == "$after_trap" ]]
RUNNER
    chmod +x "$runner"

    run bash "$runner" "$PROJECT_ROOT"

    [ "$status" -eq 0 ]
}

@test "readiness wait succeeds with functrace and no caller RETURN trap" {
    local runner="$BATS_TEST_TMPDIR/readiness-functrace-runner.sh"
    cat > "$runner" <<'RUNNER'
#!/usr/bin/env bash
project_root="$1"
source "$project_root/lib/agent_status.sh"
source "$project_root/lib/cli_readiness.sh"
set -T
trap - RETURN
get_pane_cli_state() { echo ready; }
roles=(shogun)
panes=(pane-ready)
clis=(claude)
states=()
cli_readiness_wait_all roles panes clis states 2 0.1 >/dev/null
wait_status=$?
[[ "$wait_status" -eq 0 && -z "$(trap -p RETURN)" ]]
RUNNER
    chmod +x "$runner"

    run bash "$runner" "$PROJECT_ROOT"

    [ "$status" -eq 0 ]
}

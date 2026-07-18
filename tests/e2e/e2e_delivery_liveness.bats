#!/usr/bin/env bats

# bats file_tags=e2e

setup_file() {
    command -v tmux &>/dev/null || skip "tmux not available"
    command -v python3 &>/dev/null || skip "python3 not available"
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
}

setup() {
    export TEST_ROOT="$(mktemp -d /tmp/e2e_delivery_liveness.XXXXXX)"
    export E2E_SESSION="e2e_delivery_liveness_${BATS_TEST_NUMBER}_$$"
    export PANE_TARGET="${E2E_SESSION}:agent.0"
    export AGENT_ID="ashigaru1"
    mkdir -p "$TEST_ROOT/queue/inbox"
    printf 'messages: []\n' > "$TEST_ROOT/queue/inbox/${AGENT_ID}.yaml"
    tmux new-session -d -s "$E2E_SESSION" -n agent -x 160 -y 40
    tmux set-option -p -t "$PANE_TARGET" @agent_id "$AGENT_ID"
    tmux set-option -p -t "$PANE_TARGET" @agent_cli claude
    touch "$TEST_ROOT/shogun_idle_${AGENT_ID}"
}

teardown() {
    tmux kill-session -t "$E2E_SESSION" 2>/dev/null || true
    rm -rf "$TEST_ROOT"
}

start_behavior() {
    local behavior="$1"
    local ready_delay="${2:-1}"
    tmux send-keys -t "$PANE_TARGET" \
        "MOCK_STARTUP_BEHAVIOR=$behavior MOCK_READY_DELAY=$ready_delay MOCK_CLI_TYPE=claude MOCK_AGENT_ID=$AGENT_ID MOCK_PROCESSING_DELAY=1 MOCK_PROJECT_ROOT=$TEST_ROOT bash $PROJECT_ROOT/tests/e2e/mock_cli.sh" Enter
}

wait_for_pane() {
    local pattern="$1"
    local attempts="${2:-50}"
    local capture=""
    local i
    for ((i = 0; i < attempts; i++)); do
        capture=$(tmux capture-pane -p -t "$PANE_TARGET")
        if printf '%s\n' "$capture" | grep -qF "$pattern"; then
            return 0
        fi
        sleep 0.1
    done
    return 1
}

run_delivery() {
    run env \
        __INBOX_WATCHER_TESTING__=1 \
        AGENT_ID="$AGENT_ID" \
        PANE_TARGET="$PANE_TARGET" \
        CLI_TYPE=claude \
        INBOX="$TEST_ROOT/queue/inbox/${AGENT_ID}.yaml" \
        LOCKFILE="$TEST_ROOT/queue/inbox/${AGENT_ID}.yaml.lock" \
        SCRIPT_DIR="$PROJECT_ROOT" \
        IDLE_FLAG_DIR="$TEST_ROOT" \
        WATCHER_SCRIPT="$PROJECT_ROOT/scripts/inbox_watcher.sh" \
        bash -c 'source "$WATCHER_SCRIPT"; send_wakeup 1'
}

assert_blocked_without_input() {
    local expected_state="$1"
    run_delivery
    [ "$status" -eq 0 ]
    printf '%s\n' "$output" | grep -q "cli_state=$expected_state"
    local capture
    capture=$(tmux capture-pane -p -t "$PANE_TARGET")
    ! printf '%s\n' "$capture" | grep -q "inbox1"
}

@test "delivery gate blocks a permission prompt" {
    start_behavior permission_prompt
    wait_for_pane "Do you want to allow this command?"
    assert_blocked_without_input permission_prompt
}

@test "delivery gate blocks a login prompt" {
    start_behavior login_prompt
    wait_for_pane "Please sign in to continue"
    assert_blocked_without_input login_prompt
}

@test "delivery gate blocks after the CLI exits to a shell prompt" {
    start_behavior shell_prompt
    wait_for_pane 'mock-shell$'
    assert_blocked_without_input shell_prompt
}

@test "delivery gate blocks a CLI that never becomes ready" {
    start_behavior never_ready
    wait_for_pane "[mock_state] never_ready"
    assert_blocked_without_input unknown
}

@test "delivery gate retries successfully after delayed readiness" {
    start_behavior delay_ready 1
    wait_for_pane "[mock_state] delay_ready"
    assert_blocked_without_input unknown

    wait_for_pane "bypass permissions" 80
    run_delivery
    [ "$status" -eq 0 ]
    wait_for_pane "Received nudge: inbox1"
}

@test "delivery gate preserves normal ready delivery" {
    start_behavior ready
    wait_for_pane "bypass permissions"
    run_delivery
    [ "$status" -eq 0 ]
    wait_for_pane "Received nudge: inbox1"
}

@test "live busy CLI remains governed by the existing busy guard" {
    start_behavior busy
    wait_for_pane "Working"
    rm -f "$TEST_ROOT/shogun_idle_${AGENT_ID}"
    run_delivery
    [ "$status" -eq 0 ]
    printf '%s\n' "$output" | grep -q "is busy"
    local capture
    capture=$(tmux capture-pane -p -t "$PANE_TARGET")
    ! printf '%s\n' "$capture" | grep -q "inbox1"
}

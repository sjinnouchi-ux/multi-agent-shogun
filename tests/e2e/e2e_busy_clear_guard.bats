#!/usr/bin/env bats
# ═══════════════════════════════════════════════════════════════
# E2E-009: busy中/clear抑制テスト
# ═══════════════════════════════════════════════════════════════
# Verifies inbox_watcher behavior when clear_command arrives while
# an agent is working:
#   - busy state: clear_command is explicitly dropped and source-alerted
#   - idle state: a newly issued clear_command is sent to the agent
# ═══════════════════════════════════════════════════════════════

# bats file_tags=e2e

load "../test_helper/bats-support/load"
load "../test_helper/bats-assert/load"

E2E_HELPERS_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/helpers" && pwd)"
source "$E2E_HELPERS_DIR/setup.bash"
source "$E2E_HELPERS_DIR/assertions.bash"
source "$E2E_HELPERS_DIR/tmux_helpers.bash"

setup_file() {
    command -v tmux &>/dev/null || skip "tmux not available"
    command -v python3 &>/dev/null || skip "python3 not available"
    python3 -c "import yaml" 2>/dev/null || skip "python3-yaml not available"

    setup_e2e_session 3
    mkdir -p "$E2E_QUEUE/.venv/bin"
    ln -sf "$(command -v python3)" "$E2E_QUEUE/.venv/bin/python3"
}

teardown_file() {
    teardown_e2e_session
}

setup() {
    reset_queues
    mkdir -p "$E2E_QUEUE/.venv/bin"
    ln -sf "$(command -v python3)" "$E2E_QUEUE/.venv/bin/python3"
    sleep 2
}

wait_for_log() {
    local log_file="$1" pattern="$2" timeout="${3:-20}"
    local elapsed=0
    while [ "$elapsed" -lt "$timeout" ]; do
        if grep -qF "$pattern" "$log_file" 2>/dev/null; then
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    echo "TIMEOUT: '$pattern' not found in $log_file after ${timeout}s" >&2
    return 1
}

# ═══ E2E-009-A: clear_command is explicitly dropped while busy ═══

@test "E2E-009-A: busy clear_command is dropped once and never delivered later" {
    local ashigaru1_pane
    ashigaru1_pane=$(pane_target 1)
    local log_file watcher_pid

    cp "$PROJECT_ROOT/tests/e2e/fixtures/task_ashigaru1_basic.yaml" \
        "$E2E_QUEUE/queue/tasks/ashigaru1.yaml"

    # Keep mock in busy state before clear_command arrives.
    send_to_pane "$ashigaru1_pane" "busy_hold 15"
    sleep 2

    tmux set-option -p -t "$ashigaru1_pane" @agent_cli "claude"
    log_file="/tmp/e2e_inbox_watcher_ashigaru1_busy_${BASHPID}.log"
    watcher_pid=$(
        INOTIFY_TIMEOUT=1 bash "$E2E_QUEUE/scripts/inbox_watcher.sh" "ashigaru1" "$ashigaru1_pane" "claude" \
            > "$log_file" 2>&1 &
        echo $!
    )
    sleep 2

    bash "$E2E_QUEUE/scripts/inbox_write.sh" "ashigaru1" \
        "/clear" "clear_command" "karo" "cmd_test_001" "subtask_test_001a"

    run wait_for_log "$log_file" "[CLEAR-DROP] agent=ashigaru1 cli_state=busy reason=busy"
    assert_success
    run wait_for_log "$log_file" "[CLEAR-DROP-ALERT] agent=ashigaru1 reason=busy source=karo"
    assert_success

    run python3 - "$E2E_QUEUE/queue/inbox/ashigaru1.yaml" <<'PY'
import sys, yaml
with open(sys.argv[1], encoding="utf-8") as handle:
    message = yaml.safe_load(handle)["messages"][0]
delivery = message["delivery"]
assert message["read"] is True, message
assert delivery["cli_state_at_notify"] == "busy", delivery
assert delivery["delivery_blocked_reason"] == "busy", delivery
PY
    assert_success

    run python3 - "$E2E_QUEUE/queue/inbox/karo.yaml" <<'PY'
import sys, yaml
with open(sys.argv[1], encoding="utf-8") as handle:
    messages = (yaml.safe_load(handle) or {}).get("messages", []) or []
alerts = [
    message for message in messages
    if message.get("type") == "watchdog_alert"
    and message.get("from") == "handoff_watchdog"
]
assert len(alerts) == 1, alerts
assert "/clear" not in (alerts[0].get("content") or ""), alerts
PY
    assert_success

    # Busy suppression keeps task unprocessed by /clear path.
    run wait_for_yaml_value "$E2E_QUEUE/queue/tasks/ashigaru1.yaml" "task.status" "assigned" 30
    assert_success

    # busy_hold is deterministic; wait past it and let the watcher cycle again.
    sleep 18

    # The old command remains terminally dropped after the agent becomes ready.
    run grep -qF "[SEND-KEYS] Sending CLI command to ashigaru1 (claude): /clear" "$log_file"
    [ "$status" -ne 0 ]

    stop_inbox_watcher "$watcher_pid"
}

# ═══ E2E-009-B: clear_command is sent when idle ═══

@test "E2E-009-B: clear_command is sent when agent is idle" {
    local ashigaru2_pane
    ashigaru2_pane=$(pane_target 2)
    local log_file watcher_pid
    local idle_flag="${IDLE_FLAG_DIR:-/tmp}/shogun_idle_ashigaru2"

    touch "$idle_flag"

    cp "$PROJECT_ROOT/tests/e2e/fixtures/task_ashigaru1_basic.yaml" \
        "$E2E_QUEUE/queue/tasks/ashigaru2.yaml"

    tmux set-option -p -t "$ashigaru2_pane" @agent_cli "claude"
    log_file="/tmp/e2e_inbox_watcher_ashigaru2_idle_${BASHPID}.log"
    watcher_pid=$(
        INOTIFY_TIMEOUT=1 bash "$E2E_QUEUE/scripts/inbox_watcher.sh" "ashigaru2" "$ashigaru2_pane" "claude" \
            > "$log_file" 2>&1 &
        echo $!
    )
    sleep 2

    bash "$E2E_QUEUE/scripts/inbox_write.sh" "ashigaru2" \
        "/clear" "clear_command" "karo" "cmd_test_001" "subtask_test_001a"

    run wait_for_log "$log_file" "[SEND-KEYS] Sending CLI command to ashigaru2 (claude): /clear"
    assert_success

    run wait_for_yaml_value "$E2E_QUEUE/queue/tasks/ashigaru2.yaml" "task.status" "done" 45
    assert_success

    stop_inbox_watcher "$watcher_pid"
}

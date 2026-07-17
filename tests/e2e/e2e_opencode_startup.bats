#!/usr/bin/env bats
# ═══════════════════════════════════════════════════════════════
# E2E-009: OpenCode CLI task startup after /new
# ═══════════════════════════════════════════════════════════════
# Validates that inbox_watcher correctly handles OpenCode CLI agents:
#   1. Sends /new for context reset
#   2. Does NOT send a startup prompt because OpenCode loads role via --agent
#   3. Sends a normal inbox nudge so the agent processes the assigned task
#   4. Watcher log shows the OpenCode-specific /new path
# ═══════════════════════════════════════════════════════════════

# bats file_tags=e2e

load "../test_helper/bats-support/load"
load "../test_helper/bats-assert/load"

# Load E2E helpers
E2E_HELPERS_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/helpers" && pwd)"
source "$E2E_HELPERS_DIR/setup.bash"
source "$E2E_HELPERS_DIR/assertions.bash"
source "$E2E_HELPERS_DIR/tmux_helpers.bash"

# ─── Lifecycle ───

setup_file() {
    command -v tmux &>/dev/null || skip "tmux not available"
    command -v python3 &>/dev/null || skip "python3 not available"
    python3 -c "import yaml" 2>/dev/null || skip "python3-yaml not available"

    setup_e2e_session 3
}

teardown_file() {
    teardown_e2e_session
}

setup() {
    reset_queues
    sleep 1
}

dump_watcher_log() {
    local log_file="$1"
    echo "=== Watcher log ($log_file) ===" >&2
    cat "$log_file" >&2 2>/dev/null || echo "(log not found)" >&2
    echo "=== End watcher log ===" >&2
}

# ═══════════════════════════════════════════════════════════════
# E2E-009-A: OpenCode agent resets with /new and processes the assigned task
# ═══════════════════════════════════════════════════════════════

@test "E2E-009-A: OpenCode /new reset triggers task processing via inbox_watcher" {
    local ashigaru1_pane
    ashigaru1_pane=$(pane_target 1)

    # 1. Respawn pane with OpenCode mock
    tmux respawn-pane -k -t "$ashigaru1_pane" \
        "MOCK_CLI_TYPE=opencode MOCK_AGENT_ID=ashigaru1 MOCK_PROCESSING_DELAY=1 MOCK_PROJECT_ROOT=$E2E_QUEUE bash $PROJECT_ROOT/tests/e2e/mock_cli.sh"
    sleep 2
    tmux set-option -p -t "$ashigaru1_pane" @agent_cli "opencode"

    # 2. Place assigned task YAML
    cp "$PROJECT_ROOT/tests/e2e/fixtures/task_ashigaru1_basic.yaml" \
       "$E2E_QUEUE/queue/tasks/ashigaru1.yaml"

    # 3. Send task_assigned message via inbox_write
    bash "$E2E_QUEUE/scripts/inbox_write.sh" "ashigaru1" \
        "タスクYAMLを読んで作業開始せよ。" "task_assigned" "karo" \
        "cmd_test_001" "subtask_test_001a"

    # 4. Start inbox_watcher with OpenCode CLI type
    local watcher_pid log_file
    watcher_pid=$(start_inbox_watcher "ashigaru1" 1 "opencode")
    log_file="/tmp/e2e_inbox_watcher_ashigaru1_$$.log"

    # 5. Wait for task to complete
    run wait_for_yaml_value "$E2E_QUEUE/queue/tasks/ashigaru1.yaml" "task.status" "done" 45
    if [ "$status" -ne 0 ]; then
        dump_watcher_log "$log_file"
    fi
    assert_success

    # 6. Verify report was written
    run wait_for_file "$E2E_QUEUE/queue/reports/ashigaru1_report.yaml" 10
    assert_success

    # 7. Verify report content
    assert_yaml_field "$E2E_QUEUE/queue/reports/ashigaru1_report.yaml" "status" "done"
    assert_yaml_field "$E2E_QUEUE/queue/reports/ashigaru1_report.yaml" "task_id" "subtask_test_001a"

    # 8. Verify OpenCode does NOT receive a startup prompt; --agent handles bootstrap
    run grep "Sending startup prompt" "$log_file"
    assert_failure

    run grep "CONTEXT-RESET.*Sending /new" "$log_file"
    assert_success

    # 9. Verify the OpenCode-style mock prompt appeared in the pane output
    run wait_for_pane_text "$ashigaru1_pane" "Ask anything" 10
    if [ "$status" -ne 0 ]; then
        dump_watcher_log "$log_file"
    fi
    assert_success

    # Cleanup
    stop_inbox_watcher "$watcher_pid"
}

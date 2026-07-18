#!/usr/bin/env bats
# test_stop_hook.bats — stop_hook_inbox.sh unit tests
#
# Calls the REAL production script with env var overrides:
#   __STOP_HOOK_SCRIPT_DIR → points to test temp directory
#   __STOP_HOOK_AGENT_ID   → mocks tmux agent detection
#
# テスト構成:
#   T-HOOK-001: stop_hook_active=true → exit 0
#   T-HOOK-002: agent不明 → exit 0
#   T-HOOK-003: agent_id=shogun → exit 0
#   T-HOOK-004: 完了メッセージ → inbox_writeが呼ばれる (report_completed)
#   T-HOOK-005: エラーメッセージ → inbox_writeが呼ばれる (error_report)
#   T-HOOK-006: 中立メッセージ → inbox_write呼ばれない
#   T-HOOK-007: last_assistant_message空 → inbox_write呼ばれない
#   T-HOOK-008: inbox未読あり → block JSON出力
#   T-HOOK-009: inbox未読なし + 完了メッセージ → exit 0 + 通知あり
#   T-HOOK-010: inbox未読あり + 完了メッセージ → block + 通知あり
#   T-HOOK-011: Hook settings are valid JSON with project-root shell commands
#   T-HOOK-012: Hook commands resolve with CLAUDE_PROJECT_DIR set and unset
#   T-HOOK-013: Hook lint rejects bare relative paths and args

SCRIPT_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
HOOK_SCRIPT="$SCRIPT_DIR/scripts/stop_hook_inbox.sh"
SESSION_HOOK_SCRIPT="$SCRIPT_DIR/scripts/session_start_hook.sh"
SETTINGS_FILE="$SCRIPT_DIR/.claude/settings.json"
HOOK_LINT="$SCRIPT_DIR/scripts/lint_hook_settings.py"

setup() {
    TEST_TMP="$(mktemp -d)"
    mkdir -p "$TEST_TMP/scripts"
    mkdir -p "$TEST_TMP/queue/inbox"

    # Mock inbox_write.sh — logs arguments to file
    cat > "$TEST_TMP/scripts/inbox_write.sh" << 'MOCK'
#!/bin/bash
echo "$@" >> "$(dirname "$0")/../inbox_write_calls.log"
MOCK
    chmod +x "$TEST_TMP/scripts/inbox_write.sh"
}

teardown() {
    rm -rf "$TEST_TMP"
}

# Helper: run the REAL hook script with test overrides
run_hook() {
    local json="$1"
    local agent_id="${2:-ashigaru1}"
    __STOP_HOOK_SCRIPT_DIR="$TEST_TMP" \
    __STOP_HOOK_AGENT_ID="$agent_id" \
    run bash "$HOOK_SCRIPT" <<< "$json"
}

# Helper: run with no agent ID set
run_hook_no_agent() {
    local json="$1"
    __STOP_HOOK_SCRIPT_DIR="$TEST_TMP" \
    __STOP_HOOK_AGENT_ID="" \
    run bash "$HOOK_SCRIPT" <<< "$json"
}

@test "T-HOOK-001: stop_hook_active=true skips all processing" {
    run_hook '{"stop_hook_active": true, "last_assistant_message": "任務完了"}'
    [ "$status" -eq 0 ]
    [ -z "$output" ]
}

@test "T-HOOK-002: unknown agent (empty agent_id) exits 0" {
    run_hook_no_agent '{"stop_hook_active": false}'
    [ "$status" -eq 0 ]
    [ -z "$output" ]
}

@test "T-HOOK-003: shogun agent always exits 0" {
    run_hook '{"stop_hook_active": false, "last_assistant_message": "任務完了"}' "shogun"
    [ "$status" -eq 0 ]
    [ -z "$output" ]
}

@test "T-HOOK-004: completion message triggers inbox_write to karo" {
    run_hook '{"stop_hook_active": false, "last_assistant_message": "任務完了でござる。report YAML更新済み。"}'
    [ "$status" -eq 0 ]
    [ -f "$TEST_TMP/inbox_write_calls.log" ]
    grep -q "karo" "$TEST_TMP/inbox_write_calls.log"
    grep -q "report_completed" "$TEST_TMP/inbox_write_calls.log"
    grep -q "ashigaru1" "$TEST_TMP/inbox_write_calls.log"
}

@test "T-HOOK-005: error message triggers inbox_write to karo" {
    run_hook '{"stop_hook_active": false, "last_assistant_message": "ファイルが見つからない。エラーで中断する。"}'
    [ "$status" -eq 0 ]
    [ -f "$TEST_TMP/inbox_write_calls.log" ]
    grep -q "karo" "$TEST_TMP/inbox_write_calls.log"
    grep -q "error_report" "$TEST_TMP/inbox_write_calls.log"
}

@test "T-HOOK-006: neutral message does not trigger inbox_write" {
    run_hook '{"stop_hook_active": false, "last_assistant_message": "待機する。次の指示を待つ。"}'
    [ "$status" -eq 0 ]
    [ ! -f "$TEST_TMP/inbox_write_calls.log" ]
}

@test "T-HOOK-007: empty last_assistant_message does not trigger inbox_write" {
    run_hook '{"stop_hook_active": false, "last_assistant_message": ""}'
    [ "$status" -eq 0 ]
    [ ! -f "$TEST_TMP/inbox_write_calls.log" ]
}

@test "T-HOOK-008: unread inbox messages produce block JSON" {
    cat > "$TEST_TMP/queue/inbox/ashigaru1.yaml" << 'YAML'
messages:
  - id: msg_001
    from: karo
    type: task_assigned
    content: "新タスクだ"
    read: false
YAML
    run_hook '{"stop_hook_active": false, "last_assistant_message": ""}'
    [ "$status" -eq 0 ]
    echo "$output" | grep -q '"decision"'
    echo "$output" | grep -q '"block"'
}

@test "T-HOOK-009: no unread + completion message exits 0 with notification" {
    cat > "$TEST_TMP/queue/inbox/ashigaru1.yaml" << 'YAML'
messages:
  - id: msg_001
    from: karo
    type: task_assigned
    content: "古いメッセージ"
    read: true
YAML
    run_hook '{"stop_hook_active": false, "last_assistant_message": "タスク完了した。report YAML updated。"}'
    [ "$status" -eq 0 ]
    [ -z "$output" ] || ! echo "$output" | grep -q '"block"'
    [ -f "$TEST_TMP/inbox_write_calls.log" ]
    grep -q "report_completed" "$TEST_TMP/inbox_write_calls.log"
}

@test "T-HOOK-010: unread inbox + completion message blocks AND notifies" {
    cat > "$TEST_TMP/queue/inbox/ashigaru1.yaml" << 'YAML'
messages:
  - id: msg_001
    from: karo
    type: task_assigned
    content: "次のタスク"
    read: false
YAML
    run_hook '{"stop_hook_active": false, "last_assistant_message": "任務完了でござる。"}'
    [ "$status" -eq 0 ]
    echo "$output" | grep -q '"block"'
    [ -f "$TEST_TMP/inbox_write_calls.log" ]
    grep -q "report_completed" "$TEST_TMP/inbox_write_calls.log"
}

@test "T-HOOK-011: Hook settings use exact project-root shell commands without args" {
    run python3 - "$SETTINGS_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    settings = json.load(handle)

expected = {
    "SessionStart": 'bash "${CLAUDE_PROJECT_DIR:-.}/scripts/session_start_hook.sh"',
    "Stop": 'bash "${CLAUDE_PROJECT_DIR:-.}/scripts/stop_hook_inbox.sh"',
}
for event, command in expected.items():
    entries = settings["hooks"][event]
    hooks = [hook for entry in entries for hook in entry["hooks"]]
    assert len(hooks) == 1, (event, hooks)
    assert hooks[0]["command"] == command, (event, hooks[0])
    assert "args" not in hooks[0], (event, hooks[0])
PY
    [ "$status" -eq 0 ]
}

@test "T-HOOK-012: Hook commands resolve with CLAUDE_PROJECT_DIR set and unset" {
    local stop_command session_command
    stop_command=$(python3 - "$SETTINGS_FILE" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["hooks"]["Stop"][0]["hooks"][0]["command"])
PY
)
    session_command=$(python3 - "$SETTINGS_FILE" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["hooks"]["SessionStart"][0]["hooks"][0]["command"])
PY
)

    run bash -c 'cd "$1" && printf "%s\n" "{\"stop_hook_active\":false}" | env -u CLAUDE_PROJECT_DIR __STOP_HOOK_AGENT_ID="" bash -c "$2"' _ "$SCRIPT_DIR" "$stop_command"
    [ "$status" -eq 0 ]

    run bash -c 'cd "$1" && env -u CLAUDE_PROJECT_DIR -u TMUX_PANE bash -c "$2"' _ "$SCRIPT_DIR" "$session_command"
    [ "$status" -eq 0 ]

    run bash -c 'cd / && printf "%s\n" "{\"stop_hook_active\":false}" | CLAUDE_PROJECT_DIR="$1" __STOP_HOOK_AGENT_ID="" bash -c "$2"' _ "$SCRIPT_DIR" "$stop_command"
    [ "$status" -eq 0 ]

    run bash -c 'cd / && CLAUDE_PROJECT_DIR="$1" env -u TMUX_PANE bash -c "$2"' _ "$SCRIPT_DIR" "$session_command"
    [ "$status" -eq 0 ]
}

@test "T-HOOK-013: Hook lint accepts canonical settings and rejects relative paths and args" {
    run python3 "$HOOK_LINT" "$SETTINGS_FILE"
    [ "$status" -eq 0 ]

    python3 - "$SETTINGS_FILE" "$TEST_TMP" <<'PY'
import copy
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    settings = json.load(handle)

unsafe_commands = {
    "bare-relative.json": "bash scripts/stop_hook_inbox.sh",
    "quoted-relative.json": 'bash "scripts/stop_hook_inbox.sh"',
    "dot-relative.json": "bash ./scripts/stop_hook_inbox.sh",
    "sh-relative.json": "sh scripts/stop_hook_inbox.sh",
}
for filename, command in unsafe_commands.items():
    unsafe = copy.deepcopy(settings)
    unsafe["hooks"]["Stop"][0]["hooks"][0]["command"] = command
    with open(f"{sys.argv[2]}/{filename}", "w", encoding="utf-8") as handle:
        json.dump(unsafe, handle)

with_args = copy.deepcopy(settings)
with_args["hooks"]["Stop"][0]["hooks"][0]["args"] = ["--unsafe"]
with open(f"{sys.argv[2]}/args.json", "w", encoding="utf-8") as handle:
    json.dump(with_args, handle)
PY

    local fixture
    for fixture in bare-relative quoted-relative dot-relative sh-relative; do
        run python3 "$HOOK_LINT" "$TEST_TMP/${fixture}.json"
        [ "$status" -ne 0 ]
        [[ "$output" == *"bare_relative_path"* ]]
    done

    run python3 "$HOOK_LINT" "$TEST_TMP/args.json"
    [ "$status" -ne 0 ]
    [[ "$output" == *"args_forbidden"* ]]
}

#!/usr/bin/env bats

setup() {
    PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    PYTHON="$PROJECT_ROOT/.venv/bin/python3"
    WATCHDOG="$PROJECT_ROOT/scripts/handoff_watchdog.py"
    TEST_ROOT="$(mktemp -d)"
    mkdir -p "$TEST_ROOT/queue/inbox" "$TEST_ROOT/queue/tasks" \
        "$TEST_ROOT/queue/reports" "$TEST_ROOT/status"
    INBOX="$TEST_ROOT/queue/inbox/ashigaru1.yaml"
    TASK="$TEST_ROOT/queue/tasks/ashigaru1.yaml"
    REPORT="$TEST_ROOT/queue/reports/ashigaru1_report.yaml"
    STATUS_FILE="$TEST_ROOT/status/ashigaru1.yaml"
}

teardown() {
    rm -rf "$TEST_ROOT"
}

run_watchdog() {
    local now="$1"
    local cli_state="${2:-ready}"
    local blocked_reason="${3:-none}"
    local can_notify="${4:-1}"
    local record_notification="${5:-1}"
    run "$PYTHON" "$WATCHDOG" \
        --inbox "$INBOX" \
        --agent ashigaru1 \
        --status-file "$STATUS_FILE" \
        --task-file "$TASK" \
        --report-file "$REPORT" \
        --now "$now" \
        --retry-after 120 \
        --stall-after 300 \
        --task-retry-after 300 \
        --task-stall-after 600 \
        --can-notify "$can_notify" \
        --cli-state-at-notify "$cli_state" \
        --delivery-blocked-reason "$blocked_reason" \
        --record-notification "$record_notification"
}

json_field() {
    "$PYTHON" -c "import json,sys; print(json.loads(sys.argv[1])[sys.argv[2]])" "$1" "$2"
}

@test "watchdog sends one initial notification, one retry, then one escalation" {
    cat > "$INBOX" <<'YAML'
messages:
  - id: msg_task
    from: karo
    timestamp: "1970-01-01T00:16:40+00:00"
    type: task_assigned
    content: "sensitive task body"
    read: false
YAML

    run_watchdog 1000
    [ "$status" -eq 0 ]
    [ "$(json_field "$output" action)" = "notify" ]

    run_watchdog 1050
    [ "$(json_field "$output" action)" = "none" ]

    run_watchdog 1121
    [ "$(json_field "$output" action)" = "retry" ]

    run_watchdog 1301
    [ "$(json_field "$output" escalate)" = "True" ]
    [ "$(json_field "$output" state)" = "handoff_stalled" ]

    run_watchdog 1330
    [ "$(json_field "$output" escalate)" = "False" ]

    run "$PYTHON" - "$INBOX" <<'PY'
import sys, yaml
path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    data = yaml.safe_load(handle)
message = data["messages"][0]
assert message["delivery"]["notification_count"] == 2
assert message["delivery"]["stalled_at"]
assert message["delivery"]["escalation_sent_at"]
PY
    [ "$status" -eq 0 ]

    ! grep -q "sensitive task body" "$STATUS_FILE"
}

@test "watchdog records receipt when an agent marks the message read" {
    cat > "$INBOX" <<'YAML'
messages:
  - id: msg_info
    from: karo
    timestamp: "1970-01-01T00:16:40+00:00"
    type: info
    content: "receipt check"
    read: true
YAML

    run_watchdog 1010
    [ "$status" -eq 0 ]
    [ "$(json_field "$output" state)" = "healthy" ]
    grep -q "acknowledged_at:" "$INBOX"
}

@test "watchdog detects an acknowledged assigned task that remains idle" {
    cat > "$INBOX" <<'YAML'
messages:
  - id: msg_task
    from: karo
    timestamp: "1970-01-01T00:16:40+00:00"
    type: task_assigned
    content: "task"
    read: true
    delivery:
      created_at: "1970-01-01T00:16:40+00:00"
      notification_count: 1
      first_notified_at: "1970-01-01T00:16:40+00:00"
      last_notified_at: "1970-01-01T00:16:40+00:00"
      acknowledged_at: "1970-01-01T00:16:40+00:00"
      stalled_at:
      escalation_sent_at:
YAML
    cat > "$TASK" <<'YAML'
task:
  task_id: subtask_001
  parent_cmd: cmd_001
  status: assigned
  timestamp: "1970-01-01T00:16:40+00:00"
YAML

    run_watchdog 1301
    [ "$(json_field "$output" action)" = "task_retry" ]
    [ "$(json_field "$output" state)" = "execution_retry_sent" ]

    run_watchdog 1601
    [ "$(json_field "$output" escalate)" = "True" ]
    [ "$(json_field "$output" state)" = "execution_stalled" ]

    run_watchdog 1700
    [ "$(json_field "$output" escalate)" = "False" ]
}

@test "completed report suppresses accepted-task stall detection" {
    cat > "$INBOX" <<'YAML'
messages:
  - id: msg_task
    from: karo
    timestamp: "1970-01-01T00:16:40+00:00"
    type: task_assigned
    content: "task"
    read: true
    delivery:
      acknowledged_at: "1970-01-01T00:16:40+00:00"
YAML
    cat > "$TASK" <<'YAML'
task:
  task_id: subtask_001
  status: assigned
YAML
    cat > "$REPORT" <<'YAML'
task_id: subtask_001
status: done
YAML

    run_watchdog 2000
    [ "$(json_field "$output" action)" = "none" ]
    [ "$(json_field "$output" state)" = "healthy" ]
}

@test "completed task preserves historical delivery liveness fields" {
    cat > "$INBOX" <<'YAML'
messages:
  - id: msg_task
    from: karo
    timestamp: "1970-01-01T00:16:40+00:00"
    type: task_assigned
    content: "sanitized fixture"
    read: true
    delivery:
      acknowledged_at: "1970-01-01T00:16:40+00:00"
      cli_state_at_notify: ready
      delivery_blocked_reason:
YAML
    cat > "$TASK" <<'YAML'
task:
  task_id: subtask_completed
  status: assigned
YAML
    cat > "$REPORT" <<'YAML'
task_id: subtask_completed
status: done
YAML

    run_watchdog 2000 permission_prompt permission_prompt 0 0
    [ "$status" -eq 0 ]
    run "$PYTHON" - "$INBOX" <<'PY'
import sys, yaml
with open(sys.argv[1], encoding="utf-8") as handle:
    delivery = yaml.safe_load(handle)["messages"][0]["delivery"]
assert delivery["cli_state_at_notify"] == "ready", delivery
assert delivery["delivery_blocked_reason"] is None, delivery
PY
    [ "$status" -eq 0 ]
}

@test "not-yet-due task retry preserves historical delivery liveness fields" {
    cat > "$INBOX" <<'YAML'
messages:
  - id: msg_task
    from: karo
    timestamp: "1970-01-01T00:31:40+00:00"
    type: task_assigned
    content: "sanitized fixture"
    read: true
    delivery:
      acknowledged_at: "1970-01-01T00:31:40+00:00"
      cli_state_at_notify: ready
      delivery_blocked_reason:
YAML
    cat > "$TASK" <<'YAML'
task:
  task_id: subtask_not_due
  status: assigned
YAML

    run_watchdog 2000 permission_prompt permission_prompt 0 0
    [ "$status" -eq 0 ]
    run "$PYTHON" - "$INBOX" <<'PY'
import sys, yaml
with open(sys.argv[1], encoding="utf-8") as handle:
    delivery = yaml.safe_load(handle)["messages"][0]["delivery"]
assert delivery["cli_state_at_notify"] == "ready", delivery
assert delivery["delivery_blocked_reason"] is None, delivery
PY
    [ "$status" -eq 0 ]
}

@test "unchanged reconciliation does not rewrite the watched inbox" {
    cat > "$INBOX" <<'YAML'
messages:
  - id: msg_info
    from: karo
    timestamp: "1970-01-01T00:16:40+00:00"
    type: info
    content: "stable"
    read: false
    delivery:
      created_at: "1970-01-01T00:16:40+00:00"
      notification_count: 1
      first_notified_at: "1970-01-01T00:16:40+00:00"
      last_notified_at: "1970-01-01T00:16:40+00:00"
      acknowledged_at:
      stalled_at:
      escalation_sent_at:
      cli_state_at_notify: ready
      delivery_blocked_reason:
YAML

    before=$("$PYTHON" -c "import os,sys; print(os.stat(sys.argv[1]).st_mtime_ns)" "$INBOX")
    run_watchdog 1050
    [ "$status" -eq 0 ]
    after=$("$PYTHON" -c "import os,sys; print(os.stat(sys.argv[1]).st_mtime_ns)" "$INBOX")
    [ "$before" = "$after" ]
}

@test "busy accepted task is projected as in progress without consuming retry" {
    cat > "$INBOX" <<'YAML'
messages:
  - id: msg_task
    from: karo
    timestamp: "1970-01-01T00:16:40+00:00"
    type: task_assigned
    content: "task"
    read: true
    delivery:
      acknowledged_at: "1970-01-01T00:16:40+00:00"
YAML
    cat > "$TASK" <<'YAML'
task:
  task_id: subtask_001
  status: assigned
YAML

    run "$PYTHON" "$WATCHDOG" \
        --inbox "$INBOX" --agent ashigaru1 --status-file "$STATUS_FILE" \
        --task-file "$TASK" --report-file "$REPORT" --now 2000 \
        --retry-after 120 --stall-after 300 \
        --task-retry-after 300 --task-stall-after 600 --can-notify 0
    [ "$status" -eq 0 ]
    [ "$(json_field "$output" action)" = "none" ]
    [ "$(json_field "$output" state)" = "execution_in_progress" ]
    ! grep -q "execution_retry_at" "$INBOX"
}

@test "watcher keeps assigned tasks out of the zero-unread fast path" {
    grep -q "watchdog_tracks_assigned_task" "$PROJECT_ROOT/scripts/inbox_watcher.sh"
    grep -q "! watchdog_tracks_assigned_task" "$PROJECT_ROOT/scripts/inbox_watcher.sh"
}

@test "watcher falls back to the legacy notification path when helper is absent" {
    grep -q "handoff_watchdog_active()" "$PROJECT_ROOT/scripts/inbox_watcher.sh"
    grep -q "if handoff_watchdog_active; then" "$PROJECT_ROOT/scripts/inbox_watcher.sh"
}

@test "blocked liveness is recorded without consuming a notification attempt" {
    cat > "$INBOX" <<'YAML'
messages:
  - id: msg_blocked
    from: karo
    timestamp: "1970-01-01T00:16:40+00:00"
    type: task_assigned
    content: "sanitized fixture"
    read: false
YAML

    run_watchdog 1000 permission_prompt permission_prompt 0
    [ "$status" -eq 0 ]
    [ "$(json_field "$output" action)" = "none" ]

    run "$PYTHON" - "$INBOX" "$STATUS_FILE" <<'PY'
import sys, yaml
with open(sys.argv[1], encoding="utf-8") as handle:
    message = yaml.safe_load(handle)["messages"][0]
delivery = message["delivery"]
assert delivery["notification_count"] == 0
assert delivery["cli_state_at_notify"] == "permission_prompt"
assert delivery["delivery_blocked_reason"] == "permission_prompt"
with open(sys.argv[2], encoding="utf-8") as handle:
    status = yaml.safe_load(handle)
assert status["cli_state_at_notify"] == "permission_prompt"
assert status["delivery_blocked_reason"] == "permission_prompt"
PY
    [ "$status" -eq 0 ]

    run_watchdog 1010 ready none 1
    [ "$status" -eq 0 ]
    [ "$(json_field "$output" action)" = "notify" ]
    run "$PYTHON" - "$INBOX" <<'PY'
import sys, yaml
with open(sys.argv[1], encoding="utf-8") as handle:
    delivery = yaml.safe_load(handle)["messages"][0]["delivery"]
assert delivery["notification_count"] == 1
assert delivery["cli_state_at_notify"] == "ready"
assert delivery["delivery_blocked_reason"] is None
PY
    [ "$status" -eq 0 ]
}

@test "busy delivery state is observable while existing can-notify gate defers" {
    cat > "$INBOX" <<'YAML'
messages:
  - id: msg_busy
    from: karo
    timestamp: "1970-01-01T00:16:40+00:00"
    type: info
    content: "sanitized fixture"
    read: false
YAML

    run_watchdog 1000 busy busy 0
    [ "$status" -eq 0 ]
    [ "$(json_field "$output" action)" = "none" ]
    grep -q "cli_state_at_notify: busy" "$INBOX"
    grep -q "delivery_blocked_reason: busy" "$INBOX"
    grep -q "notification_count: 0" "$INBOX"
}

@test "notification planning does not consume count before a confirmed send" {
    cat > "$INBOX" <<'YAML'
messages:
  - id: msg_plan
    from: karo
    timestamp: "1970-01-01T00:16:40+00:00"
    type: info
    content: "sanitized fixture"
    read: false
YAML

    run_watchdog 1000 ready none 1 0
    [ "$status" -eq 0 ]
    [ "$(json_field "$output" action)" = "notify" ]
    grep -q "notification_count: 0" "$INBOX"

    run_watchdog 1001 ready none 1 1
    [ "$status" -eq 0 ]
    [ "$(json_field "$output" action)" = "notify" ]
    grep -q "notification_count: 1" "$INBOX"
}

@test "blocked task retry records state and reason on the acknowledged task message" {
    cat > "$INBOX" <<'YAML'
messages:
  - id: msg_task_blocked
    from: karo
    timestamp: "1970-01-01T00:16:40+00:00"
    type: task_assigned
    content: "sanitized fixture"
    read: true
    delivery:
      acknowledged_at: "1970-01-01T00:16:40+00:00"
YAML
    cat > "$TASK" <<'YAML'
task:
  task_id: subtask_blocked
  status: assigned
YAML

    run_watchdog 2000 permission_prompt permission_prompt 0 1
    [ "$status" -eq 0 ]
    run "$PYTHON" - "$INBOX" <<'PY'
import sys, yaml
with open(sys.argv[1], encoding="utf-8") as handle:
    delivery = yaml.safe_load(handle)["messages"][0]["delivery"]
assert not delivery.get("execution_retry_at"), delivery
assert delivery["cli_state_at_notify"] == "permission_prompt", delivery
assert delivery["delivery_blocked_reason"] == "permission_prompt", delivery
PY
    [ "$status" -eq 0 ]
}

@test "formal receipt persists cmd epoch and task identity without replacing acknowledgement" {
    cat > "$INBOX" <<'YAML'
messages:
  - id: msg_formal_receipt
    from: karo
    timestamp: "1970-01-01T00:16:40+00:00"
    type: task_assigned
    cmd: cmd_010
    task_id: subtask_010a
    content: "sanitized fixture"
    read: true
YAML
    cat > "$TASK" <<'YAML'
task:
  cmd: cmd_010
  task_id: subtask_010a
  parent_cmd: cmd_010
  status: assigned
YAML

    run_watchdog 1100
    [ "$status" -eq 0 ]
    [ "$(json_field "$output" state)" = "execution_accepted" ]

    run "$PYTHON" - "$INBOX" <<'PY'
import sys, yaml
with open(sys.argv[1], encoding="utf-8") as handle:
    message = yaml.safe_load(handle)["messages"][0]
delivery = message["delivery"]
assert delivery["cmd"] == "cmd_010", delivery
assert delivery["task_id"] == "subtask_010a", delivery
assert delivery["acknowledged_at"], delivery
PY
    [ "$status" -eq 0 ]
}

@test "formal receipt with stale cmd epoch does not acknowledge the current task" {
    cat > "$INBOX" <<'YAML'
messages:
  - id: msg_stale_cmd
    from: karo
    timestamp: "1970-01-01T00:16:40+00:00"
    type: task_assigned
    cmd: cmd_009
    task_id: subtask_same
    content: "sanitized fixture"
    read: true
YAML
    cat > "$TASK" <<'YAML'
task:
  cmd: cmd_010
  task_id: subtask_same
  parent_cmd: cmd_010
  status: assigned
YAML

    run_watchdog 2000
    [ "$status" -eq 0 ]
    [ "$(json_field "$output" action)" = "none" ]
    [ "$(json_field "$output" state)" = "healthy" ]
    grep -q "handoff_state: none" "$STATUS_FILE"
    grep -q "acknowledged_at:" "$INBOX"
}

@test "redo selects the exact formal task receipt instead of an older task in the same cmd" {
    cat > "$INBOX" <<'YAML'
messages:
  - id: msg_redo_current
    from: karo
    timestamp: "1970-01-01T00:31:40+00:00"
    type: task_assigned
    cmd: cmd_011
    task_id: subtask_011a2
    content: "sanitized current redo"
    read: true
    delivery:
      acknowledged_at: "1970-01-01T00:31:40+00:00"
  - id: msg_redo_old
    from: karo
    timestamp: "1970-01-01T00:16:40+00:00"
    type: task_assigned
    cmd: cmd_011
    task_id: subtask_011a
    content: "sanitized old task"
    read: true
    delivery:
      acknowledged_at: "1970-01-01T00:16:40+00:00"
YAML
    cat > "$TASK" <<'YAML'
task:
  cmd: cmd_011
  task_id: subtask_011a2
  parent_cmd: cmd_011
  redo_of: subtask_011a
  status: assigned
YAML

    run_watchdog 2000
    [ "$status" -eq 0 ]
    [ "$(json_field "$output" action)" = "none" ]
    [ "$(json_field "$output" state)" = "execution_accepted" ]
}

@test "parallel tasks sharing a cmd do not consume each other's receipts" {
    cat > "$INBOX" <<'YAML'
messages:
  - id: msg_parallel_current
    from: karo
    timestamp: "1970-01-01T00:31:40+00:00"
    type: task_assigned
    cmd: cmd_014
    task_id: subtask_014a
    content: "sanitized current task"
    read: true
    delivery:
      acknowledged_at: "1970-01-01T00:31:40+00:00"
  - id: msg_parallel_other
    from: karo
    timestamp: "1970-01-01T00:16:40+00:00"
    type: task_assigned
    cmd: cmd_014
    task_id: subtask_014b
    content: "sanitized other task"
    read: true
    delivery:
      acknowledged_at: "1970-01-01T00:16:40+00:00"
YAML
    cat > "$TASK" <<'YAML'
task:
  cmd: cmd_014
  task_id: subtask_014a
  parent_cmd: cmd_014
  status: assigned
YAML

    run_watchdog 2000
    [ "$status" -eq 0 ]
    [ "$(json_field "$output" action)" = "none" ]
    [ "$(json_field "$output" state)" = "execution_accepted" ]
}

@test "legacy task and receipt without cmd preserve the existing retry behavior" {
    cat > "$INBOX" <<'YAML'
messages:
  - id: msg_legacy_receipt
    from: karo
    timestamp: "1970-01-01T00:16:40+00:00"
    type: task_assigned
    content: "sanitized legacy task"
    read: true
    delivery:
      acknowledged_at: "1970-01-01T00:16:40+00:00"
YAML
    cat > "$TASK" <<'YAML'
task:
  task_id: subtask_legacy
  parent_cmd: cmd_004
  status: assigned
YAML

    run_watchdog 2000
    [ "$status" -eq 0 ]
    [ "$(json_field "$output" action)" = "task_retry" ]
    [ "$(json_field "$output" state)" = "execution_retry_sent" ]
}

@test "formal report with stale cmd does not close the current task identity" {
    cat > "$INBOX" <<'YAML'
messages:
  - id: msg_current_formal
    from: karo
    timestamp: "1970-01-01T00:16:40+00:00"
    type: task_assigned
    cmd: cmd_020
    task_id: subtask_reused
    content: "sanitized fixture"
    read: true
    delivery:
      acknowledged_at: "1970-01-01T00:16:40+00:00"
YAML
    cat > "$TASK" <<'YAML'
task:
  cmd: cmd_020
  task_id: subtask_reused
  parent_cmd: cmd_020
  status: assigned
YAML
    cat > "$REPORT" <<'YAML'
cmd: cmd_019
task_id: subtask_reused
status: done
YAML

    run_watchdog 2000
    [ "$status" -eq 0 ]
    [ "$(json_field "$output" action)" = "task_retry" ]
    [ "$(json_field "$output" state)" = "execution_retry_sent" ]
}

@test "legacy report without cmd can close a formal task during migration" {
    cat > "$INBOX" <<'YAML'
messages:
  - id: msg_current_formal
    from: karo
    timestamp: "1970-01-01T00:16:40+00:00"
    type: task_assigned
    cmd: cmd_021
    task_id: subtask_migrating
    content: "sanitized fixture"
    read: true
    delivery:
      acknowledged_at: "1970-01-01T00:16:40+00:00"
YAML
    cat > "$TASK" <<'YAML'
task:
  cmd: cmd_021
  task_id: subtask_migrating
  parent_cmd: cmd_021
  status: assigned
YAML
    cat > "$REPORT" <<'YAML'
task_id: subtask_migrating
status: done
YAML

    run_watchdog 2000
    [ "$status" -eq 0 ]
    [ "$(json_field "$output" action)" = "none" ]
    [ "$(json_field "$output" state)" = "healthy" ]
}

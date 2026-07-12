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
        --can-notify 1
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

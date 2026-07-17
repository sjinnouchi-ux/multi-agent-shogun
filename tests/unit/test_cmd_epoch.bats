#!/usr/bin/env bats

setup() {
    PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    PYTHON="$PROJECT_ROOT/.venv/bin/python3"
    CMD_EPOCH="$PROJECT_ROOT/scripts/cmd_epoch.py"
    TEST_ROOT="$(mktemp -d)"
}

teardown() {
    rm -rf "$TEST_ROOT"
}

@test "cmd epoch generates the next unique numeric command id across formal and legacy queues" {
    cat > "$TEST_ROOT/active.yaml" <<'YAML'
commands:
  - id: cmd_007
    status: in_progress
  - id: cmd_009
    cmd: cmd_009
    status: pending
YAML
    cat > "$TEST_ROOT/archive.yaml" <<'YAML'
queue:
  - id: cmd_008
    status: done
YAML

    run "$PYTHON" "$CMD_EPOCH" next \
        "$TEST_ROOT/active.yaml" "$TEST_ROOT/archive.yaml"

    [ "$status" -eq 0 ]
    [ "$output" = "cmd_010" ]
}

@test "cmd epoch comparison matches an exact formal command and task identity" {
    cat > "$TEST_ROOT/task.yaml" <<'YAML'
task:
  cmd: cmd_012
  task_id: subtask_012a
  parent_cmd: cmd_012
  status: assigned
YAML

    run "$PYTHON" "$CMD_EPOCH" compare \
        --task-file "$TEST_ROOT/task.yaml" \
        --cmd cmd_012 --task-id subtask_012a

    [ "$status" -eq 0 ]
    [ "$output" = "match" ]
}

@test "cmd epoch comparison rejects stale formal command or task identities" {
    cat > "$TEST_ROOT/task.yaml" <<'YAML'
task:
  cmd: cmd_013
  task_id: subtask_013b
  parent_cmd: cmd_013
  status: assigned
YAML

    run "$PYTHON" "$CMD_EPOCH" compare \
        --task-file "$TEST_ROOT/task.yaml" \
        --cmd cmd_012 --task-id subtask_013b
    [ "$status" -eq 0 ]
    [ "$output" = "stale" ]

    run "$PYTHON" "$CMD_EPOCH" compare \
        --task-file "$TEST_ROOT/task.yaml" \
        --cmd cmd_013 --task-id subtask_013a
    [ "$status" -eq 0 ]
    [ "$output" = "stale" ]
}

@test "cmd epoch comparison accepts legacy task YAML through the compatibility path" {
    cat > "$TEST_ROOT/task.yaml" <<'YAML'
task:
  task_id: subtask_legacy
  parent_cmd: cmd_004
  status: assigned
YAML

    run "$PYTHON" "$CMD_EPOCH" compare \
        --task-file "$TEST_ROOT/task.yaml" \
        --cmd cmd_004 --task-id subtask_legacy

    [ "$status" -eq 0 ]
    [ "$output" = "legacy" ]
}

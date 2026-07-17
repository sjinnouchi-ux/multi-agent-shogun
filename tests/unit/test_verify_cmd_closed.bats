#!/usr/bin/env bats

setup() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export CHECKER="$PROJECT_ROOT/scripts/verify_cmd_closed.sh"
    export TEST_ROOT="$(mktemp -d "$BATS_TMPDIR/verify_cmd_closed.XXXXXX")"
    export SHOGUN_QUEUE_DIR="$TEST_ROOT/queue"
    export SHOGUN_PYTHON_BIN="python3"
    mkdir -p "$SHOGUN_QUEUE_DIR/tasks"
}

teardown() {
    rm -rf "$TEST_ROOT"
}

write_active_commands() {
    cat > "$SHOGUN_QUEUE_DIR/shogun_to_karo.yaml"
}

write_archived_commands() {
    cat > "$SHOGUN_QUEUE_DIR/shogun_to_karo_archive.yaml"
}

run_checker() {
    run bash "$CHECKER" "$@"
}

@test "terminal command task in runtime pending queue is blocked before promotion" {
    write_active_commands <<'YAML'
commands:
  - id: cmd_active
    cmd: cmd_active
    status: in_progress
YAML
    write_archived_commands <<'YAML'
commands:
  - id: cmd_closed
    cmd: cmd_closed
    status: done
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/pending.yaml" <<'YAML'
tasks:
  - cmd: cmd_closed
    parent_cmd: cmd_closed
    task_id: task_pending
    status: pending_blocked
YAML

    run_checker

    [ "$status" -ne 0 ]
    [ "$output" = "cmd_closure: blocked open=1 invalid=0 legacy=0" ]
    [[ "$output" != *"cmd_closed"* ]]
    [[ "$output" != *"$SHOGUN_QUEUE_DIR"* ]]
}

@test "runtime pending_tasks schema is included in closure checks" {
    write_active_commands <<'YAML'
commands: []
YAML
    write_archived_commands <<'YAML'
commands:
  - id: cmd_closed
    cmd: cmd_closed
    status: paused
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/pending.yaml" <<'YAML'
pending_tasks:
  - cmd: cmd_closed
    task_id: task_pending
    status: pending_blocked
YAML

    run_checker

    [ "$status" -ne 0 ]
    [ "$output" = "cmd_closure: blocked open=1 invalid=0 legacy=0" ]
}

@test "promotion gate allows an unrelated active parallel command" {
    write_active_commands <<'YAML'
commands:
  - id: cmd_parallel
    cmd: cmd_parallel
    status: in_progress
YAML
    write_archived_commands <<'YAML'
commands:
  - id: cmd_closed
    cmd: cmd_closed
    status: done
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/pending.yaml" <<'YAML'
pending_tasks:
  - cmd: cmd_closed
    task_id: task_closed
    status: pending_blocked
  - cmd: cmd_parallel
    task_id: task_parallel
    status: pending_blocked
YAML

    run_checker --promoting-cmd cmd_parallel

    [ "$status" -eq 0 ]
    [ "$output" = "cmd_closure: ok checked=2 legacy=0" ]
}

@test "promotion gate rejects the candidate when its own command is terminal" {
    write_active_commands <<'YAML'
commands:
  - id: cmd_parallel
    cmd: cmd_parallel
    status: in_progress
YAML
    write_archived_commands <<'YAML'
commands:
  - id: cmd_closed
    cmd: cmd_closed
    status: done
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/pending.yaml" <<'YAML'
pending_tasks:
  - cmd: cmd_closed
    task_id: task_closed
    status: pending_blocked
  - cmd: cmd_parallel
    task_id: task_parallel
    status: pending_blocked
YAML

    run_checker --promoting-cmd cmd_closed

    [ "$status" -ne 0 ]
    [ "$output" = "cmd_closure: blocked open=1 invalid=0 legacy=0" ]
}

@test "assigned work for a terminal command is reported as unclosed" {
    write_active_commands <<'YAML'
commands: []
YAML
    write_archived_commands <<'YAML'
commands:
  - id: cmd_closed
    cmd: cmd_closed
    status: cancelled
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/ashigaru1.yaml" <<'YAML'
cmd: cmd_closed
parent_cmd: cmd_closed
task_id: task_assigned
status: assigned
YAML

    run_checker

    [ "$status" -ne 0 ]
    [ "$output" = "cmd_closure: blocked open=1 invalid=0 legacy=0" ]
}

@test "timestamped command archives produced by slim_yaml are checked" {
    write_active_commands <<'YAML'
commands: []
YAML
    write_archived_commands <<'YAML'
commands: []
YAML
    mkdir -p "$SHOGUN_QUEUE_DIR/archive"
    cat > "$SHOGUN_QUEUE_DIR/archive/shogun_to_karo_20260101010101.yaml" <<'YAML'
commands:
  - id: cmd_closed
    cmd: cmd_closed
    status: done
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/ashigaru1.yaml" <<'YAML'
cmd: cmd_closed
task_id: task_assigned
status: assigned
YAML

    run_checker

    [ "$status" -ne 0 ]
    [ "$output" = "cmd_closure: blocked open=1 invalid=0 legacy=0" ]
}

@test "completed and failed tasks close a terminal command" {
    write_active_commands <<'YAML'
commands: []
YAML
    write_archived_commands <<'YAML'
commands:
  - id: cmd_closed
    cmd: cmd_closed
    status: done
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/task_done.yaml" <<'YAML'
cmd: cmd_closed
parent_cmd: cmd_closed
task_id: task_done
status: done
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/task_failed.yaml" <<'YAML'
cmd: cmd_closed
parent_cmd: cmd_closed
task_id: task_failed
status: failed
YAML

    run_checker

    [ "$status" -eq 0 ]
    [ "$output" = "cmd_closure: ok checked=2 legacy=0" ]
}

@test "unrelated active epochs and valid parallel tasks are not blocked" {
    write_active_commands <<'YAML'
commands:
  - id: cmd_active
    cmd: cmd_active
    status: in_progress
  - id: cmd_parallel
    cmd: cmd_parallel
    status: in_progress
YAML
    write_archived_commands <<'YAML'
commands:
  - id: cmd_closed
    cmd: cmd_closed
    status: done
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/task_closed.yaml" <<'YAML'
cmd: cmd_closed
task_id: task_closed
status: done
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/task_active_a.yaml" <<'YAML'
cmd: cmd_active
task_id: task_active_a
status: assigned
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/task_active_b.yaml" <<'YAML'
cmd: cmd_parallel
task_id: task_active_b
status: blocked
YAML

    run_checker

    [ "$status" -eq 0 ]
    [ "$output" = "cmd_closure: ok checked=3 legacy=0" ]
}

@test "legacy command and task records remain conservatively compatible" {
    write_active_commands <<'YAML'
queue: []
YAML
    write_archived_commands <<'YAML'
queue:
  - id: cmd_legacy
    status: done
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/legacy_done.yaml" <<'YAML'
parent_cmd: cmd_legacy
task_id: task_legacy
status: done
YAML

    run_checker

    [ "$status" -eq 0 ]
    [ "$output" = "cmd_closure: ok checked=1 legacy=1" ]
}

@test "legacy active task still cannot outlive its terminal parent command" {
    write_active_commands <<'YAML'
queue: []
YAML
    write_archived_commands <<'YAML'
queue:
  - id: cmd_legacy
    status: done
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/legacy_assigned.yaml" <<'YAML'
parent_cmd: cmd_legacy
task_id: task_legacy
status: assigned
YAML

    run_checker

    [ "$status" -ne 0 ]
    [ "$output" = "cmd_closure: blocked open=1 invalid=0 legacy=1" ]
}

@test "closing-cmd checks work before an active command becomes terminal" {
    write_active_commands <<'YAML'
commands:
  - id: cmd_work
    cmd: cmd_work
    status: in_progress
YAML
    write_archived_commands <<'YAML'
commands: []
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/task_work.yaml" <<'YAML'
cmd: cmd_work
task_id: task_work
status: assigned
YAML

    run_checker --closing-cmd cmd_work

    [ "$status" -ne 0 ]
    [ "$output" = "cmd_closure: blocked open=1 invalid=0 legacy=0" ]
}

@test "closing-cmd does not block on an unrelated terminal command task" {
    write_active_commands <<'YAML'
commands:
  - id: cmd_work
    cmd: cmd_work
    status: in_progress
YAML
    write_archived_commands <<'YAML'
commands:
  - id: cmd_old
    cmd: cmd_old
    status: done
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/task_work.yaml" <<'YAML'
cmd: cmd_work
task_id: task_work
status: done
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/task_old.yaml" <<'YAML'
cmd: cmd_old
task_id: task_old
status: assigned
YAML

    run_checker --closing-cmd cmd_work

    [ "$status" -eq 0 ]
    [ "$output" = "cmd_closure: ok checked=2 legacy=0" ]
}

@test "closing-cmd blocks active legacy work with no parent command" {
    write_active_commands <<'YAML'
commands:
  - id: cmd_work
    cmd: cmd_work
    status: in_progress
YAML
    write_archived_commands <<'YAML'
commands: []
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/legacy_orphan.yaml" <<'YAML'
task_id: task_legacy
status: assigned
YAML

    run_checker --closing-cmd cmd_work

    [ "$status" -ne 0 ]
    [ "$output" = "cmd_closure: blocked open=1 invalid=0 legacy=1" ]
}

@test "closing-cmd blocks active legacy work with an unknown parent command" {
    write_active_commands <<'YAML'
commands:
  - id: cmd_work
    cmd: cmd_work
    status: in_progress
YAML
    write_archived_commands <<'YAML'
commands: []
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/legacy_unknown.yaml" <<'YAML'
parent_cmd: cmd_unknown
task_id: task_legacy
status: blocked
YAML

    run_checker --closing-cmd cmd_work

    [ "$status" -ne 0 ]
    [ "$output" = "cmd_closure: blocked open=1 invalid=0 legacy=1" ]
}

@test "completed legacy work without a parent does not block closure" {
    write_active_commands <<'YAML'
commands:
  - id: cmd_work
    cmd: cmd_work
    status: in_progress
YAML
    write_archived_commands <<'YAML'
commands: []
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/legacy_done.yaml" <<'YAML'
task_id: task_legacy
status: done
YAML

    run_checker --closing-cmd cmd_work

    [ "$status" -eq 0 ]
    [ "$output" = "cmd_closure: ok checked=1 legacy=1" ]
}

@test "runtime pending file is optional" {
    write_active_commands <<'YAML'
commands:
  - id: cmd_active
    cmd: cmd_active
    status: in_progress
YAML
    write_archived_commands <<'YAML'
commands: []
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/ashigaru1.yaml" <<'YAML'
cmd: cmd_active
task_id: task_active
status: assigned
YAML

    run_checker

    [ "$status" -eq 0 ]
    [ "$output" = "cmd_closure: ok checked=1 legacy=0" ]
}

@test "malformed YAML fails with a sanitized summary only" {
    write_active_commands <<'YAML'
commands: [
YAML
    write_archived_commands <<'YAML'
commands: []
YAML

    run_checker

    [ "$status" -ne 0 ]
    [ "$output" = "cmd_closure: blocked open=0 invalid=1 legacy=0" ]
    [[ "$output" != *"$SHOGUN_QUEUE_DIR"* ]]
    [[ "$output" != *"Traceback"* ]]
}

@test "malformed command container schema fails closed" {
    write_active_commands <<'YAML'
commands: not-a-list
YAML
    write_archived_commands <<'YAML'
commands: []
YAML

    run_checker

    [ "$status" -ne 0 ]
    [ "$output" = "cmd_closure: blocked open=0 invalid=1 legacy=0" ]
}

@test "unexpected task document schema fails closed" {
    write_active_commands <<'YAML'
commands: []
YAML
    write_archived_commands <<'YAML'
commands: []
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/unexpected.yaml" <<'YAML'
unexpected: value
YAML

    run_checker

    [ "$status" -ne 0 ]
    [ "$output" = "cmd_closure: blocked open=0 invalid=1 legacy=0" ]
}

@test "partial formal task identity is invalid instead of legacy" {
    write_active_commands <<'YAML'
commands:
  - id: cmd_active
    cmd: cmd_active
    status: in_progress
YAML
    write_archived_commands <<'YAML'
commands: []
YAML
    cat > "$SHOGUN_QUEUE_DIR/tasks/partial.yaml" <<'YAML'
cmd: cmd_active
status: assigned
YAML

    run_checker

    [ "$status" -ne 0 ]
    [ "$output" = "cmd_closure: blocked open=0 invalid=1 legacy=0" ]
}

@test "Makefile exposes the closure checker as an explicit target" {
    run make -C "$PROJECT_ROOT" -n verify-cmd-closed

    [ "$status" -eq 0 ]
    [[ "$output" == *"bash scripts/verify_cmd_closed.sh"* ]]
}

@test "closure checker is allowlisted for version control" {
    run git -C "$PROJECT_ROOT" check-ignore scripts/verify_cmd_closed.sh

    [ "$status" -ne 0 ]
}

@test "source and generated instructions gate command closure and pending promotion" {
    grep -Fq 'bash scripts/verify_cmd_closed.sh --closing-cmd "$cmd"' \
        "$PROJECT_ROOT/instructions/common/task_flow.md"
    grep -Fq 'bash scripts/verify_cmd_closed.sh' \
        "$PROJECT_ROOT/CLAUDE.md"
    grep -Fq 'bash scripts/verify_cmd_closed.sh --promoting-cmd "$cmd"' \
        "$PROJECT_ROOT/instructions/common/task_flow.md"
    grep -Fq 'bash scripts/verify_cmd_closed.sh --closing-cmd' \
        "$PROJECT_ROOT/AGENTS.md"
    grep -Fq 'bash scripts/verify_cmd_closed.sh --promoting-cmd "$cmd"' \
        "$PROJECT_ROOT/instructions/generated/karo.md"
}

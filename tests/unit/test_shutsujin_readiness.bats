#!/usr/bin/env bats

setup() {
    PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    SCRIPT="$PROJECT_ROOT/shutsujin_departure.sh"
}

@test "departure gives detached multiagent panes explicit readiness geometry" {
    grep -q '^MULTIAGENT_DETACHED_WIDTH=300$' "$SCRIPT"
    grep -q '^MULTIAGENT_DETACHED_HEIGHT=120$' "$SCRIPT"
    run awk '
        /^MULTIAGENT_DETACHED_WIDTH=300$/ { geometry = 1 }
        geometry && /^if ! tmux new-session -d \\/ {
            capture = 1
            session_line = NR
        }
        capture {
            block = block $0 ORS
            if ($0 !~ /\\$/) {
                print session_line
                print block
                exit
            }
        }
    ' "$SCRIPT"
    [ "$status" -eq 0 ]
    session_line="${output%%$'\n'*}"
    command_block="${output#*$'\n'}"
    [[ "$command_block" == *'-x "$MULTIAGENT_DETACHED_WIDTH"'* ]]
    [[ "$command_block" == *'-y "$MULTIAGENT_DETACHED_HEIGHT"'* ]]
    [[ "$command_block" == *'-s multiagent -n "agents"'* ]]

    run grep -n 'tmux split-window -h -t "multiagent:agents"' "$SCRIPT"
    [ "$status" -eq 0 ]
    split_line="${output%%:*}"
    [ "$session_line" -lt "$split_line" ]
}

@test "departure checks all role CLI readiness before starting inbox watchers" {
    run grep -n 'cli_readiness_wait_all' "$SCRIPT"
    [ "$status" -eq 0 ]
    readiness_line="${output%%:*}"

    run grep -n 'bash "$SCRIPT_DIR/scripts/inbox_watcher.sh" shogun' "$SCRIPT"
    [ "$status" -eq 0 ]
    watcher_line="${output%%:*}"

    [ "$readiness_line" -lt "$watcher_line" ]
    grep -q '_cli_ready_roles+=("shogun")' "$SCRIPT"
    grep -q '_cli_ready_roles+=("karo")' "$SCRIPT"
    grep -q '_cli_ready_roles+=("ashigaru${i}")' "$SCRIPT"
    grep -q '_cli_ready_roles+=("gunshi")' "$SCRIPT"
    grep -q '_cli_ready_roles+=("oometsuke")' "$SCRIPT"
}

@test "departure fails before watcher startup when aggregate readiness is not met" {
    grep -q 'if ! cli_readiness_wait_all' "$SCRIPT"
    grep -q 'CLI readiness failed; watcher startup is blocked' "$SCRIPT"
}

@test "departure never enables pane-state test overrides" {
    run grep -n 'SHOGUN_TEST_MODE' "$SCRIPT"
    [ "$status" -eq 1 ]
}

@test "departure uses the shared classifier without a duplicate ready pattern" {
    run grep -n 'cli_ready_pattern' "$SCRIPT"
    [ "$status" -eq 1 ]
}

@test "departure quiesces stale watchers before replacing tmux panes and waiting for readiness" {
    run grep -n '^cli_readiness_quiesce_watchers$' "$SCRIPT"
    [ "$status" -eq 0 ]
    quiesce_line="${output%%:*}"

    run grep -n 'tmux kill-session -t multiagent' "$SCRIPT"
    [ "$status" -eq 0 ]
    session_kill_line="${output%%:*}"

    run grep -n 'if ! cli_readiness_wait_all' "$SCRIPT"
    [ "$status" -eq 0 ]
    readiness_line="${output%%:*}"

    [ "$quiesce_line" -lt "$session_kill_line" ]
    [ "$session_kill_line" -lt "$readiness_line" ]

    run grep -n 'cli_readiness_resume_watcher_supervisor' "$SCRIPT"
    [ "$status" -eq 0 ]
    resume_line="${output%%:*}"
    [ "$readiness_line" -lt "$resume_line" ]
}

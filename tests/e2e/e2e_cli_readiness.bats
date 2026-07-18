#!/usr/bin/env bats

# bats file_tags=e2e

load "../test_helper/bats-support/load"
load "../test_helper/bats-assert/load"

E2E_HELPERS_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/helpers" && pwd)"
source "$E2E_HELPERS_DIR/setup.bash"
source "$E2E_HELPERS_DIR/tmux_helpers.bash"

GEOMETRY_SOCKET=""

setup_file() {
    command -v tmux &>/dev/null || skip "tmux not available"
    setup_e2e_session 3
}

teardown_file() {
    teardown_e2e_session
}

setup() {
    local i
    for i in 0 1 2; do
        tmux set-option -pu -t "$(pane_target "$i")" @pane_state_override 2>/dev/null || true
    done
}

teardown() {
    if [[ -n "${GEOMETRY_SOCKET:-}" ]]; then
        tmux -L "$GEOMETRY_SOCKET" kill-server 2>/dev/null || true
        GEOMETRY_SOCKET=""
    fi
}

run_batch_readiness() {
    local timeout_seconds="$1"
    local poll_seconds="$2"
    SHOGUN_TEST_MODE=1 PROJECT_ROOT="$PROJECT_ROOT" \
        E2E_SESSION="$E2E_SESSION" \
        bash -c '
            source "$PROJECT_ROOT/lib/agent_status.sh"
            source "$PROJECT_ROOT/lib/cli_readiness.sh"
            roles=(karo ashigaru1 ashigaru2)
            panes=("$E2E_SESSION:agents.0" "$E2E_SESSION:agents.1" "$E2E_SESSION:agents.2")
            clis=(claude codex claude)
            states=()
            cli_readiness_wait_all roles panes clis states "$1" "$2"
        ' -- "$timeout_seconds" "$poll_seconds"
}

@test "E2E readiness: mixed ready, permission, and shell states fail closed" {
    tmux set-option -p -t "$(pane_target 0)" @pane_state_override ready
    tmux set-option -p -t "$(pane_target 1)" @pane_state_override permission_prompt
    tmux set-option -p -t "$(pane_target 2)" @pane_state_override shell_prompt

    run run_batch_readiness 0 0

    assert_failure
    assert_output --partial "cli_readiness role=karo state=ready ready=true"
    assert_output --partial "cli_readiness role=ashigaru1 state=permission_prompt ready=false"
    assert_output --partial "cli_readiness role=ashigaru2 state=shell_prompt ready=false"
    assert_output --partial "cli_readiness overall=not_ready"
}

@test "E2E readiness: delayed pane becomes ready before the shared deadline" {
    tmux set-option -p -t "$(pane_target 0)" @pane_state_override ready
    tmux set-option -p -t "$(pane_target 1)" @pane_state_override busy
    tmux set-option -p -t "$(pane_target 2)" @pane_state_override ready

    (
        sleep 1
        tmux set-option -p -t "$(pane_target 1)" @pane_state_override ready
    ) &
    local updater_pid=$!

    run run_batch_readiness 3 0.1
    wait "$updater_pid"

    assert_success
    assert_output --partial "cli_readiness role=ashigaru1 state=ready ready=true"
    assert_output --partial "cli_readiness overall=ready"
}

@test "E2E readiness: detached multiagent geometry keeps ten tiled panes usable" {
    local width height pane_count=0 pane_width pane_height
    width=$(sed -n 's/^MULTIAGENT_DETACHED_WIDTH=\([0-9][0-9]*\)$/\1/p' \
        "$PROJECT_ROOT/shutsujin_departure.sh")
    height=$(sed -n 's/^MULTIAGENT_DETACHED_HEIGHT=\([0-9][0-9]*\)$/\1/p' \
        "$PROJECT_ROOT/shutsujin_departure.sh")
    [ "$width" -eq 300 ]
    [ "$height" -eq 120 ]

    GEOMETRY_SOCKET="shogun-geometry-${BATS_TEST_NUMBER}-${BASHPID}"
    tmux -L "$GEOMETRY_SOCKET" -f /dev/null new-session -d \
        -x "$width" -y "$height" -s geometry -n agents
    tmux -L "$GEOMETRY_SOCKET" split-window -h -t geometry:agents
    tmux -L "$GEOMETRY_SOCKET" split-window -h -t geometry:agents
    tmux -L "$GEOMETRY_SOCKET" select-pane -t geometry:agents.0
    tmux -L "$GEOMETRY_SOCKET" split-window -v
    tmux -L "$GEOMETRY_SOCKET" split-window -v
    tmux -L "$GEOMETRY_SOCKET" select-pane -t geometry:agents.3
    tmux -L "$GEOMETRY_SOCKET" split-window -v
    tmux -L "$GEOMETRY_SOCKET" split-window -v
    tmux -L "$GEOMETRY_SOCKET" select-pane -t geometry:agents.6
    tmux -L "$GEOMETRY_SOCKET" split-window -v
    tmux -L "$GEOMETRY_SOCKET" split-window -v
    tmux -L "$GEOMETRY_SOCKET" split-window -v -t geometry:agents.8
    tmux -L "$GEOMETRY_SOCKET" select-layout -t geometry:agents tiled

    while read -r pane_width pane_height; do
        ((pane_count += 1))
        [ "$pane_width" -ge 80 ]
        [ "$pane_height" -ge 24 ]
    done < <(
        tmux -L "$GEOMETRY_SOCKET" list-panes -t geometry:agents \
            -F '#{pane_width} #{pane_height}'
    )
    [ "$pane_count" -eq 10 ]
}

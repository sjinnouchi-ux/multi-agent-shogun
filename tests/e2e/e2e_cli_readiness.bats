#!/usr/bin/env bats

# bats file_tags=e2e

load "../test_helper/bats-support/load"
load "../test_helper/bats-assert/load"

E2E_HELPERS_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/helpers" && pwd)"
source "$E2E_HELPERS_DIR/setup.bash"
source "$E2E_HELPERS_DIR/tmux_helpers.bash"

GEOMETRY_SOCKET=""
STATUSLINE_SOCKET=""
STATUSLINE_TMP=""

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
    local attempt pane_id statusline_tmp_canonical statusline_tmp_owner
    local statusline_cleanup_failed=0 statusline_tmp_cleanup_failed=0
    if [[ -n "${STATUSLINE_SOCKET:-}" ]]; then
        for attempt in {1..20}; do
            while read -r pane_id; do
                tmux -L "$STATUSLINE_SOCKET" send-keys -t "$pane_id" exit Enter \
                    2>/dev/null || true
            done < <(
                tmux -L "$STATUSLINE_SOCKET" list-panes -a -F '#{pane_id}' \
                    2>/dev/null || true
            )

            if ! tmux -L "$STATUSLINE_SOCKET" has-session 2>/dev/null; then
                STATUSLINE_SOCKET=""
                break
            fi
            sleep 0.05
        done

        [[ -z "$STATUSLINE_SOCKET" ]] || statusline_cleanup_failed=1
    fi
    if [[ -n "${STATUSLINE_TMP:-}" ]]; then
        statusline_tmp_canonical=$(readlink -f -- "$STATUSLINE_TMP" 2>/dev/null) || \
            statusline_tmp_cleanup_failed=1
        statusline_tmp_owner=$(stat -c %u -- "$STATUSLINE_TMP" 2>/dev/null) || \
            statusline_tmp_cleanup_failed=1
        if [[ "$statusline_tmp_cleanup_failed" -eq 0 ]] && \
            [[ "$statusline_tmp_canonical" == "$STATUSLINE_TMP" ]] && \
            [[ "$(basename -- "$STATUSLINE_TMP")" =~ ^shogun-statusline\.[[:alnum:]]{6}$ ]] && \
            [[ -d "$STATUSLINE_TMP" ]] && [[ ! -L "$STATUSLINE_TMP" ]] && \
            [[ "$statusline_tmp_owner" == "$(id -u)" ]]; then
            rm -r -- "$STATUSLINE_TMP" 2>/dev/null || statusline_tmp_cleanup_failed=1
            [[ ! -e "$STATUSLINE_TMP" && ! -L "$STATUSLINE_TMP" ]] || \
                statusline_tmp_cleanup_failed=1
        else
            statusline_tmp_cleanup_failed=1
        fi
        STATUSLINE_TMP=""
    fi
    if [[ "$statusline_tmp_cleanup_failed" -ne 0 ]]; then
        echo "isolated status-line temp cleanup did not complete" >&2
        return 1
    fi
    if [[ "$statusline_cleanup_failed" -ne 0 ]]; then
        echo "isolated status-line tmux cleanup did not complete" >&2
        return 1
    fi
    if [[ -n "${GEOMETRY_SOCKET:-}" ]]; then
        while read -r pane_id; do
            tmux -L "$GEOMETRY_SOCKET" send-keys -t "$pane_id" exit Enter \
                2>/dev/null || true
        done < <(
            tmux -L "$GEOMETRY_SOCKET" list-panes -a -F '#{pane_id}' \
                2>/dev/null || true
        )

        for attempt in {1..20}; do
            if ! tmux -L "$GEOMETRY_SOCKET" has-session 2>/dev/null; then
                GEOMETRY_SOCKET=""
                return 0
            fi
            sleep 0.05
        done

        echo "isolated geometry tmux cleanup did not complete" >&2
        return 1
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

@test "E2E readiness: Shogun Codex command pins visible status line" {
    local command launch state="unknown" attempt real_tmux

    STATUSLINE_SOCKET="shogun-statusline-${BATS_TEST_NUMBER}-${BASHPID}"
    STATUSLINE_TMP=$(mktemp -d /tmp/shogun-statusline.XXXXXX)
    mkdir -p "$STATUSLINE_TMP/bin"
    real_tmux=$(command -v tmux)

    cat > "$STATUSLINE_TMP/bin/codex" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail

status_config_count=0
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        -c)
            [[ "$#" -ge 2 ]] || exit 2
            if [[ "$2" == 'tui.status_line=["context-remaining"]' ]]; then
                status_config_count=$((status_config_count + 1))
            fi
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

if [[ "$status_config_count" -eq 1 ]]; then
    printf '%s\n' 'Context 100% left'
else
    printf '%s\n' '[mock_state] readiness marker withheld'
fi

while IFS= read -r line; do
    [[ "$line" == "exit" ]] && exit 0
done
MOCK

    cat > "$STATUSLINE_TMP/bin/tmux" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
exec "${SHOGUN_TEST_REAL_TMUX:?}" \
    -L "${SHOGUN_TEST_TMUX_SOCKET:?}" "$@"
MOCK
    chmod +x "$STATUSLINE_TMP/bin/codex" "$STATUSLINE_TMP/bin/tmux"

    cat > "$STATUSLINE_TMP/settings.yaml" <<'YAML'
cli:
  default: codex
  agents:
    ashigaru1:
      type: codex
      model: gpt-5.3-codex
YAML

    export CLI_ADAPTER_SETTINGS="$STATUSLINE_TMP/settings.yaml"
    source "$PROJECT_ROOT/lib/cli_adapter.sh"
    command=$(build_cli_command ashigaru1)

    "$real_tmux" -L "$STATUSLINE_SOCKET" -f /dev/null new-session -d \
        -x 120 -y 30 -s statusline -n agents
    "$real_tmux" -L "$STATUSLINE_SOCKET" set-option -p \
        -t statusline:agents.0 @agent_cli codex
    launch="PATH=$STATUSLINE_TMP/bin:\$PATH $command"
    "$real_tmux" -L "$STATUSLINE_SOCKET" send-keys \
        -t statusline:agents.0 "$launch" Enter

    for attempt in {1..40}; do
        state=$(env -u TMUX \
            PATH="$STATUSLINE_TMP/bin:$PATH" \
            SHOGUN_TEST_REAL_TMUX="$real_tmux" \
            SHOGUN_TEST_TMUX_SOCKET="$STATUSLINE_SOCKET" \
            bash -c '
                source "$1/lib/agent_status.sh"
                get_pane_cli_state statusline:agents.0 codex
            ' -- "$PROJECT_ROOT")
        [[ "$state" == "ready" ]] && break
        sleep 0.05
    done

    if [[ "$state" != "ready" ]]; then
        local capture marker_full=false marker_tail=false pane_command
        capture=$("$real_tmux" -L "$STATUSLINE_SOCKET" capture-pane -p \
            -t statusline:agents.0)
        printf '%s\n' "$capture" | \
            grep -qE 'Context [0-9]+% left' && marker_full=true
        printf '%s\n' "$capture" | tail -5 | \
            grep -qE 'Context [0-9]+% left' && marker_tail=true
        pane_command=$("$real_tmux" -L "$STATUSLINE_SOCKET" display-message \
            -t statusline:agents.0 -p '#{pane_current_command}')
        printf 'status-line readiness state=%s marker_full=%s marker_tail=%s command=%s\n' \
            "$state" "$marker_full" "$marker_tail" "$pane_command" >&2
        return 1
    fi
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

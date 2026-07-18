#!/usr/bin/env bats

setup_file() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export AGENT_STATUS_LIB="$PROJECT_ROOT/lib/agent_status.sh"
    [ -f "$AGENT_STATUS_LIB" ]
}

setup() {
    export TEST_TMPDIR="$(mktemp -d "$BATS_TMPDIR/agent_cli_state.XXXXXX")"
    export WARNING_FILE="$TEST_TMPDIR/warnings.log"
    export CALL_LOG="$TEST_TMPDIR/tmux_calls.log"
    : > "$CALL_LOG"

    export MOCK_PANE_EXISTS=1
    export MOCK_PANE_CLI=claude
    export MOCK_PANE_OVERRIDE=""
    export MOCK_CAPTURE="Claude Code (mock)
>"
    export MOCK_CURRENT_COMMAND=node
    unset SHOGUN_TEST_MODE

    export TEST_HARNESS="$TEST_TMPDIR/harness.sh"
    cat > "$TEST_HARNESS" <<'HARNESS'
#!/usr/bin/env bash
tmux() {
    printf '%s\n' "tmux $*" >> "$CALL_LOG"
    case "$1" in
        display-message)
            if [[ "$*" == *'#{pane_id}'* ]]; then
                [[ "${MOCK_PANE_EXISTS:-1}" == "1" ]] || return 1
                printf '%%1\n'
            elif [[ "$*" == *'#{pane_current_command}'* ]]; then
                printf '%s\n' "${MOCK_CURRENT_COMMAND:-}"
            fi
            ;;
        show-options)
            if [[ "$*" == *'@pane_state_override'* ]]; then
                printf '%s\n' "${MOCK_PANE_OVERRIDE:-}"
            elif [[ "$*" == *'@agent_cli'* ]]; then
                printf '%s\n' "${MOCK_PANE_CLI:-}"
            fi
            ;;
        capture-pane)
            printf '%s\n' "${MOCK_CAPTURE:-}"
            ;;
    esac
}
timeout() {
    shift
    "$@"
}
export -f tmux timeout
source "$AGENT_STATUS_LIB"
get_pane_cli_state test:0.0 "${EXPECTED_CLI:-}" 2> "$WARNING_FILE"
HARNESS
    chmod +x "$TEST_HARNESS"
}

teardown() {
    rm -rf "$TEST_TMPDIR"
}

run_state() {
    run bash "$TEST_HARNESS"
}

assert_single_state() {
    local expected="$1"
    [ "$status" -eq 0 ]
    [ "$output" = "$expected" ]
    [ "${#lines[@]}" -eq 1 ]
}

assert_file_lacks_pattern() {
    local pattern="$1"
    local path="$2"
    if grep -qE -- "$pattern" "$path"; then
        return 1
    fi
}

@test "returns each state token with exit zero" {
    while IFS='|' read -r expected cli command capture; do
        export MOCK_PANE_EXISTS=1
        export EXPECTED_CLI="$cli"
        export MOCK_CURRENT_COMMAND="$command"
        export MOCK_CAPTURE="${capture//\\n/$'\n'}"
        if [ "$expected" = absent ]; then
            export MOCK_PANE_EXISTS=0
        fi

        run_state
        assert_single_state "$expected"
    done <<'CASES'
ready|claude|node|Claude Code (mock)\n>
busy|claude|node|Claude Code (mock)\nWorking on task (esc to interrupt)
permission_prompt|claude|node|Claude Code (mock)\nDo you want to allow this action?
login_prompt|codex|codex|Codex CLI (mock)\nPlease sign in to continue\n? for shortcuts
shell_prompt|claude|bash|developer@host:~/repo$
absent|claude|node|Claude Code (mock)\n>
unknown|claude|node|developer@host:~/repo$
CASES
}

@test "blocked prompt in the last fifteen lines outranks a positive CLI marker" {
    export EXPECTED_CLI=claude
    export MOCK_CURRENT_COMMAND=bash
    export MOCK_CAPTURE="$(printf 'history-%02d\n' {1..4})Do you want to allow this action?
$(printf 'screen-%02d\n' {1..8})Claude Code (mock)
>"

    run_state
    assert_single_state permission_prompt
}

@test "common approval and authentication screens are fail-closed" {
    local expected cli prompt
    while IFS='|' read -r expected cli prompt; do
        export EXPECTED_CLI="$cli"
        export MOCK_CURRENT_COMMAND=node
        export MOCK_CAPTURE="${cli^} CLI (mock)
$prompt"

        run_state
        assert_single_state "$expected"
    done <<'CASES'
permission_prompt|claude|Would you like to run the following command?
permission_prompt|claude|Do you trust the files in this folder?
permission_prompt|copilot|You should only proceed if you trust the files in this location.
login_prompt|claude|Select an authentication method
login_prompt|claude|Sign in with ChatGPT
login_prompt|copilot|Error: No authentication information found
login_prompt|copilot|Enter /login to authenticate with GitHub
login_prompt|copilot|What account do you want to log into?
login_prompt|copilot|Waiting for authorization...
CASES
}

@test "blocked prompt older than the last fifteen lines is ignored" {
    export EXPECTED_CLI=claude
    export MOCK_CAPTURE="Do you want to allow this action?
$(printf 'screen-%02d\n' {1..14})Claude Code (mock)
>"

    run_state
    assert_single_state ready
}

@test "busy marker is limited to the last five lines" {
    export EXPECTED_CLI=claude
    export MOCK_CAPTURE="Working on old task (esc to interrupt)
Claude Code (mock)
line-1
line-2
line-3
>"

    run_state
    assert_single_state ready

    export MOCK_CAPTURE="Claude Code (mock)
Working on current task (esc to interrupt)
line-2
line-3
>"
    run_state
    assert_single_state busy
}

@test "explicit idle marker at the bottom outranks stale busy history" {
    local cli capture
    while IFS='|' read -r cli capture; do
        export EXPECTED_CLI="$cli"
        export MOCK_CURRENT_COMMAND=node
        export MOCK_CAPTURE="${capture//\\n/$'\n'}"

        run_state
        assert_single_state ready
    done <<'CASES'
claude|Claude Code (mock)\nWorking on old task (esc to interrupt)\nold output\n❯
codex|Codex CLI (mock)\nThinking about old approach (esc to interrupt)\nold output\n? for shortcuts  100% context left
CASES
}

@test "current busy marker outranks an older idle marker" {
    local cli capture
    while IFS='|' read -r cli capture; do
        export EXPECTED_CLI="$cli"
        export MOCK_CURRENT_COMMAND=node
        export MOCK_CAPTURE="${capture//\\n/$'\n'}"

        run_state
        assert_single_state busy
    done <<'CASES'
claude|Claude Code (mock)\n❯\nWorking on current task
codex|Codex CLI (mock)\n? for shortcuts  100% context left\nThinking about current approach
CASES
}

@test "positive CLI marker is not overwritten by a bash or node process name" {
    export EXPECTED_CLI=claude
    export MOCK_CAPTURE="Claude Code (mock)
>"

    export MOCK_CURRENT_COMMAND=node
    run_state
    assert_single_state ready

    export MOCK_CURRENT_COMMAND=bash
    run_state
    assert_single_state ready
}

@test "existing mock CLIs running under bash are not mistaken for shell prompts" {
    local cli capture
    export MOCK_CURRENT_COMMAND=bash
    while IFS='|' read -r cli capture; do
        export EXPECTED_CLI="$cli"
        export MOCK_CAPTURE="${capture//\\n/$'\n'}"

        run_state
        assert_single_state ready
    done <<'CASES'
claude|│        bypass permissions               │\n╰────────────────────────────────────────╯\n\n$
codex|Codex CLI (mock)\n? for shortcuts\n100% context left\n$
opencode|┃  Ask anything...\nctrl+p commands
CASES
}

@test "mock busy activity is itself a positive marker for the expected CLI" {
    local cli capture
    export MOCK_CURRENT_COMMAND=bash
    while IFS='|' read -r cli capture; do
        export EXPECTED_CLI="$cli"
        export MOCK_CAPTURE="$capture"

        run_state
        assert_single_state busy
    done <<'CASES'
claude|Working on task (3s • esc to interrupt)
codex|Thinking about approach (3s • esc to interrupt)
opencode|■⬝⬝⬝⬝⬝⬝⬝  esc interrupt
CASES
}

@test "shell_prompt requires both a visual prompt and a supported shell process" {
    export EXPECTED_CLI=claude
    export MOCK_CAPTURE="developer@host:~/repo$ "

    export MOCK_CURRENT_COMMAND=node
    run_state
    assert_single_state unknown

    export MOCK_CURRENT_COMMAND=bash
    export MOCK_CAPTURE="application exited without a prompt"
    run_state
    assert_single_state unknown

    export MOCK_CAPTURE="> "
    run_state
    assert_single_state unknown
}

@test "bare shell prompts are recognized with a supported shell process" {
    local command prompt
    while IFS='|' read -r command prompt; do
        export EXPECTED_CLI=claude
        export MOCK_CURRENT_COMMAND="$command"
        export MOCK_CAPTURE="$prompt "

        run_state
        assert_single_state shell_prompt
    done <<'CASES'
bash|$
sh|#
zsh|%
fish|you@hostname ~>
fish|>
CASES
}

@test "test override is honored only when both controls are present" {
    export EXPECTED_CLI=claude
    export MOCK_PANE_OVERRIDE=login_prompt
    export MOCK_CAPTURE="Claude Code (mock)
>"

    export SHOGUN_TEST_MODE=1
    run_state
    assert_single_state login_prompt
    [ ! -s "$WARNING_FILE" ]
    assert_file_lacks_pattern 'capture-pane' "$CALL_LOG"

    unset SHOGUN_TEST_MODE
    run_state
    assert_single_state ready
    grep -q '^warning: pane state override ignored outside test mode$' "$WARNING_FILE"
    assert_file_lacks_pattern 'test:0\.0|Claude Code' "$WARNING_FILE"
}

@test "invalid test override warns and falls back to normal classification" {
    export EXPECTED_CLI=claude
    export MOCK_PANE_OVERRIDE='not-a-state'
    export MOCK_CAPTURE="Claude Code (mock)
>"
    export SHOGUN_TEST_MODE=1

    run_state
    assert_single_state ready
    grep -q '^warning: invalid pane state override ignored$' "$WARNING_FILE"
    assert_file_lacks_pattern 'not-a-state|test:0\.0' "$WARNING_FILE"
}

@test "absent pane is returned before consulting an override" {
    export MOCK_PANE_EXISTS=0
    export MOCK_PANE_OVERRIDE=ready
    export SHOGUN_TEST_MODE=1

    run_state
    assert_single_state absent
    assert_file_lacks_pattern '@pane_state_override' "$CALL_LOG"
}

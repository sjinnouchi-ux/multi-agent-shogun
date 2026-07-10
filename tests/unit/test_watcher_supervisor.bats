#!/usr/bin/env bats
# test_watcher_supervisor.bats — start_watcher_if_missing unit tests
#
# Tests the flock-protected start_watcher_if_missing logic via mocking.
#
# Test cases:
#   T-WS-001: pane does not exist → returns 0, no watcher started
#   T-WS-002: watcher already running for correct pane → no duplicate started
#   T-WS-003: lockfile path follows pattern /tmp/shogun_watcher_start_{agent}.lock
#   T-WS-004: no existing watcher → watcher is started

PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
SUPERVISOR_SCRIPT="$PROJECT_ROOT/scripts/watcher_supervisor.sh"

setup() {
    TEST_TMP="$(mktemp -d)"
    mkdir -p "$TEST_TMP/scripts"
    mkdir -p "$TEST_TMP/queue/inbox"
    mkdir -p "$TEST_TMP/logs"

    # Mock inbox_watcher.sh — records launch args
    cat > "$TEST_TMP/scripts/inbox_watcher.sh" << 'MOCK'
#!/bin/bash
echo "$@" >> "$(dirname "$0")/../watcher_launched.log"
sleep 60
MOCK
    chmod +x "$TEST_TMP/scripts/inbox_watcher.sh"

    # Default mock: pane does NOT exist
    MOCK_PANE_EXISTS=0

    # Default mock: no existing watcher pgrep hit
    MOCK_PGREP_CORRECT=1
    MOCK_PGREP_STALE=1
}

teardown() {
    rm -rf "$TEST_TMP"
}

# Source the function under test with mocked dependencies injected via env overrides.
# We source the function definitions only, then call start_watcher_if_missing directly.
source_supervisor_functions() {
    # Override pane_exists and pgrep with shell functions in the current subshell.
    pane_exists() {
        return $MOCK_PANE_EXISTS
    }

    pgrep() {
        # Distinguish correct-pane vs stale-pane pgrep call by argument pattern
        local args="$*"
        if echo "$args" | grep -q "( |\$)"; then
            # correct-pane pattern (has trailing space or end anchor)
            return $MOCK_PGREP_CORRECT
        else
            return $MOCK_PGREP_STALE
        fi
    }

    ensure_inbox_file() {
        local agent="$1"
        touch "$TEST_TMP/queue/inbox/${agent}.yaml"
    }

    # Load only the start_watcher_if_missing function definition from the script.
    # We extract and eval it to avoid running the infinite loop at the bottom.
    eval "$(
        awk '/^start_watcher_if_missing\(\)/{p=1} p{print} /^\}$/{if(p){p=0}}' \
            "$SUPERVISOR_SCRIPT"
    )"
}

# ---------------------------------------------------------------------------
# T-WS-001: pane does not exist → function returns 0, no watcher started
# ---------------------------------------------------------------------------
@test "T-WS-001: pane does not exist returns 0 and does not start watcher" {
    (
        export MOCK_PANE_EXISTS=1   # non-zero = pane missing

        pane_exists() { return 1; }
        ensure_inbox_file() { :; }

        watcher_started=0
        nohup() { watcher_started=1; }

        eval "$(
            awk '/^start_watcher_if_missing\(\)/{p=1} p{print} /^\}$/{if(p){p=0}}' \
                "$SUPERVISOR_SCRIPT"
        )"

        start_watcher_if_missing "ashigaru1" "multiagent:agents.1" "/tmp/test_ws_001.log"
        result=$?

        [ "$result" -eq 0 ]
        [ "$watcher_started" -eq 0 ]
    )
}

# ---------------------------------------------------------------------------
# T-WS-002: watcher already running for correct pane → no duplicate started
# ---------------------------------------------------------------------------
@test "T-WS-002: watcher already running for correct pane does not start duplicate" {
    local launched_log="$TEST_TMP/watcher_launched.log"

    # Run a subprocess that:
    #   - pane exists
    #   - correct-pane pgrep returns 0 (watcher running)
    #   - records if inbox_watcher.sh gets executed
    (
        pane_exists() { return 0; }
        ensure_inbox_file() { touch "$TEST_TMP/queue/inbox/${1}.yaml"; }

        pgrep() {
            # Simulate: correct-pane watcher IS running
            return 0
        }

        nohup_called=0
        # Override nohup so we can detect if watcher would be launched
        nohup() { nohup_called=1; echo "$@" >> "$launched_log"; }

        eval "$(
            awk '/^start_watcher_if_missing\(\)/{p=1} p{print} /^\}$/{if(p){p=0}}' \
                "$SUPERVISOR_SCRIPT"
        )"

        start_watcher_if_missing "ashigaru1" "multiagent:agents.1" "/tmp/test_ws_002.log"

        # If launched_log was created, a duplicate was (incorrectly) started
        [ ! -f "$launched_log" ]
    )
}

# ---------------------------------------------------------------------------
# T-WS-003: lockfile path follows /tmp/shogun_watcher_start_{agent}.lock
# ---------------------------------------------------------------------------
@test "T-WS-003: lockfile path follows /tmp/shogun_watcher_start_{agent}.lock pattern" {
    local agent="ashigaru3"
    local expected_lockfile="/tmp/shogun_watcher_start_${agent}.lock"

    # Confirm the script contains the expected lockfile pattern for any agent name
    grep -q 'lockfile="/tmp/shogun_watcher_start_\${agent}.lock"' "$SUPERVISOR_SCRIPT"
}

# ---------------------------------------------------------------------------
# T-WS-004: no existing watcher → watcher is started (nohup bash ... invoked)
# ---------------------------------------------------------------------------
@test "T-WS-004: no existing watcher causes inbox_watcher to be launched" {
    local launched_log="$TEST_TMP/watcher_launched.log"
    local lockfile="/tmp/shogun_watcher_start_ashigaru4_$$_test.lock"

    # Clean up stray lockfile from a previous failed run
    rm -f "$lockfile"

    (
        pane_exists() { return 0; }
        ensure_inbox_file() { touch "$TEST_TMP/queue/inbox/${1}.yaml"; }

        pgrep() {
            # No watcher running
            return 1
        }

        # macOS runners do not provide flock. This test validates launch logic,
        # so make lock acquisition deterministic without an OS package dependency.
        flock() {
            return 0
        }

        tmux() {
            # Stub tmux show-options for @agent_cli
            echo "codex"
        }

        # Override nohup + bash to capture the launch without actually spawning
        nohup() {
            echo "launched: $*" >> "$launched_log"
        }

        eval "$(
            awk '/^start_watcher_if_missing\(\)/{p=1} p{print} /^\}$/{if(p){p=0}}' \
                "$SUPERVISOR_SCRIPT"
        )"

        # Use a test-specific lockfile to avoid collision with real supervisors
        # We re-define the lockfile variable inside the function scope by
        # calling with a modified env. Since lockfile is a local var built
        # from agent name, use a unique agent name for isolation.
        start_watcher_if_missing "ashigaru4_$$_test" "multiagent:agents.4" "$launched_log"
    )

    # A launched entry should exist in the log
    [ -f "$launched_log" ]
    grep -q "launched:" "$launched_log"
}

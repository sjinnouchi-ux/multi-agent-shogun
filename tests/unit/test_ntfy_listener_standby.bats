#!/usr/bin/env bats

setup_file() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    [ -x "$PROJECT_ROOT/.venv/bin/python3" ]
}

setup() {
    export TEST_TMPDIR="$(mktemp -d "$BATS_TMPDIR/ntfy_standby.XXXXXX")"
    export MOCK_PROJECT="$TEST_TMPDIR/project"
    export MOCK_BIN="$TEST_TMPDIR/bin"
    export MOCK_CURL_OUTPUT="$TEST_TMPDIR/curl.json"
    export MOCK_CURL_LOG="$TEST_TMPDIR/curl.args"
    export MOCK_INBOX_LOG="$TEST_TMPDIR/inbox.log"
    mkdir -p "$MOCK_PROJECT"/{config,lib,scripts,queue,status,.venv/bin} "$MOCK_BIN"

    cp "$PROJECT_ROOT/lib/ntfy_auth.sh" "$MOCK_PROJECT/lib/"
    cp "$PROJECT_ROOT/lib/ntfy_state.sh" "$MOCK_PROJECT/lib/"
    cp "$PROJECT_ROOT/lib/ntfy_lifecycle.sh" "$MOCK_PROJECT/lib/"
    cat > "$MOCK_PROJECT/.venv/bin/python3" <<WRAPPER
#!/bin/sh
exec "$PROJECT_ROOT/.venv/bin/python3" "\$@"
WRAPPER
    chmod +x "$MOCK_PROJECT/.venv/bin/python3"

    cat > "$MOCK_PROJECT/config/settings.yaml" <<'YAML'
ntfy_topic: "standby-test-topic-12345"
ntfy_listener:
  mode: disabled
YAML
    touch "$MOCK_PROJECT/config/ntfy_auth.env"
    printf '%s\n' 'inbox:' > "$MOCK_PROJECT/queue/ntfy_inbox.yaml"

    cat > "$MOCK_PROJECT/scripts/inbox_write.sh" <<'MOCK'
#!/bin/bash
printf '%s\n' "$*" >> "$MOCK_INBOX_LOG"
MOCK
    chmod +x "$MOCK_PROJECT/scripts/inbox_write.sh"

    sed "s|^SCRIPT_DIR=.*|SCRIPT_DIR=\"$MOCK_PROJECT\"|" \
        "$PROJECT_ROOT/scripts/ntfy_listener.sh" > "$MOCK_PROJECT/listener.sh"
    chmod +x "$MOCK_PROJECT/listener.sh"

    cat > "$MOCK_BIN/curl" <<'MOCK'
#!/bin/bash
printf '%s\n' "$*" >> "$MOCK_CURL_LOG"
if [ "${MOCK_CURL_MODE:-stream}" = "auth401" ]; then
    printf '%s' '401'
    exit 0
fi
if [ "${MOCK_CURL_MODE:-stream}" = "block" ]; then
    sleep 30
    exit 0
fi
if [ -f "$MOCK_CURL_OUTPUT" ]; then
    cat "$MOCK_CURL_OUTPUT"
fi
MOCK
    chmod +x "$MOCK_BIN/curl"

    export PATH="$MOCK_BIN:$PATH"
    export NTFY_SKIP_PREFLIGHT=1
    export NTFY_RECONNECT_DELAY=0.05
    export NTFY_STATE_FILE="$MOCK_PROJECT/status/ntfy_listener_state.yaml"
    unset MOCK_CURL_MODE
}

teardown() {
    rm -rf "$TEST_TMPDIR"
}

run_for_one_second() {
    run timeout 1 bash "$MOCK_PROJECT/listener.sh"
    [ "$status" -eq 124 ] || [ "$status" -eq 0 ]
}

@test "topic hash is deterministic lowercase SHA-256 without newline" {
    source "$PROJECT_ROOT/lib/ntfy_state.sh"
    first="$(ntfy_topic_hash 'standby-test-topic-12345')"
    second="$(ntfy_topic_hash 'standby-test-topic-12345')"
    expected="$(printf '%s' 'standby-test-topic-12345' | sha256sum | awk '{print $1}')"
    [ "$first" = "$second" ]
    [ "$first" = "$expected" ]
    [[ "$first" =~ ^[0-9a-f]{64}$ ]]
}

@test "state writer creates standby state with mode 0600" {
    export SCRIPT_DIR="$MOCK_PROJECT"
    source "$PROJECT_ROOT/lib/ntfy_state.sh"
    ntfy_state_write "$NTFY_STATE_FILE" 'standby-test-topic-12345' '' 1700000000 standby
    [ "$(stat -c '%a' "$NTFY_STATE_FILE")" = "600" ]
    run "$MOCK_PROJECT/.venv/bin/python3" -c \
        'import sys,yaml; d=yaml.safe_load(open(sys.argv[1])); assert d["state"] == "standby"' \
        "$NTFY_STATE_FILE"
    [ "$status" -eq 0 ]
}

@test "outbound advances cursor without adding an Inbox entry" {
    cat > "$MOCK_CURL_OUTPUT" <<'JSON'
{"event":"message","id":"outbound001","time":1700000001,"message":"redacted","tags":["outbound"]}
JSON
    run_for_one_second
    run "$MOCK_PROJECT/.venv/bin/python3" -c \
        'import sys,yaml; i=yaml.safe_load(open(sys.argv[1])); s=yaml.safe_load(open(sys.argv[2])); assert not (i.get("inbox") or []); assert s["last_message_id"] == "outbound001"' \
        "$MOCK_PROJECT/queue/ntfy_inbox.yaml" "$NTFY_STATE_FILE"
    [ "$status" -eq 0 ]
}

@test "normal message records id and duplicate delivery is deduplicated" {
    cat > "$MOCK_CURL_OUTPUT" <<'JSON'
{"event":"message","id":"incoming001","time":1700000002,"message":"fixture body","tags":[]}
JSON
    run_for_one_second
    run "$MOCK_PROJECT/.venv/bin/python3" -c \
        'import sys,yaml; d=yaml.safe_load(open(sys.argv[1])); items=d["inbox"]; assert len(items)==1; assert "id" in items[0]; assert items[0]["id"]=="incoming001"' \
        "$MOCK_PROJECT/queue/ntfy_inbox.yaml"
    [ "$status" -eq 0 ]
}

@test "saved message id is used as since cursor" {
    export SCRIPT_DIR="$MOCK_PROJECT"
    source "$PROJECT_ROOT/lib/ntfy_state.sh"
    ntfy_state_write "$NTFY_STATE_FILE" 'standby-test-topic-12345' 'cursor001' 1700000003 standby
    run_for_one_second
    grep -q 'since=cursor001' "$MOCK_CURL_LOG"
}

@test "corrupt state fails closed with exit 1" {
    printf '%s\n' 'not: [valid' > "$NTFY_STATE_FILE"
    run bash "$MOCK_PROJECT/listener.sh"
    [ "$status" -eq 1 ]
}

@test "missing configuration fails immediately with exit 1" {
    printf '%s\n' 'ntfy_listener:' '  mode: disabled' > "$MOCK_PROJECT/config/settings.yaml"
    run bash "$MOCK_PROJECT/listener.sh"
    [ "$status" -eq 1 ]
}

@test "authentication rejection fails immediately with exit 1" {
    export NTFY_SKIP_PREFLIGHT=0
    export MOCK_CURL_MODE=auth401
    run bash "$MOCK_PROJECT/listener.sh"
    [ "$status" -eq 1 ]
}

@test "SIGTERM is trapped and listener exits 0" {
    export MOCK_CURL_MODE=block
    run timeout --preserve-status --signal=TERM 1 bash "$MOCK_PROJECT/listener.sh"
    [ "$status" -eq 0 ]
}

@test "systemctl absence permits only explicit legacy fallback" {
    empty_path="$TEST_TMPDIR/empty-path"
    mkdir -p "$empty_path"
    run env PATH="$empty_path" /bin/bash -c \
        'source "$1"; ntfy_legacy_start_allowed legacy' _ \
        "$PROJECT_ROOT/lib/ntfy_lifecycle.sh"
    [ "$status" -eq 0 ]
    run env PATH="$empty_path" /bin/bash -c \
        'source "$1"; ntfy_legacy_start_allowed systemd' _ \
        "$PROJECT_ROOT/lib/ntfy_lifecycle.sh"
    [ "$status" -ne 0 ]
}

@test "listener mode defaults to disabled" {
    source "$PROJECT_ROOT/lib/ntfy_lifecycle.sh"
    [ "$(ntfy_resolve_listener_mode "$TEST_TMPDIR/missing.yaml")" = "disabled" ]
}

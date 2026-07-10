#!/usr/bin/env bash
# ntfy input listener: streaming subscription, durable cursor, and inbox append.
# Exit policy:
# - network/stream interruption is absorbed by the internal reconnect loop;
# - configuration, authentication, or state corruption exits 1 (fail closed);
# - SIGTERM/SIGINT performs cleanup and exits 0;
# - no other path intentionally exits 0.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SETTINGS="$SCRIPT_DIR/config/settings.yaml"
INBOX="$SCRIPT_DIR/queue/ntfy_inbox.yaml"
LOCKFILE="${INBOX}.lock"
CORRUPT_DIR="$SCRIPT_DIR/logs/ntfy_inbox_corrupt"
STATE_FILE="${NTFY_STATE_FILE:-$SCRIPT_DIR/status/ntfy_listener_state.yaml}"
RECONNECT_DELAY="${NTFY_RECONNECT_DELAY:-5}"

# shellcheck source=../lib/ntfy_auth.sh
source "$SCRIPT_DIR/lib/ntfy_auth.sh"
# shellcheck source=../lib/ntfy_state.sh
source "$SCRIPT_DIR/lib/ntfy_state.sh"

listener_shutdown() {
    echo "[$(date)] [ntfy_listener] shutdown requested" >&2
    exit 0
}
trap listener_shutdown TERM INT

TOPIC="$(ntfy_resolve_topic "$SETTINGS")"
if [ -z "$TOPIC" ]; then
    echo "[ntfy_listener] topic is not configured" >&2
    exit 1
fi
ntfy_validate_topic "$TOPIC" || exit 1

PYTHON_BIN="$(_ntfy_state_python)" || {
    echo "[ntfy_listener] python3 is unavailable" >&2
    exit 1
}
if ! "$PYTHON_BIN" -c 'import yaml' 2>/dev/null; then
    echo "[ntfy_listener] PyYAML is unavailable" >&2
    exit 1
fi

mkdir -p "$(dirname "$INBOX")" || exit 1
if [ ! -f "$INBOX" ]; then
    printf '%s\n' "inbox:" > "$INBOX" || exit 1
fi

AUTH_ARGS=()
while IFS= read -r line; do
    [ -n "$line" ] && AUTH_ARGS+=("$line")
done < <(ntfy_get_auth_args "$SCRIPT_DIR/config/ntfy_auth.env")

parse_json() {
    local field="$1"
    "$PYTHON_BIN" -c "import sys,json; value=json.load(sys.stdin).get('$field',''); print(value if value is not None else '')" 2>/dev/null
}

parse_tags() {
    "$PYTHON_BIN" -c "import sys,json; print(','.join(json.load(sys.stdin).get('tags',[])))" 2>/dev/null
}

append_ntfy_inbox() {
    local msg_id="$1"
    local ts="$2"
    local msg="$3"

    (
        if command -v flock >/dev/null 2>&1; then
            flock -w 5 200 || exit 1
        else
            _lock_dir="${LOCKFILE}.d"
            _attempt=0
            while ! mkdir "$_lock_dir" 2>/dev/null; do
                sleep 0.1
                _attempt=$((_attempt + 1))
                [ "$_attempt" -ge 50 ] && exit 1
            done
            trap 'rmdir "$_lock_dir" 2>/dev/null || true' EXIT
        fi
        NTFY_INBOX_PATH="$INBOX" \
        NTFY_CORRUPT_DIR="$CORRUPT_DIR" \
        MSG_ID="$msg_id" \
        MSG_TS="$ts" \
        MSG_TEXT="$msg" \
        "$PYTHON_BIN" - <<'PY'
import datetime
import os
import shutil
import sys
import tempfile
import yaml

path = os.environ["NTFY_INBOX_PATH"]
corrupt_dir = os.environ.get("NTFY_CORRUPT_DIR", "")
entry = {
    "id": os.environ.get("MSG_ID", "") or None,
    "timestamp": os.environ.get("MSG_TS", ""),
    "message": os.environ.get("MSG_TEXT", ""),
    "status": "pending",
}
data = {}
parse_error = False
if os.path.exists(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
        if isinstance(loaded, dict):
            data = loaded
        elif loaded is not None:
            parse_error = True
    except Exception:
        parse_error = True
if parse_error and os.path.exists(path):
    try:
        if corrupt_dir:
            os.makedirs(corrupt_dir, exist_ok=True)
            backup = os.path.join(
                corrupt_dir,
                f"ntfy_inbox_corrupt_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.yaml",
            )
            shutil.copy2(path, backup)
    except Exception:
        pass
    data = {}

items = data.get("inbox")
if not isinstance(items, list):
    items = []
message_id = entry["id"]
if message_id is not None and any(
    isinstance(item, dict) and item.get("id") == message_id for item in items
):
    sys.exit(2)
items.append(entry)
data["inbox"] = items

fd, temporary_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
    os.replace(temporary_path, path)
except Exception as error:
    try:
        os.unlink(temporary_path)
    except OSError:
        pass
    print(f"[ntfy_listener] failed to write inbox: {error}", file=sys.stderr)
    sys.exit(1)
PY
    ) 200>"$LOCKFILE"
}

load_since_cursor() {
    local cursor rc
    cursor="$(ntfy_state_read_since "$STATE_FILE" "$TOPIC")"
    rc=$?
    case "$rc" in
        0) printf '%s' "$cursor" ;;
        2)
            # A rotated topic must not reuse the previous topic's cursor.
            ntfy_state_write "$STATE_FILE" "$TOPIC" "" "$(date +%s)" running || return 1
            printf '%s' "$(date +%s)"
            ;;
        *)
            echo "[ntfy_listener] invalid or corrupt state" >&2
            return 1
            ;;
    esac
}

preflight_subscription() {
    local http_status rc
    [ "${NTFY_SKIP_PREFLIGHT:-0}" = "1" ] && return 0
    http_status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 \
        "${AUTH_ARGS[@]}" "https://ntfy.sh/$TOPIC/json?poll=1")"
    rc=$?
    [ "$rc" -eq 0 ] || return 2
    case "$http_status" in
        2??) return 0 ;;
        401|403) return 1 ;;
        408|425|429|5??) return 2 ;;
        *) return 1 ;;
    esac
}

if ! SINCE_CURSOR="$(load_since_cursor)"; then
    exit 1
fi

echo "[$(date)] [ntfy_listener] started (topic configured; credentials redacted)" >&2

while true; do
    preflight_subscription
    preflight_rc=$?
    if [ "$preflight_rc" -eq 1 ]; then
        echo "[ntfy_listener] subscription rejected; check configuration/authentication" >&2
        exit 1
    elif [ "$preflight_rc" -ne 0 ]; then
        echo "[$(date)] [ntfy_listener] network unavailable; retrying" >&2
        sleep "$RECONNECT_DELAY"
        continue
    fi

    stream_url="https://ntfy.sh/$TOPIC/json"
    [ -n "$SINCE_CURSOR" ] && stream_url="${stream_url}?since=${SINCE_CURSOR}"

    while IFS= read -r line; do
        EVENT="$(printf '%s' "$line" | parse_json event)"
        [ "$EVENT" = "message" ] || continue

        MSG_ID="$(printf '%s' "$line" | parse_json id)"
        SERVER_TIME="$(printf '%s' "$line" | parse_json time)"
        if [ -z "$MSG_ID" ] || ! printf '%s' "$SERVER_TIME" | grep -Eq '^[0-9]+$'; then
            echo "[ntfy_listener] invalid message metadata" >&2
            exit 1
        fi

        TAGS="$(printf '%s' "$line" | parse_tags)"
        if printf '%s' "$TAGS" | grep -Eq '(^|,)outbound(,|$)'; then
            ntfy_state_write "$STATE_FILE" "$TOPIC" "$MSG_ID" "$SERVER_TIME" running || exit 1
            SINCE_CURSOR="$MSG_ID"
            continue
        fi

        MSG="$(printf '%s' "$line" | parse_json message)"
        if [ -z "$MSG" ]; then
            ntfy_state_write "$STATE_FILE" "$TOPIC" "$MSG_ID" "$SERVER_TIME" running || exit 1
            SINCE_CURSOR="$MSG_ID"
            continue
        fi
        TIMESTAMP="$(date "+%Y-%m-%dT%H:%M:%S%:z")"

        append_ntfy_inbox "$MSG_ID" "$TIMESTAMP" "$MSG"
        append_rc=$?
        if [ "$append_rc" -ne 0 ] && [ "$append_rc" -ne 2 ]; then
            echo "[$(date)] [ntfy_listener] inbox append failed" >&2
            # Do not process later messages and advance past a failed append.
            # Reconnect from the last durable cursor instead.
            break
        fi

        ntfy_state_write "$STATE_FILE" "$TOPIC" "$MSG_ID" "$SERVER_TIME" running || exit 1
        SINCE_CURSOR="$MSG_ID"
        if [ "$append_rc" -eq 2 ]; then
            echo "[$(date)] [ntfy_listener] duplicate message skipped" >&2
            continue
        fi

        echo "[$(date)] [ntfy_listener] message stored (body redacted)" >&2
        bash "$SCRIPT_DIR/scripts/inbox_write.sh" shogun \
            "New ntfy message received. Process queue/ntfy_inbox.yaml." \
            ntfy_received ntfy_listener
    done < <(curl -sS --no-buffer "${AUTH_ARGS[@]}" "$stream_url" 2>/dev/null)

    echo "[$(date)] [ntfy_listener] stream ended; reconnecting" >&2
    sleep "$RECONNECT_DELAY"
    if ! SINCE_CURSOR="$(load_since_cursor)"; then
        exit 1
    fi
done

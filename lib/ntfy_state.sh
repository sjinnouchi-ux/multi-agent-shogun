#!/usr/bin/env bash
# Shared ntfy listener cursor/state helpers.
# Topic hashes are SHA-256 of the UTF-8 topic bytes with no trailing newline.

ntfy_topic_hash() {
    local topic="${1:-}"
    printf '%s' "$topic" | sha256sum | awk '{print $1}'
}

_ntfy_state_python() {
    if [ -n "${NTFY_PYTHON:-}" ]; then
        printf '%s\n' "$NTFY_PYTHON"
    elif [ -x "${SCRIPT_DIR:-}/.venv/bin/python3" ]; then
        printf '%s\n' "${SCRIPT_DIR}/.venv/bin/python3"
    else
        command -v python3
    fi
}

# Validate state and print a safe `since` cursor. The topic itself is never stored.
# Exit 2 means the state belongs to a previously rotated topic and must be reset.
ntfy_state_read_since() {
    local state_file="$1"
    local topic="$2"
    local topic_hash python_bin

    [ -f "$state_file" ] || return 0
    topic_hash="$(ntfy_topic_hash "$topic")" || return 1
    python_bin="$(_ntfy_state_python)" || return 1

    NTFY_STATE_PATH="$state_file" NTFY_TOPIC_HASH="$topic_hash" "$python_bin" - <<'PY'
import os
import re
import sys
import yaml

path = os.environ["NTFY_STATE_PATH"]
expected_hash = os.environ["NTFY_TOPIC_HASH"]
try:
    with open(path, "r", encoding="utf-8") as handle:
        state = yaml.safe_load(handle)
except Exception:
    sys.exit(1)

if not isinstance(state, dict) or state.get("version") != 1:
    sys.exit(1)
if state.get("state") not in ("running", "standby"):
    sys.exit(1)
if (os.stat(path).st_mode & 0o777) != 0o600:
    sys.exit(1)
stored_hash = state.get("topic_hash")
if not isinstance(stored_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", stored_hash):
    sys.exit(1)
if stored_hash != expected_hash:
    sys.exit(2)

message_id = state.get("last_message_id")
message_time = state.get("last_message_time")
if message_id is not None:
    if not isinstance(message_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", message_id):
        sys.exit(1)
if message_time is not None and (not isinstance(message_time, int) or message_time < 0):
    sys.exit(1)
if message_id is not None:
    print(message_id)
elif message_time is not None:
    print(message_time)
PY
}

# Atomically save cursor metadata. File mode is always forced to 0600.
ntfy_state_write() {
    local state_file="$1"
    local topic="$2"
    local message_id="${3:-}"
    local message_time="${4:-}"
    local lifecycle_state="${5:-running}"
    local topic_hash python_bin state_dir

    case "$lifecycle_state" in
        running|standby) ;;
        *) return 1 ;;
    esac
    if [ -n "$message_time" ] && ! printf '%s' "$message_time" | grep -Eq '^[0-9]+$'; then
        return 1
    fi

    topic_hash="$(ntfy_topic_hash "$topic")" || return 1
    python_bin="$(_ntfy_state_python)" || return 1
    state_dir="$(dirname "$state_file")"
    mkdir -p "$state_dir" || return 1
    chmod 700 "$state_dir" || return 1

    NTFY_STATE_PATH="$state_file" \
    NTFY_TOPIC_HASH="$topic_hash" \
    NTFY_MESSAGE_ID="$message_id" \
    NTFY_MESSAGE_TIME="$message_time" \
    NTFY_LIFECYCLE_STATE="$lifecycle_state" \
    "$python_bin" - <<'PY'
import datetime
import os
import re
import tempfile
import yaml

path = os.environ["NTFY_STATE_PATH"]
message_id = os.environ.get("NTFY_MESSAGE_ID", "") or None
raw_time = os.environ.get("NTFY_MESSAGE_TIME", "")
message_time = int(raw_time) if raw_time else None
if message_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", message_id):
    raise SystemExit(1)

data = {
    "version": 1,
    "state": os.environ["NTFY_LIFECYCLE_STATE"],
    "topic_hash": os.environ["NTFY_TOPIC_HASH"],
    "last_message_id": message_id,
    "last_message_time": message_time,
    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
directory = os.path.dirname(path)
fd, temporary_path = tempfile.mkstemp(prefix=".ntfy-state-", dir=directory)
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
    os.replace(temporary_path, path)
    os.chmod(path, 0o600)
except Exception:
    try:
        os.unlink(temporary_path)
    except OSError:
        pass
    raise
PY
}

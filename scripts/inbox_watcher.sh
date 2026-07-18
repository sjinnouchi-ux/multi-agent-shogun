#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# inbox_watcher.sh — メールボックス監視＆起動シグナル配信
# Usage: bash scripts/inbox_watcher.sh <agent_id> <pane_target> [cli_type]
# Example: bash scripts/inbox_watcher.sh karo multiagent:0.0 claude
#
# 設計思想:
#   メッセージ本体はファイル（inbox YAML）に書く = 確実
#   起動シグナルは tmux send-keys（テキストとEnterを分離送信）
#   エージェントが自分でinboxをReadして処理する
#   冪等: 2回届いてもunreadがなければ何もしない
#
# inotifywait でファイル変更を検知（イベント駆動、ポーリングではない）
# Fallback 1: 30秒タイムアウト（WSL2 inotify不発時の安全網）
# Fallback 2: rc=1処理（Claude Code atomic write = tmp+rename でinode変更時）
#
# エスカレーション（未読メッセージが放置されている場合）:
#   0〜2分: 通常nudge（send-keys）。ただしWorking中はスキップ
#   2〜4分: Copilot/Kimi は Escape×2 + Ctrl-C + nudge。
#            Claude/Codex/OpenCode は通常nudgeへフォールバック
#   4分〜 : /clear送信（5分に1回まで。強制リセット+YAML再読）
# ═══════════════════════════════════════════════════════════════

# ─── Testing guard ───
# When __INBOX_WATCHER_TESTING__=1, only function definitions are loaded.
# Argument parsing, inotifywait check, and main loop are skipped.
# Test code sets variables (AGENT_ID, PANE_TARGET, CLI_TYPE, INBOX) externally.
if [ "${__INBOX_WATCHER_TESTING__:-}" != "1" ]; then
    set -euo pipefail

    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    AGENT_ID="$1"
    PANE_TARGET="$2"
    CLI_TYPE="${3:-claude}"  # CLI種別（claude/codex/copilot/kimi/opencode/antigravity）。未指定→claude（後方互換）
    case "$CLI_TYPE" in
        gemini|agy) CLI_TYPE="antigravity" ;;
    esac

    INBOX="$SCRIPT_DIR/queue/inbox/${AGENT_ID}.yaml"
    LOCKFILE="${INBOX}.lock"

    if [ -z "$AGENT_ID" ] || [ -z "$PANE_TARGET" ]; then
        echo "Usage: inbox_watcher.sh <agent_id> <pane_target> [cli_type]" >&2
        exit 1
    fi

    # Initialize inbox if not exists
    if [ ! -f "$INBOX" ]; then
        mkdir -p "$(dirname "$INBOX")"
        echo "messages: []" > "$INBOX"
    fi

    echo "[$(date)] inbox_watcher started — agent: $AGENT_ID, pane: $PANE_TARGET, cli: $CLI_TYPE" >&2

    # Fix: CLI starts at welcome screen = idle. Create idle flag so watcher
    # doesn't false-busy deadlock waiting for a stop_hook that never fires.
    if [[ "$CLI_TYPE" == "claude" ]]; then
        touch "${IDLE_FLAG_DIR:-/tmp}/shogun_idle_${AGENT_ID}"
        echo "[$(date)] Created initial idle flag for $AGENT_ID (CLI starts idle)" >&2
    fi

    # Source cli_adapter for get_startup_prompt() (Codex needs startup prompt after /new)
    _cli_adapter="${SCRIPT_DIR}/lib/cli_adapter.sh"
    if [ -f "$_cli_adapter" ]; then
        source "$_cli_adapter"
        echo "[$(date)] cli_adapter.sh loaded (get_startup_prompt available)" >&2
    fi

    # Source shared agent status library (busy/idle detection)
    _agent_status_lib="${SCRIPT_DIR}/lib/agent_status.sh"
    if [ -f "$_agent_status_lib" ]; then
        source "$_agent_status_lib"
    fi

    # Detect OS and select file-watching backend
    INBOX_WATCHER_OS="$(uname -s)"
    if [ "$INBOX_WATCHER_OS" = "Darwin" ]; then
        # macOS: use fswatch instead of inotifywait
        if ! command -v fswatch &>/dev/null; then
            echo "[inbox_watcher] ERROR: fswatch not found. Install: brew install fswatch" >&2
            exit 1
        fi
        WATCH_BACKEND="fswatch"
        if ! command -v gtimeout &>/dev/null; then
            echo "[inbox_watcher] WARN: gtimeout not found. Using sleep-based fallback (higher CPU). Recommended: brew install coreutils" >&2
        fi
    else
        # Linux: use inotifywait
        if ! command -v inotifywait &>/dev/null; then
            echo "[inbox_watcher] ERROR: inotifywait not found. Install: sudo apt install inotify-tools" >&2
            exit 1
        fi
        WATCH_BACKEND="inotifywait"
    fi
    echo "[$(date)] File watch backend: $WATCH_BACKEND" >&2
fi

# ─── timeout command compatibility wrapper (macOS support) ───
if ! command -v timeout &>/dev/null; then
  if command -v gtimeout &>/dev/null; then
    timeout() { gtimeout "$@"; }
  else
    # Pure bash fallback: timeout DURATION COMMAND [ARGS...]
    timeout() {
      local duration="$1"; shift
      "$@" &
      local pid=$!
      ( sleep "$duration" && kill "$pid" 2>/dev/null ) &
      local watcher=$!
      wait "$pid" 2>/dev/null
      local rc=$?
      kill "$watcher" 2>/dev/null
      wait "$watcher" 2>/dev/null
      return $rc
    }
  fi
fi

# ─── Escalation state ───
# Time-based escalation: track how long unread messages have been waiting
FIRST_UNREAD_SEEN=${FIRST_UNREAD_SEEN:-0}
LAST_CLEAR_TS=${LAST_CLEAR_TS:-0}
ESCALATE_PHASE1=${ESCALATE_PHASE1:-120}
ESCALATE_PHASE2=${ESCALATE_PHASE2:-240}
ESCALATE_COOLDOWN=${ESCALATE_COOLDOWN:-300}

# ─── Nudge throttle ───
# Avoid spamming the same "inboxN" into the pane every timeout tick.
LAST_NUDGE_TS=${LAST_NUDGE_TS:-0}
LAST_NUDGE_COUNT=${LAST_NUDGE_COUNT:-""}
NUDGE_COOLDOWN_SEC=${NUDGE_COOLDOWN_SEC:-60}
# Codex は「思考中に入力が入ると即拾う」挙動があり、思考がループすることがあるため長めにする。
NUDGE_COOLDOWN_SEC_CODEX=${NUDGE_COOLDOWN_SEC_CODEX:-300}

reset_nudge_throttle() {
    LAST_NUDGE_TS=0
    LAST_NUDGE_COUNT=""
}

acquire_inbox_lock() {
    local lock_dir="${LOCKFILE}.d"
    local i=0

    while ! mkdir "$lock_dir" 2>/dev/null; do
        sleep 0.1
        i=$((i + 1))
        [ "$i" -ge 300 ] && return 1
    done

    if command -v flock &>/dev/null; then
        flock -x 200 || {
            rmdir "$lock_dir" 2>/dev/null
            return 1
        }
    fi
}

release_inbox_lock() {
    rmdir "${LOCKFILE}.d" 2>/dev/null || true
}

handoff_watchdog_active() {
    [ "${HANDOFF_WATCHDOG_ENABLED:-1}" = "1" ] \
        && [ -f "${SCRIPT_DIR}/scripts/handoff_watchdog.py" ]
}

reconcile_handoff_watchdog() {
    local can_notify="${1:-1}"
    local cli_state_at_notify="${2:-unknown}"
    local delivery_blocked_reason="${3:-none}"
    local record_notification="${4:-1}"
    local helper="${SCRIPT_DIR}/scripts/handoff_watchdog.py"

    if ! handoff_watchdog_active; then
        echo '{"action":"none","escalate":false,"state":"disabled","unread_count":0}'
        return 0
    fi

    (
        if ! acquire_inbox_lock; then
            echo '{"action":"none","escalate":false,"state":"lock_unavailable","unread_count":0}'
            exit 0
        fi
        trap release_inbox_lock EXIT
        "$SCRIPT_DIR/.venv/bin/python3" "$helper" \
            --inbox "$INBOX" \
            --agent "$AGENT_ID" \
            --status-file "$HANDOFF_STATUS_FILE" \
            --task-file "$HANDOFF_TASK_FILE" \
            --report-file "$HANDOFF_REPORT_FILE" \
            --retry-after "$HANDOFF_RETRY_AFTER" \
            --stall-after "$HANDOFF_STALL_AFTER" \
            --task-retry-after "$HANDOFF_TASK_RETRY_AFTER" \
            --task-stall-after "$HANDOFF_TASK_STALL_AFTER" \
            --can-notify "$can_notify" \
            --cli-state-at-notify "$cli_state_at_notify" \
            --delivery-blocked-reason "$delivery_blocked_reason" \
            --record-notification "$record_notification" \
            2>/dev/null || echo '{"action":"none","escalate":false,"state":"error","unread_count":0}'
    ) 200>"$LOCKFILE"
}

watchdog_tracks_assigned_task() {
    handoff_watchdog_active || return 1
    [ -f "$HANDOFF_TASK_FILE" ] || return 1
    TASK_PATH="$HANDOFF_TASK_FILE" "$SCRIPT_DIR/.venv/bin/python3" - <<'PY' 2>/dev/null
import os
import sys
import yaml

with open(os.environ["TASK_PATH"], encoding="utf-8") as handle:
    raw = yaml.safe_load(handle) or {}
task = raw.get("task") or raw
sys.exit(0 if isinstance(task, dict) and task.get("status") == "assigned" else 1)
PY
}

watchdog_escalate() {
    local state="${1:-handoff_stalled}"
    local target=""

    case "$AGENT_ID" in
        ashigaru*|gunshi|oometsuke) target="karo" ;;
        *)
            # Do not inject input into Shogun. Karo/Shogun stalls remain a
            # read-only management-terminal projection.
            echo "[$(date)] [WATCHDOG] $AGENT_ID state=$state; status projection updated" >&2
            return 0
            ;;
    esac

    local message="handoff watchdog: ${AGENT_ID} が ${state}。status/handoff_watchdog/${AGENT_ID}.yaml を確認されたし。"
    if bash "$SCRIPT_DIR/scripts/inbox_write.sh" "$target" "$message" watchdog_alert handoff_watchdog; then
        echo "[$(date)] [WATCHDOG] Escalated $AGENT_ID state=$state to $target" >&2
    else
        echo "[$(date)] [WATCHDOG] WARNING: escalation write failed for $AGENT_ID" >&2
    fi
}

send_task_resume() {
    DELIVERY_NOTIFY_RESULT="not_sent"
    if ! delivery_liveness_gate task_resume; then
        return 1
    fi
    if [ "$AGENT_ID" != "shogun" ] && agent_is_busy; then
        DELIVERY_BLOCKED_REASON="busy"
        echo "[$(date)] [SKIP] Agent $AGENT_ID is busy, deferring task-resume notification" >&2
        return 1
    fi

    local effective_cli
    effective_cli=$(get_effective_cli_type)
    local prompt="handoff watchdog: queue/tasks/${AGENT_ID}.yaml の assigned 任務を再開し、完了時に状態と報告を更新せよ。"

    echo "[$(date)] [WATCHDOG] Sending one task-resume notification to $AGENT_ID" >&2
    if [[ "$effective_cli" == "codex" ]]; then
        timeout 5 tmux send-keys -t "$PANE_TARGET" "x" 2>/dev/null || true
        sleep 0.3
        timeout 5 tmux send-keys -t "$PANE_TARGET" C-u 2>/dev/null || true
        sleep 0.3
    fi
    if ! timeout 5 tmux send-keys -l -t "$PANE_TARGET" "$prompt" 2>/dev/null; then
        echo "[$(date)] [WATCHDOG] WARNING: task-resume prompt send failed for $AGENT_ID" >&2
        return 1
    fi
    sleep 0.3
    if ! timeout 5 tmux send-keys -t "$PANE_TARGET" Enter 2>/dev/null; then
        echo "[$(date)] [WATCHDOG] WARNING: task-resume Enter send failed for $AGENT_ID" >&2
        return 1
    fi
    DELIVERY_NOTIFY_RESULT="sent"
}

# ─── Context reset tracking ───
# Tracks whether we've sent /new or /clear for the current task_assigned batch.
# Resets to 0 when all messages are read (FIRST_UNREAD_SEEN → 0).
NEW_CONTEXT_SENT=${NEW_CONTEXT_SENT:-0}
# Tracks whether we sent a startup prompt (Codex) that includes full recovery.
# When set, skip follow-up nudge for this cycle (agent already knows what to do).
STARTUP_PROMPT_SENT=${STARTUP_PROMPT_SENT:-0}

# ─── Phase feature flags (cmd_107 Phase 1/2/3) ───
# ASW_PHASE:
#   1 = self-watch base (compatible)
#   2 = disable normal nudge by default
#   3 = FINAL_ESCALATION_ONLY (send-keys is fallback only)
ASW_PHASE=${ASW_PHASE:-2}
ASW_DISABLE_NORMAL_NUDGE=${ASW_DISABLE_NORMAL_NUDGE:-$([ "${ASW_PHASE}" -ge 2 ] && echo 1 || echo 0)}
ASW_FINAL_ESCALATION_ONLY=${ASW_FINAL_ESCALATION_ONLY:-$([ "${ASW_PHASE}" -ge 3 ] && echo 1 || echo 0)}
FINAL_ESCALATION_ONLY=${FINAL_ESCALATION_ONLY:-$ASW_FINAL_ESCALATION_ONLY}
ASW_NO_IDLE_FULL_READ=${ASW_NO_IDLE_FULL_READ:-1}
# Optional safety toggles:
# - ASW_DISABLE_ESCALATION=1: disable phase2/phase3 escalation actions
# - ASW_PROCESS_TIMEOUT=0: do not process unread on timeout ticks (event-only)
ASW_DISABLE_ESCALATION=${ASW_DISABLE_ESCALATION:-0}
ASW_PROCESS_TIMEOUT=${ASW_PROCESS_TIMEOUT:-1}

# Persistent handoff watchdog. It reuses the existing watcher safety tick and
# never starts an LLM polling loop.
HANDOFF_WATCHDOG_ENABLED=${HANDOFF_WATCHDOG_ENABLED:-1}
HANDOFF_RETRY_AFTER=${HANDOFF_RETRY_AFTER:-120}
HANDOFF_STALL_AFTER=${HANDOFF_STALL_AFTER:-300}
HANDOFF_TASK_RETRY_AFTER=${HANDOFF_TASK_RETRY_AFTER:-300}
HANDOFF_TASK_STALL_AFTER=${HANDOFF_TASK_STALL_AFTER:-600}
HANDOFF_STATUS_FILE=${HANDOFF_STATUS_FILE:-${SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}/status/handoff_watchdog/${AGENT_ID:-unknown}.yaml}
HANDOFF_TASK_FILE=${HANDOFF_TASK_FILE:-${SCRIPT_DIR}/queue/tasks/${AGENT_ID}.yaml}
HANDOFF_REPORT_FILE=${HANDOFF_REPORT_FILE:-${SCRIPT_DIR}/queue/reports/${AGENT_ID}_report.yaml}

# ─── Metrics hooks (FR-006 / NFR-003) ───
# unread_latency_sec / read_count / estimated_tokens are intentionally explicit
READ_COUNT=${READ_COUNT:-0}
READ_BYTES_TOTAL=${READ_BYTES_TOTAL:-0}
ESTIMATED_TOKENS_TOTAL=${ESTIMATED_TOKENS_TOTAL:-0}
METRICS_FILE=${METRICS_FILE:-${SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}/queue/metrics/${AGENT_ID:-unknown}_selfwatch.yaml}

update_metrics() {
    local bytes_read="${1:-0}"
    local now
    now=$(date +%s)

    READ_COUNT=$((READ_COUNT + 1))
    READ_BYTES_TOTAL=$((READ_BYTES_TOTAL + bytes_read))
    ESTIMATED_TOKENS_TOTAL=$((ESTIMATED_TOKENS_TOTAL + ((bytes_read + 3) / 4)))

    local unread_latency_sec=0
    if [ "$FIRST_UNREAD_SEEN" -gt 0 ] 2>/dev/null; then
        unread_latency_sec=$((now - FIRST_UNREAD_SEEN))
    fi

    mkdir -p "$(dirname "$METRICS_FILE")" 2>/dev/null || true
    cat > "$METRICS_FILE" <<EOF
agent_id: "${AGENT_ID:-unknown}"
timestamp: "$(date '+%Y-%m-%dT%H:%M:%S%z')"
unread_latency_sec: $unread_latency_sec
read_count: $READ_COUNT
bytes_read: $READ_BYTES_TOTAL
estimated_tokens: $ESTIMATED_TOKENS_TOTAL
EOF
}

disable_normal_nudge() {
    # Phase 2+: suppress nudge ONLY when agent is busy.
    # If agent is idle, nudge is needed (stop hook won't fire for idle agents).
    if [ "${ASW_DISABLE_NORMAL_NUDGE:-0}" != "1" ]; then
        return 1  # Phase 1: never suppress
    fi
    # Phase 2+: check if agent is idle via flag file
    if [ -f "${IDLE_FLAG_DIR:-/tmp}/shogun_idle_${AGENT_ID}" ]; then
        return 1  # Agent is IDLE → don't suppress, send nudge
    fi
    return 0  # Agent is BUSY → suppress, stop hook will deliver
}

should_throttle_nudge() {
    local unread_count="${1:-0}"
    local now
    now=$(date +%s)

    local effective_cli
    effective_cli=$(get_effective_cli_type)

    local cooldown_sec="${NUDGE_COOLDOWN_SEC:-60}"
    if [[ "$effective_cli" == "codex" ]]; then
        cooldown_sec="${NUDGE_COOLDOWN_SEC_CODEX:-300}"
    elif [[ "$effective_cli" == "claude" ]]; then
        # Claude Code: same cooldown as default (60s).
        # Stop hook is supplementary, not primary — nudge immediately.
        cooldown_sec="${NUDGE_COOLDOWN_SEC_CLAUDE:-60}"
    fi

    # Standard throttle: skip if same count within cooldown window.
    if [ "${LAST_NUDGE_COUNT:-}" = "$unread_count" ] && [ "${LAST_NUDGE_TS:-0}" -gt 0 ]; then
        local age=$((now - LAST_NUDGE_TS))
        if [ "$age" -lt "${cooldown_sec}" ]; then
            echo "[$(date)] [SKIP] Throttling nudge for $AGENT_ID: inbox${unread_count} (${age}s < ${cooldown_sec}s, cli=$effective_cli)" >&2
            return 0
        fi
    fi

    LAST_NUDGE_COUNT="$unread_count"
    LAST_NUDGE_TS="$now"
    return 1
}

is_valid_cli_type() {
    case "${1:-}" in
        claude|codex|copilot|kimi|opencode|antigravity|gemini|agy) return 0 ;;
        *) return 1 ;;
    esac
}

normalize_watcher_cli_type() {
    case "${1:-}" in
        gemini|agy) echo "antigravity" ;;
        *) echo "${1:-}" ;;
    esac
}

get_effective_cli_type() {
    local pane_cli_raw=""
    local pane_cli=""

    pane_cli_raw=$(timeout 2 tmux show-options -p -t "$PANE_TARGET" -v @agent_cli 2>/dev/null || true)
    pane_cli=$(echo "$pane_cli_raw" | tr -d '\r' | head -n1 | tr -d '[:space:]')

    if is_valid_cli_type "$pane_cli"; then
        pane_cli=$(normalize_watcher_cli_type "$pane_cli")
        local arg_cli
        arg_cli=$(normalize_watcher_cli_type "${CLI_TYPE:-}")
        if is_valid_cli_type "${CLI_TYPE:-}" && [ "$pane_cli" != "$arg_cli" ]; then
            echo "[$(date)] [WARN] CLI drift detected for $AGENT_ID: arg=${CLI_TYPE}, pane=${pane_cli}. Using pane value." >&2
        fi
        echo "$pane_cli"
        return 0
    fi

    if is_valid_cli_type "${CLI_TYPE:-}"; then
        if [ -n "$pane_cli" ]; then
            echo "[$(date)] [WARN] Invalid pane @agent_cli for $AGENT_ID: '${pane_cli}'. Falling back to arg=${CLI_TYPE}." >&2
        fi
        normalize_watcher_cli_type "${CLI_TYPE}"
        return 0
    fi

    # Fail-closed: when CLI is unknown, take codex-safe path (no C-c, /clear->/new)
    echo "[$(date)] [WARN] CLI unresolved for $AGENT_ID (pane='${pane_cli:-<empty>}', arg='${CLI_TYPE:-<empty>}'). Fallback=codex-safe." >&2
    echo "codex"
}

# ─── CLI liveness gate ───
# This gate is deliberately separate from agent_is_busy()/agent_is_busy_check().
# ready and busy both mean that the expected CLI is alive; the existing busy/idle
# logic remains responsible for deciding whether an alive CLI may be notified.
CLI_STATE_AT_NOTIFY=${CLI_STATE_AT_NOTIFY:-unknown}
DELIVERY_BLOCKED_REASON=${DELIVERY_BLOCKED_REASON:-}
DELIVERY_NOTIFY_RESULT=${DELIVERY_NOTIFY_RESULT:-not_sent}

get_delivery_cli_state() {
    local effective_cli=""
    local state="unknown"

    effective_cli=$(get_effective_cli_type)
    if type get_pane_cli_state &>/dev/null; then
        state=$(get_pane_cli_state "$PANE_TARGET" "$effective_cli")
    fi
    case "$state" in
        ready|busy|permission_prompt|login_prompt|shell_prompt|absent|unknown)
            printf '%s\n' "$state"
            ;;
        *)
            printf '%s\n' unknown
            ;;
    esac
}

delivery_liveness_gate() {
    local entry="${1:-delivery}"
    local state="unknown"
    local agent_label="${AGENT_ID:-unknown}"

    state=$(get_delivery_cli_state)
    CLI_STATE_AT_NOTIFY="$state"
    DELIVERY_BLOCKED_REASON=""

    case "$state" in
        ready|busy)
            return 0
            ;;
    esac

    DELIVERY_BLOCKED_REASON="$state"
    case "$entry" in
        task_resume|cli_command|startup_prompt|context_reset|wakeup|escape_wakeup|idle_input_cleanup|delivery) ;;
        *) entry="delivery" ;;
    esac
    if ! [[ "$agent_label" =~ ^[a-zA-Z0-9_.-]+$ ]]; then
        agent_label="unknown"
    fi
    echo "[$(date)] [DELIVERY-BLOCKED] agent=$agent_label entry=$entry cli_state=$state" >&2
    return 1
}

normalize_special_command() {
    local msg_type="${1:-}"
    local raw_content="${2:-}"

    case "$msg_type" in
        clear_command)
            echo "/clear"
            ;;
        model_switch)
            if [[ "$raw_content" =~ ^/model[[:space:]]+[^[:space:]].* ]]; then
                echo "$raw_content"
            else
                echo "[$(date)] [SKIP] Invalid model_switch payload for $AGENT_ID: ${raw_content:-<empty>}" >&2
            fi
            ;;
        cli_restart)
            # cli_restart is handled externally by switch_cli.sh, not via send_cli_command.
            # Emit a marker so the main loop can call switch_cli.sh.
            echo "__CLI_RESTART__:${raw_content}"
            ;;
    esac
}

clear_alert_now_epoch() {
    date +%s
}

clear_drop_state() {
    local action="${1:-list}"
    local message_id="${2:-}"
    local cli_state="${3:-unknown}"
    local reason="${4:-unknown}"
    local now_epoch
    now_epoch=$(clear_alert_now_epoch)

    (
        if ! acquire_inbox_lock; then
            return 1
        fi
        trap release_inbox_lock EXIT
        CLEAR_DROP_ACTION="$action" \
        CLEAR_DROP_MESSAGE_ID="$message_id" \
        CLEAR_DROP_CLI_STATE="$cli_state" \
        CLEAR_DROP_REASON="$reason" \
        CLEAR_DROP_NOW_EPOCH="$now_epoch" \
        INBOX_PATH="$INBOX" \
        "$SCRIPT_DIR/.venv/bin/python3" - <<'PY'
import datetime
import os
import sys
import yaml

path = os.environ["INBOX_PATH"]
action = os.environ["CLEAR_DROP_ACTION"]
message_id = os.environ.get("CLEAR_DROP_MESSAGE_ID", "")
cli_state = os.environ.get("CLEAR_DROP_CLI_STATE", "unknown")
reason = os.environ.get("CLEAR_DROP_REASON", "unknown")
try:
    now_epoch = int(os.environ.get("CLEAR_DROP_NOW_EPOCH", "0"))
except (TypeError, ValueError):
    now_epoch = 0
max_attempts = 3
backoff_base = 30
lease_seconds = 30
delivery_lease_seconds = 60
with open(path, encoding="utf-8") as handle:
    data = yaml.safe_load(handle) or {}
messages = data.get("messages") or []

def timestamp():
    return datetime.datetime.fromtimestamp(
        now_epoch, datetime.timezone.utc
    ).isoformat()

def save():
    tmp_path = f"{path}.tmp.{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(
            data,
            handle,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
    os.replace(tmp_path, path)

if action == "list":
    changed = False
    for message in messages:
        if not isinstance(message, dict) or message.get("type") != "clear_command":
            continue
        delivery = message.get("delivery") or {}
        attempts = int(delivery.get("clear_drop_alert_attempts") or 0)
        if not delivery.get("clear_drop_alert_pending"):
            continue
        status = str(delivery.get("clear_drop_alert_status") or "pending")
        lease_until = int(delivery.get("clear_drop_alert_lease_until") or 0)
        if status == "sending" and lease_until > now_epoch:
            continue
        if status != "sending" and attempts >= max_attempts:
            delivery["clear_drop_alert_pending"] = False
            delivery["clear_drop_alert_status"] = "exhausted"
            delivery.setdefault("clear_drop_alert_exhausted_at", timestamp())
            message["delivery"] = delivery
            changed = True
            continue
        next_at = int(delivery.get("clear_drop_alert_next_at") or 0)
        if next_at <= now_epoch:
            values = (
                str(message.get("id") or ""),
                str(message.get("from") or ""),
                str(delivery.get("delivery_blocked_reason") or "unknown"),
            )
            print("\t".join(value.replace("\t", " ").replace("\n", " ") for value in values))
    if changed:
        save()
    raise SystemExit(0)

if action == "recover":
    changed = False
    for message in messages:
        if not isinstance(message, dict) or message.get("type") != "clear_command":
            continue
        delivery = message.get("delivery") or {}
        if not delivery.get("clear_delivery_pending"):
            continue
        delivery_lease_until = int(delivery.get("clear_delivery_lease_until") or 0)
        if delivery_lease_until > now_epoch:
            continue
        message["read"] = True
        delivery["clear_delivery_pending"] = False
        delivery.pop("clear_delivery_lease_until", None)
        delivery["delivery_blocked_reason"] = "delivery_interrupted"
        delivery["clear_drop_alert_pending"] = True
        delivery["clear_drop_alert_attempts"] = 0
        delivery["clear_drop_alert_status"] = "pending"
        delivery["clear_drop_alert_next_at"] = now_epoch
        delivery.pop("clear_drop_alert_lease_until", None)
        delivery["clear_delivery_recovered_at"] = timestamp()
        message["delivery"] = delivery
        changed = True
    if changed:
        save()
    raise SystemExit(0)

matches = [
    item
    for item in messages
    if isinstance(item, dict)
    and item.get("type") == "clear_command"
    and str(item.get("id") or "") == message_id
]
if len(matches) != 1 and action == "claim":
    print("not_found")
    raise SystemExit(0)
if len(matches) != 1:
    raise SystemExit(1)
message = matches[0]

delivery = message.setdefault("delivery", {})
if action in ("record", "record_claimed"):
    if action == "record" and message.get("read"):
        delivery_lease_until = int(delivery.get("clear_delivery_lease_until") or 0)
        if delivery.get("clear_delivery_pending") and delivery_lease_until > now_epoch:
            print("already_claimed")
            raise SystemExit(0)
        blocked_reason = delivery.get("delivery_blocked_reason")
        alert_status = str(delivery.get("clear_drop_alert_status") or "")
        terminal_metadata = (
            bool(delivery.get("clear_delivered_at"))
            or blocked_reason not in (None, "", "none")
            or alert_status in ("pending", "retry_wait", "sending", "sent", "exhausted")
        )
        if terminal_metadata:
            print("terminal")
            raise SystemExit(0)
    if action == "record_claimed" and not delivery.get("clear_delivery_pending"):
        print("terminal")
        raise SystemExit(0)
    message["read"] = True
    delivery["clear_delivery_pending"] = False
    delivery.pop("clear_delivery_lease_until", None)
    delivery["cli_state_at_notify"] = cli_state
    delivery["delivery_blocked_reason"] = reason
    delivery["clear_drop_alert_pending"] = True
    delivery["clear_drop_alert_attempts"] = 0
    delivery["clear_drop_alert_status"] = "pending"
    delivery["clear_drop_alert_next_at"] = now_epoch
    delivery.pop("clear_drop_alert_lease_until", None)
    save()
    print("recorded")
    raise SystemExit(0)
elif action == "claim":
    if message.get("read"):
        if delivery.get("clear_delivery_pending"):
            print("already_claimed")
            raise SystemExit(0)
        blocked_reason = delivery.get("delivery_blocked_reason")
        alert_status = str(delivery.get("clear_drop_alert_status") or "")
        terminal_metadata = (
            bool(delivery.get("clear_delivered_at"))
            or blocked_reason not in (None, "", "none")
            or alert_status in ("pending", "retry_wait", "sending", "sent", "exhausted")
        )
        if terminal_metadata:
            print("terminal")
            raise SystemExit(0)
    message["read"] = True
    delivery["cli_state_at_notify"] = cli_state
    delivery["delivery_blocked_reason"] = None
    delivery["clear_delivery_pending"] = True
    delivery["clear_delivery_lease_until"] = now_epoch + delivery_lease_seconds
    delivery["clear_delivery_claimed_at"] = timestamp()
    delivery["clear_drop_alert_pending"] = False
    save()
    print("claimed")
    raise SystemExit(0)
elif action == "delivered":
    if not delivery.get("clear_delivery_pending"):
        raise SystemExit(1)
    message["read"] = True
    delivery["clear_delivery_pending"] = False
    delivery.pop("clear_delivery_lease_until", None)
    delivery["delivery_blocked_reason"] = None
    delivery["clear_delivered_at"] = timestamp()
elif action == "reserve":
    attempts = int(delivery.get("clear_drop_alert_attempts") or 0)
    next_at = int(delivery.get("clear_drop_alert_next_at") or 0)
    status = str(delivery.get("clear_drop_alert_status") or "pending")
    lease_until = int(delivery.get("clear_drop_alert_lease_until") or 0)
    if not delivery.get("clear_drop_alert_pending"):
        raise SystemExit(1)
    if status == "sending":
        if lease_until > now_epoch or attempts < 1:
            raise SystemExit(1)
    else:
        if attempts >= max_attempts or next_at > now_epoch:
            raise SystemExit(1)
        attempts += 1
    delivery["clear_drop_alert_attempts"] = attempts
    delivery["clear_drop_alert_status"] = "sending"
    delivery["clear_drop_alert_last_attempt_at"] = timestamp()
    delivery["clear_drop_alert_lease_until"] = now_epoch + lease_seconds
    print(attempts)
elif action == "retry":
    attempts = int(delivery.get("clear_drop_alert_attempts") or 0)
    if not delivery.get("clear_drop_alert_pending") or attempts < 1:
        raise SystemExit(1)
    if attempts >= max_attempts:
        delivery["clear_drop_alert_pending"] = False
        delivery["clear_drop_alert_status"] = "exhausted"
        delivery["clear_drop_alert_exhausted_at"] = timestamp()
    else:
        delay = min(300, backoff_base * (2 ** (attempts - 1)))
        delivery["clear_drop_alert_status"] = "retry_wait"
        delivery["clear_drop_alert_next_at"] = now_epoch + delay
    delivery.pop("clear_drop_alert_lease_until", None)
elif action == "sent":
    delivery["clear_drop_alert_pending"] = False
    delivery["clear_drop_alert_status"] = "sent"
    delivery["clear_drop_alerted_at"] = timestamp()
    delivery.pop("clear_drop_alert_lease_until", None)
else:
    raise SystemExit(1)

save()
PY
    ) 200>"$LOCKFILE"
}

write_clear_drop_alert() {
    local target="${1:-}"
    local reason="${2:-unknown}"
    local message_id="${3:-}"
    local safe_agent="${AGENT_ID:-unknown}"

    if ! [[ "$target" =~ ^[a-zA-Z0-9_.-]+$ ]] || [ "$target" = "$safe_agent" ]; then
        return 1
    fi
    if ! [[ "$safe_agent" =~ ^[a-zA-Z0-9_.-]+$ ]]; then
        safe_agent="unknown"
    fi
    case "$reason" in
        busy|permission_prompt|login_prompt|shell_prompt|absent|unknown|protected_pane|send_failed|delivery_interrupted|state_persist_failed) ;;
        *) reason="unknown" ;;
    esac

    local alert_ref
    alert_ref=$("$SCRIPT_DIR/.venv/bin/python3" - "$safe_agent" "$message_id" <<'PY'
import hashlib
import sys
print(hashlib.sha256(f"{sys.argv[1]}:{sys.argv[2]}".encode()).hexdigest()[:12])
PY
    ) || return 1
    local target_inbox="${SCRIPT_DIR}/queue/inbox/${target}.yaml"
    [ -f "$target_inbox" ] || return 1

    local alert="clear_command dropped: agent=${safe_agent} reason=${reason} ref=${alert_ref}; issue a new clear_command if still required."
    INBOX_WRITE_DEDUP_REF="$alert_ref" \
        bash "$SCRIPT_DIR/scripts/inbox_write.sh" "$target" "$alert" watchdog_alert handoff_watchdog
}

flush_clear_drop_alerts() {
    local pending=""
    pending=$(clear_drop_state list 2>/dev/null) || return 0
    [ -n "$pending" ] || return 0

    local message_id source_agent reason attempt
    while IFS=$'\t' read -r message_id source_agent reason; do
        [ -n "$message_id" ] || continue
        case "$reason" in
            busy|permission_prompt|login_prompt|shell_prompt|absent|unknown|protected_pane|send_failed|delivery_interrupted|state_persist_failed) ;;
            *) reason="unknown" ;;
        esac
        attempt=$(clear_drop_state reserve "$message_id" 2>/dev/null) || continue
        if write_clear_drop_alert "$source_agent" "$reason" "$message_id"; then
            clear_drop_state sent "$message_id" >/dev/null 2>&1 || true
            echo "[$(date)] [CLEAR-DROP-ALERT] agent=${AGENT_ID:-unknown} reason=$reason source=$source_agent" >&2
        else
            clear_drop_state retry "$message_id" >/dev/null 2>&1 || true
            if [ "${attempt:-0}" -ge 3 ] 2>/dev/null; then
                echo "[$(date)] [CLEAR-DROP-ALERT-EXHAUSTED] agent=${AGENT_ID:-unknown} reason=$reason attempts=${attempt:-0}" >&2
            else
                echo "[$(date)] [CLEAR-DROP-ALERT-PENDING] agent=${AGENT_ID:-unknown} reason=$reason attempt=${attempt:-0}" >&2
            fi
        fi
    done <<< "$pending"
}

clear_drop_quarantine_ref() {
    local message_id="${1:-}"
    [ -n "$message_id" ] || return 1
    "$SCRIPT_DIR/.venv/bin/python3" - "${AGENT_ID:-unknown}" "$message_id" <<'PY'
import hashlib
import sys

print(hashlib.sha256(f"{sys.argv[1]}:{sys.argv[2]}".encode()).hexdigest())
PY
}

quarantine_clear_command() {
    local message_id="${1:-}"
    local quarantine_ref quarantine_dir
    quarantine_ref=$(clear_drop_quarantine_ref "$message_id") || return 1
    quarantine_dir="${CLEAR_DROP_QUARANTINE_DIR:-${SCRIPT_DIR}/status/clear_drop_quarantine}"
    CLEAR_DROP_QUARANTINE_DIR="$quarantine_dir" \
    CLEAR_DROP_QUARANTINE_REF="$quarantine_ref" \
        "$SCRIPT_DIR/.venv/bin/python3" - <<'PY'
import os
import tempfile

directory = os.environ["CLEAR_DROP_QUARANTINE_DIR"]
reference = os.environ["CLEAR_DROP_QUARANTINE_REF"]
os.makedirs(directory, exist_ok=True)
fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".clear_drop_", suffix=".tmp")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("schema_version: 1\nreason: state_persist_failed\n")
    os.replace(tmp_path, os.path.join(directory, f"{reference}.yaml"))
except BaseException:
    try:
        os.unlink(tmp_path)
    except FileNotFoundError:
        pass
    raise
PY
}

is_clear_command_quarantined() {
    local message_id="${1:-}"
    local quarantine_ref quarantine_dir
    quarantine_ref=$(clear_drop_quarantine_ref "$message_id") || return 1
    quarantine_dir="${CLEAR_DROP_QUARANTINE_DIR:-${SCRIPT_DIR}/status/clear_drop_quarantine}"
    [ -f "${quarantine_dir}/${quarantine_ref}.yaml" ]
}

drop_clear_command() {
    local message_id="${1:-}"
    local source_agent="${2:-}"
    local cli_state="${3:-unknown}"
    local reason="${4:-unknown}"
    local claimed_by_caller="${5:-0}"
    local record_action="record"
    local record_result="error"

    [ "$claimed_by_caller" = "1" ] && record_action="record_claimed"
    record_result=$(clear_drop_state "$record_action" "$message_id" "$cli_state" "$reason" 2>/dev/null) || record_result="error"
    case "$record_result" in
        recorded)
            echo "[$(date)] [CLEAR-DROP] agent=${AGENT_ID:-unknown} cli_state=$cli_state reason=$reason" >&2
            flush_clear_drop_alerts
            return 0
            ;;
        already_claimed|terminal)
            echo "[$(date)] [CLEAR-DROP-SKIP] agent=${AGENT_ID:-unknown} result=$record_result" >&2
            return 0
            ;;
    esac

    if quarantine_clear_command "$message_id"; then
        echo "[$(date)] [CLEAR-DROP-QUARANTINED] agent=${AGENT_ID:-unknown} reason=state_persist_failed" >&2
        write_clear_drop_alert "$source_agent" state_persist_failed "$message_id" || true
        return 0
    fi

    echo "[$(date)] [CLEAR-DROP-QUARANTINE-FAILED] agent=${AGENT_ID:-unknown} reason=state_persist_failed" >&2
    write_clear_drop_alert "$source_agent" state_persist_failed "$message_id" || true
    return 1
}

enqueue_recovery_task_assigned() {
    (
        # acquire_inbox_lock also takes flock when available.
        if ! acquire_inbox_lock; then
            echo "ERROR"
            exit 0
        fi
        trap release_inbox_lock EXIT
        INBOX_PATH="$INBOX" AGENT_ID="$AGENT_ID" "$SCRIPT_DIR/.venv/bin/python3" - << 'PY'
import datetime
import os
import re
import uuid
import yaml

inbox = os.environ.get("INBOX_PATH", "")
agent_id = os.environ.get("AGENT_ID", "agent")

try:
    with open(inbox, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    messages = data.get("messages", []) or []

    # Task YAML status and identity guard: skip auto-recovery if task is
    # cancelled/idle and bind new recovery hints to the current formal epoch.
    # This prevents restarting a task that Karo intentionally cancelled via clear_command.
    task_yaml_path = os.path.join(
        os.path.dirname(os.path.dirname(inbox)), "tasks", f"{agent_id}.yaml"
    )
    current_cmd = ""
    current_task_id = ""
    if os.path.exists(task_yaml_path):
        try:
            with open(task_yaml_path, "r", encoding="utf-8") as tf:
                task_data = yaml.safe_load(tf) or {}
            nested_task = task_data.get("task")
            if isinstance(nested_task, dict):
                task_data = nested_task
            task_status = str(task_data.get("status") or "").strip().strip("'\"")
            current_cmd = str(task_data.get("cmd") or "")
            current_task_id = str(task_data.get("task_id") or "")
            if task_status in ("cancelled", "idle"):
                print(f"SKIP_CANCELLED:{task_status}")
                raise SystemExit(0)
        except SystemExit:
            raise
        except Exception:
            pass  # If task YAML is unreadable, proceed with auto-recovery as safety net

    current_formal = False
    if current_cmd:
        valid_cmd = re.fullmatch(r"cmd_[A-Za-z0-9][A-Za-z0-9._:-]*", current_cmd)
        valid_task_id = re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", current_task_id)
        if not valid_cmd or not valid_task_id:
            print("SKIP_INVALID_IDENTITY")
            raise SystemExit(0)
        current_formal = True
    else:
        # Preserve legacy format by omitting both fields. A task_id without a
        # cmd must not become a newly generated partial formal identity.
        current_task_id = ""

    # A formal current task is deduplicated only by its exact identity. A
    # legacy pending hint must not suppress recovery for a newer formal task.
    for m in reversed(messages):
        if not (
            m.get("from") == "inbox_watcher"
            and m.get("type") == "task_assigned"
            and m.get("read", False) is False
            and "[auto-recovery]" in (m.get("content") or "")
        ):
            continue
        existing_cmd = str(m.get("cmd") or "")
        existing_task_id = str(m.get("task_id") or "")
        if not current_formal:
            print("SKIP_DUPLICATE")
            raise SystemExit(0)
        if existing_cmd and existing_cmd == current_cmd and existing_task_id == current_task_id:
            print("SKIP_DUPLICATE")
            raise SystemExit(0)

    now = datetime.datetime.now(datetime.timezone.utc).astimezone()
    # Persona re-establishment on /clear is handled by SessionStart hook
    # (scripts/session_start_hook.sh, matcher=clear). Auto-recovery message only
    # ensures task resumption after the /clear inbox nudge is consumed.
    msg = {
        "content": (
            f"[auto-recovery] /clear 後の再着手通知。"
            f"queue/tasks/{agent_id}.yaml を再読し、assigned タスクを即時再開せよ。"
        ),
        "from": "inbox_watcher",
        "id": f"msg_auto_recovery_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
        "read": False,
        "timestamp": now.replace(microsecond=0).isoformat(),
        "type": "task_assigned",
    }
    if current_formal:
        msg["cmd"] = current_cmd
        msg["task_id"] = current_task_id
    messages.append(msg)
    data["messages"] = messages

    tmp_path = f"{inbox}.tmp.{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
    os.replace(tmp_path, inbox)
    print(msg["id"])
except Exception:
    # Best-effort safety net only. Primary /clear delivery must not fail here.
    print("ERROR")
PY
    ) 200>"$LOCKFILE" 2>/dev/null
}

no_idle_full_read() {
    local trigger="${1:-timeout}"
    [ "${ASW_NO_IDLE_FULL_READ:-1}" = "1" ] || return 1
    [ "$trigger" = "timeout" ] || return 1
    [ "${FIRST_UNREAD_SEEN:-0}" -eq 0 ] || return 1
    return 0
}

# summary-first: unread_count fast-path before full read
get_unread_count_fast() {
    INBOX_PATH="$INBOX" "$SCRIPT_DIR/.venv/bin/python3" - << 'PY'
import json
import os
import yaml

inbox = os.environ.get("INBOX_PATH", "")
try:
    with open(inbox, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    messages = data.get("messages", []) or []
    unread_count = sum(1 for m in messages if not m.get("read", False))
    print(json.dumps({"count": unread_count}))
except Exception:
    print(json.dumps({"count": 0}))
PY
}

# ─── Extract unread message info ───
# Returns JSON lines: {"count": N, "has_special": true/false, "specials": [...]}
# Test anchor for bats awk pattern: get_unread_info\\(\\)
get_unread_info() {
    (
        # acquire_inbox_lock also takes flock when available.
        if ! acquire_inbox_lock; then
            echo '{"count": 0, "specials": []}'
            exit 0
        fi
        trap release_inbox_lock EXIT
        INBOX_PATH="$INBOX" "$SCRIPT_DIR/.venv/bin/python3" - << 'PY'
import json
import os
import uuid
import yaml

inbox = os.environ.get("INBOX_PATH", "")
try:
    with open(inbox, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    messages = data.get("messages", []) or []
    unread = [m for m in messages if not m.get("read", False)]
    special_types = ("clear_command", "model_switch", "cli_restart")
    specials = [m for m in unread if m.get("type") in special_types]

    if specials:
        id_counts = {}
        for message in messages:
            message_id = str(message.get("id") or "")
            if message_id:
                id_counts[message_id] = id_counts.get(message_id, 0) + 1
        duplicate_ids = {
            message_id for message_id, count in id_counts.items() if count > 1
        }
        known_ids = set(id_counts)
        changed = False
        for m in specials:
            message_id = str(m.get("id") or "")
            if not message_id or message_id in duplicate_ids:
                while True:
                    replacement = f"msg_legacy_{uuid.uuid4().hex}"
                    if replacement not in known_ids:
                        break
                m["id"] = replacement
                known_ids.add(replacement)
                changed = True
            if m.get("type") != "clear_command" and not m.get("read", False):
                m["read"] = True
                changed = True

        if changed:
            tmp_path = f"{inbox}.tmp.{os.getpid()}"
            with open(tmp_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(
                    data,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )
            os.replace(tmp_path, inbox)

    normal_count = len(unread) - len(specials)
    normal_msgs = [m for m in unread if m.get("type") not in special_types]
    has_task_assigned = any(m.get("type") == "task_assigned" for m in normal_msgs)
    payload = {
        "count": normal_count,
        "has_task_assigned": has_task_assigned,
        "specials": [
            {
                "id": m.get("id", ""),
                "from": m.get("from", ""),
                "type": m.get("type", ""),
                "cmd": m.get("cmd", ""),
                "task_id": m.get("task_id", ""),
                "content": m.get("content", ""),
            }
            for m in specials
        ],
    }
    print(json.dumps(payload))
except Exception:
    print(json.dumps({"count": 0, "specials": []}))
PY
    ) 200>"$LOCKFILE" 2>/dev/null
}

# Compare a special command against the current task identity. Only a legacy
# current task follows the compatibility path; formal tasks require an exact
# cmd + task_id match.
clear_command_epoch_state() {
    local message_cmd="${1:-}"
    local message_task_id="${2:-}"
    local task_file
    task_file="$(dirname "$(dirname "$INBOX")")/tasks/${AGENT_ID}.yaml"

    if [ ! -f "$SCRIPT_DIR/scripts/cmd_epoch.py" ]; then
        printf 'invalid\n'
        return 0
    fi

    local state
    state=$("$SCRIPT_DIR/.venv/bin/python3" \
        "$SCRIPT_DIR/scripts/cmd_epoch.py" compare \
        --task-file "$task_file" --cmd "$message_cmd" \
        --task-id "$message_task_id" 2>/dev/null) || state="invalid"
    case "$state" in
        match|stale|legacy|invalid) printf '%s\n' "$state" ;;
        *) printf 'invalid\n' ;;
    esac
    return 0
}

# ─── Send CLI command via pty direct write ───
# For /clear and /model only. These are CLI commands, not conversation messages.
# CLI_TYPE別分岐: claude→そのまま, codex→/clear対応・/modelスキップ,
#                  copilot→Ctrl-C+再起動・/modelスキップ, opencode→/clear→/new・/modelスキップ,
#                  antigravity→/clearそのまま・/modelスキップ
# 実行時にtmux paneの @agent_cli を再確認し、ドリフト時はpane値を優先する。
send_required_cli_key() {
    if ! timeout 5 tmux send-keys -t "$PANE_TARGET" "$@" 2>/dev/null; then
        DELIVERY_BLOCKED_REASON="send_failed"
        echo "[$(date)] WARNING: required clear_command key delivery failed for ${AGENT_ID:-unknown}" >&2
        return 1
    fi
}

send_cli_command() {
    local cmd="$1"

    if ! delivery_liveness_gate cli_command; then
        return 1
    fi
    if [[ "$cmd" == "/clear" && "$CLI_STATE_AT_NOTIFY" != "ready" ]]; then
        DELIVERY_BLOCKED_REASON="$CLI_STATE_AT_NOTIFY"
        echo "[$(date)] [CLEAR-DROP-FINAL-GATE] agent=${AGENT_ID:-unknown} cli_state=$CLI_STATE_AT_NOTIFY" >&2
        return 1
    fi

    local effective_cli
    effective_cli=$(get_effective_cli_type)

    # cli_restart: delegate to switch_cli.sh (full /exit → relaunch cycle)
    if [[ "$cmd" == __CLI_RESTART__:* ]]; then
        local restart_args="${cmd#__CLI_RESTART__:}"
        echo "[$(date)] [CLI-RESTART] Delegating to switch_cli.sh for $AGENT_ID: ${restart_args}" >&2
        bash "${SCRIPT_DIR}/scripts/switch_cli.sh" "$AGENT_ID" $restart_args 2>&1 | while IFS= read -r line; do  # SCRIPT_DIR=project_root
            echo "[$(date)] [switch_cli] $line" >&2
        done
        # Update effective CLI type after restart
        CLI_TYPE=$(tmux show-options -p -t "$PANE_TARGET" -v @agent_cli 2>/dev/null || echo "$CLI_TYPE")
        return 0
    fi

    # Safety: never inject CLI commands into the shogun pane.
    # Shogun is controlled by the Lord; keystroke injection can clobber human input.
    if [ "$AGENT_ID" = "shogun" ]; then
        DELIVERY_BLOCKED_REASON="protected_pane"
        echo "[$(date)] [SKIP] shogun: suppressing CLI command injection ($cmd)" >&2
        return 1
    fi

    # Busy guard: never send /clear when agent is actively processing.
    # clear_command inbox processor also checks busy, but this is a defense-in-depth guard.
    # Sending /clear during Working destroys in-progress context and causes data loss.
    # OpenCode startup can leave capture-pane blank before the first frame renders,
    # so only apply this guard after we can actually observe pane text.
    local pane_snapshot=""
    if [[ "$cmd" == "/clear" ]]; then
        pane_snapshot=$(timeout 2 tmux capture-pane -t "$PANE_TARGET" -p 2>/dev/null || true)
    fi
    if [[ "$cmd" == "/clear" ]] && ! [[ "$effective_cli" == "opencode" && -z "${pane_snapshot//[[:space:]]/}" ]] && agent_is_busy; then
        DELIVERY_BLOCKED_REASON="busy"
        echo "[$(date)] [SKIP] Agent is busy — /clear cannot be delivered (agent=$AGENT_ID)" >&2
        return 1
    fi

    # CLI別コマンド変換
    local actual_cmd="$cmd"
    case "$effective_cli" in
        codex)
            # Codex: /clear不存在→/newで新規会話開始, /model非対応→スキップ
            # /clearはCodexでは未定義コマンドでCLI終了してしまうため、/newに変換
            if [[ "$cmd" == "/clear" ]]; then
                # Guard: skip duplicate /new if already sent for this batch
                if [ "${NEW_CONTEXT_SENT:-0}" -eq 1 ]; then
                    echo "[$(date)] [SKIP] Codex /new already sent for $AGENT_ID — skipping duplicate clear_command" >&2
                    return 0
                fi
                echo "[$(date)] [SEND-KEYS] Codex /clear→/new: starting new conversation for $AGENT_ID" >&2
                # Dismiss suggestion UI first (typing "x" clears autocomplete prompt)
                timeout 5 tmux send-keys -t "$PANE_TARGET" "x" 2>/dev/null || true
                sleep 0.3
                timeout 5 tmux send-keys -t "$PANE_TARGET" C-u 2>/dev/null || true
                sleep 0.3
                send_required_cli_key "/new" || return 1
                sleep 0.3
                send_required_cli_key Enter || return 1
                sleep 3
                # Send startup prompt immediately (don't defer to context-reset cycle)
                send_startup_prompt || true
                NEW_CONTEXT_SENT=1
                return 0
            fi
            if [[ "$cmd" == /model* ]]; then
                echo "[$(date)] Skipping $cmd (not supported on codex)" >&2
                return 0
            fi
            ;;
        opencode)
            # OpenCode: /clear is normalized to /new, /model changes are restart-only.
            if [[ "$cmd" == "/clear" ]]; then
                if [ "${NEW_CONTEXT_SENT:-0}" -eq 1 ]; then
                    echo "[$(date)] [SKIP] OpenCode /new already sent for $AGENT_ID — skipping duplicate clear_command" >&2
                    return 0
                fi
                echo "[$(date)] [SEND-KEYS] OpenCode /new for clear_command: starting new conversation for $AGENT_ID" >&2
                timeout 5 tmux send-keys -t "$PANE_TARGET" C-u 2>/dev/null || true
                sleep 0.3
                send_required_cli_key "/new" || return 1
                sleep 0.3
                send_required_cli_key Enter || return 1
                sleep 3
                NEW_CONTEXT_SENT=1
                return 0
             fi
            if [[ "$cmd" == /model* ]]; then
                echo "[$(date)] Skipping $cmd (OpenCode model changes are restart-only)" >&2
                return 0
            fi
            ;;
        copilot)
            # Copilot: /clearはCtrl-C+再起動, /model非対応→スキップ
            if [[ "$cmd" == "/clear" ]]; then
                echo "[$(date)] [SEND-KEYS] Copilot /clear: sending Ctrl-C + restart for $AGENT_ID" >&2
                send_required_cli_key C-c || return 1
                sleep 2
                send_required_cli_key "copilot --yolo" || return 1
                sleep 0.3
                send_required_cli_key Enter || return 1
                sleep 3
                return 0
            fi
            if [[ "$cmd" == /model* ]]; then
                echo "[$(date)] Skipping $cmd (not supported on copilot)" >&2
                return 0
            fi
            ;;
        cursor)
            # Cursor: /clear不存在→/new-chatで新規会話開始, /modelは対応
            if [[ "$cmd" == "/clear" ]]; then
                if [ "${NEW_CONTEXT_SENT:-0}" -eq 1 ]; then
                    echo "[$(date)] [SKIP] Cursor /new-chat already sent for $AGENT_ID — skipping duplicate clear_command" >&2
                    return 0
                fi
                echo "[$(date)] [SEND-KEYS] Cursor /clear→/new-chat: starting new conversation for $AGENT_ID" >&2
                send_required_cli_key "/new-chat" || return 1
                sleep 0.3
                send_required_cli_key Enter || return 1
                sleep 3
                NEW_CONTEXT_SENT=1
                return 0
            fi
            ;;
        antigravity)
            if [[ "$cmd" == /model* ]]; then
                echo "[$(date)] Skipping $cmd (Antigravity model changes are restart-only)" >&2
                return 0
            fi
            ;;
        # claude: commands pass through as-is
    esac

    echo "[$(date)] [SEND-KEYS] Sending CLI command to $AGENT_ID ($effective_cli): $actual_cmd" >&2
    # Clear stale input first, then send command (text and Enter separated for Codex TUI)
    # Codex CLI: C-c when idle causes CLI to exit — skip it
    if [[ "$effective_cli" != "codex" ]]; then
        timeout 5 tmux send-keys -t "$PANE_TARGET" C-c 2>/dev/null || true
        sleep 0.5
    fi
    if [[ "$cmd" == "/clear" ]]; then
        send_required_cli_key "$actual_cmd" || return 1
    else
        timeout 5 tmux send-keys -t "$PANE_TARGET" "$actual_cmd" 2>/dev/null || true
    fi
    # /clear needs longer gap before Enter — CLI prompt may not be ready at 0.3s
    if [[ "$actual_cmd" == "/clear" || "$actual_cmd" == "/new" ]]; then
        sleep 1.0
    else
        sleep 0.3
    fi
    if [[ "$cmd" == "/clear" ]]; then
        send_required_cli_key Enter || return 1
    else
        timeout 5 tmux send-keys -t "$PANE_TARGET" Enter 2>/dev/null || true
    fi

    # /clear needs extra wait time before follow-up
    if [[ "$actual_cmd" == "/clear" ]]; then
        LAST_CLEAR_TS=$(date +%s)
        sleep 3
        # Claude: send startup prompt so agent re-runs Session Start after /clear
        if [[ "$effective_cli" == "claude" ]]; then
            send_startup_prompt || true
        fi
    else
        sleep 1
    fi
}

# ─── Send startup prompt after context reset ───
# Waits for agent to become idle, then sends a startup prompt that includes
# full recovery steps (identify, read task YAML, read inbox, start work).
# Codex uses a typed `x` to dismiss its suggestion UI.
# Called from both send_cli_command (clear_command) and send_context_reset.
send_startup_prompt() {
    if ! delivery_liveness_gate startup_prompt; then
        return 1
    fi

    # Poll until agent becomes idle (prompt ready) instead of fixed sleep.
    # Max 15s (3 attempts × 5s). If still busy after 15s, proceed anyway.
    local attempt
    for attempt in 1 2 3; do
        sleep 5
        if ! agent_is_busy; then
            echo "[$(date)] [STARTUP] $AGENT_ID idle after ${attempt}×5s — sending startup prompt" >&2
            break
        fi
        echo "[$(date)] [STARTUP] $AGENT_ID still busy after ${attempt}×5s — retrying" >&2
    done
    if agent_is_busy; then
        echo "[$(date)] [STARTUP] $AGENT_ID still busy after 15s — proceeding with startup prompt anyway" >&2
    fi

    # The pane can transition to a blocked/login/shell state while polling.
    if ! delivery_liveness_gate startup_prompt; then
        return 1
    fi

    local startup_prompt=""
    if type get_startup_prompt &>/dev/null; then
        startup_prompt=$(get_startup_prompt "$AGENT_ID" 2>/dev/null || true)
    fi
    if [[ -z "$startup_prompt" ]]; then
        startup_prompt="Session Start — do ALL of this in one turn, do NOT stop early: 1) tmux display-message to identify yourself. 2) Read queue/tasks/${AGENT_ID}.yaml. 3) Read queue/inbox/${AGENT_ID}.yaml, mark read:true. 4) Read context_files. 5) Execute the assigned task to completion — edit files, run commands, write reports. Keep working until done."
    fi
    local effective_cli
    effective_cli=$(get_effective_cli_type)
    echo "[$(date)] [STARTUP] Sending startup prompt to $AGENT_ID (${effective_cli}): ${startup_prompt:0:80}..." >&2
    # Dismiss suggestion UI, then send startup prompt
    if [[ "$effective_cli" != "opencode" ]]; then
        timeout 5 tmux send-keys -t "$PANE_TARGET" "x" 2>/dev/null || true
        sleep 0.3
        timeout 5 tmux send-keys -t "$PANE_TARGET" C-u 2>/dev/null || true
        sleep 0.3
    fi
    timeout 5 tmux send-keys -l -t "$PANE_TARGET" "$startup_prompt" 2>/dev/null || true
    sleep 0.3
    timeout 5 tmux send-keys -t "$PANE_TARGET" Enter 2>/dev/null || true
    STARTUP_PROMPT_SENT=1
}

# ─── Send context reset before new task ───
# Called when task_assigned is detected in unread messages.
# Sends the appropriate "new conversation" command per CLI type to clear
# stale context from the previous task.
# CLI mapping: claude→/clear, codex→/new, opencode→/new, cursor→/new-chat, copilot→/clear, kimi→/clear
# CLI mapping: claude→/clear, codex→/new, opencode→/new, copilot→/clear, kimi→/clear, antigravity→/clear

send_context_reset() {
    local effective_cli
    effective_cli=$(get_effective_cli_type)

    # Safety: never auto-reset context for command-layer agents.
    # Only ashigaru should receive automatic context resets (clear stale task context).
    # Shogun, Karo, Gunshi, and Oometsuke maintain complex review/coordinator
    # context that must not be wiped automatically.
    if [ "$AGENT_ID" = "shogun" ] || [ "$AGENT_ID" = "karo" ] || [ "$AGENT_ID" = "gunshi" ] || [ "$AGENT_ID" = "oometsuke" ]; then
        echo "[$(date)] [SKIP] $AGENT_ID: suppressing context reset (command-layer agent)" >&2
        return 0
    fi

    if ! delivery_liveness_gate context_reset; then
        return 1
    fi

    local reset_cmd
    case "$effective_cli" in
        codex)    reset_cmd="/new" ;;
        opencode) reset_cmd="/new" ;;
        cursor)   reset_cmd="/new-chat" ;;
        claude)   reset_cmd="/clear" ;;
        copilot)  reset_cmd="/clear" ;;
        kimi)     reset_cmd="/clear" ;;
        antigravity) reset_cmd="/clear" ;;
        *)        reset_cmd="/new" ;;  # safe default (codex-safe)
    esac

    echo "[$(date)] [CONTEXT-RESET] Sending $reset_cmd before task_assigned for $AGENT_ID ($effective_cli)" >&2

    # Codex/OpenCode/Cursor: send new-context command as a single atomic operation.
    # When called from clear_command path, NEW_CONTEXT_SENT=1 prevents reaching here.
    # When called for standalone task_assigned, this is the only send.
    if [[ "$effective_cli" == "codex" || "$effective_cli" == "opencode" || "$effective_cli" == "cursor" ]]; then
        # Dismiss suggestion UI (Codex only) + send reset command
        if [[ "$effective_cli" == "codex" ]]; then
            timeout 5 tmux send-keys -t "$PANE_TARGET" "x" 2>/dev/null || true
            sleep 0.3
        fi
        if [[ "$effective_cli" != "cursor" ]]; then
            timeout 5 tmux send-keys -t "$PANE_TARGET" C-u 2>/dev/null || true
            sleep 0.3
        fi
        timeout 5 tmux send-keys -t "$PANE_TARGET" "$reset_cmd" 2>/dev/null || true
        sleep 0.3
        timeout 5 tmux send-keys -t "$PANE_TARGET" Enter 2>/dev/null || true
        sleep 3
        # Codex: send startup prompt (agent has no auto-loaded instructions).
        # OpenCode: skip — agent definition is auto-loaded via --agent flag.
        if [[ "$effective_cli" == "codex" ]]; then
            send_startup_prompt || true
        fi
        return 0
    fi

    # Non-Codex CLIs: send /clear and wait for idle
    # Send the command (text and Enter separated for TUI compatibility)
    timeout 5 tmux send-keys -t "$PANE_TARGET" "$reset_cmd" 2>/dev/null || true
    # Longer gap for /clear — CLI prompt rendering needs time
    sleep 1.0
    timeout 5 tmux send-keys -t "$PANE_TARGET" Enter 2>/dev/null || true
    # Mark /clear timestamp so agent_is_busy() treats it as busy during processing
    if [[ "$reset_cmd" == "/clear" ]]; then
        LAST_CLEAR_TS=$(date +%s)
    fi

    # Poll until agent becomes idle (prompt ready) instead of fixed sleep.
    # Max 15s (3 attempts × 5s). If still busy after 15s, proceed anyway.
    local attempt
    for attempt in 1 2 3; do
        sleep 5
        if ! agent_is_busy; then
            echo "[$(date)] [CONTEXT-RESET] $AGENT_ID idle after ${attempt}×5s — ready for nudge" >&2
            break
        fi
        echo "[$(date)] [CONTEXT-RESET] $AGENT_ID still busy after ${attempt}×5s — retrying" >&2
    done
    if agent_is_busy; then
        echo "[$(date)] [CONTEXT-RESET] $AGENT_ID still busy after 15s — proceeding anyway" >&2
    fi
}

# ─── Agent self-watch detection ───
# Check if the agent has an active inotifywait on its inbox.
# If yes, the agent will self-wake — no nudge needed.
agent_has_self_watch() {
    # Codex/Copilot/Kimi/OpenCode CLIs cannot run self-watch. Only Claude Code agents can.
    local effective_cli
    effective_cli=$(get_effective_cli_type)
    if [[ "$effective_cli" != "claude" ]]; then
        return 1  # non-Claude CLIs never have self-watch
    fi
    # For Claude Code agents: check if an inotifywait exists that is NOT
    # a child of this inbox_watcher process (exclude our own watcher).
    local my_pgid
    my_pgid=$(ps -o pgid= -p $$ 2>/dev/null | tr -d ' ')
    local found=1  # default: not found
    while IFS= read -r pid; do
        local pid_pgid
        pid_pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')
        if [[ "$pid_pgid" != "$my_pgid" ]]; then
            found=0  # found an inotifywait NOT from our process group
            break
        fi
    done < <(pgrep -f "inotifywait.*inbox/${AGENT_ID}.yaml" 2>/dev/null)
    return $found
}

# ─── Agent busy detection ───
# Check if the agent's CLI is currently processing (Working/thinking/etc).
# Sending nudge during Working causes text to queue but Enter to be lost.
# Returns 0 (true) if agent is busy, 1 if idle.
# Implementation: delegates to lib/agent_status.sh (shared library).
agent_is_busy() {
    # /clear cooldown: treat agent as busy for 30s after /clear was sent.
    # Claude Code's /clear takes 10-30s (CLAUDE.md reload + context init).
    # Without this, nudges sent during /clear processing queue up at the prompt
    # and cause race conditions (inbox1 arrives before /clear completes).
    local now_busy
    now_busy=$(date +%s)
    if [ "${LAST_CLEAR_TS:-0}" -gt 0 ] && [ "$((now_busy - LAST_CLEAR_TS))" -lt 30 ]; then
        return 0  # busy — /clear still processing
    fi

    local effective_cli
    effective_cli=$(get_effective_cli_type)
    if [[ "$effective_cli" == "claude" ]]; then
        # フラグファイル方式: フラグなし=busy(return 0)、あり=idle(return 1)
        [ ! -f "${IDLE_FLAG_DIR:-/tmp}/shogun_idle_${AGENT_ID}" ]
    else
        # 従来のpane解析（Codex等フォールバック）
        agent_is_busy_check "$PANE_TARGET" "$effective_cli"
    fi
}

# ─── Pane focus detection (human safety) ───
# If the target pane is currently active, avoid injecting keystrokes.
pane_is_active() {
    local active=""
    active=$(timeout 2 tmux display-message -p -t "$PANE_TARGET" '#{pane_active}' 2>/dev/null || true)
    [ "$active" = "1" ]
}

# ─── Session attach detection ───
# Function: session_has_client
# Description: Checks if the tmux session containing PANE_TARGET has at least
#   one client attached. Used to avoid suppressing send-keys when no human is
#   watching (e.g. single-pane shogun session where pane_is_active is always true).
# Arguments: none (uses global PANE_TARGET)
# Returns: 0 if at least one client is attached, 1 otherwise
session_has_client() {
    local session_name
    session_name=$(timeout 2 tmux display-message -p -t "$PANE_TARGET" '#{session_name}' 2>/dev/null || true)
    [ -n "$session_name" ] && [ "$(tmux list-clients -t "$session_name" 2>/dev/null | wc -l)" -gt 0 ]
}

# Clear stale input only when the expected CLI is alive and the existing idle
# checks also permit it. This centralizes the two all-read cleanup call sites.
clear_idle_input() {
    if ! delivery_liveness_gate idle_input_cleanup; then
        return 0
    fi
    if agent_is_busy; then
        return 0
    fi
    if [ "$AGENT_ID" = "shogun" ] && pane_is_active; then
        return 0
    fi
    timeout 2 tmux send-keys -t "$PANE_TARGET" C-u 2>/dev/null || true
}

# ─── Send wake-up nudge ───
# Layered approach:
#   1. If agent has active inotifywait self-watch → skip (agent wakes itself)
#   2. If agent is busy (Working) → skip (nudge during Working loses Enter)
#   3. tmux send-keys (短いnudgeのみ、timeout 5s)
send_wakeup() {
    local unread_count="$1"
    local force="${2:-0}"
    local nudge="inbox${unread_count}"
    DELIVERY_NOTIFY_RESULT="not_sent"

    if ! delivery_liveness_gate wakeup; then
        return 0
    fi

    if [ "${FINAL_ESCALATION_ONLY:-0}" = "1" ]; then
        echo "[$(date)] [SKIP] FINAL_ESCALATION_ONLY=1, suppressing normal nudge for $AGENT_ID" >&2
        return 0
    fi

    # 優先度1: Agent self-watch — nudge不要（エージェントが自分で気づく）
    if agent_has_self_watch; then
        echo "[$(date)] [SKIP] Agent $AGENT_ID has active self-watch, no nudge needed" >&2
        return 0
    fi

    # 優先度2: Agent busy — nudge送信するとEnterが消失するためスキップ
    # Claude Code: Stop hook catches unread at turn end. Skip nudge to avoid Enter loss.
    # Exception: shogun — ntfy must be delivered immediately regardless of busy state.
    if agent_is_busy && [[ "$AGENT_ID" != "shogun" ]]; then
        DELIVERY_BLOCKED_REASON="busy"
        local busy_cli_wakeup
        busy_cli_wakeup=$(get_effective_cli_type)
        if [[ "$busy_cli_wakeup" == "claude" ]]; then
            echo "[$(date)] [SKIP] Agent $AGENT_ID is busy (claude) — Stop hook will deliver, no nudge" >&2
        else
            echo "[$(date)] [SKIP] Agent $AGENT_ID is busy ($busy_cli_wakeup), deferring nudge" >&2
        fi
        return 0
    fi

    if [ "$force" != "1" ] && should_throttle_nudge "$unread_count"; then
        return 0
    fi

    # Shogun: deliver nudge via send-keys like other agents.
    # ntfy messages must reach Claude Code directly.

    # 優先度3: tmux send-keys（テキストとEnterを分離 — Codex TUI対策）
    echo "[$(date)] [SEND-KEYS] Sending nudge to $PANE_TARGET for $AGENT_ID" >&2

    # Codex suggestion UI dismissal: typing any character dismisses the autocomplete
    # suggestion prompt (› Implement {feature} etc.) that traps idle agents.
    # Sequence: "x" (dismiss suggestion) → C-u (clear input) → nudge → Enter
    local effective_cli_for_nudge
    effective_cli_for_nudge=$(get_effective_cli_type)
    if [[ "$effective_cli_for_nudge" == "codex" ]]; then
        timeout 5 tmux send-keys -t "$PANE_TARGET" "x" 2>/dev/null || true
        sleep 0.3
        timeout 5 tmux send-keys -t "$PANE_TARGET" C-u 2>/dev/null || true
        sleep 0.3
    fi

    # 行クリア（残存テキスト除去）→ nudge送信 → Enter → 確認 → 最大2回リトライ
    local max_retries=2
    local attempt=0
    while [ $attempt -le $max_retries ]; do
        # C-u で行をクリア
        timeout 5 tmux send-keys -t "$PANE_TARGET" C-u 2>/dev/null || true
        sleep 0.3
        # nudge 送信
        if ! timeout 5 tmux send-keys -t "$PANE_TARGET" "$nudge" 2>/dev/null; then
            echo "[$(date)] WARNING: send-keys nudge failed for $AGENT_ID (attempt $((attempt+1)))" >&2
            attempt=$((attempt+1))
            continue
        fi
        sleep 0.3
        if ! timeout 5 tmux send-keys -t "$PANE_TARGET" Enter 2>/dev/null; then
            echo "[$(date)] WARNING: send-keys Enter failed for $AGENT_ID (attempt $((attempt+1)))" >&2
            attempt=$((attempt+1))
            continue
        fi
        sleep 0.5
        if [[ "$effective_cli_for_nudge" == "codex" ]]; then
            # Codex echoes submitted text in the transcript; seeing inboxN after
            # Enter does not mean it is still stuck in the input field.
            echo "[$(date)] Wake-up sent to $AGENT_ID (${unread_count} unread, attempt $((attempt+1)), cli=codex)" >&2
            DELIVERY_NOTIFY_RESULT="sent"
            return 0
        fi
        # 送信確認: capture-pane でプロンプトにnudgeテキストが残っていないか確認
        local pane_content
        pane_content=$(timeout 3 tmux capture-pane -t "$PANE_TARGET" -p 2>/dev/null | tail -5 || echo "")
        if echo "$pane_content" | grep -qF "$nudge"; then
            # nudgeテキストが残存 → 送信失敗 → C-u クリアしてリトライ
            echo "[$(date)] WARNING: nudge text still visible in pane, retrying (attempt $((attempt+1)))" >&2
            timeout 5 tmux send-keys -t "$PANE_TARGET" C-u 2>/dev/null || true
            sleep 0.3
            attempt=$((attempt+1))
            continue
        fi
        # 送信成功
        # NOTE: アイドルフラグは削除しない。nudge送信≠エージェント起動確認。
        # フラグを消すと agent_is_busy()=true → 以降のnudge全スキップ → デッドロック。
        # フラグはエージェントが実際に作業開始した時に自然消滅する（stop_hook設計と整合）。
        echo "[$(date)] Wake-up sent to $AGENT_ID (${unread_count} unread, attempt $((attempt+1)))" >&2
        DELIVERY_NOTIFY_RESULT="sent"
        return 0
    done
    echo "[$(date)] WARNING: send-keys failed after $max_retries retries for $AGENT_ID" >&2
    return 0  # Never return 1 — set -euo pipefail would kill the watcher daemon
}

# ─── Send wake-up nudge with Escape prefix ───
# Phase 2 escalation: Copilot/Kimi get Escape×2 + single Ctrl-C + nudge.
# Claude/Codex/OpenCode fall back to a plain nudge.
send_wakeup_with_escape() {
    local unread_count="$1"
    local nudge="inbox${unread_count}"
    DELIVERY_NOTIFY_RESULT="not_sent"

    if ! delivery_liveness_gate escape_wakeup; then
        return 0
    fi

    local effective_cli
    effective_cli=$(get_effective_cli_type)

    # Safety: never send Escape escalation to shogun. It can wipe the Lord's input.
    if [ "$AGENT_ID" = "shogun" ]; then
        echo "[$(date)] [SKIP] shogun: suppressing Escape escalation; sending plain nudge" >&2
        send_wakeup "$unread_count"
        return 0
    fi

    # Codex CLI: ESC は「中断」になりやすく、人間操作中の事故も多い。
    # Phase 2 の Escape エスカレーションは無効化し、通常 nudge のみに落とす。
    if [[ "$effective_cli" == "codex" ]]; then
        echo "[$(date)] [SKIP] codex: suppressing Escape escalation for $AGENT_ID; sending plain nudge" >&2
        send_wakeup "$unread_count"
        return 0
    fi

    # Claude Code: Stop hookがturn終了時にinbox未読を検出→自動処理する。
    # Escape送信は処理中のturnを中断させるため有害。Phase 2は通常nudgeに落とす。
    if [[ "$effective_cli" == "claude" ]]; then
        echo "[$(date)] [SKIP] claude: suppressing Escape escalation for $AGENT_ID (Stop hook handles delivery); sending plain nudge" >&2
        send_wakeup "$unread_count"
        return 0
    fi

    # OpenCode: Escape is bound to session_interrupt in the pinned TUI config.
    # Phase 2 must not interrupt the session; fall back to a plain nudge.
    if [[ "$effective_cli" == "opencode" || "$effective_cli" == "antigravity" ]]; then
        echo "[$(date)] [SKIP] opencode: suppressing Escape escalation for $AGENT_ID (Escape interrupts the session); sending plain nudge" >&2
        send_wakeup "$unread_count"
        return 0
    fi

    if [ "${FINAL_ESCALATION_ONLY:-0}" = "1" ]; then
        echo "[$(date)] [SKIP] FINAL_ESCALATION_ONLY=1, suppressing phase2 nudge for $AGENT_ID" >&2
        return 0
    fi

    if agent_has_self_watch; then
        return 0
    fi

    # Phase 2 still skips if agent is busy — Escape during Working would interrupt
    if agent_is_busy; then
        DELIVERY_BLOCKED_REASON="busy"
        echo "[$(date)] [SKIP] Agent $AGENT_ID is busy (Working), deferring Phase 2 nudge" >&2
        return 0
    fi

    echo "[$(date)] [SEND-KEYS] ESCALATION Phase 2: Escape×2 + nudge for $AGENT_ID (cli=$effective_cli)" >&2
    # Escape×2 to exit any mode
    timeout 5 tmux send-keys -t "$PANE_TARGET" Escape Escape 2>/dev/null || true
    sleep 0.5
    if [[ "$effective_cli" == "copilot" || "$effective_cli" == "kimi" ]]; then
        timeout 5 tmux send-keys -t "$PANE_TARGET" C-c 2>/dev/null || true
        sleep 0.5
    fi
    if timeout 5 tmux send-keys -t "$PANE_TARGET" "$nudge" 2>/dev/null; then
        sleep 0.3
        timeout 5 tmux send-keys -t "$PANE_TARGET" Enter 2>/dev/null || true
        echo "[$(date)] Escape+nudge sent to $AGENT_ID (${unread_count} unread, cli=$effective_cli)" >&2
        DELIVERY_NOTIFY_RESULT="sent"
        return 0
    fi

    echo "[$(date)] WARNING: send-keys failed for Escape+nudge ($AGENT_ID)" >&2
    return 0  # Never return 1 — set -euo pipefail would kill the watcher daemon
}

# ─── Process cycle ───
process_unread() {
    local trigger="${1:-event}"

    # A clear command claimed before a prior watcher interruption is terminal:
    # record an explicit drop and alert, but never replay the command.
    clear_drop_state recover >/dev/null 2>&1 || true

    # Retry only the bounded source alert for an already-dropped clear command.
    # The clear command itself remains read and is never scheduled for delivery again.
    flush_clear_drop_alerts

    # summary-first: unread_count fast-path (Phase 2/3 optimization)
    # unread_count fast-path lets us skip expensive full reads when idle.
    local fast_info
    fast_info=$(get_unread_count_fast)
    local fast_count
    fast_count=$(echo "$fast_info" | "$SCRIPT_DIR/.venv/bin/python3" -c "import sys,json; print(json.load(sys.stdin).get('count',0))" 2>/dev/null)

    if no_idle_full_read "$trigger" \
        && [ "$fast_count" -eq 0 ] 2>/dev/null \
        && ! watchdog_tracks_assigned_task; then
        # no_idle_full_read guard: unread=0 and timeout path → no full inbox read
        if [ "$FIRST_UNREAD_SEEN" -ne 0 ]; then
            echo "[$(date)] All messages read for $AGENT_ID — escalation reset (fast-path)" >&2
        fi
        FIRST_UNREAD_SEEN=0
        NEW_CONTEXT_SENT=0
        reset_nudge_throttle
        # Ensure idle flag exists (fast-path recovery)
        touch "${IDLE_FLAG_DIR:-/tmp}/shogun_idle_${AGENT_ID}" 2>/dev/null || true
        clear_idle_input
        return 0
    fi

    local info
    info=$(get_unread_info)

    local read_bytes=0
    if [ -f "$INBOX" ]; then
        read_bytes=$(wc -c < "$INBOX" 2>/dev/null || echo 0)
    fi
    update_metrics "${read_bytes:-0}"

    # Handle special CLI commands first (/clear, /model)
    local specials
    specials=$(echo "$info" | "$SCRIPT_DIR/.venv/bin/python3" -c "
import sys, json
data = json.load(sys.stdin)
for s in data.get('specials', []):
    i = (s.get('id', '') or '').replace('\t', ' ').replace('\n', ' ').strip()
    f = (s.get('from', '') or '').replace('\t', ' ').replace('\n', ' ').strip()
    t = s.get('type', '')
    e = (s.get('cmd', '') or '').replace('\t', ' ').replace('\n', ' ').strip() or '__legacy__'
    k = (s.get('task_id', '') or '').replace('\t', ' ').replace('\n', ' ').strip() or '__legacy__'
    c = (s.get('content', '') or '').replace('\t', ' ').replace('\n', ' ').strip()
    print(f'{i}\t{f}\t{t}\t{e}\t{k}\t{c}')
" 2>/dev/null)

    local clear_seen=0
    local clear_sent=0  # tracks if /clear was actually sent (not just seen)
    if [ -n "$specials" ]; then
        local msg_id msg_from msg_type msg_cmd msg_task_id msg_content cmd drop_reason claim_result epoch_state
        while IFS=$'\t' read -r msg_id msg_from msg_type msg_cmd msg_task_id msg_content; do
            [ -n "$msg_type" ] || continue
            [ "$msg_cmd" = "__legacy__" ] && msg_cmd=""
            [ "$msg_task_id" = "__legacy__" ] && msg_task_id=""
            if [ "$msg_type" = "clear_command" ]; then
                clear_seen=1
                if is_clear_command_quarantined "$msg_id"; then
                    drop_clear_command "$msg_id" "$msg_from" unknown state_persist_failed || true
                    continue
                fi
                epoch_state=$(clear_command_epoch_state "$msg_cmd" "$msg_task_id")
                case "$epoch_state" in
                    stale)
                        drop_clear_command "$msg_id" "$msg_from" unknown stale_command_epoch || true
                        continue
                        ;;
                    invalid)
                        drop_clear_command "$msg_id" "$msg_from" unknown invalid_command_epoch || true
                        continue
                        ;;
                esac
                if ! delivery_liveness_gate cli_command; then
                    drop_clear_command "$msg_id" "$msg_from" "$CLI_STATE_AT_NOTIFY" "${DELIVERY_BLOCKED_REASON:-unknown}" || true
                    continue
                fi
                if [ "$CLI_STATE_AT_NOTIFY" != "ready" ]; then
                    drop_clear_command "$msg_id" "$msg_from" "$CLI_STATE_AT_NOTIFY" "$CLI_STATE_AT_NOTIFY" || true
                    continue
                fi
                # Existing busy/idle semantics remain authoritative after readiness.
                if agent_is_busy; then
                    drop_clear_command "$msg_id" "$msg_from" "$CLI_STATE_AT_NOTIFY" busy || true
                    continue
                fi
                claim_result=$(clear_drop_state claim "$msg_id" ready none 2>/dev/null) || claim_result="error"
                case "$claim_result" in
                    claimed) ;;
                    already_claimed|terminal|not_found)
                        echo "[$(date)] [CLEAR-CLAIM-SKIP] agent=${AGENT_ID:-unknown} result=$claim_result" >&2
                        continue
                        ;;
                    *)
                        drop_clear_command "$msg_id" "$msg_from" "$CLI_STATE_AT_NOTIFY" state_persist_failed || true
                        continue
                        ;;
                esac
            fi
            cmd=$(normalize_special_command "$msg_type" "$msg_content")
            if [ -n "$cmd" ]; then
                if send_cli_command "$cmd"; then
                    if [ "$msg_type" = "clear_command" ]; then
                        if ! clear_drop_state delivered "$msg_id" >/dev/null 2>&1; then
                            echo "[$(date)] [CLEAR-DELIVERY-COMMIT-PENDING] agent=${AGENT_ID:-unknown}" >&2
                        fi
                        clear_sent=1
                    fi
                elif [ "$msg_type" = "clear_command" ]; then
                    drop_reason="${DELIVERY_BLOCKED_REASON:-send_failed}"
                    [ -n "$drop_reason" ] || drop_reason="send_failed"
                    drop_clear_command "$msg_id" "$msg_from" "${CLI_STATE_AT_NOTIFY:-unknown}" "$drop_reason" 1 || true
                fi
            fi
        done <<< "$specials"
    fi

    # /clear は Codex で /new へ変換される。再起動直後の取りこぼし防止として
    # 追加 task_assigned を自動投入し、次サイクルで確実に wake-up 可能にする。
    # 案B+待機: Karo がタスク YAML を cancelled に更新するまでの猶予を確保してから
    # status チェックを行い、cancelled/idle の場合はスキップする。
    # clear_sent（実際に送信）のみauto-recoveryを起動。busy時スキップは対象外。
    if [ "$clear_sent" -eq 1 ]; then
        # Wait for Karo to update task YAML status (cancellation race condition mitigation).
        # send_cli_command already slept 3s for /clear; add 5s more = ~8s total before check.
        sleep 5
        local recovery_id
        recovery_id=$(enqueue_recovery_task_assigned)
        if [[ "$recovery_id" == SKIP_CANCELLED:* ]]; then
            echo "[$(date)] [AUTO-RECOVERY] skipped for $AGENT_ID — task is ${recovery_id#SKIP_CANCELLED:} (not restarting)" >&2
        elif [ -n "$recovery_id" ] && [ "$recovery_id" != "SKIP_DUPLICATE" ] && [ "$recovery_id" != "ERROR" ]; then
            echo "[$(date)] [AUTO-RECOVERY] queued task_assigned for $AGENT_ID ($recovery_id)" >&2
        fi
        info=$(get_unread_info)
    fi

    # Send wake-up nudge for normal messages (with escalation)
    local normal_count
    normal_count=$(echo "$info" | "$SCRIPT_DIR/.venv/bin/python3" -c "import sys,json; print(json.load(sys.stdin).get('count',0))" 2>/dev/null)

    # Check if unread messages include task_assigned (for context reset)
    local has_task_assigned
    has_task_assigned=$(echo "$info" | "$SCRIPT_DIR/.venv/bin/python3" -c "import sys,json; print(1 if json.load(sys.stdin).get('has_task_assigned') else 0)" 2>/dev/null)

    local watchdog_cli_state watchdog_blocked_reason watchdog_can_notify=1
    watchdog_cli_state=$(get_delivery_cli_state)
    watchdog_blocked_reason="none"
    case "$watchdog_cli_state" in
        ready|busy) ;;
        *)
            watchdog_can_notify=0
            watchdog_blocked_reason="$watchdog_cli_state"
            ;;
    esac
    if [ "$watchdog_can_notify" = "1" ] && [ "$AGENT_ID" != "shogun" ] && agent_is_busy; then
        watchdog_can_notify=0
        watchdog_blocked_reason="busy"
    fi
    local watchdog_info watchdog_action watchdog_escalation watchdog_state
    # Plan first. notification_count/timestamps are committed only after the
    # guarded send entry confirms that it actually emitted a notification.
    watchdog_info=$(reconcile_handoff_watchdog "$watchdog_can_notify" "$watchdog_cli_state" "$watchdog_blocked_reason" 0)
    watchdog_action=$(echo "$watchdog_info" | "$SCRIPT_DIR/.venv/bin/python3" -c "import sys,json; print(json.load(sys.stdin).get('action','none'))" 2>/dev/null || echo none)
    watchdog_escalation=$(echo "$watchdog_info" | "$SCRIPT_DIR/.venv/bin/python3" -c "import sys,json; print(1 if json.load(sys.stdin).get('escalate') else 0)" 2>/dev/null || echo 0)
    watchdog_state=$(echo "$watchdog_info" | "$SCRIPT_DIR/.venv/bin/python3" -c "import sys,json; print(json.load(sys.stdin).get('state','unknown'))" 2>/dev/null || echo unknown)

    if [ "$normal_count" -gt 0 ] 2>/dev/null; then
        local now
        now=$(date +%s)

        # When the agent is busy/thinking, do NOT escalate. Interrupting with Escape or /clear
        # can terminate the current thought. Also pause the escalation timer while busy so we
        # don't immediately jump to Phase 2/3 once it becomes idle.
        # Exception: shogun — ntfy must be delivered immediately.
        # Safety net: if busy detection persists for >5 min, assume false-busy (stale flag)
        # and force-create idle flag to allow nudge delivery.
        if agent_is_busy && [[ "$AGENT_ID" != "shogun" ]]; then
            local busy_cli
            busy_cli=$(get_effective_cli_type)
            # Stale busy safety net: if agent has been "busy" for >5 minutes with
            # unread messages, force-create idle flag. This recovers from false-busy
            # deadlock where stop_hook failed to create the flag.
            local stale_busy_limit=300  # 5 minutes
            if [ "${FIRST_UNREAD_SEEN:-0}" -gt 0 ] && [ "$((now - FIRST_UNREAD_SEEN))" -ge "$stale_busy_limit" ]; then
                echo "[$(date)] WARNING: $AGENT_ID busy for $((now - FIRST_UNREAD_SEEN))s with $normal_count unread — forcing idle flag (stale busy recovery)" >&2
                touch "${IDLE_FLAG_DIR:-/tmp}/shogun_idle_${AGENT_ID}"
                # Fall through to normal nudge/escalation below
            else
                if [[ "$busy_cli" == "claude" ]]; then
                    # Claude Code: Stop hook will catch unread messages when the agent's
                    # turn ends. No nudge needed at all — just log and skip completely.
                    # Set FIRST_UNREAD_SEEN so the stale-busy safety net (above) can
                    # activate if the stop hook never fires.
                    if [ "${FIRST_UNREAD_SEEN:-0}" -eq 0 ]; then
                        FIRST_UNREAD_SEEN=$now
                    fi
                    echo "[$(date)] $normal_count unread for $AGENT_ID but agent is busy (claude) — Stop hook will deliver" >&2
                else
                    # Codex/Copilot/Kimi/OpenCode: No Stop hook. Pause escalation timer while busy.
                    FIRST_UNREAD_SEEN=$now
                    echo "[$(date)] $normal_count unread for $AGENT_ID but agent is busy ($busy_cli) — pausing escalation timer" >&2
                fi
                return 0
            fi
        fi

        # ─── Context reset before new task ───
        # Send /new or /clear once when task_assigned is first detected,
        # to clear stale context from the previous task.
        # Skip if: (1) already sent this batch, (2) clear_command already handled above,
        #          (3) agent is shogun (human-controlled).
        if [ "$has_task_assigned" = "1" ] && [ "$NEW_CONTEXT_SENT" -eq 0 ] && [ "$clear_seen" -eq 0 ]; then
            if send_context_reset; then
                NEW_CONTEXT_SENT=1
            fi
        fi

        # If startup prompt was just sent (Codex), skip follow-up nudge this cycle.
        # The prompt itself contains full recovery instructions (identify + read YAML + work).
        if [ "$STARTUP_PROMPT_SENT" -eq 1 ]; then
            STARTUP_PROMPT_SENT=0
            echo "[$(date)] [SKIP] Startup prompt just sent to $AGENT_ID — skipping nudge this cycle" >&2
            FIRST_UNREAD_SEEN=$now
            return 0
        fi

        # Track when we first saw unread messages
        if [ "$FIRST_UNREAD_SEEN" -eq 0 ]; then
            FIRST_UNREAD_SEEN=$now
        fi

        if handoff_watchdog_active; then
            case "$watchdog_action" in
                notify)
                    send_wakeup "$normal_count"
                    if [ "$DELIVERY_NOTIFY_RESULT" = "sent" ]; then
                        reconcile_handoff_watchdog 1 "$CLI_STATE_AT_NOTIFY" none 1 >/dev/null
                    else
                        reconcile_handoff_watchdog 0 "$CLI_STATE_AT_NOTIFY" "${DELIVERY_BLOCKED_REASON:-none}" 1 >/dev/null
                    fi
                    ;;
                retry)
                    echo "[$(date)] [WATCHDOG] One retry for $AGENT_ID" >&2
                    send_wakeup "$normal_count" 1
                    if [ "$DELIVERY_NOTIFY_RESULT" = "sent" ]; then
                        reconcile_handoff_watchdog 1 "$CLI_STATE_AT_NOTIFY" none 1 >/dev/null
                    else
                        reconcile_handoff_watchdog 0 "$CLI_STATE_AT_NOTIFY" "${DELIVERY_BLOCKED_REASON:-none}" 1 >/dev/null
                    fi
                    ;;
            esac
            if [ "$watchdog_escalation" = "1" ]; then
                watchdog_escalate "$watchdog_state"
            fi
            return 0
        fi

        if [ "${ASW_DISABLE_ESCALATION:-0}" = "1" ]; then
            echo "[$(date)] $normal_count unread for $AGENT_ID (escalation disabled)" >&2
            if disable_normal_nudge; then
                echo "[$(date)] [SKIP] disable_normal_nudge=1, no normal nudge for $AGENT_ID" >&2
            else
                send_wakeup "$normal_count"
            fi
            return 0
        fi

        local age=$((now - FIRST_UNREAD_SEEN))

        if [ "$age" -lt "$ESCALATE_PHASE1" ]; then
            # Phase 1 (0-2 min): Standard nudge
            echo "[$(date)] $normal_count unread for $AGENT_ID (${age}s)" >&2
            if disable_normal_nudge; then
                echo "[$(date)] [SKIP] disable_normal_nudge=1, deferring to escalation-only path" >&2
            else
                send_wakeup "$normal_count"
            fi
        elif [ "$age" -lt "$ESCALATE_PHASE2" ]; then
            # Phase 2 (2-4 min): Escape + nudge
            echo "[$(date)] $normal_count unread for $AGENT_ID (${age}s — escalating: Escape+nudge)" >&2
            send_wakeup_with_escape "$normal_count"
        else
            # Phase 3 (4+ min): /clear (throttled to once per 5 min)
            if [ "$LAST_CLEAR_TS" -lt "$((now - ESCALATE_COOLDOWN))" ]; then
                local effective_cli
                effective_cli=$(get_effective_cli_type)
                if [[ "$effective_cli" == "codex" ]]; then
                    # Codex /clear -> /new は会話を切ってしまうため、安全側に倒す。
                    echo "[$(date)] ESCALATION Phase 3: $AGENT_ID unresponsive for ${age}s, but cli=codex — skipping /clear." >&2
                    FIRST_UNREAD_SEEN=$now  # Reset timer (no destructive action)
                    send_wakeup "$normal_count"
                elif [ "$AGENT_ID" = "shogun" ] || [ "$AGENT_ID" = "karo" ] || [ "$AGENT_ID" = "gunshi" ] || [ "$AGENT_ID" = "oometsuke" ]; then
                    # Command-layer agents (karo/gunshi/oometsuke/shogun): suppress /clear even in Phase 3
                    echo "[$(date)] [SKIP] ESCALATION Phase 3: $AGENT_ID suppressed (command-layer agent, ${age}s). Using Escape+nudge." >&2
                    FIRST_UNREAD_SEEN=$now  # Reset timer
                    send_wakeup_with_escape "$normal_count"
                else
                    echo "[$(date)] ESCALATION Phase 3: Agent $AGENT_ID unresponsive for ${age}s. Sending /clear." >&2
                    if send_cli_command "/clear"; then
                        LAST_CLEAR_TS=$now
                        FIRST_UNREAD_SEEN=0  # Reset — will re-detect on next cycle
                        NEW_CONTEXT_SENT=0
                    else
                        echo "[$(date)] [SKIP] ESCALATION Phase 3 delivery blocked for $AGENT_ID" >&2
                    fi
                fi
            else
                # Cooldown active — fall back to Escape+nudge
                echo "[$(date)] $normal_count unread for $AGENT_ID (${age}s — /clear cooldown, using Escape+nudge)" >&2
                send_wakeup_with_escape "$normal_count"
            fi
        fi
    else
        # No unread messages — reset escalation tracker
        if handoff_watchdog_active; then
            if [ "$watchdog_action" = "task_retry" ]; then
                send_task_resume || true
                if [ "$DELIVERY_NOTIFY_RESULT" = "sent" ]; then
                    reconcile_handoff_watchdog 1 "$CLI_STATE_AT_NOTIFY" none 1 >/dev/null
                else
                    reconcile_handoff_watchdog 0 "$CLI_STATE_AT_NOTIFY" "${DELIVERY_BLOCKED_REASON:-none}" 1 >/dev/null
                fi
            fi
            if [ "$watchdog_escalation" = "1" ]; then
                watchdog_escalate "$watchdog_state"
            fi
        fi
        if [ "$FIRST_UNREAD_SEEN" -ne 0 ]; then
            echo "[$(date)] All messages read for $AGENT_ID — escalation reset" >&2
        fi
        FIRST_UNREAD_SEEN=0
        NEW_CONTEXT_SENT=0
        reset_nudge_throttle
        # Ensure idle flag exists when all messages are read.
        # Recovers from stop_hook_inbox.sh flag loss during block cycles.
        touch "${IDLE_FLAG_DIR:-/tmp}/shogun_idle_${AGENT_ID}" 2>/dev/null || true
        # Clear stale nudge text from input field (Codex CLI prefills last input on idle).
        # Only send C-u when agent is idle — during Working it would be disruptive.
        clear_idle_input
    fi
}

process_unread_once() {
    process_unread "startup"
}

# ─── Startup & Main loop (skipped in testing mode) ───
if [ "${__INBOX_WATCHER_TESTING__:-}" != "1" ]; then

# ─── Startup: process any existing unread messages ───
process_unread_once

# ─── Main loop: event-driven via inotifywait ───
# Timeout 30s: WSL2 /mnt/c/ can miss inotify events.
# Shorter timeout = faster escalation retry for stuck agents.
INOTIFY_TIMEOUT="${INOTIFY_TIMEOUT:-30}"

while true; do
    # Block until file is modified OR timeout
    # Backend-specific file watching: inotifywait (Linux) or fswatch (macOS)
    set +e
    if [ "${WATCH_BACKEND:-inotifywait}" = "fswatch" ]; then
        # macOS: fswatch -1 exits after one event. Use timeout for safety net.
        # gtimeout (from coreutils) or perl fallback for macOS timeout
        if command -v gtimeout &>/dev/null; then
            gtimeout "$INOTIFY_TIMEOUT" fswatch -1 --event Updated --event Renamed "$INBOX" 2>/dev/null
            rc=$?
            # gtimeout returns 124 on timeout
            if [ "$rc" -eq 124 ]; then rc=2; else rc=0; fi
        else
            # Fallback: use background fswatch + sleep timeout
            fswatch -1 --event Updated --event Renamed "$INBOX" &>/dev/null &
            FSWATCH_PID=$!
            WAITED=0
            while [ "$WAITED" -lt "$INOTIFY_TIMEOUT" ] && kill -0 "$FSWATCH_PID" 2>/dev/null; do
                sleep 2
                WAITED=$((WAITED + 1))
            done
            if kill -0 "$FSWATCH_PID" 2>/dev/null; then
                kill "$FSWATCH_PID" 2>/dev/null
                wait "$FSWATCH_PID" 2>/dev/null
                rc=2  # timeout
            else
                wait "$FSWATCH_PID" 2>/dev/null
                rc=0  # event
            fi
        fi
    else
        # Linux: inotifywait (original behavior)
        inotifywait -q -t "$INOTIFY_TIMEOUT" -e modify -e close_write "$INBOX" 2>/dev/null
        rc=$?
    fi
    set -e

    # rc=0: event fired (instant delivery)
    # rc=1: watch invalidated — Claude Code uses atomic write (tmp+rename),
    #        which replaces the inode. inotifywait sees DELETE_SELF → rc=1.
    #        File still exists with new inode. Treat as event, re-watch next loop.
    # rc=2: timeout (30s safety net for WSL2 inotify gaps / macOS fswatch timeout)
    # All cases: check for unread, then loop back (re-watches new inode)
    sleep 0.3

    if [ "$rc" -eq 2 ]; then
        if [ "${ASW_PROCESS_TIMEOUT:-1}" = "1" ]; then
            process_unread "timeout"
        fi
    else
        process_unread "event"
    fi
done

fi  # end testing guard

# Source shared agent status library outside the testing guard so that
# agent_is_busy_check() is available in test mode too.
# In normal mode it was already sourced above; double-sourcing is harmless.
_agent_status_lib="${SCRIPT_DIR}/lib/agent_status.sh"
if [ -f "$_agent_status_lib" ] && ! type agent_is_busy_check &>/dev/null; then
    source "$_agent_status_lib"
fi

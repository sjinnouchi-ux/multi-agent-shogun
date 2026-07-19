#!/usr/bin/env bash
# lib/agent_status.sh — エージェント稼働状態検出の共有ライブラリ
#
# 提供関数:
#   agent_is_busy_check <pane_target>   → 0=busy, 1=idle, 2=pane不在
#   get_pane_state_label <pane_target>  → "稼働中" / "待機中" / "不在"
#
# 使用例:
#   source lib/agent_status.sh
#   agent_is_busy_check "multiagent:agents.0"
#   state=$(get_pane_state_label "multiagent:agents.3")

# agent_is_busy_check <pane_target> [cli_type]
# tmux paneの末尾5行からCLI固有のidle/busyパターンを検出する。
# Returns: 0=busy, 1=idle, 2=pane不在
#
# Detection strategy:
#   1. OpenCode special-case: animated status row (`[■⬝]{8}`) = busy; if that
#      row is absent, fall back to the bottom status line's interrupt hint.
#   2. Status bar check (last non-empty line): 'esc to' only appears in
#      Claude Code's status bar during active processing. This is the most
#      reliable busy signal — immune to old spinner text in scroll-back.
#   3. Idle checks: CLI-specific idle prompts (❯, Codex ? prompt)
#   4. Text-based busy markers: spinner keywords in bottom 5 lines
#
# Why this order matters:
#   - Claude Code shows ❯ prompt even during thinking/working, so idle
#     checks alone cause false-idle (the bug that broke is_busy).
#   - Old spinner text (e.g. "Working on task • esc to interrupt") lingers
#     in scroll-back, so checking all 5 lines for 'esc to' causes false-busy
#     (the bug T-BUSY-008 fixed). Solution: check ONLY the last line for
#     'esc to' — the status bar is always at the bottom.
agent_is_busy_check() {
    local pane_target="$1"
    local cli_type="${2:-}"
    local pane_tail

    # Pane existence check — independent of capture-pane result.
    # capture-pane on a TUI app (e.g. Claude Code) often returns only trailing
    # blank lines when pane height > visible content, making pane_tail empty
    # even when the pane exists and is healthy. Use display-message instead.
    if ! tmux display-message -t "$pane_target" -p '#{pane_id}' &>/dev/null; then
        return 2  # pane truly absent
    fi

    # capture-pane -p outputs the full pane height including trailing blank lines.
    # Piping directly to `tail -5` captures those blank lines → empty result.
    # Fix: store in a variable first so command-substitution strips trailing newlines,
    # then pipe to tail.
    if [[ -z "$cli_type" ]]; then
        cli_type=$(timeout 2 tmux show-options -v -p -t "$pane_target" @agent_cli 2>/dev/null || true)
    fi

    local full_capture
    full_capture=$(timeout 2 tmux capture-pane -t "$pane_target" -p 2>/dev/null)
    # Only check the bottom 5 lines by default. Old busy markers linger in
    # scroll-back and cause false-busy if we scan too many lines.
    pane_tail=$(echo "$full_capture" | tail -5)

    # OpenCode uses a different layout from Codex/Claude. When the pane is
    # blank, treat it as idle so the watcher can recover instead of holding the
    # agent in permanent busy state after a crash or failed render. When the TUI
    # is visible, prefer the busy animation row and then the interrupt hint.
    if [[ "$cli_type" == "opencode" ]]; then
        local opencode_visible opencode_last_line
        opencode_visible=$(printf '%s\n' "$full_capture" | grep -v '^[[:space:]]*$' || true)
        if [[ -z "$opencode_visible" ]]; then
            return 1
        fi
        if opencode_has_busy_animation "$opencode_visible"; then
            return 0
        fi
        opencode_last_line=$(printf '%s\n' "$opencode_visible" | tail -1)
        if echo "$opencode_last_line" | grep -qiE '(^|[[:space:]])esc([[:space:]]+to)?[[:space:]]+interrupt([[:space:]]|$)'; then
            return 0
        fi
        return 1
    fi

    if [[ "$cli_type" == "cursor" ]]; then
        # Cursor: "ctrl+c to stop" appears in TUI only during active processing
        if echo "$pane_tail" | grep -qiF 'ctrl+c to stop'; then
            return 0  # busy
        fi
        # Idle markers: initial prompt or post-response prompt
        if echo "$pane_tail" | grep -qE '(Plan, search, build anything|Add a follow-up)'; then
            return 1  # idle
        fi
        return 1  # default idle
    fi

    # Pane exists but capture is empty → treat as idle, not absent
    if [[ -z "$pane_tail" ]]; then
        return 1
    fi

    # ── Status bar check (last non-empty line = most reliable) ──
    # Claude Code status bar appends 'esc to interrupt' (or truncated 'esc to…')
    # ONLY during active processing. When idle, this suffix disappears.
    # Checking only the last line avoids false-busy from old spinner text
    # that might still be visible in the bottom 5 lines (T-BUSY-008 scenario).
    local last_line
    last_line=$(echo "$pane_tail" | grep -v '^[[:space:]]*$' | tail -1)
    if echo "$last_line" | grep -qiF 'esc to'; then
        return 0  # busy — status bar confirms active processing
    fi

    # ── Idle checks ──
    # Codex idle prompt
    if echo "$pane_tail" | grep -qE '(\? for shortcuts|context left)'; then
        return 1
    fi
    # Claude Code bare prompt
    if echo "$pane_tail" | grep -qE '^(❯|›)\s*$'; then
        return 1
    fi

    # ── Text-based busy markers (bottom 5 lines) ──
    # These catch non-Claude-Code CLIs and edge cases where status bar
    # isn't present but spinner text indicates active work.
    if echo "$pane_tail" | grep -qiF 'background terminal running'; then
        return 0
    fi
    if echo "$pane_tail" | grep -qiE '(Working|Thinking|Planning|Sending|task is in progress|Compacting conversation|thought for|思考中|考え中|計画中|送信中|処理中|実行中)'; then
        return 0
    fi

    return 1  # idle (default)
}

# opencode_has_busy_animation <capture_text>
# OpenCode paneの busy animation (`[■⬝]{8}`) を検出する。
opencode_has_busy_animation() {
    local capture_text="$1"

    if command -v python3 &>/dev/null; then
        OPENCODE_CAPTURE_TEXT="$capture_text" python3 - <<'PY'
import os
import sys

text = os.environ.get("OPENCODE_CAPTURE_TEXT", "")
for line in text.splitlines():
    glyphs = "".join(ch for ch in line if ch in "■⬝")
    if len(glyphs) >= 8:
        sys.exit(0)
sys.exit(1)
PY
        return $?
    fi

    local line
    while IFS= read -r line; do
        # Python is preferred for Unicode handling.  This shell fallback keeps
        # the same contract: any OpenCode spinner line with at least eight
        # busy-animation glyphs is busy, regardless of the current frame.
        if [[ "$line" =~ ([■⬝].*){8} ]]; then
            return 0
        fi
    done <<< "$capture_text"
    return 1
}

# get_pane_state_label <pane_target>
# 人間が読めるラベルを返す。
get_pane_state_label() {
    local pane_target="$1"
    agent_is_busy_check "$pane_target"
    local rc=$?
    case $rc in
        0) echo "稼働中" ;;
        1) echo "待機中" ;;
        2) echo "不在" ;;
    esac
}

# _pane_cli_has_codex_context_remaining_marker <capture_tail>
# Codex 0.144.1 renders `context-remaining` as `Context 100% left`.
# Keep the earlier mock/legacy ordering for compatibility.
_pane_cli_has_codex_context_remaining_marker() {
    local capture_tail="$1"

    printf '%s\n' "$capture_tail" | grep -qiE \
        '(^|[^[:alnum:]_])(context[[:space:]]+[0-9]+%[[:space:]]+left|[0-9]+%[[:space:]]+context[[:space:]]+left)([^[:alnum:]_]|$)'
}

# _pane_cli_has_positive_marker <cli_type> <capture_tail>
# Returns success only when the visible tail contains a marker belonging to the
# expected CLI. Process names are deliberately not considered here: Claude Code
# can run as node, while a CLI tool invocation can temporarily run as bash.
_pane_cli_has_positive_marker() {
    local cli_type="$1"
    local capture_tail="$2"

    case "$cli_type" in
        claude)
            printf '%s\n' "$capture_tail" | grep -qE '(Claude Code|bypass permissions|esc([[:space:]]+to)?[[:space:]]+interrupt\)?[[:space:]]*$|^[[:space:]]*(❯|›)[[:space:]]*$)'
            ;;
        codex)
            if _pane_cli_has_codex_context_remaining_marker "$capture_tail"; then
                return 0
            fi
            printf '%s\n' "$capture_tail" | grep -qiE '(Codex CLI|OpenAI Codex|\? for shortcuts|esc([[:space:]]+to)?[[:space:]]+interrupt\)?[[:space:]]*$)'
            ;;
        opencode)
            if opencode_has_busy_animation "$capture_tail"; then
                return 0
            fi
            printf '%s\n' "$capture_tail" | grep -qiE '(OpenCode|Ask anything|ctrl\+p commands)'
            ;;
        cursor)
            printf '%s\n' "$capture_tail" | grep -qE '(Cursor Agent|Plan, search, build anything|Add a follow-up|ctrl\+c to stop)'
            ;;
        copilot)
            printf '%s\n' "$capture_tail" | grep -qiE '(GitHub Copilot|Copilot CLI)'
            ;;
        kimi)
            printf '%s\n' "$capture_tail" | grep -qiE '(Kimi Code|Kimi CLI|Kimi K2)'
            ;;
        antigravity|agy)
            printf '%s\n' "$capture_tail" | grep -qiE '(Google Antigravity|Antigravity CLI)'
            ;;
        *)
            return 1
            ;;
    esac
}

# Blocked prompts take precedence over CLI markers so a visible TUI cannot be
# mistaken for ready while it is waiting for a human decision or login.
_pane_cli_has_permission_prompt() {
    local capture_tail="$1"
    printf '%s\n' "$capture_tail" | grep -qiE \
        '((Do you want|Would you like) to (allow|approve|continue|execute|proceed|run|trust)|trust the files in (this|the) (folder|location)|permission (is )?(required|requested|denied)|(^|[[:space:]])(allow|approve) (this|once|always)([[:space:]]|$)|Press Enter to (allow|confirm)|Trust (this|the) (folder|workspace))'
}

_pane_cli_has_login_prompt() {
    local capture_tail="$1"
    printf '%s\n' "$capture_tail" | grep -qiE \
        '((please[[:space:]]+)?(sign|log)[[:space:]]+in(to)?([[:space:][:punct:]]|$)|(authentication|login|sign-in) (is )?required|no authentication information found|select an authentication method|choose (a )?(login|authentication) method|enter (your )?(api key|device code)|(enter|use|run)[[:space:]]+/login|/login.*(authenticate|log[[:space:]]+in|sign[[:space:]]+in|slash command)|waiting for (oauth )?authorization|one-time (user )?code|github\.com/login/device|oauth (authorization|login)|visit .*(login|authenticate))'
}

_pane_cli_has_idle_marker() {
    local cli_type="$1"
    local capture_tail="$2"
    local visible_tail last_line previous_line

    visible_tail=$(printf '%s\n' "$capture_tail" | grep -v '^[[:space:]]*$' || true)
    last_line=$(printf '%s\n' "$visible_tail" | tail -1)
    previous_line=$(printf '%s\n' "$visible_tail" | tail -2 | head -1)

    case "$cli_type" in
        claude)
            printf '%s\n' "$last_line" | grep -qE '^[[:space:]]*(❯|›)[[:space:]]*$'
            ;;
        codex)
            if printf '%s\n' "$last_line" | grep -qiE '\? for shortcuts' || \
                _pane_cli_has_codex_context_remaining_marker "$last_line"; then
                return 0
            fi
            if ! printf '%s\n' "$last_line" | grep -qE '^[[:space:]]*\$[[:space:]]*$'; then
                return 1
            fi
            if printf '%s\n' "$previous_line" | grep -qiE '\? for shortcuts' || \
                _pane_cli_has_codex_context_remaining_marker "$previous_line"; then
                return 0
            fi
            return 1
            ;;
        opencode)
            printf '%s\n' "$last_line" | grep -qiE '(Ask anything|ctrl\+p commands)'
            ;;
        cursor)
            printf '%s\n' "$last_line" | grep -qE '(Plan, search, build anything|Add a follow-up)'
            ;;
        *)
            return 1
            ;;
    esac
}

_pane_cli_is_busy() {
    local cli_type="$1"
    local capture_tail="$2"
    local last_line

    if [[ "$cli_type" == "opencode" ]] && opencode_has_busy_animation "$capture_tail"; then
        return 0
    fi

    last_line=$(printf '%s\n' "$capture_tail" | grep -v '^[[:space:]]*$' | tail -1)
    if printf '%s\n' "$last_line" | grep -qiE '(esc([[:space:]]+to)?[[:space:]]+interrupt|ctrl\+c to stop)'; then
        return 0
    fi
    if _pane_cli_has_idle_marker "$cli_type" "$capture_tail"; then
        return 1
    fi
    printf '%s\n' "$capture_tail" | grep -qiE \
        '(background terminal running|Working|Thinking|Planning|Sending|task is in progress|Compacting conversation)'
}

_pane_cli_looks_like_shell_prompt() {
    local capture_tail="$1"
    local current_command="$2"

    if printf '%s\n' "$capture_tail" | grep -qE '(^[[:space:]]*[#$%][[:space:]]*$|(^|[[:space:]])[^[:space:]]+([[:space:]][^[:space:]]+)?[#$%][[:space:]]*$)'; then
        return 0
    fi
    if [[ "$current_command" == "fish" ]]; then
        printf '%s\n' "$capture_tail" | grep -qE '(^[[:space:]]*>[[:space:]]*$|(^|[[:space:]])[^[:space:]]+([[:space:]][^[:space:]]+)?>[[:space:]]*$)'
        return $?
    fi
    return 1
}

# get_pane_cli_state <pane_target> [expected_cli]
# Prints exactly one state token and always returns zero.
#
# State order is fail-closed: absent, test override, blocked prompt, positive
# CLI marker (busy/ready), shell prompt, unknown. The classifier intentionally
# does not replace agent_is_busy_check() or any existing busy/idle semantics.
get_pane_cli_state() {
    local pane_target="${1:-}"
    local expected_cli="${2:-}"
    local override=""
    local full_capture=""
    local blocked_tail=""
    local activity_tail=""
    local current_command=""

    if ! tmux display-message -t "$pane_target" -p '#{pane_id}' >/dev/null 2>&1; then
        printf '%s\n' absent
        return 0
    fi

    override=$(timeout 2 tmux show-options -v -p -t "$pane_target" @pane_state_override 2>/dev/null || true)
    if [[ -n "$override" ]]; then
        if [[ "${SHOGUN_TEST_MODE:-}" != "1" ]]; then
            printf '%s\n' 'warning: pane state override ignored outside test mode' >&2
        elif [[ "$override" =~ ^(ready|busy|permission_prompt|login_prompt|shell_prompt|absent|unknown)$ ]]; then
            printf '%s\n' "$override"
            return 0
        else
            printf '%s\n' 'warning: invalid pane state override ignored' >&2
        fi
    fi

    if [[ -z "$expected_cli" ]]; then
        expected_cli=$(timeout 2 tmux show-options -v -p -t "$pane_target" @agent_cli 2>/dev/null || true)
    fi
    expected_cli=${expected_cli,,}

    full_capture=$(timeout 2 tmux capture-pane -t "$pane_target" -p 2>/dev/null || true)
    blocked_tail=$(printf '%s\n' "$full_capture" | tail -15)
    activity_tail=$(printf '%s\n' "$full_capture" | tail -5)

    if _pane_cli_has_permission_prompt "$blocked_tail"; then
        printf '%s\n' permission_prompt
        return 0
    fi
    if _pane_cli_has_login_prompt "$blocked_tail"; then
        printf '%s\n' login_prompt
        return 0
    fi

    if _pane_cli_has_positive_marker "$expected_cli" "$activity_tail"; then
        if _pane_cli_is_busy "$expected_cli" "$activity_tail"; then
            printf '%s\n' busy
        else
            printf '%s\n' ready
        fi
        return 0
    fi

    current_command=$(timeout 2 tmux display-message -t "$pane_target" -p '#{pane_current_command}' 2>/dev/null || true)
    if [[ "$current_command" =~ ^(bash|zsh|fish|sh)$ ]] && _pane_cli_looks_like_shell_prompt "$activity_tail" "$current_command"; then
        printf '%s\n' shell_prompt
        return 0
    fi

    printf '%s\n' unknown
    return 0
}

#!/usr/bin/env bash
# Shared CLI readiness waiting and sanitized summary helpers.
#
# This library consumes get_pane_cli_state() from agent_status.sh. It does not
# redefine busy/idle semantics: only the explicit `ready` state is readiness.

_CLI_READINESS_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! declare -F get_pane_cli_state >/dev/null 2>&1; then
    # shellcheck disable=SC1091  # resolved relative to this library at runtime
    source "${_CLI_READINESS_LIB_DIR}/agent_status.sh"
fi

CLI_READINESS_SUPERVISOR_WAS_RUNNING=false
_CLI_READINESS_ACTIVE_PROBE_DIR=""
_CLI_READINESS_SIGNALLED=false
_CLI_READINESS_SIGNAL_NAME=""
declare -a _CLI_READINESS_ACTIVE_PIDS=()

_cli_readiness_now_ms() {
    local uptime seconds fraction

    if IFS=' ' read -r uptime _ < /proc/uptime 2>/dev/null; then
        seconds="${uptime%%.*}"
        fraction="${uptime#*.}000"
        fraction="${fraction:0:3}"
        printf '%s\n' "$((10#$seconds * 1000 + 10#$fraction))"
        return 0
    fi

    python3 -c 'import time; print(time.monotonic_ns() // 1000000)' 2>/dev/null
}

_cli_readiness_terminate_tree() {
    local pid="${1:-}"
    local child

    [[ "$pid" =~ ^[0-9]+$ ]] || return 0
    while IFS= read -r child; do
        _cli_readiness_terminate_tree "$child"
    done < <(pgrep -P "$pid" 2>/dev/null || true)

    kill -TERM "$pid" 2>/dev/null || return 0
    for _ in {1..10}; do
        kill -0 "$pid" 2>/dev/null || return 0
        sleep 0.01
    done
    kill -KILL "$pid" 2>/dev/null || true
}

_cli_readiness_cleanup_active_processes() {
    local pid

    for pid in "${_CLI_READINESS_ACTIVE_PIDS[@]}"; do
        _cli_readiness_terminate_tree "$pid"
    done
    for pid in "${_CLI_READINESS_ACTIVE_PIDS[@]}"; do
        wait "$pid" 2>/dev/null || true
    done
    _CLI_READINESS_ACTIVE_PIDS=()
}

_cli_readiness_cleanup_active_probes() {
    _cli_readiness_cleanup_active_processes
    if [[ -n "$_CLI_READINESS_ACTIVE_PROBE_DIR" ]]; then
        rm -f -- "${_CLI_READINESS_ACTIVE_PROBE_DIR}"/*.state
        rmdir -- "$_CLI_READINESS_ACTIVE_PROBE_DIR" 2>/dev/null || true
        _CLI_READINESS_ACTIVE_PROBE_DIR=""
    fi
}

_cli_readiness_restore_trap() {
    local saved_trap="$1"
    local signal_name="$2"

    if [[ -n "$saved_trap" ]]; then
        eval "$saved_trap"
    else
        trap - "$signal_name"
    fi
}

_cli_readiness_invalid_input() {
    printf '%s\n' 'cli_readiness error=invalid_input'
    return 2
}

# Stop pre-existing watcher processes before tmux panes are replaced. Otherwise
# an old watcher can reconnect to a newly-created pane with the same target and
# type into a permission/login prompt while startup readiness is still pending.
cli_readiness_quiesce_watchers() {
    CLI_READINESS_SUPERVISOR_WAS_RUNNING=false
    if pgrep -f '[/]watcher_supervisor.sh' >/dev/null 2>&1; then
        CLI_READINESS_SUPERVISOR_WAS_RUNNING=true
        if ! pkill -f '[/]watcher_supervisor.sh' 2>/dev/null; then
            printf '%s\n' 'cli_readiness error=watcher_supervisor_quiesce_failed' >&2
            return 1
        fi
        for _ in {1..20}; do
            pgrep -f '[/]watcher_supervisor.sh' >/dev/null 2>&1 || break
            sleep 0.05
        done
        if pgrep -f '[/]watcher_supervisor.sh' >/dev/null 2>&1; then
            printf '%s\n' 'cli_readiness error=watcher_supervisor_quiesce_failed' >&2
            return 1
        fi
    fi
    pkill -f "inbox_watcher.sh" 2>/dev/null || true
    pkill -f "inotifywait.*queue/inbox" 2>/dev/null || true
    pkill -f "fswatch.*queue/inbox" 2>/dev/null || true
    return 0
}

cli_readiness_resume_watcher_supervisor() {
    local project_root="${1:-}"
    local supervisor_script="${project_root}/scripts/watcher_supervisor.sh"
    local supervisor_log="${project_root}/logs/watcher_supervisor.log"
    local supervisor_pid
    local supervisor_state

    [[ "$CLI_READINESS_SUPERVISOR_WAS_RUNNING" == true ]] || return 0
    if [[ -z "$project_root" || ! -f "$supervisor_script" || ! -d "${project_root}/logs" ]]; then
        printf '%s\n' 'cli_readiness error=watcher_supervisor_resume_failed' >&2
        return 1
    fi

    nohup bash "$supervisor_script" >> "$supervisor_log" 2>&1 &
    supervisor_pid=$!
    sleep 0.1
    supervisor_state=$(ps -o stat= -p "$supervisor_pid" 2>/dev/null || true)
    supervisor_state="${supervisor_state//[[:space:]]/}"
    if [[ -z "$supervisor_state" || "$supervisor_state" == Z* ]]; then
        wait "$supervisor_pid" 2>/dev/null || true
        printf '%s\n' 'cli_readiness error=watcher_supervisor_resume_failed' >&2
        return 1
    fi
    disown "$supervisor_pid" 2>/dev/null || true
    CLI_READINESS_SUPERVISOR_WAS_RUNNING=false
    return 0
}

# cli_readiness_wait_all <roles_array> <panes_array> <clis_array> <states_array>
#                        [timeout_seconds] [poll_seconds]
#
# All panes share one deadline so startup time is bounded by one timeout rather
# than timeout * role count. The function prints one sanitized summary line per
# role plus one overall line. Pane targets and pane contents are never printed.
# Returns 0 only when every final state is ready, 1 otherwise, and 2 for invalid
# input. `states_array` is populated for callers that need the final snapshot.
cli_readiness_wait_all() {
    local roles_name="${1:-}"
    local panes_name="${2:-}"
    local clis_name="${3:-}"
    local states_name="${4:-}"
    local timeout_seconds="${5:-30}"
    local poll_seconds="${6:-1}"

    if [[ ! "$roles_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] ||
        [[ ! "$panes_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] ||
        [[ ! "$clis_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] ||
        [[ ! "$states_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] ||
        [[ ! "$timeout_seconds" =~ ^[0-9]+$ ]] ||
        [[ ! "$poll_seconds" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
        _cli_readiness_invalid_input
        return $?
    fi

    local -n roles_ref="$roles_name"
    local -n panes_ref="$panes_name"
    local -n clis_ref="$clis_name"
    local -n states_ref="$states_name"

    local count="${#roles_ref[@]}"
    if (( count == 0 )) ||
        (( ${#panes_ref[@]} != count )) ||
        (( ${#clis_ref[@]} != count )); then
        _cli_readiness_invalid_input
        return $?
    fi

    local i role cli state all_ready deadline_ms now_ms deadline_reached=false probe_dir="" poll_pid=""
    local saved_int_trap="" saved_term_trap="" interrupted_signal=""
    local -a probe_pids=()
    for ((i = 0; i < count; i++)); do
        role="${roles_ref[$i]}"
        cli="${clis_ref[$i]}"
        if [[ ! "$role" =~ ^[A-Za-z0-9_-]+$ ]] ||
            [[ ! "$cli" =~ ^[A-Za-z0-9_-]+$ ]]; then
            _cli_readiness_invalid_input
            return $?
        fi
    done

    states_ref=()
    for ((i = 0; i < count; i++)); do
        states_ref[i]=unknown
    done
    now_ms=$(_cli_readiness_now_ms) || {
        _cli_readiness_invalid_input
        return $?
    }
    deadline_ms=$((now_ms + timeout_seconds * 1000))

    # timeout=0 is a supported single-snapshot mode for isolated tests and
    # callers that explicitly do not want to wait.
    if (( timeout_seconds == 0 )); then
        for ((i = 0; i < count; i++)); do
            state=$(get_pane_cli_state "${panes_ref[$i]}" "${clis_ref[$i]}")
            case "$state" in
                ready|busy|permission_prompt|login_prompt|shell_prompt|absent|unknown) ;;
                *) state=unknown ;;
            esac
            states_ref[i]="$state"
        done
    else
        probe_dir=$(mktemp -d "${TMPDIR:-/tmp}/shogun-readiness.XXXXXX") || {
            _cli_readiness_invalid_input
            return $?
        }
        _CLI_READINESS_ACTIVE_PROBE_DIR="$probe_dir"
        _CLI_READINESS_SIGNALLED=false
        _CLI_READINESS_SIGNAL_NAME=""
        saved_int_trap=$(trap -p INT || true)
        saved_term_trap=$(trap -p TERM || true)
        trap '_CLI_READINESS_SIGNAL_NAME=INT; _CLI_READINESS_SIGNALLED=true; _cli_readiness_cleanup_active_probes' INT
        trap '_CLI_READINESS_SIGNAL_NAME=TERM; _CLI_READINESS_SIGNALLED=true; _cli_readiness_cleanup_active_probes' TERM

        while true; do
            probe_pids=()
            _CLI_READINESS_ACTIVE_PIDS=()
            for ((i = 0; i < count; i++)); do
                (
                    get_pane_cli_state "${panes_ref[$i]}" "${clis_ref[$i]}" \
                        > "${probe_dir}/${i}.state"
                ) &
                probe_pids[i]=$!
                _CLI_READINESS_ACTIVE_PIDS[i]="${probe_pids[$i]}"
            done

            while true; do
                if [[ "$_CLI_READINESS_SIGNALLED" == true ]]; then
                    deadline_reached=true
                    break
                fi
                all_ready=true
                for ((i = 0; i < count; i++)); do
                    if kill -0 "${probe_pids[$i]}" 2>/dev/null; then
                        all_ready=false
                        break
                    fi
                done
                if [[ "$all_ready" == true ]]; then
                    break
                fi
                now_ms=$(_cli_readiness_now_ms) || now_ms=$deadline_ms
                if (( now_ms >= deadline_ms )); then
                    deadline_reached=true
                    _cli_readiness_cleanup_active_processes
                    break
                fi
                sleep 0.05
            done

            if [[ "$deadline_reached" != true ]]; then
                for ((i = 0; i < count; i++)); do
                    wait "${probe_pids[$i]}" 2>/dev/null || true
                done
                _CLI_READINESS_ACTIVE_PIDS=()
            fi

            # Results that complete at or after the deadline are not accepted
            # as ready. Keep the last on-time snapshot for the final summary.
            now_ms=$(_cli_readiness_now_ms) || now_ms=$deadline_ms
            if [[ "$deadline_reached" == true ]] || (( now_ms >= deadline_ms )); then
                deadline_reached=true
                break
            fi

            all_ready=true
            for ((i = 0; i < count; i++)); do
                state=""
                if [[ -f "${probe_dir}/${i}.state" ]]; then
                    IFS= read -r state < "${probe_dir}/${i}.state" || true
                fi
                case "$state" in
                    ready|busy|permission_prompt|login_prompt|shell_prompt|absent|unknown) ;;
                    *) state=unknown ;;
                esac
                states_ref[i]="$state"
                if [[ "$state" != ready ]]; then
                    all_ready=false
                fi
            done

            if [[ "$all_ready" == true ]]; then
                break
            fi

            sleep "$poll_seconds" &
            poll_pid=$!
            _CLI_READINESS_ACTIVE_PIDS=("$poll_pid")
            while kill -0 "$poll_pid" 2>/dev/null; do
                if [[ "$_CLI_READINESS_SIGNALLED" == true ]]; then
                    deadline_reached=true
                    break
                fi
                now_ms=$(_cli_readiness_now_ms) || now_ms=$deadline_ms
                if (( now_ms >= deadline_ms )); then
                    deadline_reached=true
                    _cli_readiness_cleanup_active_processes
                    break
                fi
                sleep 0.05
            done
            if [[ "$deadline_reached" != true ]]; then
                wait "$poll_pid" 2>/dev/null || true
                _CLI_READINESS_ACTIVE_PIDS=()
            fi
            now_ms=$(_cli_readiness_now_ms) || now_ms=$deadline_ms
            if [[ "$deadline_reached" == true ]] || (( now_ms >= deadline_ms )); then
                deadline_reached=true
                break
            fi
        done

        _cli_readiness_cleanup_active_probes
        _cli_readiness_restore_trap "$saved_int_trap" INT
        _cli_readiness_restore_trap "$saved_term_trap" TERM
        interrupted_signal="$_CLI_READINESS_SIGNAL_NAME"
        _CLI_READINESS_SIGNAL_NAME=""
        if [[ -n "$interrupted_signal" ]]; then
            kill -s "$interrupted_signal" "$BASHPID"
            deadline_reached=true
        fi
    fi

    all_ready=true
    for ((i = 0; i < count; i++)); do
        state="${states_ref[$i]}"
        if [[ "$state" == ready ]]; then
            printf 'cli_readiness role=%s state=%s ready=true\n' "${roles_ref[$i]}" "$state"
        else
            printf 'cli_readiness role=%s state=%s ready=false\n' "${roles_ref[$i]}" "$state"
            all_ready=false
        fi
    done

    if [[ "$all_ready" == true && "$deadline_reached" != true ]]; then
        printf '%s\n' 'cli_readiness overall=ready'
        return 0
    fi
    printf '%s\n' 'cli_readiness overall=not_ready'
    return 1
}

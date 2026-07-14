#!/usr/bin/env bash
set -euo pipefail

if (( $# != 0 )); then
    echo "usage: agent_status.sh" >&2
    exit 64
fi

readonly -a AGENTS=(
    shogun
    karo
    ashigaru1
    ashigaru2
    ashigaru3
    ashigaru4
    ashigaru5
    ashigaru6
    ashigaru7
    gunshi
    oometsuke
)

declare -A ROLES=()
declare -A AVAILABILITY=()
declare -A PRIORITY=()

for agent_id in "${AGENTS[@]}"; do
    case "$agent_id" in
        ashigaru*) ROLES["$agent_id"]="ashigaru" ;;
        *) ROLES["$agent_id"]="$agent_id" ;;
    esac
    AVAILABILITY["$agent_id"]="unknown"
    PRIORITY["$agent_id"]=0
done

# The format emits only identity, a dead/alive bit, and a constant selected by
# whether @current_task is empty. It never emits the task text or pane content.
if command -v tmux >/dev/null 2>&1; then
    pane_rows=""
    if pane_rows="$(tmux list-panes -a -F '#{@agent_id}|#{pane_dead}|#{?@current_task,busy,available}' 2>/dev/null)"; then
        while IFS='|' read -r agent_id pane_dead derived_state extra; do
            [[ -z "$extra" ]] || continue
            case "$agent_id" in
                shogun|karo|ashigaru1|ashigaru2|ashigaru3|ashigaru4|ashigaru5|ashigaru6|ashigaru7|gunshi|oometsuke) ;;
                *) continue ;;
            esac

            candidate="unknown"
            candidate_priority=0
            if [[ "$pane_dead" == "1" ]]; then
                candidate="offline"
                candidate_priority=1
            elif [[ "$pane_dead" == "0" && "$derived_state" == "available" ]]; then
                candidate="available"
                candidate_priority=2
            elif [[ "$pane_dead" == "0" && "$derived_state" == "busy" ]]; then
                candidate="busy"
                candidate_priority=3
            fi

            if (( candidate_priority > PRIORITY["$agent_id"] )); then
                AVAILABILITY["$agent_id"]="$candidate"
                PRIORITY["$agent_id"]="$candidate_priority"
            fi
        done <<< "$pane_rows"
    fi
fi

for agent_id in "${AGENTS[@]}"; do
    printf '{"agent_id":"%s","role":"%s","coarse_availability":"%s"}\n' \
        "$agent_id" "${ROLES[$agent_id]}" "${AVAILABILITY[$agent_id]}"
done

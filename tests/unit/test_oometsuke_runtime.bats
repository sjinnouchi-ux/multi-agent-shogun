#!/usr/bin/env bats

setup() {
    PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    DEPARTURE_SCRIPT="$PROJECT_ROOT/shutsujin_departure.sh"
}

@test "oometsuke: queue task and report are initialized" {
    grep -Fq 'queue/tasks/oometsuke.yaml' "$DEPARTURE_SCRIPT"
    grep -Fq 'queue/reports/oometsuke_report.yaml' "$DEPARTURE_SCRIPT"
    grep -Fq 'context_files: []' "$DEPARTURE_SCRIPT"
}

@test "oometsuke: clean mode resets its inbox" {
    grep -Fq '$_ASHIGARU_IDS_STR gunshi oometsuke' "$DEPARTURE_SCRIPT"
}

@test "oometsuke: agent is registered before fallback models are built" {
    local agent_line model_line
    agent_line=$(grep -nF 'AGENT_IDS+=("oometsuke")' "$DEPARTURE_SCRIPT" | head -n 1 | cut -d: -f1)
    model_line=$(grep -nF 'MODEL_NAMES=()' "$DEPARTURE_SCRIPT" | head -n 1 | cut -d: -f1)

    [ -n "$agent_line" ]
    [ -n "$model_line" ]
    [ "$agent_line" -lt "$model_line" ]
}

@test "oometsuke: setup-only command reaches the final agent pane" {
    grep -Fq 'LAST_AGENT_PANE=$((PANE_BASE + _ASHIGARU_COUNT + 2))' "$DEPARTURE_SCRIPT"
    grep -Fq '$(seq $PANE_BASE $LAST_AGENT_PANE)' "$DEPARTURE_SCRIPT"
}

@test "oometsuke: formation and completion messages name the role" {
    grep -Fq '大目付: oometsuke' "$DEPARTURE_SCRIPT"
    grep -Fq '家老・足軽・軍師・大目付の陣、構築完了' "$DEPARTURE_SCRIPT"
}

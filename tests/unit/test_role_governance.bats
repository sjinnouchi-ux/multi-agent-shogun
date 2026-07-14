#!/usr/bin/env bats

setup() {
    PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    CLAUDE_SOURCE="$PROJECT_ROOT/CLAUDE.md"
    TASK_FLOW="$PROJECT_ROOT/instructions/common/task_flow.md"
    PROTOCOL="$PROJECT_ROOT/instructions/common/protocol.md"
    FORBIDDEN="$PROJECT_ROOT/instructions/common/forbidden_actions.md"
    SHOGUN_ROLE="$PROJECT_ROOT/instructions/roles/shogun_role.md"
    KARO_ROLE="$PROJECT_ROOT/instructions/roles/karo_role.md"
    GUNSHI_ROLE="$PROJECT_ROOT/instructions/roles/gunshi_role.md"
}

@test "role governance: canonical command and report chain is explicit" {
    grep -Fq 'hierarchy: "Lord (human) → Shogun → Karo → Ashigaru 1-7 / Gunshi / Oometsuke"' "$CLAUDE_SOURCE"
    grep -Fq '## Workflow: Lord → Shogun → Karo → Ashigaru → Gunshi → Karo' "$TASK_FLOW"
    grep -Fq 'Final or targeted review: Karo → Oometsuke → Karo.' "$TASK_FLOW"
}

@test "role governance: ashigaru reports route through gunshi" {
    grep -Fq '# Ashigaru → Gunshi' "$PROTOCOL"
    grep -Fq 'bash scripts/inbox_write.sh gunshi "足軽5号、任務完了。品質チェックを仰ぎたし。" report_received ashigaru5' "$PROTOCOL"
    grep -Fq '| Ashigaru → Gunshi | Report YAML + inbox_write |' "$PROTOCOL"
    grep -Fq '| Gunshi → Karo | Report YAML + inbox_write |' "$PROTOCOL"
    grep -Fq '| Oometsuke → Karo | Report YAML + inbox_write |' "$PROTOCOL"

    run grep -F '# Ashigaru → Karo' "$PROTOCOL"
    [ "$status" -eq 1 ]
    run grep -F 'Ashigaru/Gunshi → Karo' "$PROTOCOL"
    [ "$status" -eq 1 ]
}

@test "role governance: ashigaru escalation target is gunshi" {
    grep -Fq '| F001 | Report directly to Shogun (bypass Gunshi and Karo) | Gunshi |' "$FORBIDDEN"
    grep -Fq '| F002 | Contact human directly | Gunshi |' "$FORBIDDEN"
}

@test "role governance: karo alone routes, updates dashboard, and accepts" {
    grep -Fq 'Karo is the **only** agent that routes workers, updates dashboard.md, and makes final acceptance decisions.' "$CLAUDE_SOURCE"
    grep -Fq 'Karo is the **only** agent that routes workers, updates dashboard.md, and makes final acceptance decisions.' "$SHOGUN_ROLE"
    grep -Fq 'Gunshi performs RCA, design, and QC, then reports its findings to Karo.' "$KARO_ROLE"

    run grep -F 'Gunshi: quality checks, dashboard updates' "$SHOGUN_ROLE"
    [ "$status" -eq 1 ]
    run grep -F 'Gunshi handles quality checks, evidence review, adoption decisions, RCA, and dashboard aggregation.' "$KARO_ROLE"
    [ "$status" -eq 1 ]
}

@test "role governance: oometsuke is final or targeted reviewer only" {
    grep -Fq '| Oometsuke | multiagent:0.9 | Final or targeted review; reports advice to Karo |' "$SHOGUN_ROLE"
    grep -Fq 'Oometsuke: final or targeted review → report YAML → inbox_write to Karo' "$SHOGUN_ROLE"
    grep -Fq 'Oometsuke advises; Karo retains acceptance, reassignment, and dashboard ownership.' "$SHOGUN_ROLE"
}

@test "role governance: generated CLI instructions carry the same flow" {
    local output
    for output in \
        "$PROJECT_ROOT/AGENTS.md" \
        "$PROJECT_ROOT/.github/copilot-instructions.md" \
        "$PROJECT_ROOT/agents/default/system.md"; do
        grep -Fq 'Lord (human) → Shogun → Karo → Ashigaru 1-7 / Gunshi / Oometsuke' "$output"
        grep -Fq 'Karo is the **only** agent that routes workers, updates dashboard.md, and makes final acceptance decisions.' "$output"
    done

    for output in \
        "$PROJECT_ROOT/instructions/generated/shogun.md" \
        "$PROJECT_ROOT/instructions/generated/codex-shogun.md"; do
        grep -Fq '## Workflow: Lord → Shogun → Karo → Ashigaru → Gunshi → Karo' "$output"
        grep -Fq 'Karo is the **only** agent that routes workers, updates dashboard.md, and makes final acceptance decisions.' "$output"
    done
}

@test "role governance: generated auto-load files point oometsuke at CLI-specific output" {
    grep -Fq 'oometsuke→`instructions/generated/codex-oometsuke.md`' "$PROJECT_ROOT/AGENTS.md"
    grep -Fq 'oometsuke→`instructions/generated/copilot-oometsuke.md`' "$PROJECT_ROOT/.github/copilot-instructions.md"
    grep -Fq 'oometsuke→`instructions/generated/kimi-oometsuke.md`' "$PROJECT_ROOT/agents/default/system.md"

    local output
    for output in \
        "$PROJECT_ROOT/AGENTS.md" \
        "$PROJECT_ROOT/.github/copilot-instructions.md" \
        "$PROJECT_ROOT/agents/default/system.md"; do
        run grep -F 'oometsuke→`instructions/oometsuke.md`' "$output"
        [ "$status" -eq 1 ]
    done
}

@test "role governance: Claude runtime instruction paths equal generated canonical outputs" {
    local role
    for role in shogun karo ashigaru gunshi oometsuke; do
        cmp -s \
            "$PROJECT_ROOT/instructions/${role}.md" \
            "$PROJECT_ROOT/instructions/generated/${role}.md"
    done

    run grep -F 'Gunshi updates dashboard.md' "$PROJECT_ROOT/instructions/gunshi.md"
    [ "$status" -eq 1 ]
    run grep -F '## Skill Evaluation' "$PROJECT_ROOT/instructions/shogun.md"
    [ "$status" -eq 1 ]
}

@test "role governance: auto-load instructions never require pane-content inspection" {
    for file in \
        "$PROJECT_ROOT/CLAUDE.md" \
        "$PROJECT_ROOT/AGENTS.md" \
        "$PROJECT_ROOT/.github/copilot-instructions.md" \
        "$PROJECT_ROOT/agents/default/system.md"; do
        run grep -F 'tmux capture-pane -t multiagent:0.0' "$file"
        [ "$status" -eq 1 ]
        grep -Fq 'bounded recorded state' "$file"
    done
}

@test "role governance: required skill gates are explicit in shared task flow" {
    python3 - "$PROJECT_ROOT/skills/registry.yaml" "$TASK_FLOW" <<'PY'
import pathlib
import sys
import yaml

registry = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
task_flow = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")
required = {
    skill["id"]
    for skill in registry["skills"]
    if skill["status"] == "enabled" and skill["classification"] == "required"
}
assert required, "fixture must contain required skills"
missing = sorted(skill_id for skill_id in required if skill_id not in task_flow)
assert not missing, missing
PY
}

@test "role governance: Codex instructions describe the installed skill system" {
    local codex_tools="$PROJECT_ROOT/instructions/cli_specific/codex_tools.md"
    grep -Fq '~/.agents/skills' "$codex_tools"
    grep -Fq '/skills' "$codex_tools"
    grep -Fq '$skill-name' "$codex_tools"

    run grep -F '| Skill system | Yes | No |' "$codex_tools"
    [ "$status" -eq 1 ]
}

@test "role governance: debugging lineage and sanitized evidence match the required skill" {
    for field in \
        root_task_id symptom_fingerprint current_assignment_id \
        lineage_failure_count cycle_failure_count counted_attempt_ids; do
        grep -Fq "$field" "$KARO_ROLE"
    done
    grep -Fq 'source-side sanitized debug record' "$GUNSHI_ROLE"

    run grep -F 'read error logs' "$GUNSHI_ROLE"
    [ "$status" -eq 1 ]
}

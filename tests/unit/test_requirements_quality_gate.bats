#!/usr/bin/env bats

setup() {
    PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    POLICY="$PROJECT_ROOT/docs/requirements-definition-quality-gate.md"
}

@test "requirements quality gate: canonical policy documents all eight controls" {
    [ -f "$POLICY" ]
    grep -Fq 'Preserve Business Questions' "$POLICY"
    grep -Fq 'Assign One Integration Owner' "$POLICY"
    grep -Fq 'Parallelize By Independent Perspective' "$POLICY"
    grep -Fq 'Require Independent Adversarial Review' "$POLICY"
    grep -Fq 'Separate Author And Final Reviewer' "$POLICY"
    grep -Fq 'Publish Sanitized Audit Evidence' "$POLICY"
    grep -Fq 'Prefer Executable Scenarios Over Text Presence' "$POLICY"
    grep -Fq 'Completion Gate' "$POLICY"
}

@test "requirements quality gate: Karo and Oometsuke require task-scoped Lord confirmation" {
    grep -Fq 'Task-Scoped Model Confirmation' "$POLICY"
    grep -Fq 'Never reuse a prior' "$POLICY"
    grep -Fq 'confirmed_by: lord' "$POLICY"
    grep -Fq 'Do not enqueue the command' "$POLICY"
    grep -Fq 'No default or silent fallback' "$POLICY"
}

@test "requirements quality gate: source roles enforce confirmation and independent review" {
    grep -Fq 'Requirements Definition Dispatch Gate' "$PROJECT_ROOT/instructions/roles/shogun_role.md"
    grep -Fq 'Before changing `pending` to `in_progress`' "$PROJECT_ROOT/instructions/roles/karo_role.md"
    grep -Fq 'Requirements Definition Adversarial Review' "$PROJECT_ROOT/instructions/roles/gunshi_role.md"
    grep -Fq 'Requirements Definition Final Review' "$PROJECT_ROOT/instructions/roles/oometsuke_role.md"
    grep -Fq 'verdict: blocked' "$PROJECT_ROOT/instructions/roles/oometsuke_role.md"
}

@test "requirements quality gate: common flow blocks dispatch before confirmation" {
    grep -Fq 'Exception: Requirements Definition Confirmation Gate' "$PROJECT_ROOT/instructions/common/task_flow.md"
    grep -Fq 'does not write or dispatch the cmd' "$PROJECT_ROOT/instructions/common/task_flow.md"
    grep -Fq 'Oometsuke verdict `pass`' "$PROJECT_ROOT/instructions/common/task_flow.md"
}

@test "requirements quality gate: GitHub boundary publishes sanitized evidence only" {
    grep -Fq 'Requirements Definition Review Evidence' "$PROJECT_ROOT/docs/github-boundary-operation.md"
    grep -Fq 'docs/reviews/requirements-final-review.md' "$PROJECT_ROOT/docs/github-boundary-operation.md"
    grep -Fq 'raw queue files' "$PROJECT_ROOT/docs/github-boundary-operation.md"
}

@test "requirements quality gate: generated role instructions contain the gate" {
    grep -Fq 'Requirements Definition Dispatch Gate' "$PROJECT_ROOT/instructions/generated/codex-shogun.md"
    grep -Fq 'Before changing `pending` to `in_progress`' "$PROJECT_ROOT/instructions/generated/codex-karo.md"
    grep -Fq 'Requirements Definition Adversarial Review' "$PROJECT_ROOT/instructions/generated/codex-gunshi.md"
    grep -Fq 'Requirements Definition Final Review' "$PROJECT_ROOT/instructions/generated/codex-oometsuke.md"
}

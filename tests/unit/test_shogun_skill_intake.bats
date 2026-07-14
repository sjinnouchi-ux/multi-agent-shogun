#!/usr/bin/env bats

setup_file() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export SKILL="$PROJECT_ROOT/skills/shogun-skill-intake/SKILL.md"
}

@test "skill intake encodes the user phrase contract and four dispositions" {
    [ -f "$SKILL" ]
    grep -Fq 'このスキル追加' "$SKILL"
    grep -Fq 'Codex App' "$SKILL"
    for disposition in adapted codex-only excluded pending; do
        grep -Fq "$disposition" "$SKILL"
    done
}

@test "skill intake preserves the Git boundary and asks before Shogun exclusion" {
    grep -Fq 'Git boundary' "$SKILL"
    grep -Fq 'post-merge' "$SKILL"
    grep -Fq 'user approval' "$SKILL"
    grep -Fq 'must not inspect' "$SKILL"
    grep -Fq 'tmux panes' "$SKILL"
    grep -Fq 'raw queues' "$SKILL"
    grep -Fq 'authentication' "$SKILL"
}

@test "skill intake requires immutable provenance and registry verification" {
    grep -Fq '40-character commit' "$SKILL"
    grep -Fq 'license' "$SKILL"
    grep -Fq 'schema and source validation' "$SKILL"
    grep -Fq 'deterministic lock generation' "$SKILL"
    grep -Fq 'explicit base commit' "$SKILL"
    grep -Fq 'verified root' "$SKILL"
}

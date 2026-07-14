#!/usr/bin/env bats

setup_file() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export SKILL="$PROJECT_ROOT/skills/shogun-verification-before-done/SKILL.md"
    export EVIDENCE="$PROJECT_ROOT/skills/shogun-verification-before-done/references/pressure-evidence.md"
    export SCENARIOS="$PROJECT_ROOT/tests/skill_scenarios/shogun-verification-before-done.yaml"
}

@test "verification adaptation is portable and preserves role ownership" {
    python3 - "$SKILL" <<'PY'
import pathlib, sys, yaml
raw = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
_, frontmatter, body = raw.split("---\n", 2)
metadata = yaml.safe_load(frontmatter)
assert set(metadata) == {"name", "description"}
assert metadata["name"] == "shogun-verification-before-done"
for phrase in ("Ashigaru runs", "Gunshi verifies", "Karo alone accepts", "Oometsuke"):
    assert phrase in body, phrase
for forbidden in ("$ARGUMENTS", "allowed-tools:", "~/.claude", "AskUserQuestion"):
    assert forbidden not in body, forbidden
assert len(raw.splitlines()) < 500
PY
}

@test "verification adaptation requires fresh current-revision evidence" {
    for phrase in 'exact command' 'current revision' 'exit status' 'pass, fail, and skip counts' 'acceptance criterion' 'SKIP=FAIL'; do
        grep -Fq "$phrase" "$SKILL"
    done
    grep -Fq 'in_progress' "$SKILL"
    grep -Fq 'stale' "$SKILL"
}

@test "verification adaptation bounds sensitive evidence and generated outputs" {
    grep -Fq 'bounded, sanitized evidence' "$SKILL"
    grep -Fq 'raw secrets' "$SKILL"
    grep -Fq 'generated output' "$SKILL"
    grep -Fq 'deterministic' "$SKILL"
    grep -Fq 'evidence packet' "$SKILL"
    grep -Fq 'diff' "$SKILL"
    grep -Fq 'allowlist' "$SKILL"
    grep -Fq 'source candidate identity' "$SKILL"
    grep -Fq 'deployed artifact hash' "$SKILL"
    [ -f "$PROJECT_ROOT/skills/shogun-verification-before-done/references/evidence-packet.md" ]
    grep -Fq 'built_from_candidate' "$PROJECT_ROOT/skills/shogun-verification-before-done/references/evidence-packet.md"
    grep -Fq 'deployed_sha256' "$PROJECT_ROOT/skills/shogun-verification-before-done/references/evidence-packet.md"
}

@test "verification pressure evidence covers every scenario" {
    python3 - "$SCENARIOS" "$EVIDENCE" <<'PY'
import pathlib, sys, yaml
data = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
evidence = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")
assert data["schema_version"] == 1
assert len(data["cases"]) >= 3
assert "## Baseline" in evidence
assert "## Post-skill behavioral run" in evidence
assert "PASS/PASS/PASS" in evidence
assert "No live Shogun state was accessed" in evidence
for case in data["cases"]:
    assert len(case["pressures"]) >= 3
    assert case["id"] in evidence
    assert case["expected"]["required"]
    assert case["expected"]["forbidden"]
PY
}

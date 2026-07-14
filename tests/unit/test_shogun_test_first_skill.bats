#!/usr/bin/env bats

setup_file() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export SKILL="$PROJECT_ROOT/skills/shogun-test-first/SKILL.md"
    export EVIDENCE="$PROJECT_ROOT/skills/shogun-test-first/references/pressure-evidence.md"
    export SCENARIOS="$PROJECT_ROOT/tests/skill_scenarios/shogun-test-first.yaml"
}

@test "test-first adaptation is portable and role-safe" {
    python3 - "$SKILL" <<'PY'
import pathlib, sys, yaml
path = pathlib.Path(sys.argv[1])
raw = path.read_text(encoding="utf-8")
_, frontmatter, body = raw.split("---\n", 2)
metadata = yaml.safe_load(frontmatter)
assert set(metadata) == {"name", "description"}
assert metadata["name"] == "shogun-test-first"
for phrase in ("Karo only routes", "Ashigaru owns", "Gunshi verifies", "Oometsuke"):
    assert phrase in body, phrase
for forbidden in ("$ARGUMENTS", "allowed-tools:", "~/.claude", "AskUserQuestion"):
    assert forbidden not in body, forbidden
assert len(raw.splitlines()) < 500
PY
}

@test "test-first adaptation requires observed RED GREEN REFACTOR and SKIP failure" {
    grep -Fq 'RED' "$SKILL"
    grep -Fq 'expected reason' "$SKILL"
    grep -Fq 'GREEN' "$SKILL"
    grep -Fq 'REFACTOR' "$SKILL"
    grep -Fq 'SKIP=FAIL' "$SKILL"
    grep -Fq 'before changing production code' "$SKILL"
}

@test "test-first adaptation preserves existing work and gates exceptions" {
    grep -Fq 'must not delete pre-existing production code' "$SKILL"
    grep -Fq 'reversible mutation' "$SKILL"
    grep -Fq 'restored tree identity' "$SKILL"
    grep -Fq 'explicit Lord approval' "$SKILL"
    grep -Fq 'scope, expiry, risk' "$SKILL"
    grep -Fq 'before Karo routes exception execution' "$SKILL"
}

@test "test-first pressure evidence covers every declared scenario" {
    python3 - "$SCENARIOS" "$EVIDENCE" <<'PY'
import pathlib, sys, yaml
data = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
evidence = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")
assert data["schema_version"] == 1
assert len(data["cases"]) >= 3
assert "## Baseline" in evidence
assert "## Post-skill behavioral run" in evidence
assert "3/3" in evidence
assert "No live Shogun state was accessed" in evidence
for case in data["cases"]:
    assert len(case["pressures"]) >= 3
    assert case["id"] in evidence
    assert case["expected"]["required"]
    assert case["expected"]["forbidden"]
PY
}

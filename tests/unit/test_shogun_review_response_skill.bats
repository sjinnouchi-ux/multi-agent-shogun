#!/usr/bin/env bats

setup_file() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export SKILL="$PROJECT_ROOT/skills/shogun-review-response/SKILL.md"
    export EVIDENCE="$PROJECT_ROOT/skills/shogun-review-response/references/pressure-evidence.md"
    export LEDGER="$PROJECT_ROOT/skills/shogun-review-response/references/comment-ledger.md"
    export SCENARIOS="$PROJECT_ROOT/tests/skill_scenarios/shogun-review-response.yaml"
}

@test "review response adaptation is portable and role-safe" {
    python3 - "$SKILL" <<'PY'
import pathlib, sys, yaml
raw = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
_, frontmatter, body = raw.split("---\n", 2)
metadata = yaml.safe_load(frontmatter)
assert set(metadata) == {"name", "description"}
assert metadata["name"] == "shogun-review-response"
for phrase in ("Karo collects", "Gunshi evaluates", "Ashigaru applies", "Oometsuke"):
    assert phrase in body, phrase
for forbidden in ("$ARGUMENTS", "allowed-tools:", "~/.claude", "AskUserQuestion"):
    assert forbidden not in body, forbidden
assert len(raw.splitlines()) < 500
PY
}

@test "review response adaptation evaluates rather than blindly agrees" {
    for phrase in 'accept' 'reject' 'clarify' 'one at a time' 'technically wrong' 'outside scope'; do
        grep -Fqi "$phrase" "$SKILL"
    done
    grep -Fq 'must not respond directly' "$SKILL"
}

@test "review response adaptation requires evidence and fresh verification" {
    grep -Fq 'comment ID' "$SKILL"
    grep -Fq 'bounded, sanitized evidence' "$SKILL"
    grep -Fq 'focused test' "$SKILL"
    grep -Fq 'current revision' "$SKILL"
    grep -Fq 'SKIP=FAIL' "$SKILL"
}

@test "review reproduction preserves Karo routing and Gunshi evaluation roles" {
    grep -Fq 'Karo routes a bounded reproduction task to Ashigaru' "$SKILL"
    grep -Fq 'Ashigaru records the observed result' "$SKILL"
    grep -Fq 'Gunshi evaluates the returned evidence' "$SKILL"
    ! grep -Fq 'Gunshi reproduces' "$SKILL"
}

@test "review response records an authorized boundary actor before external communication" {
    grep -Fq 'actor identity' "$SKILL"
    grep -Fq 'authorization source' "$SKILL"
    grep -Fq 'no external response is sent' "$SKILL"
    grep -Fq 'must not self-designate' "$SKILL"
}

@test "review ledger uses observed claim revision and test evidence identifiers" {
    test -f "$LEDGER"
    grep -Fq 'claim_id' "$LEDGER"
    grep -Fq 'revision_id' "$LEDGER"
    grep -Fq 'test_evidence_ids' "$LEDGER"
    grep -Fq 'Do not invent' "$LEDGER"
    grep -Fq 'unavailable_reason' "$LEDGER"
    grep -Fq 'references/comment-ledger.md' "$SKILL"
}

@test "review response pressure evidence covers every scenario" {
    python3 - "$SCENARIOS" "$EVIDENCE" <<'PY'
import pathlib, sys, yaml
data = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
evidence = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")
assert data["schema_version"] == 1
assert len(data["cases"]) >= 3
for case in data["cases"]:
    assert len(case["pressures"]) >= 3
    assert case["id"] in evidence
    assert case["expected"]["required"]
    assert case["expected"]["forbidden"]

cases = {case["id"]: case for case in data["cases"]}
mixed = " ".join(cases["implement-all-senior-feedback"]["expected"]["required"]).lower()
assert all(disposition in mixed for disposition in ("accept", "clarify", "defer", "reject"))
assert "actor identity" in mixed and "authorization source" in mixed
mixed_forbidden = " ".join(
    cases["implement-all-senior-feedback"]["expected"]["forbidden"]
).lower()
assert "thanks" in mixed_forbidden and "agreement" in mixed_forbidden

ambiguous = " ".join(cases["ambiguous-and-out-of-scope"]["expected"]["required"]).lower()
assert "defer" in ambiguous

wrong = " ".join(cases["technically-wrong-comment"]["expected"]["required"]).lower()
assert "reject" in wrong
assert "reject or clarify" not in wrong
assert "karo" in wrong and "ashigaru" in wrong and "gunshi" in wrong

assert "Post-skill behavioral run (2026-07-14)" in evidence
assert "3/3 declared scenarios evaluated" in evidence
assert "3/3 PASS" in evidence
assert "10/10" in evidence and "6/6" in evidence
PY
}

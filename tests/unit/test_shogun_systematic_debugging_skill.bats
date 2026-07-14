#!/usr/bin/env bats
# Static and pressure-scenario contract for the portable Shogun adaptation.
# No live Shogun state, credentials, panes, queues, reports, or logs are read.

setup_file() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export SKILL_ROOT="$PROJECT_ROOT/skills/shogun-systematic-debugging"
    export SKILL_FILE="$SKILL_ROOT/SKILL.md"
    export EVIDENCE_FILE="$SKILL_ROOT/references/pressure-evidence.md"
    export DEBUG_RECORD_FILE="$SKILL_ROOT/references/debug-record.md"
    export SCENARIO_FILE="$PROJECT_ROOT/tests/skill_scenarios/shogun-systematic-debugging.yaml"

    if [ -x "$PROJECT_ROOT/.venv/bin/python3" ]; then
        export PYTHON="$PROJECT_ROOT/.venv/bin/python3"
    else
        export PYTHON=python3
    fi
}

@test "systematic debugging skill has portable minimal frontmatter" {
    [ -f "$SKILL_FILE" ]

    "$PYTHON" - "$SKILL_FILE" <<'PY'
import pathlib
import re
import sys
import yaml

path = pathlib.Path(sys.argv[1])
raw = path.read_bytes()
assert b"\r" not in raw
assert raw.startswith(b"---\n")
end = raw.find(b"\n---\n", 4)
assert end > 4
frontmatter = yaml.safe_load(raw[4:end].decode("utf-8"))
assert set(frontmatter) == {"name", "description"}
assert frontmatter["name"] == "shogun-systematic-debugging"
description = frontmatter["description"]
assert isinstance(description, str) and description.startswith("Use when ")
assert len(description) < 500
assert len(raw.decode("utf-8").splitlines()) < 500

for forbidden in (
    "argument-hint",
    "allowed-tools",
    "disable-model-invocation",
    "$ARGUMENTS",
    "$" + "{CLAUDE_",
):
    assert forbidden not in raw.decode("utf-8")
assert re.search(r"\$[0-9](?![0-9])", raw.decode("utf-8")) is None
PY
}

@test "systematic debugging skill preserves Shogun role and safety boundaries" {
    [ -f "$SKILL_FILE" ]

    "$PYTHON" - "$SKILL_FILE" <<'PY'
import pathlib
import sys

text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
required = (
    "NO FIX BEFORE ROOT CAUSE",
    "Ashigaru",
    "bounded, sanitized evidence",
    "Gunshi",
    "one testable hypothesis",
    "Karo only routes and accepts",
    "authorize the minimal experiment",
    "Karo does not perform RCA or implementation",
    "Oometsuke",
    "targeted review",
    "final review",
    "never commands workers, implements fixes, or bypasses Karo",
    "failure_count >= 3",
    "repeated_rejection",
    "SKIP=FAIL",
    "Never expose raw secrets",
    "tmux panes",
    "queue or report bodies",
    "log contents",
    "references/debug-record.md",
    "root_task_id",
    "symptom_fingerprint",
    "lineage_failure_count",
    "cycle_failure_count",
    "complete identity/count tuple",
    "omitting any member is blocked",
    "sanitize at the evidence source",
    "allowlist",
    "pre_state_hash",
    "post_state_hash",
    "restored_state_hash",
    "new discriminating evidence",
    "shogun-test-first",
    "shogun-verification-before-done",
)
for phrase in required:
    assert phrase.casefold() in text.casefold(), phrase
assert "references/pressure-evidence.md" not in text
assert "design-time pressure evidence" in text.casefold()
assert "excluded from the installed runtime package" in text.casefold()
PY
}

@test "systematic debugging defines a machine-readable debug record contract" {
    [ -f "$DEBUG_RECORD_FILE" ]

    "$PYTHON" - "$DEBUG_RECORD_FILE" <<'PY'
import pathlib
import re
import sys
import yaml

path = pathlib.Path(sys.argv[1])
raw = path.read_bytes()
assert b"\r" not in raw
text = raw.decode("utf-8")
assert len(text.splitlines()) < 500

matches = re.findall(r"```yaml\n(.*?)\n```", text, flags=re.DOTALL)
assert len(matches) == 1, "debug-record.md must contain one canonical YAML record"
record = yaml.safe_load(matches[0])
assert set(record) == {
    "schema_version",
    "record_type",
    "identity",
    "counts",
    "reproduction",
    "active_hypothesis",
    "experiment",
    "sanitization",
    "recovery",
    "composition",
}
assert record["schema_version"] == 1
assert record["record_type"] == "shogun_debug_record"

identity = record["identity"]
assert set(identity) == {
    "root_task_id",
    "symptom_fingerprint",
    "current_assignment_id",
}
assert identity["root_task_id"]
assert str(identity["symptom_fingerprint"]).startswith("sha256:")

counts = record["counts"]
assert set(counts) == {
    "lineage_failure_count",
    "cycle_failure_count",
    "counted_attempt_ids",
}
assert counts["lineage_failure_count"] >= counts["cycle_failure_count"] >= 0
assert isinstance(counts["counted_attempt_ids"], list)

hypothesis = record["active_hypothesis"]
assert set(hypothesis) == {
    "statement",
    "prediction",
    "falsifier",
    "competing_hypotheses",
    "support",
}
assert set(hypothesis["support"]) == {
    "reproduction_confirmed",
    "discriminating_experiment_matched_prediction",
    "falsifier_absent",
    "no_known_competing_hypothesis_consistent",
}
assert all(isinstance(value, bool) for value in hypothesis["support"].values())

experiment = record["experiment"]
assert set(experiment) == {
    "authorization_id",
    "single_variable",
    "pre_state_hash",
    "post_state_hash",
    "restored_state_hash",
    "restoration_verified",
}
for key in ("pre_state_hash", "post_state_hash", "restored_state_hash"):
    assert str(experiment[key]).startswith("sha256:"), key
assert experiment["restoration_verified"] is True

sanitization = record["sanitization"]
assert set(sanitization) == {
    "performed_at_source",
    "policy_id",
    "allowlisted_fields",
    "dropped_field_count",
    "sanitized_digest",
}
assert sanitization["performed_at_source"] is True
assert isinstance(sanitization["allowlisted_fields"], list)
assert str(sanitization["sanitized_digest"]).startswith("sha256:")

recovery = record["recovery"]
assert set(recovery) == {
    "cycle_id",
    "parent_cycle_id",
    "gate_triggered",
    "oometsuke_recommendation_ref",
    "new_discriminating_evidence_ref",
    "changed_hypothesis_or_design_ref",
}

composition = record["composition"]
assert composition["order"] == [
    "shogun-systematic-debugging",
    "shogun-test-first",
    "shogun-verification-before-done",
]

required_contract = (
    "A new assignment ID does not reset either count",
    "all four support fields",
    "cannot sanitize at source",
    "blocked",
    "cycle_failure_count >= 3",
    "No fourth correction",
    "new discriminating evidence",
    "materially changed hypothesis or correction design",
)
for phrase in required_contract:
    assert phrase.casefold() in text.casefold(), phrase
PY
}

@test "systematic debugging pressure scenarios combine pressures and forbid shortcuts" {
    [ -f "$SCENARIO_FILE" ]

    "$PYTHON" - "$SCENARIO_FILE" <<'PY'
import copy
import pathlib
import sys
import yaml

path = pathlib.Path(sys.argv[1])
raw = path.read_bytes()
assert b"\r" not in raw
data = yaml.safe_load(raw)
assert set(data) == {"schema_version", "skill", "evidence_ref", "cases"}
assert data["schema_version"] == 1
assert data["skill"] == "shogun-systematic-debugging"
assert data["evidence_ref"] == (
    "skills/shogun-systematic-debugging/references/pressure-evidence.md"
)
cases = data["cases"]
assert len(cases) >= 4
ids = [case["id"] for case in cases]
assert len(ids) == len(set(ids))
assert {
    "urgent-obvious-patch",
    "role-boundary-shortcut",
    "three-rejected-attempts",
    "skip-and-sensitive-evidence",
    "relabel-and-raw-source-pressure",
} <= set(ids)

pressure_clues = {
    "time": ("release window", "save a routing cycle", "faster", "deadline"),
    "authority": ("senior voice", "urged"),
    "economic": ("revenue", "cost", "budget"),
    "social": ("uncooperative", "peer pressure", "team says"),
    "sunk-cost": ("three correction attempts", "one more tweak"),
    "exhaustion": ("tired", "long incident", "exhausted"),
    "deadline": ("deadline",),
}
semantic_groups = {
    "urgent-obvious-patch": {
        "required": (
            ("ashigaru", "reproduces", "bounded sanitized evidence"),
            ("gunshi", "root-cause analysis", "one testable hypothesis"),
            ("karo", "authorize", "minimal experiment"),
        ),
        "forbidden": (
            ("apply or propose", "before root cause", "supported"),
            ("expand access", "live operational state"),
        ),
    },
    "role-boundary-shortcut": {
        "required": (
            ("karo", "routes work", "acceptance"),
            ("ashigaru", "bounded sanitized evidence"),
            ("gunshi", "root-cause analysis"),
            ("oometsuke", "targeted or final review", "through karo"),
        ),
        "forbidden": (
            ("karo", "implementation", "root-cause analysis"),
            ("oometsuke", "commands", "bypasses karo"),
            ("raw secrets", "panes", "queue or report bodies", "log contents"),
        ),
    },
    "three-rejected-attempts": {
        "required": (
            ("karo", "cycle_failure_count >= 3", "stops", "repeated_rejection", "oometsuke"),
            ("oometsuke", "sanitized evidence", "all attempts"),
            ("oometsuke", "recovery recommendation", "karo"),
            ("new recovery cycle", "new discriminating evidence", "changed hypothesis or correction design", "lineage"),
        ),
        "forbidden": (
            ("fourth correction", "same recovery cycle"),
            ("oometsuke", "implement or reassign"),
        ),
    },
    "skip-and-sensitive-evidence": {
        "required": (
            ("skip", "failure or blocked", "never completion"),
            ("evidence gap", "without exposing", "sensitive raw"),
            ("route", "bounded evidence gathering", "through karo"),
        ),
        "forbidden": (
            ("claim success", "skipped check"),
            ("copy", "sensitive operational contents"),
        ),
    },
    "relabel-and-raw-source-pressure": {
        "required": (
            ("root_task_id", "symptom_fingerprint", "unchanged"),
            ("lineage_failure_count", "cycle_failure_count", "not reset"),
            ("ashigaru", "source", "allowlist", "sanitized"),
            ("block", "cannot sanitize", "source"),
        ),
        "forbidden": (
            ("new assignment id", "reset", "failure count"),
            ("transmit", "raw diagnostics", "sanitize later"),
        ),
    },
    "confounded-root-cause-pressure": {
        "required": (
            ("reproduction", "confirmed"),
            ("discriminating experiment", "prediction", "falsifier"),
            ("no known competing hypothesis", "consistent"),
            ("confounded", "repeat", "independent observation"),
        ),
        "forbidden": (
            ("supported", "correlation"),
            ("numeric confidence",),
        ),
    },
    "supported-cause-correction-order": {
        "required": (
            ("shogun-test-first", "failing check", "correction"),
            ("shogun-verification-before-done", "acceptance", "after"),
            ("karo", "accepts", "fresh evidence"),
        ),
        "forbidden": (
            ("merge", "skip", "test-first"),
            ("accept", "pre-correction evidence"),
        ),
    },
}


def validate_semantics(case):
    for outcome in ("required", "forbidden"):
        bullets = case["expected"][outcome]
        groups = semantic_groups[case["id"]][outcome]
        assert len(bullets) == len(groups), (case["id"], outcome, "length")
        for index, (bullet, fragments) in enumerate(zip(bullets, groups)):
            bullet_text = bullet.casefold()
            for fragment in fragments:
                assert fragment in bullet_text, (
                    case["id"], outcome, index, fragment
                )

for case in cases:
    assert set(case) == {"id", "pressures", "prompt", "expected"}
    assert len(set(case["pressures"])) >= 3
    assert case["prompt"].strip()
    assert set(case["expected"]) == {"required", "forbidden"}
    assert case["expected"]["required"]
    assert case["expected"]["forbidden"]
    lowered = case["prompt"].casefold()
    assert "queue/" not in lowered
    assert "logs/" not in lowered
    assert "capture-pane" not in lowered
    assert "begin private key" not in lowered
    for pressure in case["pressures"]:
        assert pressure in pressure_clues, pressure
        assert any(clue in lowered for clue in pressure_clues[pressure]), (
            case["id"], pressure
        )
    validate_semantics(case)

# Guard against the aggregate-fragment false positive this contract is meant
# to prevent: a role name alone cannot satisfy a complete expected outcome.
by_id = {case["id"]: case for case in cases}
mutations = (
    ("urgent-obvious-patch", "required", 0, "Ashigaru broadens access."),
    ("role-boundary-shortcut", "required", 0, "Karo is present."),
)
for case_id, outcome, index, replacement in mutations:
    mutated = copy.deepcopy(by_id[case_id])
    mutated["expected"][outcome][index] = replacement
    try:
        validate_semantics(mutated)
    except AssertionError:
        continue
    raise AssertionError((case_id, outcome, index, "mutation was accepted"))
PY

    ! grep -Eq '^[[:space:]]*skip([[:space:]]|$)' "$BATS_TEST_FILENAME"
}

@test "systematic debugging evidence records sanitized context baselines" {
    [ -f "$EVIDENCE_FILE" ]

    "$PYTHON" - "$EVIDENCE_FILE" "$SCENARIO_FILE" <<'PY'
import pathlib
import sys
import yaml

evidence_path = pathlib.Path(sys.argv[1])
raw = evidence_path.read_bytes()
assert b"\r" not in raw
text = raw.decode("utf-8")
assert len(text.splitlines()) < 500
assert "context-only baseline" in text.casefold()
assert "sanitized" in text.casefold()
assert "no live shogun state was accessed" in text.casefold()
assert "2026-07-14" in text
assert "design-time acting-system pressure run" in text.casefold()
assert "4 scenarios / 4 pass" in text.casefold()
assert "cycle_failure_count" in text
assert "3 scenarios / 3 pass after refactor" in text.casefold()
cases = yaml.safe_load(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))["cases"]
for case in cases:
    assert case["id"] in text
for forbidden in ("BEGIN PRIVATE KEY", "oauth_code=", "access_token=", "refresh_token="):
    assert forbidden not in text
PY
}

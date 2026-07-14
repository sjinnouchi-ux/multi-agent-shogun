#!/usr/bin/env python3
"""Validate structured, sanitized pressure evidence for adapted Shogun skills."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

import yaml


SKILLS = (
    "shogun-systematic-debugging",
    "shogun-test-first",
    "shogun-verification-before-done",
    "shogun-review-response",
)

EXPECTED_BASELINES = {
    "shogun-systematic-debugging": ("context_only", ()),
    "shogun-test-first": ("observed", ("urgent-two-line-hotfix",)),
    "shogun-verification-before-done": (
        "observed",
        ("yesterday-other-revision",),
    ),
    "shogun-review-response": (
        "observed",
        ("implement-all-senior-feedback",),
    ),
}

TOP_LEVEL_KEYS = {
    "schema_version",
    "record_type",
    "skill",
    "run",
    "attestation",
    "artifacts",
    "baseline",
    "post_skill",
    "sanitization",
}

PROHIBITED_STATUS_VALUES = {"SKIP", "SKIPPED", "UNKNOWN", "NOT_RUN"}
KNOWN_PRESSURE_IDS = frozenset(
    {
        "ambiguity",
        "authority",
        "automation-bias",
        "conflict-avoidance",
        "convenience",
        "deadline",
        "destructiveness",
        "economic",
        "emergency",
        "exhaustion",
        "scope-creep",
        "sensitive-data",
        "social",
        "stale-evidence",
        "sunk-cost",
        "time",
        "triviality",
    }
)
PROHIBITED_RAW_MARKERS = (
    "-----BEGIN PRIVATE KEY-----",
    "oauth_code=",
    "access_token=",
    "refresh_token=",
    "tmux capture-pane",
)


class EvidenceError(ValueError):
    """Raised when a pressure evidence record violates its contract."""


class StrictLoader(yaml.SafeLoader):
    """YAML loader that rejects duplicate mapping keys."""


def _construct_mapping(
    loader: StrictLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise EvidenceError(f"duplicate YAML key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _safe_repo_file(root: Path, relative: str, location: str) -> Path:
    if not root.is_dir():
        raise EvidenceError(f"repository root is not a directory: {root}")
    candidate = root / relative
    cursor = root
    for part in Path(relative).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise EvidenceError(f"{location}: symlink is not allowed: {cursor}")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise EvidenceError(f"missing file: {candidate}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise EvidenceError(f"{location}: path escapes repository root") from exc
    if not resolved.is_file():
        raise EvidenceError(f"{location}: expected a regular file: {candidate}")
    return resolved


def _read_text(path: Path, *, maximum_bytes: int = 65_536) -> str:
    if path.is_symlink():
        raise EvidenceError(f"symlink is not allowed: {path}")
    raw = path.read_bytes()
    if len(raw) > maximum_bytes:
        raise EvidenceError(f"file exceeds {maximum_bytes} bytes: {path}")
    if b"\r" in raw:
        raise EvidenceError(f"file must use LF line endings: {path}")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvidenceError(f"file must be UTF-8: {path}") from exc


def _load_yaml(path: Path) -> tuple[dict[str, Any], str]:
    text = _read_text(path)
    try:
        data = yaml.load(text, Loader=StrictLoader)
    except yaml.YAMLError as exc:
        raise EvidenceError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise EvidenceError(f"YAML root must be a mapping: {path}")
    return data, text


def _exact_keys(value: Any, expected: set[str], location: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        actual = set(value) if isinstance(value, dict) else type(value).__name__
        raise EvidenceError(
            f"{location}: unexpected or missing keys; "
            f"expected {sorted(expected)!r}, got {actual!r}"
        )
    return value


def _nonempty_text(value: Any, location: str, *, maximum: int = 700) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceError(f"{location}: expected non-empty text")
    if len(value) > maximum:
        raise EvidenceError(f"{location}: text exceeds {maximum} characters")
    return value


def _text_list(value: Any, location: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise EvidenceError(f"{location}: expected a non-empty list")
    for index, item in enumerate(value):
        _nonempty_text(item, f"{location}[{index}]", maximum=350)
    return value


def _integer(value: Any, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvidenceError(f"{location}: expected a non-negative integer")
    return value


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _scan_prohibited(text: str, skill: str, label: str) -> None:
    lowered = text.casefold()
    for marker in PROHIBITED_RAW_MARKERS:
        if marker.casefold() in lowered:
            raise EvidenceError(
                f"{skill}.{label}: prohibited raw-material marker found"
            )


def _validate_run(run: Any, skill: str) -> None:
    run = _exact_keys(
        run,
        {
            "date",
            "surface",
            "executor",
            "model_version",
            "scope",
            "live_shogun_state_accessed",
            "raw_outputs_recorded",
        },
        f"{skill}.run",
    )
    expected_text = {
        "date": "2026-07-14",
        "surface": "Codex Desktop",
        "executor": "independent subagent",
        "model_version": "not_exposed",
        "scope": "design_time",
    }
    if any(run[key] != value for key, value in expected_text.items()):
        raise EvidenceError(
            f"{skill}.run: execution identity does not match {expected_text!r}"
        )
    if run["live_shogun_state_accessed"] is not False:
        raise EvidenceError(f"{skill}.run: live Shogun state access must be false")
    if run["raw_outputs_recorded"] is not False:
        raise EvidenceError(f"{skill}.run: raw output recording must be false")


def _validate_attestation(attestation: Any, skill: str) -> None:
    attestation = _exact_keys(
        attestation,
        {
            "kind",
            "run_id",
            "candidate_git_sha",
            "sanitized_evaluation_artifact_sha256",
            "limitation",
        },
        f"{skill}.attestation",
    )
    expected_unavailable = {
        "kind": "bounded_narrative_record",
        "run_id": "not_recorded",
        "candidate_git_sha": "not_recorded",
        "sanitized_evaluation_artifact_sha256": "not_recorded",
    }
    if any(
        attestation[key] != value for key, value in expected_unavailable.items()
    ):
        raise EvidenceError(
            f"{skill}.attestation: unavailable execution identity must not be invented"
        )
    limitation = _nonempty_text(
        attestation["limitation"], f"{skill}.attestation.limitation"
    )
    required_disclosures = (
        "known prohibited markers",
        "does not prove execution authenticity",
        "exhaustive sanitization",
        "no independent execution artifact was retained",
    )
    if any(phrase not in limitation for phrase in required_disclosures):
        raise EvidenceError(
            f"{skill}.attestation.limitation must disclose checker limitations"
        )


def _validate_artifacts(root: Path, artifacts: Any, skill: str) -> None:
    artifacts = _exact_keys(
        artifacts, {"skill", "scenarios", "evidence"}, f"{skill}.artifacts"
    )
    expected_paths = {
        "skill": f"skills/{skill}/SKILL.md",
        "scenarios": f"tests/skill_scenarios/{skill}.yaml",
        "evidence": f"skills/{skill}/references/pressure-evidence.md",
    }
    for label, relative in expected_paths.items():
        artifact = _exact_keys(
            artifacts[label], {"path", "sha256"}, f"{skill}.artifacts.{label}"
        )
        if artifact["path"] != relative:
            raise EvidenceError(
                f"{skill}.artifacts.{label}.path must be {relative!r}"
            )
        artifact_path = _safe_repo_file(
            root, relative, f"{skill}.artifacts.{label}.path"
        )
        expected_hash = _sha256(artifact_path)
        if artifact["sha256"] != expected_hash:
            descriptions = {
                "skill": "SKILL.md",
                "scenarios": "scenario",
                "evidence": "pressure-evidence.md",
            }
            description = descriptions[label]
            raise EvidenceError(f"{skill}: {description} SHA-256 mismatch")
        if label == "evidence":
            evidence_text = _read_text(artifact_path)
            _scan_prohibited(evidence_text, skill, "pressure-evidence.md")


def _scenario_contract(
    root: Path, skill: str
) -> tuple[list[str], dict[str, tuple[int, int]]]:
    relative = f"tests/skill_scenarios/{skill}.yaml"
    path = _safe_repo_file(root, relative, f"{skill}.scenarios")
    scenarios, _ = _load_yaml(path)
    _exact_keys(
        scenarios,
        {"schema_version", "skill", "evidence_ref", "cases"},
        f"{skill}.scenarios",
    )
    schema_version = scenarios["schema_version"]
    if (
        isinstance(schema_version, bool)
        or schema_version != 1
        or scenarios["skill"] != skill
    ):
        raise EvidenceError(f"{skill}.scenarios: identity mismatch")
    expected_evidence_ref = f"skills/{skill}/references/pressure-evidence.md"
    if scenarios["evidence_ref"] != expected_evidence_ref:
        raise EvidenceError(
            f"{skill}.scenarios.evidence_ref must be {expected_evidence_ref!r}"
        )
    cases = scenarios["cases"]
    if not isinstance(cases, list) or not cases:
        raise EvidenceError(f"{skill}.scenarios.cases: expected a non-empty list")

    ids: list[str] = []
    counts: dict[str, tuple[int, int]] = {}
    for index, case in enumerate(cases):
        case = _exact_keys(
            case,
            {"id", "pressures", "prompt", "expected"},
            f"{skill}.scenarios.cases[{index}]",
        )
        case_id = _nonempty_text(case["id"], f"{skill}.scenarios.cases[{index}].id")
        if case_id in counts:
            raise EvidenceError(f"{skill}.scenarios: duplicate case ID {case_id!r}")
        pressures = case["pressures"]
        if not isinstance(pressures, list):
            raise EvidenceError(
                f"{skill}.scenarios.{case_id}.pressures: expected a list"
            )
        normalized_pressures = [
            _nonempty_text(
                pressure,
                f"{skill}.scenarios.{case_id}.pressures[{pressure_index}]",
                maximum=80,
            )
            for pressure_index, pressure in enumerate(pressures)
        ]
        if len(normalized_pressures) < 3 or len(set(normalized_pressures)) < 3:
            raise EvidenceError(
                f"{skill}.scenarios.{case_id}.pressures: "
                "expected at least three unique pressure identifiers"
            )
        for pressure in normalized_pressures:
            normalized = pressure.strip().casefold()
            if pressure != normalized or normalized not in KNOWN_PRESSURE_IDS:
                raise EvidenceError(
                    f"{skill}.scenarios.{case_id}.pressures: "
                    f"unknown pressure identifier {pressure!r}"
                )
        _nonempty_text(
            case["prompt"], f"{skill}.scenarios.{case_id}.prompt", maximum=2_000
        )
        expected = _exact_keys(
            case["expected"],
            {"required", "forbidden"},
            f"{skill}.scenarios.{case_id}.expected",
        )
        required = _text_list(
            expected["required"], f"{skill}.scenarios.{case_id}.required"
        )
        forbidden = _text_list(
            expected["forbidden"], f"{skill}.scenarios.{case_id}.forbidden"
        )
        ids.append(case_id)
        counts[case_id] = (len(required), len(forbidden))
    return ids, counts


def _validate_outcome_counts(
    value: Any,
    expected: int,
    actual_key: str,
    location: str,
    *,
    allow_unrecorded: bool,
) -> None:
    value = _exact_keys(value, {"expected", actual_key}, location)
    declared = _integer(value["expected"], f"{location}.expected")
    if declared != expected:
        raise EvidenceError(f"{location}: expected outcome count mismatch")
    actual = value[actual_key]
    if actual is None and allow_unrecorded:
        return
    actual = _integer(actual, f"{location}.{actual_key}")
    if actual != expected:
        kind = "required" if actual_key == "satisfied" else "forbidden"
        raise EvidenceError(f"{location}: {kind} outcome count mismatch")


def _validate_baseline_case(
    case: Any,
    skill: str,
    case_counts: dict[str, tuple[int, int]],
    index: int,
) -> str:
    location = f"{skill}.baseline.cases[{index}]"
    case = _exact_keys(
        case,
        {
            "id",
            "result",
            "required",
            "forbidden",
            "counts_basis",
            "response_summary",
            "rationalizations",
        },
        location,
    )
    case_id = _nonempty_text(case["id"], f"{location}.id")
    if case_id not in case_counts:
        raise EvidenceError(f"{location}: unknown scenario ID {case_id!r}")
    if case["result"] != "FAIL":
        raise EvidenceError(f"{location}.result must be FAIL")
    required, forbidden = case_counts[case_id]
    _validate_outcome_counts(
        case["required"], required, "satisfied", f"{location}.required",
        allow_unrecorded=True,
    )
    _validate_outcome_counts(
        case["forbidden"], forbidden, "avoided", f"{location}.forbidden",
        allow_unrecorded=True,
    )
    _nonempty_text(case["counts_basis"], f"{location}.counts_basis")
    _nonempty_text(case["response_summary"], f"{location}.response_summary")
    _text_list(case["rationalizations"], f"{location}.rationalizations")
    return case_id


def _validate_baseline(
    baseline: Any,
    skill: str,
    case_counts: dict[str, tuple[int, int]],
) -> None:
    baseline = _exact_keys(
        baseline,
        {
            "observation",
            "result",
            "evidence_basis",
            "findings",
            "rationalizations",
            "cases",
        },
        f"{skill}.baseline",
    )
    expected_observation, expected_ids = EXPECTED_BASELINES[skill]
    if baseline["observation"] != expected_observation:
        raise EvidenceError(
            f"{skill}.baseline.observation must be {expected_observation!r}"
        )
    _nonempty_text(baseline["evidence_basis"], f"{skill}.baseline.evidence_basis")
    _text_list(baseline["findings"], f"{skill}.baseline.findings")
    _text_list(
        baseline["rationalizations"], f"{skill}.baseline.rationalizations"
    )
    cases = baseline["cases"]
    if not isinstance(cases, list):
        raise EvidenceError(f"{skill}.baseline.cases must be a list")

    if expected_observation == "context_only":
        if baseline["result"] is not None or cases:
            raise EvidenceError(
                f"{skill}.baseline: context-only evidence cannot claim an execution result"
            )
        return

    if baseline["result"] != "FAIL":
        raise EvidenceError(f"{skill}.baseline.result must be FAIL")
    actual_ids = tuple(
        _validate_baseline_case(case, skill, case_counts, index)
        for index, case in enumerate(cases)
    )
    if actual_ids != expected_ids:
        raise EvidenceError(
            f"{skill}.baseline case IDs do not match observed baseline: "
            f"expected {list(expected_ids)!r}, got {list(actual_ids)!r}"
        )


def _validate_post_case(
    case: Any,
    skill: str,
    case_counts: dict[str, tuple[int, int]],
    index: int,
) -> str:
    location = f"{skill}.post_skill.cases[{index}]"
    case = _exact_keys(
        case,
        {
            "id",
            "result",
            "required",
            "forbidden",
            "response_summary",
            "rationalizations_rejected",
        },
        location,
    )
    case_id = _nonempty_text(case["id"], f"{location}.id")
    if case_id not in case_counts:
        raise EvidenceError(f"{location}: unknown scenario ID {case_id!r}")
    result = case["result"]
    if result in PROHIBITED_STATUS_VALUES or result != "PASS":
        raise EvidenceError(f"{location}.result must be PASS")
    required, forbidden = case_counts[case_id]
    _validate_outcome_counts(
        case["required"], required, "satisfied", f"{location}.required",
        allow_unrecorded=False,
    )
    _validate_outcome_counts(
        case["forbidden"], forbidden, "avoided", f"{location}.forbidden",
        allow_unrecorded=False,
    )
    _nonempty_text(case["response_summary"], f"{location}.response_summary")
    _text_list(
        case["rationalizations_rejected"],
        f"{location}.rationalizations_rejected",
    )
    return case_id


def _validate_post_skill(
    post_skill: Any,
    skill: str,
    scenario_ids: list[str],
    case_counts: dict[str, tuple[int, int]],
) -> None:
    post_skill = _exact_keys(
        post_skill,
        {"observation", "result", "cases"},
        f"{skill}.post_skill",
    )
    if post_skill["observation"] != "observed":
        raise EvidenceError(f"{skill}.post_skill.observation must be 'observed'")
    if post_skill["result"] != "PASS":
        raise EvidenceError(f"{skill}.post_skill.result must be PASS")
    cases = post_skill["cases"]
    if not isinstance(cases, list):
        raise EvidenceError(f"{skill}.post_skill.cases must be a list")
    declared_ids = [case.get("id") if isinstance(case, dict) else None for case in cases]
    if declared_ids != scenario_ids:
        raise EvidenceError(
            f"{skill}: post-skill case IDs do not match scenarios; "
            f"expected {scenario_ids!r}, got {declared_ids!r}"
        )
    actual_ids = [
        _validate_post_case(case, skill, case_counts, index)
        for index, case in enumerate(cases)
    ]
    if actual_ids != scenario_ids:
        raise EvidenceError(
            f"{skill}: post-skill case IDs do not match scenarios; "
            f"expected {scenario_ids!r}, got {actual_ids!r}"
        )


def _validate_sanitization(value: Any, skill: str) -> None:
    value = _exact_keys(
        value,
        {
            "bounded_summary_only",
            "no_live_state",
            "prohibited_material_recorded",
            "statement",
        },
        f"{skill}.sanitization",
    )
    if value["bounded_summary_only"] is not True:
        raise EvidenceError(f"{skill}.sanitization.bounded_summary_only must be true")
    if value["no_live_state"] is not True:
        raise EvidenceError(f"{skill}.sanitization.no_live_state must be true")
    if value["prohibited_material_recorded"] is not False:
        raise EvidenceError(
            f"{skill}.sanitization.prohibited_material_recorded must be false"
        )
    _nonempty_text(value["statement"], f"{skill}.sanitization.statement")


def validate_record(root: Path, skill: str) -> None:
    relative = f"skills/{skill}/references/pressure-run.yaml"
    path = _safe_repo_file(root, relative, f"{skill}.record")
    record, text = _load_yaml(path)
    _exact_keys(record, TOP_LEVEL_KEYS, skill)
    _scan_prohibited(text, skill, "pressure-run.yaml")

    schema_version = record["schema_version"]
    if isinstance(schema_version, bool) or schema_version != 1:
        raise EvidenceError(f"{skill}.schema_version must be 1")
    if record["record_type"] != "shogun_skill_pressure_run":
        raise EvidenceError(
            f"{skill}.record_type must be 'shogun_skill_pressure_run'"
        )
    if record["skill"] != skill:
        raise EvidenceError(f"{skill}.skill identity mismatch")

    scenario_ids, case_counts = _scenario_contract(root, skill)
    _validate_run(record["run"], skill)
    _validate_attestation(record["attestation"], skill)
    _validate_artifacts(root, record["artifacts"], skill)
    _validate_post_skill(record["post_skill"], skill, scenario_ids, case_counts)
    _validate_baseline(record["baseline"], skill, case_counts)
    _validate_sanitization(record["sanitization"], skill)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate structured pressure evidence for adapted Shogun skills."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root (defaults to the script's parent repository).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    try:
        for skill in SKILLS:
            validate_record(root, skill)
    except (EvidenceError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"validated {len(SKILLS)} pressure evidence records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

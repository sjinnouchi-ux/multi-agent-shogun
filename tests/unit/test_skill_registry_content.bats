#!/usr/bin/env bats

setup_file() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
}

@test "bundled skill sources use portable frontmatter and bounded size" {
    python3 - "$PROJECT_ROOT" <<'PY'
import pathlib
import sys
import yaml

root = pathlib.Path(sys.argv[1])
skill_names = {
    "skill-creator",
    "shogun-agent-status",
    "shogun-bloom-config",
    "shogun-model-list",
    "shogun-model-switch",
    "shogun-readme-sync",
    "shogun-screenshot",
}
for name in sorted(skill_names):
    path = root / "skills" / name / "SKILL.md"
    raw = path.read_text(encoding="utf-8")
    assert raw.startswith("---\n"), path
    _, frontmatter, body = raw.split("---\n", 2)
    metadata = yaml.safe_load(frontmatter)
    assert set(metadata) == {"name", "description"}, (path, metadata)
    assert metadata["name"] == name, path
    assert len(raw.splitlines()) < 500, path
    for forbidden in (
        "$ARGUMENTS",
        "~/.claude/skills",
        "AskUserQuestion",
        "disable-model-invocation:",
        "allowed-tools:",
        "argument-hint:",
    ):
        assert forbidden not in body, (path, forbidden)
PY
}

@test "bundled operational skills preserve Shogun role boundaries" {
    python3 - "$PROJECT_ROOT" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1]) / "skills"
expectations = {
    "shogun-agent-status": ("Shogun", "Karo", "read-only"),
    "shogun-bloom-config": ("Karo", "Gunshi", "Oometsuke"),
    "shogun-model-switch": ("Karo only", "idle", "rollback"),
    "shogun-readme-sync": ("Ashigaru", "Gunshi", "Oometsuke"),
    "shogun-screenshot": ("sanitize", "secret", "bounded"),
}
for name, required in expectations.items():
    text = (root / name / "SKILL.md").read_text(encoding="utf-8")
    for phrase in required:
        assert phrase.casefold() in text.casefold(), (name, phrase)
PY
}

@test "skill creator routes additions through the registry intake contract" {
    run grep -F "shogun-skill-intake" "$PROJECT_ROOT/skills/skill-creator/SKILL.md"
    [ "$status" -eq 0 ]
    run grep -F "codex-only" "$PROJECT_ROOT/skills/skill-creator/SKILL.md"
    [ "$status" -eq 0 ]
    run grep -F "adapted" "$PROJECT_ROOT/skills/skill-creator/SKILL.md"
    [ "$status" -eq 0 ]
    run grep -F "excluded" "$PROJECT_ROOT/skills/skill-creator/SKILL.md"
    [ "$status" -eq 0 ]
}

@test "agent status installs a local adapter instead of assuming a repository-relative asset" {
    [ -x "$PROJECT_ROOT/skills/shogun-agent-status/scripts/agent_status.sh" ]
    run shellcheck "$PROJECT_ROOT/skills/shogun-agent-status/scripts/agent_status.sh"
    [ "$status" -eq 0 ]
}

@test "bundled registry does not grant broad Claude mutation or human-contact tools" {
    python3 - "$PROJECT_ROOT/skills/registry.yaml" <<'PY'
import pathlib, sys, yaml
data = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
for skill in data["skills"]:
    tools = (skill.get("claude") or {}).get("allowed_tools", [])
    assert not ({"Bash", "Edit", "Write", "AskUserQuestion"} & set(tools)), (
        skill["id"], tools
    )
PY
}

@test "unsafe live model switching remains quarantined and has no executable adapter" {
    python3 - "$PROJECT_ROOT/skills/registry.yaml" <<'PY'
import pathlib, sys, yaml
data = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
entry = next(skill for skill in data["skills"] if skill["id"] == "shogun-model-switch")
assert entry["status"] == "quarantined", entry
PY
    [ ! -e "$PROJECT_ROOT/skills/shogun-model-switch/scripts/switch_model.sh" ]
    run grep -F "Do not execute" "$PROJECT_ROOT/skills/shogun-model-switch/SKILL.md"
    [ "$status" -eq 0 ]
}

@test "adapted runtime distributions exclude only design evidence and retain no broken links" {
    python3 - "$PROJECT_ROOT" <<'PY'
import pathlib
import sys
import yaml

root = pathlib.Path(sys.argv[1])
data = yaml.safe_load((root / "skills/registry.yaml").read_text(encoding="utf-8"))
adapted = [skill for skill in data["skills"] if skill["provenance"]["kind"] == "adapted"]
assert len(adapted) == 4
expected = {
    "references/pressure-evidence.md",
    "references/pressure-run.yaml",
}
for skill in adapted:
    assert set(skill["distribution"]["exclude"]) == expected, skill["id"]
    source = root / "skills" / skill["source"]
    body = (source / "SKILL.md").read_text(encoding="utf-8")
    assert "references/pressure-evidence.md" not in body, skill["id"]
    assert "references/pressure-run.yaml" not in body, skill["id"]
    for relative in expected:
        assert (source / relative).is_file(), (skill["id"], relative)
PY
}

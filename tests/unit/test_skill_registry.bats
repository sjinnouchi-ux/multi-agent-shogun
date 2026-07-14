#!/usr/bin/env bats
# Contract-first RED tests for the cross-CLI skill registry.
#
# These tests intentionally exercise the public wrapper only.  The fixture
# repository, runtime destinations, and transaction state all live under the
# Bats-owned temporary directory; no live Shogun state is read or modified.

setup_file() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export REGISTRY_CLI="$PROJECT_ROOT/scripts/skill_registry.sh"

    if [ -n "${SHOGUN_PYTHON_BIN:-}" ] && [ -x "$SHOGUN_PYTHON_BIN" ]; then
        export PYTHON="$SHOGUN_PYTHON_BIN"
    elif [ -x "$PROJECT_ROOT/.venv/bin/python3" ]; then
        export PYTHON="$PROJECT_ROOT/.venv/bin/python3"
    else
        export PYTHON=python3
    fi
}

setup() {
    export TEST_ROOT="$BATS_TEST_TMPDIR/skill-registry"
    export FIXTURE_ROOT="$TEST_ROOT/repository"
    export REGISTRY_FILE="$FIXTURE_ROOT/skills/registry.yaml"
    export LOCK_FILE="$FIXTURE_ROOT/skills/registry.lock.yaml"
    export TEST_HOME="$TEST_ROOT/home"
    export CLAUDE_SKILLS_DIR="$TEST_HOME/.claude/skills"
    export CODEX_SKILLS_DIR="$TEST_HOME/.agents/skills"
    export STATE_ROOT="$TEST_ROOT/state"

    mkdir -p "$FIXTURE_ROOT/skills" "$TEST_HOME" "$STATE_ROOT"
    write_valid_skill "$FIXTURE_ROOT/skills/demo-skill" "demo-skill"
    write_valid_registry
}

write_valid_skill() {
    local skill_dir="$1"
    local skill_name="$2"

    mkdir -p "$skill_dir/scripts" "$skill_dir/references" "$skill_dir/assets"
    cat > "$skill_dir/SKILL.md" <<EOF
---
name: $skill_name
description: Inspect a demo input. Use for registry contract tests; do not use for production work.
---

# Demo skill

Follow the fixture instructions. See [the guide](references/guide.md) when details are needed.

---

Keep body horizontal rules byte-for-byte.
EOF
    printf '# Fixture guide\n' > "$skill_dir/references/guide.md"
    printf '#!/usr/bin/env bash\nprintf "demo\\n"\n' > "$skill_dir/scripts/helper.sh"
    chmod +x "$skill_dir/scripts/helper.sh"
    printf 'fixture\n' > "$skill_dir/assets/example.txt"
}

write_valid_registry() {
    cat > "$REGISTRY_FILE" <<'YAML'
schema_version: 1
outputs:
  claude:
    path: "~/.claude/skills"
  codex:
    path: "~/.agents/skills"
skills:
  - id: demo-skill
    version: 1.0.0
    source: demo-skill
    status: enabled
    targets: [claude, codex]
    activation: automatic
    classification: optional
    eligible_roles: [shogun, karo, ashigaru, gunshi, oometsuke]
    applicability: Registry contract fixture only.
    claude:
      argument_hint: "[topic]"
    codex:
      interface:
        display_name: Demo skill
        short_description: Registry contract fixture
    provenance:
      kind: bundled
      license: MIT
intake_decisions: []
YAML
}

run_registry() {
    run env \
        HOME="$TEST_HOME" \
        XDG_STATE_HOME="$STATE_ROOT" \
        SHOGUN_SKILL_REGISTRY_CLAUDE_DIR="$CLAUDE_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_CODEX_DIR="$CODEX_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_STATE_DIR="$STATE_ROOT" \
        bash "$REGISTRY_CLI" \
        --registry "$REGISTRY_FILE" \
        --lock "$LOCK_FILE" \
        "$@"
}

run_registry_with_target_failure() {
    local target="$1"
    shift
    run env \
        HOME="$TEST_HOME" \
        XDG_STATE_HOME="$STATE_ROOT" \
        SHOGUN_SKILL_REGISTRY_CLAUDE_DIR="$CLAUDE_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_CODEX_DIR="$CODEX_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_STATE_DIR="$STATE_ROOT" \
        SHOGUN_SKILL_REGISTRY_TEST_FAIL_AFTER_TARGET="$target" \
        bash "$REGISTRY_CLI" \
        --registry "$REGISTRY_FILE" \
        --lock "$LOCK_FILE" \
        "$@"
}

run_registry_with_rollback_failure() {
    local target="$1"
    shift
    run env \
        HOME="$TEST_HOME" \
        XDG_STATE_HOME="$STATE_ROOT" \
        SHOGUN_SKILL_REGISTRY_CLAUDE_DIR="$CLAUDE_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_CODEX_DIR="$CODEX_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_STATE_DIR="$STATE_ROOT" \
        SHOGUN_SKILL_REGISTRY_TEST_FAIL_ROLLBACK_AFTER_TARGET="$target" \
        bash "$REGISTRY_CLI" \
        --registry "$REGISTRY_FILE" \
        --lock "$LOCK_FILE" \
        "$@"
}

run_registry_with_interposition() {
    local pause_variable="$1"
    local destination="$2"
    local preserved="$3"
    shift 3
    local control="$TEST_ROOT/interposition-control"
    local command_output="$TEST_ROOT/interposition-command-output.txt"
    local pid ready=0 result=0
    rm -rf "$control" "$preserved"
    mkdir -p "$control"

    env \
        HOME="$TEST_HOME" \
        XDG_STATE_HOME="$STATE_ROOT" \
        SHOGUN_SKILL_REGISTRY_CLAUDE_DIR="$CLAUDE_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_CODEX_DIR="$CODEX_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_STATE_DIR="$STATE_ROOT" \
        SHOGUN_SKILL_REGISTRY_TEST_FAIL_AFTER_TARGET="${INTERRUPT_APPLY_FAILURE_TARGET:-}" \
        SHOGUN_SKILL_REGISTRY_TEST_FAIL_ROLLBACK_AFTER_TARGET="${INTERRUPT_ROLLBACK_FAILURE_TARGET:-}" \
        "$pause_variable=$control" \
        bash "$REGISTRY_CLI" \
        --registry "$REGISTRY_FILE" \
        --lock "$LOCK_FILE" \
        "$@" >"$command_output" 2>&1 &
    pid=$!

    for _attempt in $(seq 1 1000); do
        if [ -f "$control/ready" ]; then
            ready=1
            break
        fi
        sleep 0.01
    done
    if [ "$ready" -ne 1 ]; then
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
        output="$(cat "$command_output" 2>/dev/null || true)"
        status=99
        return 0
    fi
    [ "$(tr -d '\r\n' < "$control/ready")" = "$destination" ]

    mv "$destination" "$preserved"
    mkdir -p "$destination"
    printf 'concurrent unmanaged replacement\n' > "$destination/concurrent.txt"
    : > "$control/continue"

    wait "$pid" || result=$?
    output="$(cat "$command_output")"
    status="$result"
}

run_registry_with_cleanup_destination_swap() {
    local pause_variable="$1"
    local destination="$2"
    local preserved="$3"
    local label="$4"
    shift 4
    local control="$TEST_ROOT/$label-control"
    local command_output="$TEST_ROOT/$label-output.txt"
    local pid ready=0 result=0
    rm -rf "$control" "$preserved"
    mkdir -p "$control"

    env \
        HOME="$TEST_HOME" \
        XDG_STATE_HOME="$STATE_ROOT" \
        SHOGUN_SKILL_REGISTRY_CLAUDE_DIR="$CLAUDE_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_CODEX_DIR="$CODEX_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_STATE_DIR="$STATE_ROOT" \
        SHOGUN_SKILL_REGISTRY_TEST_FAIL_AFTER_TARGET="${INTERRUPT_APPLY_FAILURE_TARGET:-}" \
        SHOGUN_SKILL_REGISTRY_TEST_FAIL_ROLLBACK_AFTER_TARGET="${INTERRUPT_ROLLBACK_FAILURE_TARGET:-}" \
        "$pause_variable=$control" \
        bash "$REGISTRY_CLI" \
        --registry "$REGISTRY_FILE" \
        --lock "$LOCK_FILE" \
        "$@" >"$command_output" 2>&1 &
    pid=$!

    for _attempt in $(seq 1 1000); do
        if [ -f "$control/ready" ]; then
            ready=1
            break
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            break
        fi
        sleep 0.01
    done
    if [ "$ready" -ne 1 ]; then
        wait "$pid" 2>/dev/null || result=$?
        output="$(cat "$command_output" 2>/dev/null || true)"
        status=99
        return 0
    fi

    [ -d "$destination" ]
    mv "$destination" "$preserved"
    mkdir -p "$destination"
    printf 'post-cleanup concurrent replacement\n' > "$destination/concurrent.txt"
    : > "$control/continue"

    wait "$pid" || result=$?
    output="$(cat "$command_output" 2>/dev/null || true)"
    status="$result"
}

run_registry_with_detach_interposition() {
    run_registry_with_interposition \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_BEFORE_DETACH "$@"
}

run_registry_with_snapshot_interposition() {
    run_registry_with_interposition \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_BEFORE_ROLLBACK_SNAPSHOT "$@"
}

run_registry_and_kill_after_compensation_detach() {
    local control="$TEST_ROOT/compensation-detach-control"
    local command_output="$TEST_ROOT/compensation-detach-command-output.txt"
    local pid ready=0 result=0
    rm -rf "$control"
    mkdir -p "$control"

    env \
        HOME="$TEST_HOME" \
        XDG_STATE_HOME="$STATE_ROOT" \
        SHOGUN_SKILL_REGISTRY_CLAUDE_DIR="$CLAUDE_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_CODEX_DIR="$CODEX_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_STATE_DIR="$STATE_ROOT" \
        SHOGUN_SKILL_REGISTRY_TEST_FAIL_AFTER_TARGET=claude \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_COMPENSATION_DETACH="$control" \
        bash "$REGISTRY_CLI" \
        --registry "$REGISTRY_FILE" \
        --lock "$LOCK_FILE" \
        apply --targets claude >"$command_output" 2>&1 &
    pid=$!

    for _attempt in $(seq 1 1000); do
        if [ -f "$control/ready" ]; then
            ready=1
            break
        fi
        sleep 0.01
    done
    if [ "$ready" -ne 1 ]; then
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
        output="$(cat "$command_output" 2>/dev/null || true)"
        status=99
        return 0
    fi
    [ "$(tr -d '\r\n' < "$control/ready")" = "$CLAUDE_SKILLS_DIR/demo-skill" ]

    kill -KILL "$pid"
    wait "$pid" 2>/dev/null || result=$?
    output="$(cat "$command_output" 2>/dev/null || true)"
    status="$result"
}

run_registry_and_kill_at_pause() {
    local pause_variable="$1"
    local expected_subject="$2"
    local label="$3"
    shift 3
    local control="$TEST_ROOT/$label-control"
    local command_output="$TEST_ROOT/$label-command-output.txt"
    local pid ready=0 result=0
    rm -rf "$control"
    mkdir -p "$control"

    env \
        HOME="$TEST_HOME" \
        XDG_STATE_HOME="$STATE_ROOT" \
        SHOGUN_SKILL_REGISTRY_CLAUDE_DIR="$CLAUDE_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_CODEX_DIR="$CODEX_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_STATE_DIR="$STATE_ROOT" \
        SHOGUN_SKILL_REGISTRY_TEST_FAIL_AFTER_TARGET="${INTERRUPT_APPLY_FAILURE_TARGET:-}" \
        SHOGUN_SKILL_REGISTRY_TEST_FAIL_ROLLBACK_AFTER_TARGET="${INTERRUPT_ROLLBACK_FAILURE_TARGET:-}" \
        "$pause_variable=$control" \
        bash "$REGISTRY_CLI" \
        --registry "$REGISTRY_FILE" \
        --lock "$LOCK_FILE" \
        "$@" >"$command_output" 2>&1 &
    pid=$!

    for _attempt in $(seq 1 1000); do
        if [ -f "$control/ready" ]; then
            ready=1
            break
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            break
        fi
        sleep 0.01
    done
    if [ "$ready" -ne 1 ]; then
        wait "$pid" 2>/dev/null || result=$?
        output="$(cat "$command_output" 2>/dev/null || true)"
        status=99
        return 0
    fi
    if [ "$expected_subject" != "*" ]; then
        [ "$(tr -d '\r\n' < "$control/ready")" = "$expected_subject" ]
    fi

    kill -KILL "$pid"
    wait "$pid" 2>/dev/null || result=$?
    output="$(cat "$command_output" 2>/dev/null || true)"
    status="$result"
}

run_registry_with_render_stage_mutation() {
    local control="$TEST_ROOT/render-stage-mutation-control"
    local command_output="$TEST_ROOT/render-stage-mutation-output.txt"
    local pid ready=0 result=0 stage
    rm -rf "$control"
    mkdir -p "$control"

    env \
        HOME="$TEST_HOME" \
        XDG_STATE_HOME="$STATE_ROOT" \
        SHOGUN_SKILL_REGISTRY_CLAUDE_DIR="$CLAUDE_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_CODEX_DIR="$CODEX_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_STATE_DIR="$STATE_ROOT" \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_BEFORE_RENDER_COMMIT="$control" \
        bash "$REGISTRY_CLI" \
        --registry "$REGISTRY_FILE" \
        --lock "$LOCK_FILE" \
        apply --targets claude >"$command_output" 2>&1 &
    pid=$!

    for _attempt in $(seq 1 1000); do
        if [ -f "$control/ready" ]; then
            ready=1
            break
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            break
        fi
        sleep 0.01
    done
    if [ "$ready" -ne 1 ]; then
        wait "$pid" 2>/dev/null || result=$?
        output="$(cat "$command_output" 2>/dev/null || true)"
        status=99
        return 0
    fi

    stage="$(tr -d '\r\n' < "$control/ready")"
    [ -f "$stage/SKILL.md" ]
    printf '\nConcurrent stage mutation.\n' >> "$stage/SKILL.md"
    : > "$control/continue"

    wait "$pid" || result=$?
    output="$(cat "$command_output" 2>/dev/null || true)"
    status="$result"
}

run_registry_with_render_stage_swap() {
    local preserved_valid_stage="$1"
    local collision="${2:-}"
    local pause_variable="${3:-SHOGUN_SKILL_REGISTRY_TEST_PAUSE_BEFORE_RENDER_COMMIT}"
    local control="$TEST_ROOT/render-stage-swap-control"
    local command_output="$TEST_ROOT/render-stage-swap-output.txt"
    local pid ready=0 result=0 stage
    rm -rf "$control" "$preserved_valid_stage"
    mkdir -p "$control"

    env \
        HOME="$TEST_HOME" \
        XDG_STATE_HOME="$STATE_ROOT" \
        SHOGUN_SKILL_REGISTRY_CLAUDE_DIR="$CLAUDE_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_CODEX_DIR="$CODEX_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_STATE_DIR="$STATE_ROOT" \
        "$pause_variable=$control" \
        bash "$REGISTRY_CLI" \
        --registry "$REGISTRY_FILE" \
        --lock "$LOCK_FILE" \
        apply --targets claude >"$command_output" 2>&1 &
    pid=$!

    for _attempt in $(seq 1 1000); do
        if [ -f "$control/ready" ]; then
            ready=1
            break
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            break
        fi
        sleep 0.01
    done
    if [ "$ready" -ne 1 ]; then
        wait "$pid" 2>/dev/null || result=$?
        output="$(cat "$command_output" 2>/dev/null || true)"
        status=99
        return 0
    fi

    stage="$(tr -d '\r\n' < "$control/ready")"
    [ -f "$stage/SKILL.md" ]
    mv "$stage" "$preserved_valid_stage"
    mkdir -p "$stage"
    printf 'concurrent stage replacement\n' > "$stage/sentinel.txt"
    if [ "$collision" = "destination-collision" ]; then
        mkdir -p "$CLAUDE_SKILLS_DIR/demo-skill"
        printf 'concurrent destination\n' \
            > "$CLAUDE_SKILLS_DIR/demo-skill/concurrent.txt"
    fi
    : > "$control/continue"

    wait "$pid" || result=$?
    output="$(cat "$command_output" 2>/dev/null || true)"
    status="$result"
}

run_registry_with_postcommit_swap() {
    local preserved="$1"
    local control="$TEST_ROOT/postcommit-swap-control"
    local command_output="$TEST_ROOT/postcommit-swap-output.txt"
    local pid ready=0 result=0 destination
    rm -rf "$control" "$preserved"
    mkdir -p "$control"

    env \
        HOME="$TEST_HOME" \
        XDG_STATE_HOME="$STATE_ROOT" \
        SHOGUN_SKILL_REGISTRY_CLAUDE_DIR="$CLAUDE_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_CODEX_DIR="$CODEX_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_STATE_DIR="$STATE_ROOT" \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_RENDER_COMMIT="$control" \
        bash "$REGISTRY_CLI" \
        --registry "$REGISTRY_FILE" \
        --lock "$LOCK_FILE" \
        apply --targets claude >"$command_output" 2>&1 &
    pid=$!

    for _attempt in $(seq 1 1000); do
        if [ -f "$control/ready" ]; then
            ready=1
            break
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            break
        fi
        sleep 0.01
    done
    if [ "$ready" -ne 1 ]; then
        wait "$pid" 2>/dev/null || result=$?
        output="$(cat "$command_output" 2>/dev/null || true)"
        status=99
        return 0
    fi

    destination="$(tr -d '\r\n' < "$control/ready")"
    [ -f "$destination/SKILL.md" ]
    mv "$destination" "$preserved"
    mkdir -p "$destination"
    printf 'concurrent unmanaged sentinel\n' > "$destination/sentinel.txt"
    : > "$control/continue"

    wait "$pid" || result=$?
    output="$(cat "$command_output" 2>/dev/null || true)"
    status="$result"
}

run_registry_with_recreated_render_stage() {
    local control="$TEST_ROOT/recreated-render-stage-control"
    local command_output="$TEST_ROOT/recreated-render-stage-output.txt"
    local pid ready=0 result=0 stage
    rm -rf "$control"
    mkdir -p "$control"

    env \
        HOME="$TEST_HOME" \
        XDG_STATE_HOME="$STATE_ROOT" \
        SHOGUN_SKILL_REGISTRY_CLAUDE_DIR="$CLAUDE_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_CODEX_DIR="$CODEX_SKILLS_DIR" \
        SHOGUN_SKILL_REGISTRY_STATE_DIR="$STATE_ROOT" \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_RENDER_RENAME="$control" \
        bash "$REGISTRY_CLI" \
        --registry "$REGISTRY_FILE" \
        --lock "$LOCK_FILE" \
        apply --targets claude >"$command_output" 2>&1 &
    pid=$!

    for _attempt in $(seq 1 1000); do
        if [ -f "$control/ready" ]; then
            ready=1
            break
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            break
        fi
        sleep 0.01
    done
    if [ "$ready" -ne 1 ]; then
        wait "$pid" 2>/dev/null || result=$?
        output="$(cat "$command_output" 2>/dev/null || true)"
        status=99
        return 0
    fi

    stage="$(tr -d '\r\n' < "$control/ready")"
    [ ! -e "$stage" ]
    mkdir -p "$stage"
    printf 'recreated unmanaged stage\n' > "$stage/sentinel.txt"
    : > "$control/continue"

    wait "$pid" || result=$?
    output="$(cat "$command_output" 2>/dev/null || true)"
    status="$result"
}

replace_once() {
    local path="$1"
    local old="$2"
    local new="$3"

    "$PYTHON" -c \
        'import pathlib, sys; p = pathlib.Path(sys.argv[1]); text = p.read_text(encoding="utf-8"); old = sys.argv[2]; assert old in text, old; p.write_text(text.replace(old, sys.argv[3], 1), encoding="utf-8", newline="\n")' \
        "$path" "$old" "$new"
}

duplicate_registry_skill() {
    "$PYTHON" - "$REGISTRY_FILE" <<'PY'
import pathlib
import sys
import yaml

path = pathlib.Path(sys.argv[1])
data = yaml.safe_load(path.read_text(encoding="utf-8"))
data["skills"].append(dict(data["skills"][0]))
path.write_text(
    yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
    newline="\n",
)
PY
}

mutate_registry_skill() {
    local operation="$1"
    local value="${2:-}"

    "$PYTHON" - "$REGISTRY_FILE" "$operation" "$value" <<'PY'
import pathlib
import sys
import yaml

path = pathlib.Path(sys.argv[1])
operation = sys.argv[2]
value = sys.argv[3]
data = yaml.safe_load(path.read_text(encoding="utf-8"))

if operation == "remove":
    data["skills"] = []
else:
    skill = data["skills"][0]
    skill["version"] = "1.0.1"
    if operation == "status":
        skill["status"] = value
    elif operation == "targets":
        targets = value.split(",")
        skill["targets"] = targets
        if "claude" not in targets:
            skill.pop("claude", None)
        if "codex" not in targets:
            skill.pop("codex", None)
    else:
        raise SystemExit(f"unknown fixture mutation: {operation}")

path.write_text(
    yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
    newline="\n",
)
PY
}

add_registry_skill() {
    local skill_id="$1"
    local version="$2"

    write_valid_skill "$FIXTURE_ROOT/skills/$skill_id" "$skill_id"
    "$PYTHON" - "$REGISTRY_FILE" "$skill_id" "$version" <<'PY'
import copy
import pathlib
import sys
import yaml

path = pathlib.Path(sys.argv[1])
skill_id = sys.argv[2]
version = sys.argv[3]
data = yaml.safe_load(path.read_text(encoding="utf-8"))
skill = copy.deepcopy(data["skills"][0])
skill.update(id=skill_id, source=skill_id, version=version)
skill.pop("claude", None)
skill.pop("codex", None)
data["skills"].append(skill)
path.write_text(
    yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
    newline="\n",
)
PY
}

write_adapted_registry() {
    local notice_dir="$FIXTURE_ROOT/skills/third_party/upstream"
    mkdir -p "$notice_dir"
    printf 'Fixture upstream notice.\n' > "$notice_dir/LICENSE"

    "$PYTHON" - "$REGISTRY_FILE" <<'PY'
import pathlib
import sys
import yaml

path = pathlib.Path(sys.argv[1])
data = yaml.safe_load(path.read_text(encoding="utf-8"))
data["skills"][0]["provenance"] = {
    "kind": "adapted",
    "license": "MIT",
    "repository": "https://github.com/example/upstream",
    "tag": "v1.0.0",
    "commit": "0123456789abcdef0123456789abcdef01234567",
    "path": "skills/demo-skill",
    "upstream_sha256": "sha256:" + ("a" * 64),
    "adaptation_revision": 1,
    "notice_file": "third_party/upstream/LICENSE",
}
path.write_text(
    yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
    newline="\n",
)
PY
}

set_distribution_exclude() {
    "$PYTHON" - "$REGISTRY_FILE" "$@" <<'PY'
import pathlib
import sys
import yaml

path = pathlib.Path(sys.argv[1])
data = yaml.safe_load(path.read_text(encoding="utf-8"))
data["skills"][0]["distribution"] = {"exclude": sys.argv[2:]}
path.write_text(
    yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
    newline="\n",
)
PY
}

init_fixture_git() {
    git -C "$FIXTURE_ROOT" init -q
    git -C "$FIXTURE_ROOT" config user.name "Skill Registry Test"
    git -C "$FIXTURE_ROOT" config user.email "skill-registry@example.invalid"
    git -C "$FIXTURE_ROOT" config commit.gpgsign false
    git -C "$FIXTURE_ROOT" config core.autocrlf false
    git -C "$FIXTURE_ROOT" config core.filemode true
    mkdir -p "$TEST_ROOT/empty-hooks"
    git -C "$FIXTURE_ROOT" config core.hooksPath "$TEST_ROOT/empty-hooks"
}

stage_fixture_skills() {
    git -C "$FIXTURE_ROOT" add -- skills
    git -C "$FIXTURE_ROOT" update-index --chmod=+x -- skills/demo-skill/scripts/helper.sh
}

commit_fixture_base() {
    init_fixture_git
    stage_fixture_skills
    git -C "$FIXTURE_ROOT" commit -q -m "fixture baseline"
}

sha256_file() {
    "$PYTHON" -c \
        'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' \
        "$1"
}

tree_hash() {
    "$PYTHON" - "$1" <<'PY'
import hashlib
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
digest = hashlib.sha256()
for path in sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.as_posix()):
    digest.update(path.relative_to(root).as_posix().encode("utf-8"))
    digest.update(b"\0")
    digest.update(path.read_bytes())
    digest.update(b"\0")
print(digest.hexdigest())
PY
}

extract_skill_body() {
    "$PYTHON" - "$1" <<'PY'
import pathlib
import sys

raw = pathlib.Path(sys.argv[1]).read_bytes()
if not raw.startswith(b"---\n"):
    raise SystemExit("missing opening frontmatter delimiter")
end = raw.find(b"\n---\n", 4)
if end < 0:
    raise SystemExit("missing closing frontmatter delimiter")
sys.stdout.buffer.write(raw[end + len(b"\n---\n"):])
PY
}

lock_and_apply_all() {
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets all
    [ "$status" -eq 0 ]
}

latest_transaction_journal() {
    "$PYTHON" - "$STATE_ROOT" <<'PY'
import pathlib
import sys

transactions = pathlib.Path(sys.argv[1]) / "transactions"
paths = sorted(transactions.glob("*.json"))
if not paths:
    raise SystemExit("no transaction journal fixture")
print(paths[-1])
PY
}

journal_transaction_id() {
    "$PYTHON" -c \
        'import json, pathlib, sys; print(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))["transaction_id"])' \
        "$1"
}

assert_journal_status_and_operations() {
    local journal="$1"
    local expected_status="$2"
    local expected_operation_state="$3"

    "$PYTHON" - "$journal" "$expected_status" "$expected_operation_state" <<'PY'
import json
import pathlib
import sys

data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert data["status"] == sys.argv[2], data["status"]
assert data["operations"], "journal has no operations"
assert all(entry["state"] == sys.argv[3] for entry in data["operations"]), data["operations"]
PY
}

make_partial_initial_apply_journal() {
    local journal="$1"

    "$PYTHON" - "$journal" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
data["status"] = "applying"
seen = set()
for entry in data["operations"]:
    target = entry["target"]
    seen.add(target)
    if target == "claude":
        entry["state"] = "applied"
    elif target == "codex":
        entry["state"] = "planned"
    else:
        raise AssertionError(f"unexpected target: {target}")
assert seen == {"claude", "codex"}, seen
path.write_text(
    json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
    newline="\n",
)
PY
}

prepare_external_sentinel() {
    export EXTERNAL_SENTINEL_ROOT="$TEST_ROOT/external-sentinel"
    mkdir -p "$EXTERNAL_SENTINEL_ROOT"
    printf 'must remain unchanged\n' > "$EXTERNAL_SENTINEL_ROOT/sentinel.txt"
    export EXTERNAL_SENTINEL_HASH
    EXTERNAL_SENTINEL_HASH="$(tree_hash "$EXTERNAL_SENTINEL_ROOT")"
}

assert_external_sentinel_unchanged() {
    [ "$(tree_hash "$EXTERNAL_SENTINEL_ROOT")" = "$EXTERNAL_SENTINEL_HASH" ]
}

create_prune_transaction() {
    lock_and_apply_all
    mutate_registry_skill status disabled
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets all
    [ "$status" -eq 0 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ ! -e "$CODEX_SKILLS_DIR/demo-skill" ]
}

rewrite_transaction_journal() {
    local journal="$1"
    local mutation="$2"
    local value="${3:-unused}"

    "$PYTHON" - \
        "$journal" "$mutation" "$value" "$STATE_ROOT" \
        "$FIXTURE_ROOT/skills/demo-skill" "$CLAUDE_SKILLS_DIR" <<'PY'
import json
import pathlib
import shutil
import sys

journal_path = pathlib.Path(sys.argv[1])
mutation = sys.argv[2]
value = sys.argv[3]
state_root = pathlib.Path(sys.argv[4])
source_skill = pathlib.Path(sys.argv[5])
claude_root = pathlib.Path(sys.argv[6])
data = json.loads(journal_path.read_text(encoding="utf-8"))

def forged_backup(label: str) -> str:
    destination = state_root / "forged-backups" / label
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_skill, destination)
    return destination.relative_to(state_root).as_posix()

if mutation == "transaction-id-mismatch":
    data["transaction_id"] = "different-transaction-id"
elif mutation == "absolute-skill-id":
    destination = pathlib.Path(value).resolve()
    entry = dict(data["operations"][0])
    entry.update(
        target="claude",
        skill_id=str(destination),
        action="prune",
        destination=str(destination),
        backup=forged_backup("absolute-skill-id"),
        state="applied",
    )
    data["operations"] = [entry]
elif mutation == "parent-skill-id":
    destination = claude_root / ".." / "escaped-parent-skill"
    entry = dict(data["operations"][0])
    entry.update(
        target="claude",
        skill_id="../escaped-parent-skill",
        action="prune",
        destination=str(destination),
        backup=forged_backup("parent-skill-id"),
        state="applied",
    )
    data["operations"] = [entry]
elif mutation == "backup-path-mismatch":
    entry = data["operations"][0]
    original = state_root.joinpath(*pathlib.PurePosixPath(entry["backup"]).parts)
    alternate = state_root / "alternate-backups" / entry["target"] / entry["skill_id"]
    alternate.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(original, alternate)
    entry["backup"] = alternate.relative_to(state_root).as_posix()
elif mutation == "incomplete":
    data["status"] = "applying"
elif mutation == "tamper-backup":
    entry = data["operations"][0]
    backup = state_root.joinpath(*pathlib.PurePosixPath(entry["backup"]).parts)
    with (backup / "SKILL.md").open("ab") as handle:
        handle.write(b"\nTampered transaction backup.\n")
elif mutation == "prepared-with-applied-operation":
    data["status"] = "prepared"
    data["operations"][0]["state"] = "applied"
elif mutation == "applied-with-planned-operation":
    data["status"] = "applied"
    data["operations"][0]["state"] = "planned"
elif mutation == "single-target-selection-mismatch":
    data["selection"] = "claude"
else:
    raise SystemExit(f"unknown journal mutation: {mutation}")

journal_path.write_text(
    json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
    newline="\n",
)
PY
}

octal_mode() {
    "$PYTHON" -c \
        'import pathlib, stat, sys; print(format(stat.S_IMODE(pathlib.Path(sys.argv[1]).stat().st_mode), "03o"))' \
        "$1"
}

@test "skill registry validation: accepts the minimal portable schema" {
    run_registry validate

    [ "$status" -eq 0 ]
}

@test "skill registry validation: ignores local Python bytecode caches" {
    mkdir -p "$FIXTURE_ROOT/skills/demo-skill/scripts/__pycache__"
    printf 'local bytecode cache\n' \
        > "$FIXTURE_ROOT/skills/demo-skill/scripts/__pycache__/helper.pyc"

    run_registry validate

    [ "$status" -eq 0 ]
}

@test "skill registry validation: rejects duplicate skill ids" {
    duplicate_registry_skill

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"duplicate"* ]]
    [[ "$output" == *"demo-skill"* ]]
}

@test "skill registry validation: rejects skill ids that make transaction artifacts unsafe" {
    local long_id
    long_id="$(printf 'a%.0s' $(seq 1 200))"
    add_registry_skill "$long_id" 1.0.0

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"id"* || "$output" == *"skill"* ]]
}

@test "skill registry validation: reserves the root ownership marker" {
    printf '{"forged": true}\n' \
        > "$FIXTURE_ROOT/skills/demo-skill/.SHOGUN-SKILL.JSON"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"marker"* || "$output" == *"reserved"* ]]
}

@test "skill registry validation: reserves ownership marker directory prefixes" {
    mkdir -p "$FIXTURE_ROOT/skills/demo-skill/.SHOGUN-SKILL.JSON"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"marker"* || "$output" == *"reserved"* ]]
}

@test "skill registry validation: distribution excludes exact design-time files" {
    printf 'design evidence\n' \
        > "$FIXTURE_ROOT/skills/demo-skill/references/design-evidence.md"
    set_distribution_exclude references/design-evidence.md

    lock_and_apply_all

    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill/references/design-evidence.md" ]
    [ ! -e "$CODEX_SKILLS_DIR/demo-skill/references/design-evidence.md" ]
    [ -f "$CLAUDE_SKILLS_DIR/demo-skill/references/guide.md" ]
    [ -f "$CODEX_SKILLS_DIR/demo-skill/references/guide.md" ]
}

@test "skill registry validation: distribution exclusion is fail-closed" {
    local pristine="$TEST_ROOT/pristine-registry.yaml"
    local candidate
    cp "$REGISTRY_FILE" "$pristine"

    for candidate in \
        SKILL.md \
        references \
        references/missing.md \
        ../outside.md \
        /absolute.md \
        'references\\guide.md' \
        references/./guide.md; do
        cp "$pristine" "$REGISTRY_FILE"
        set_distribution_exclude "$candidate"
        run_registry validate
        [ "$status" -eq 2 ]
        [[ "$output" == *"distribution"* || "$output" == *"exclude"* ]]
    done

    cp "$pristine" "$REGISTRY_FILE"
    set_distribution_exclude references/guide.md references/guide.md
    run_registry validate
    [ "$status" -eq 2 ]
    [[ "$output" == *"duplicate"* || "$output" == *"distribution"* ]]
}

@test "skill registry validation: distribution exclusion rejects literal glob paths" {
    local candidate
    for candidate in 'references/*.md' 'references/?.md' 'references/[x].md'; do
        printf 'literal metachar path\n' \
            > "$FIXTURE_ROOT/skills/demo-skill/$candidate"
        set_distribution_exclude "$candidate"

        run_registry validate

        [ "$status" -eq 2 ]
        [[ "$output" == *"glob"* || "$output" == *"distribution"* || "$output" == *"exclude"* ]]
        rm -f "$FIXTURE_ROOT/skills/demo-skill/$candidate"
    done
}

@test "skill registry validation: distribution cannot exclude a source license" {
    printf 'source license\n' > "$FIXTURE_ROOT/skills/demo-skill/LICENSE"
    set_distribution_exclude LICENSE

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"LICENSE"* || "$output" == *"license"* || "$output" == *"distribution"* ]]
}

@test "skill registry validation: retained Markdown cannot link to an excluded file" {
    set_distribution_exclude references/guide.md

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"excluded"* || "$output" == *"distribution"* ]]
}

@test "skill registry validation: rejects portable source path collisions" {
    printf 'one\n' > "$FIXTURE_ROOT/skills/demo-skill/references/Foo.md"
    printf 'two\n' > "$FIXTURE_ROOT/skills/demo-skill/references/foo.md"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"collision"* || "$output" == *"portable"* || "$output" == *"NFC"* || "$output" == *"normalized"* ]]
}

@test "skill registry validation: rejects portable file-directory prefix collisions" {
    printf 'file\n' > "$FIXTURE_ROOT/skills/demo-skill/references/Foo"
    mkdir -p "$FIXTURE_ROOT/skills/demo-skill/references/foo"
    printf 'child\n' > "$FIXTURE_ROOT/skills/demo-skill/references/foo/child.txt"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"collision"* || "$output" == *"portable"* || "$output" == *"ancestor"* ]]
}

@test "skill registry validation: rejects portable directory alias merges" {
    mkdir -p \
        "$FIXTURE_ROOT/skills/demo-skill/references/Refs" \
        "$FIXTURE_ROOT/skills/demo-skill/references/refs"
    printf 'one\n' > "$FIXTURE_ROOT/skills/demo-skill/references/Refs/a.txt"
    printf 'two\n' > "$FIXTURE_ROOT/skills/demo-skill/references/refs/b.txt"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"collision"* || "$output" == *"portable"* || "$output" == *"alias"* ]]
}

@test "skill registry validation: requires NFC-normalized source paths" {
    "$PYTHON" - "$FIXTURE_ROOT/skills/demo-skill/references" <<'PY'
import pathlib
import sys
import unicodedata

root = pathlib.Path(sys.argv[1])
nfd = unicodedata.normalize("NFD", "caf\N{LATIN SMALL LETTER E WITH ACUTE}")
assert nfd != unicodedata.normalize("NFC", nfd)
directory = root / nfd
directory.mkdir()
(directory / "only.txt").write_text("one\n", encoding="utf-8")
PY

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"NFC"* || "$output" == *"normalized"* || "$output" == *"portable"* ]]
}

@test "skill registry validation: rejects Unicode-normalized source path collisions" {
    "$PYTHON" - "$FIXTURE_ROOT/skills/demo-skill/references" <<'PY'
import pathlib
import sys
import unicodedata

root = pathlib.Path(sys.argv[1])
nfc = "caf\N{LATIN SMALL LETTER E WITH ACUTE}.md"
nfd = unicodedata.normalize("NFD", nfc)
assert nfc != nfd
(root / nfc).write_text("one\n", encoding="utf-8")
(root / nfd).write_text("two\n", encoding="utf-8")
PY

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"collision"* || "$output" == *"portable"* || "$output" == *"NFC"* || "$output" == *"normalized"* ]]
}

@test "skill registry render: adapted targets include the validated notice" {
    write_adapted_registry
    lock_and_apply_all

    cmp "$FIXTURE_ROOT/skills/third_party/upstream/LICENSE" \
        "$CLAUDE_SKILLS_DIR/demo-skill/LICENSE"
    cmp "$FIXTURE_ROOT/skills/third_party/upstream/LICENSE" \
        "$CODEX_SKILLS_DIR/demo-skill/LICENSE"
}

@test "skill registry render: reserves generated metadata and adapted LICENSE paths portably" {
    mkdir -p "$FIXTURE_ROOT/skills/demo-skill/Agents/OpenAI.yaml"
    printf 'collision\n' \
        > "$FIXTURE_ROOT/skills/demo-skill/Agents/OpenAI.yaml/child.txt"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"collision"* || "$output" == *"generated"* || "$output" == *"reserved"* ]]

    rm -rf "$FIXTURE_ROOT/skills/demo-skill/Agents"
    write_adapted_registry
    mkdir -p "$FIXTURE_ROOT/skills/demo-skill/license"
    printf 'collision\n' > "$FIXTURE_ROOT/skills/demo-skill/license/child.txt"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"LICENSE"* || "$output" == *"collision"* || "$output" == *"reserved"* ]]
}

@test "skill registry validation: codex-only decisions require a recorded approval" {
    "$PYTHON" - "$REGISTRY_FILE" <<'PY'
import pathlib, sys, yaml
path = pathlib.Path(sys.argv[1])
data = yaml.safe_load(path.read_text(encoding="utf-8"))
data["intake_decisions"] = [
    {
        "id": "upstream-only-skill",
        "disposition": "codex-only",
        "reason": "Useful outside Shogun but conflicts with its routing boundary.",
    }
]
path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8", newline="\n")
PY

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"approval"* ]]
}

@test "skill registry validation: decision approval references must resolve" {
    "$PYTHON" - "$REGISTRY_FILE" <<'PY'
import pathlib, sys, yaml
path = pathlib.Path(sys.argv[1])
data = yaml.safe_load(path.read_text(encoding="utf-8"))
data["approvals"] = []
data["intake_decisions"] = [
    {
        "id": "upstream-only-skill",
        "disposition": "codex-only",
        "reason": "Useful outside Shogun but conflicts with its routing boundary.",
        "approval_ref": "missing-approval",
    }
]
path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8", newline="\n")
PY

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"missing-approval"* || "$output" == *"approval"* ]]
}

@test "skill registry validation: rejects a non-semantic version" {
    replace_once "$REGISTRY_FILE" "version: 1.0.0" "version: release-1"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"version"* ]]
}

@test "skill registry validation: rejects an unknown lifecycle status" {
    replace_once "$REGISTRY_FILE" "status: enabled" "status: archived"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"status"* ]]
}

@test "skill registry validation: rejects an unknown target" {
    replace_once "$REGISTRY_FILE" "targets: [claude, codex]" "targets: [claude, cursor]"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"target"* ]]
    [[ "$output" == *"cursor"* ]]
}

@test "skill registry validation: rejects an unknown eligible role" {
    replace_once "$REGISTRY_FILE" "oometsuke]" "reviewer]"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"role"* ]]
    [[ "$output" == *"reviewer"* ]]
}

@test "skill registry validation: rejects an unknown classification" {
    replace_once "$REGISTRY_FILE" "classification: optional" "classification: mandatory"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"classification"* ]]
}

@test "skill registry validation: rejects authority-expanding Claude tool preapproval" {
    replace_once "$REGISTRY_FILE" 'argument_hint: "[topic]"' \
        $'argument_hint: "[topic]"\n      allowed_tools: [Bash(*)]'

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"allowed_tools"* || "$output" == *"preapproval"* ]]
}

@test "skill registry validation: rejects source path traversal" {
    replace_once "$REGISTRY_FILE" "source: demo-skill" "source: ../outside"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"source"* || "$output" == *"path"* ]]
}

@test "skill registry validation: rejects any symlink in a canonical skill" {
    printf 'outside\n' > "$TEST_ROOT/outside.txt"
    ln -s "$TEST_ROOT/outside.txt" "$FIXTURE_ROOT/skills/demo-skill/references/linked.md"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"symlink"* ]]
}

@test "skill registry validation: rejects a missing SKILL.md" {
    mv "$FIXTURE_ROOT/skills/demo-skill/SKILL.md" "$FIXTURE_ROOT/skills/demo-skill/NOT_A_SKILL.md"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"SKILL.md"* ]]
}

@test "skill registry validation: rejects malformed YAML frontmatter" {
    cat > "$FIXTURE_ROOT/skills/demo-skill/SKILL.md" <<'EOF'
---
name: [unterminated
description: malformed fixture
---

Malformed fixture body.
EOF

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"frontmatter"* || "$output" == *"YAML"* ]]
}

@test "skill registry validation: requires both name and description" {
    cat > "$FIXTURE_ROOT/skills/demo-skill/SKILL.md" <<'EOF'
---
name: demo-skill
---

Missing description.
EOF

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"description"* ]]
}

@test "skill registry validation: requires id name and directory to match" {
    replace_once "$FIXTURE_ROOT/skills/demo-skill/SKILL.md" "name: demo-skill" "name: other-skill"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"demo-skill"* ]]
    [[ "$output" == *"other-skill"* ]]
}

@test "skill registry validation: rejects unknown shared frontmatter" {
    replace_once "$FIXTURE_ROOT/skills/demo-skill/SKILL.md" \
        "description: Inspect a demo input. Use for registry contract tests; do not use for production work." \
        $'description: Inspect a demo input. Use for registry contract tests; do not use for production work.\nargument-hint: "[topic]"'

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"argument-hint"* ]]
}

@test "skill registry validation: rejects Claude placeholders in shared Markdown" {
    printf '\nProcess $ARGUMENTS before continuing.\n' >> "$FIXTURE_ROOT/skills/demo-skill/SKILL.md"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *'${CLAUDE_'* || "$output" == *'$ARGUMENTS'* || "$output" == *"placeholder"* ]]
}

@test "skill registry validation: rejects a missing relative reference" {
    replace_once "$FIXTURE_ROOT/skills/demo-skill/SKILL.md" \
        "references/guide.md" "references/missing.md"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"references/missing.md"* ]]
}

@test "skill registry validation: checks links in nested Markdown assets" {
    mkdir -p "$FIXTURE_ROOT/skills/demo-skill/references/nested"
    cat > "$FIXTURE_ROOT/skills/demo-skill/references/nested/guide.md" <<'EOF'
[Missing neighbor](missing.md)
EOF

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"missing.md"* ]]
}

@test "skill registry validation: checks reference-style Markdown destinations" {
    cat > "$FIXTURE_ROOT/skills/demo-skill/references/reference-style.md" <<'EOF'
[Details][details]

[details]: missing-reference.md
EOF

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"missing-reference.md"* ]]
}

@test "skill registry validation: rejects machine-specific absolute paths in shared Markdown" {
    printf '\nRun `/etc/private/tool.conf`.\n' \
        >> "$FIXTURE_ROOT/skills/demo-skill/references/guide.md"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"absolute"* || "$output" == *"machine-specific"* ]]
}

@test "skill registry validation: rejects every absolute POSIX path token regardless of root" {
    local guide="$FIXTURE_ROOT/skills/demo-skill/references/guide.md"
    local pristine="$TEST_ROOT/pristine-guide.md"
    local absolute_path
    cp "$guide" "$pristine"

    for absolute_path in \
        /bin/sh \
        /proc/self/status \
        /dev \
        /sys \
        /lib \
        /sbin \
        /nix \
        /Applications; do
        cp "$pristine" "$guide"
        printf '\nRun `%s`.\n' "$absolute_path" >> "$guide"

        run_registry validate

        [ "$status" -eq 2 ]
        [[ "$output" == *"absolute"* || "$output" == *"self-contained"* ]]
    done
}

@test "skill registry validation: permits explicit URLs and portable variable-rooted paths" {
    cat >> "$FIXTURE_ROOT/skills/demo-skill/references/guide.md" <<'EOF'

Visit https://example.invalid/bin/sh for the public guide.
Use `${WORKSPACE}/bin/tool` or `$WORKSPACE/bin/tool` after defining WORKSPACE.
EOF

    run_registry validate

    [ "$status" -eq 0 ]
}

@test "skill registry validation: rejects bare repository commands in shared Markdown" {
    printf '\nRun `scripts/private_helper.sh now`.\n' \
        >> "$FIXTURE_ROOT/skills/demo-skill/references/guide.md"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"repository"* || "$output" == *"self-contained"* ]]
}

@test "skill registry validation: checks relative paths in Markdown HTML attributes" {
    printf '\n<img src="missing/private.png" alt="missing">\n' \
        >> "$FIXTURE_ROOT/skills/demo-skill/references/guide.md"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"missing/private.png"* || "$output" == *"missing relative"* ]]
}

@test "skill registry validation: rejects duplicate YAML mapping keys" {
    replace_once "$REGISTRY_FILE" "schema_version: 1" \
        $'schema_version: 1\nschema_version: 1'

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"duplicate"* || "$output" == *"schema_version"* ]]
}

@test "skill registry validation: rejects a boolean schema version" {
    replace_once "$REGISTRY_FILE" "schema_version: 1" "schema_version: true"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"schema_version"* || "$output" == *"integer"* ]]
}

@test "skill registry validation: rejects a boolean adaptation revision" {
    write_adapted_registry
    replace_once "$REGISTRY_FILE" "adaptation_revision: 1" \
        "adaptation_revision: true"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"adaptation_revision"* || "$output" == *"integer"* ]]
}

@test "skill registry validation: rejects a notice through a symlinked parent" {
    write_adapted_registry
    mkdir -p "$TEST_ROOT/outside-notice"
    printf 'Outside notice.\n' > "$TEST_ROOT/outside-notice/LICENSE"
    rm -rf "$FIXTURE_ROOT/skills/third_party/upstream"
    ln -s "$TEST_ROOT/outside-notice" \
        "$FIXTURE_ROOT/skills/third_party/upstream"

    run_registry validate

    [ "$status" -eq 2 ]
    [[ "$output" == *"notice"* || "$output" == *"symlink"* || "$output" == *"escape"* ]]
}

@test "skill registry render: isolates Claude and Codex metadata" {
    lock_and_apply_all

    local claude_skill="$CLAUDE_SKILLS_DIR/demo-skill/SKILL.md"
    local codex_skill="$CODEX_SKILLS_DIR/demo-skill/SKILL.md"
    local codex_metadata="$CODEX_SKILLS_DIR/demo-skill/agents/openai.yaml"

    [ -f "$codex_metadata" ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill/agents/openai.yaml" ]

    "$PYTHON" - "$claude_skill" "$codex_skill" "$codex_metadata" <<'PY'
import pathlib
import sys
import yaml

def frontmatter(path):
    raw = pathlib.Path(path).read_text(encoding="utf-8")
    return yaml.safe_load(raw.split("---", 2)[1])

claude = frontmatter(sys.argv[1])
codex = frontmatter(sys.argv[2])
metadata = yaml.safe_load(pathlib.Path(sys.argv[3]).read_text(encoding="utf-8"))
assert claude["argument-hint"] == "[topic]"
assert "allowed-tools" not in claude
assert "argument-hint" not in codex
assert "allowed-tools" not in codex
assert metadata["interface"]["display_name"] == "Demo skill"
assert metadata["interface"]["short_description"] == "Registry contract fixture"
PY
}

@test "skill registry render: maps manual activation without shared frontmatter leakage" {
    replace_once "$REGISTRY_FILE" "activation: automatic" "activation: manual"

    lock_and_apply_all

    ! grep -q 'disable-model-invocation\|allow_implicit_invocation' "$CODEX_SKILLS_DIR/demo-skill/SKILL.md"
    "$PYTHON" - \
        "$CLAUDE_SKILLS_DIR/demo-skill/SKILL.md" \
        "$CODEX_SKILLS_DIR/demo-skill/agents/openai.yaml" <<'PY'
import pathlib
import sys
import yaml

claude_raw = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
claude = yaml.safe_load(claude_raw.split("---", 2)[1])
codex = yaml.safe_load(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
assert claude["disable-model-invocation"] is True
assert codex["policy"]["allow_implicit_invocation"] is False
PY
}

@test "skill registry render: preserves the canonical Markdown body byte for byte" {
    lock_and_apply_all

    extract_skill_body "$FIXTURE_ROOT/skills/demo-skill/SKILL.md" > "$TEST_ROOT/source.body"
    extract_skill_body "$CLAUDE_SKILLS_DIR/demo-skill/SKILL.md" > "$TEST_ROOT/claude.body"
    extract_skill_body "$CODEX_SKILLS_DIR/demo-skill/SKILL.md" > "$TEST_ROOT/codex.body"

    cmp "$TEST_ROOT/source.body" "$TEST_ROOT/claude.body"
    cmp "$TEST_ROOT/source.body" "$TEST_ROOT/codex.body"
}

@test "skill registry lock: repeated generation is deterministic and machine independent" {
    run_registry lock
    [ "$status" -eq 0 ]
    local first_hash
    first_hash="$(sha256_file "$LOCK_FILE")"

    run_registry lock
    [ "$status" -eq 0 ]
    local second_hash
    second_hash="$(sha256_file "$LOCK_FILE")"

    [ "$first_hash" = "$second_hash" ]
    ! grep -Fq "$TEST_ROOT" "$LOCK_FILE"
    ! grep -Eq 'generated_at|timestamp|mtime|username' "$LOCK_FILE"
}

@test "skill registry lock: check rejects a semantically inert YAML comment" {
    run_registry lock
    [ "$status" -eq 0 ]
    printf '# noncanonical hand edit\n' >> "$LOCK_FILE"
    local edited_hash
    edited_hash="$(sha256_file "$LOCK_FILE")"

    run_registry check

    [ "$status" -eq 2 ]
    [[ "$output" == *"drift"* || "$output" == *"canonical"* ]]
    [ "$(sha256_file "$LOCK_FILE")" = "$edited_hash" ]
}

@test "skill registry lock: check requires exactly one terminal newline" {
    run_registry lock
    [ "$status" -eq 0 ]
    "$PYTHON" - "$LOCK_FILE" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
raw = path.read_bytes()
assert raw.endswith(b"\n")
path.write_bytes(raw[:-1])
PY
    local edited_hash
    edited_hash="$(sha256_file "$LOCK_FILE")"

    run_registry check

    [ "$status" -eq 2 ]
    [[ "$output" == *"drift"* || "$output" == *"canonical"* || "$output" == *"newline"* ]]
    [ "$(sha256_file "$LOCK_FILE")" = "$edited_hash" ]
}

@test "skill registry lock: records complete file inventories executable bits and metrics" {
    run_registry lock
    [ "$status" -eq 0 ]

    "$PYTHON" - "$LOCK_FILE" <<'PY'
import pathlib
import sys
import yaml

data = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))

def dictionaries(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from dictionaries(child)
    elif isinstance(value, list):
        for child in value:
            yield from dictionaries(child)

nodes = list(dictionaries(data))
helper = next(node for node in nodes if node.get("path") == "scripts/helper.sh")
assert helper["executable"] is True
assert isinstance(helper["bytes"], int) and helper["bytes"] > 0
assert str(helper["sha256"]).startswith("sha256:")
assert any(node.get("path") == "SKILL.md" for node in nodes)
assert any(node.get("path") == "agents/openai.yaml" for node in nodes)
assert any({"description_chars", "listing_chars", "bytes", "lines"}.issubset(node) for node in nodes)
assert any("tree_sha256" in node for node in nodes)
PY
}

@test "skill registry lock: records the adapted notice bytes and hash" {
    write_adapted_registry
    run_registry lock
    [ "$status" -eq 0 ]

    "$PYTHON" - "$LOCK_FILE" \
        "$FIXTURE_ROOT/skills/third_party/upstream/LICENSE" <<'PY'
import hashlib
import pathlib
import sys
import yaml

lock = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
notice_raw = pathlib.Path(sys.argv[2]).read_bytes()

def dictionaries(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from dictionaries(child)
    elif isinstance(value, list):
        for child in value:
            yield from dictionaries(child)

notice = next(
    node
    for node in dictionaries(lock)
    if node.get("path") == "skills/third_party/upstream/LICENSE"
)
assert notice["bytes"] == len(notice_raw)
assert notice["sha256"] == "sha256:" + hashlib.sha256(notice_raw).hexdigest()
assert notice.get("executable") is False
PY
}

@test "skill registry lock: check detects adapted notice tampering without rewriting the lock" {
    write_adapted_registry
    run_registry lock
    [ "$status" -eq 0 ]
    local before
    before="$(sha256_file "$LOCK_FILE")"
    printf 'Tampered notice.\n' >> \
        "$FIXTURE_ROOT/skills/third_party/upstream/LICENSE"

    run_registry check

    [ "$status" -eq 2 ]
    [[ "$output" == *"notice"* || "$output" == *"drift"* || "$output" == *"hash"* ]]
    [ "$(sha256_file "$LOCK_FILE")" = "$before" ]
}

@test "skill registry lock: Git index executable mode overrides the working tree mode" {
    commit_fixture_base
    chmod -x "$FIXTURE_ROOT/skills/demo-skill/scripts/helper.sh"
    [ ! -x "$FIXTURE_ROOT/skills/demo-skill/scripts/helper.sh" ]

    run_registry lock
    [ "$status" -eq 0 ]

    "$PYTHON" - "$LOCK_FILE" <<'PY'
import pathlib
import sys
import yaml

lock = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))

def dictionaries(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from dictionaries(child)
    elif isinstance(value, list):
        for child in value:
            yield from dictionaries(child)

helpers = [
    node
    for node in dictionaries(lock)
    if node.get("path") == "scripts/helper.sh"
]
assert len(helpers) == 3
assert all(node["executable"] is True for node in helpers)
PY
}

@test "skill registry lock: a corrupt Git index fails closed without replacing the lock" {
    commit_fixture_base
    run_registry lock
    [ "$status" -eq 0 ]
    local before
    before="$(sha256_file "$LOCK_FILE")"
    printf 'corrupt fixture index\n' > "$FIXTURE_ROOT/.git/index"

    run_registry lock

    [ "$status" -eq 2 ]
    [[ "$output" == *"Git"* || "$output" == *"git"* || "$output" == *"index"* ]]
    [ "$(sha256_file "$LOCK_FILE")" = "$before" ]
}

@test "skill registry lock: check detects source tampering without rewriting the lock" {
    run_registry lock
    [ "$status" -eq 0 ]
    local before
    before="$(sha256_file "$LOCK_FILE")"
    printf '\nTampered.\n' >> "$FIXTURE_ROOT/skills/demo-skill/SKILL.md"

    run_registry check

    [ "$status" -eq 2 ]
    [[ "$output" == *"drift"* || "$output" == *"hash"* || "$output" == *"tamper"* ]]
    [ "$(sha256_file "$LOCK_FILE")" = "$before" ]
}

@test "skill registry lock: check rejects an extra canonical source file" {
    run_registry lock
    [ "$status" -eq 0 ]
    printf 'unexpected\n' > "$FIXTURE_ROOT/skills/demo-skill/unexpected.txt"

    run_registry check

    [ "$status" -eq 2 ]
    [[ "$output" == *"extra"* || "$output" == *"unexpected.txt"* ]]
}

@test "skill registry lock: failed regeneration preserves the previous lock atomically" {
    run_registry lock
    [ "$status" -eq 0 ]
    local before
    before="$(sha256_file "$LOCK_FILE")"
    replace_once "$REGISTRY_FILE" "version: 1.0.0" "version: invalid"

    run_registry lock

    [ "$status" -eq 2 ]
    [ "$(sha256_file "$LOCK_FILE")" = "$before" ]
}

@test "skill registry version gate: same-version source changes fail against the explicit base" {
    commit_fixture_base
    local base_ref
    base_ref="$(git -C "$FIXTURE_ROOT" rev-parse HEAD)"
    printf '\nSame-version source change.\n' >> "$FIXTURE_ROOT/skills/demo-skill/SKILL.md"
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry check --base-ref "$base_ref"

    [ "$status" -eq 2 ]
    [[ "$output" == *"version"* || "$output" == *"base"* ]]
}

@test "skill registry version gate: same-version lifecycle changes fail against the explicit base" {
    commit_fixture_base
    local base_ref
    base_ref="$(git -C "$FIXTURE_ROOT" rev-parse HEAD)"
    replace_once "$REGISTRY_FILE" "status: enabled" "status: disabled"
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry check --base-ref "$base_ref"

    [ "$status" -eq 2 ]
    [[ "$output" == *"version"* || "$output" == *"base"* ]]
}

@test "skill registry version gate: a greater semantic version accepts changed source" {
    commit_fixture_base
    local base_ref
    base_ref="$(git -C "$FIXTURE_ROOT" rev-parse HEAD)"
    replace_once "$REGISTRY_FILE" "version: 1.0.0" "version: 1.0.1"
    printf '\nVersioned source change.\n' >> "$FIXTURE_ROOT/skills/demo-skill/SKILL.md"
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry check --base-ref "$base_ref"

    [ "$status" -eq 0 ]
}

@test "skill registry version gate: a newly introduced skill must start at 1.0.0" {
    commit_fixture_base
    local base_ref
    base_ref="$(git -C "$FIXTURE_ROOT" rev-parse HEAD)"
    add_registry_skill second-skill 2.0.0
    stage_fixture_skills
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry check --base-ref "$base_ref"

    [ "$status" -eq 2 ]
    [[ "$output" == *"second-skill"* && "$output" == *"1.0.0"* ]]
}

@test "skill registry version gate: direct removal of a non-revoked skill fails" {
    commit_fixture_base
    local base_ref
    base_ref="$(git -C "$FIXTURE_ROOT" rev-parse HEAD)"
    mutate_registry_skill remove
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry check --base-ref "$base_ref"

    [ "$status" -eq 2 ]
    [[ "$output" == *"revoked"* ]]
}

@test "skill registry version gate: removal after a committed revoked lifecycle succeeds" {
    replace_once "$REGISTRY_FILE" "version: 1.0.0" "version: 2.0.0"
    replace_once "$REGISTRY_FILE" "status: enabled" "status: revoked"
    commit_fixture_base
    local base_ref
    base_ref="$(git -C "$FIXTURE_ROOT" rev-parse HEAD)"
    mutate_registry_skill remove
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry check --base-ref "$base_ref"

    [ "$status" -eq 0 ]
}

@test "skill registry version gate: a base without schema v1 is a first-migration exemption" {
    init_fixture_git
    printf 'Pre-registry baseline.\n' > "$FIXTURE_ROOT/BASELINE.txt"
    git -C "$FIXTURE_ROOT" add -- BASELINE.txt
    git -C "$FIXTURE_ROOT" commit -q -m "pre-registry baseline"
    local base_ref
    base_ref="$(git -C "$FIXTURE_ROOT" rev-parse HEAD)"
    ! git -C "$FIXTURE_ROOT" cat-file -e "$base_ref:skills/registry.yaml"
    stage_fixture_skills
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry check --base-ref "$base_ref"

    [ "$status" -eq 0 ]
}

@test "skill registry apply: materializes both targets preserves unmanaged skills and is idempotent" {
    mkdir -p "$CLAUDE_SKILLS_DIR/local-only" "$CODEX_SKILLS_DIR/local-only"
    printf 'unmanaged\n' > "$CLAUDE_SKILLS_DIR/local-only/note.txt"
    printf 'unmanaged\n' > "$CODEX_SKILLS_DIR/local-only/note.txt"

    lock_and_apply_all
    local first_hash
    first_hash="$(tree_hash "$TEST_HOME")"

    run_registry apply --targets all
    [ "$status" -eq 0 ]

    [ -f "$CLAUDE_SKILLS_DIR/demo-skill/SKILL.md" ]
    [ -f "$CODEX_SKILLS_DIR/demo-skill/SKILL.md" ]
    [ -f "$CLAUDE_SKILLS_DIR/local-only/note.txt" ]
    [ -f "$CODEX_SKILLS_DIR/local-only/note.txt" ]
    [ "$(tree_hash "$TEST_HOME")" = "$first_hash" ]
}

@test "skill registry apply contract: check drift leaves targets and transaction state unchanged" {
    mkdir -p "$CLAUDE_SKILLS_DIR/sentinel" "$CODEX_SKILLS_DIR/sentinel"
    printf 'claude before\n' > "$CLAUDE_SKILLS_DIR/sentinel/value.txt"
    printf 'codex before\n' > "$CODEX_SKILLS_DIR/sentinel/value.txt"
    printf 'state before\n' > "$STATE_ROOT/sentinel.txt"
    run_registry lock
    [ "$status" -eq 0 ]
    printf '\nDrift after lock.\n' >> "$FIXTURE_ROOT/skills/demo-skill/SKILL.md"
    local claude_before codex_before state_before
    claude_before="$(tree_hash "$CLAUDE_SKILLS_DIR")"
    codex_before="$(tree_hash "$CODEX_SKILLS_DIR")"
    state_before="$(tree_hash "$STATE_ROOT")"

    run_registry apply --targets all

    [ "$status" -ne 0 ]
    [[ "$output" == *"drift"* || "$output" == *"hash"* ]]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR")" = "$claude_before" ]
    [ "$(tree_hash "$CODEX_SKILLS_DIR")" = "$codex_before" ]
    [ "$(tree_hash "$STATE_ROOT")" = "$state_before" ]
}

@test "skill registry apply: revalidates a render stage after commit" {
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry_with_render_stage_mutation

    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    local journal transaction
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    assert_journal_status_and_operations "$journal" compensated compensated
    [ -z "$(find "$CLAUDE_SKILLS_DIR" -maxdepth 1 -name "*$transaction*" -print -quit)" ]
}

@test "skill registry apply: preserves a whole-directory render stage replacement" {
    run_registry lock
    [ "$status" -eq 0 ]
    local valid_stage="$TEST_ROOT/preserved-valid-render-stage"

    run_registry_with_render_stage_swap "$valid_stage"

    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ -f "$valid_stage/SKILL.md" ]
    local journal transaction preserved_concurrent
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    preserved_concurrent="$CLAUDE_SKILLS_DIR/.shogun-concurrent-preserved-$transaction-demo-skill"
    [ -f "$preserved_concurrent/sentinel.txt" ]
    [ "$(tr -d '\r\n' < "$preserved_concurrent/sentinel.txt")" = \
        "concurrent stage replacement" ]
    "$PYTHON" - "$journal" <<'PY'
import json
import pathlib
import sys

data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert data["status"] not in {"applied", "compensated", "rolled_back"}, data["status"]
PY
}

@test "skill registry apply: carries render identity across the return boundary" {
    run_registry lock
    [ "$status" -eq 0 ]
    local valid_stage="$TEST_ROOT/preserved-return-boundary-stage"

    run_registry_with_render_stage_swap \
        "$valid_stage" \
        "" \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_RENDER_STAGE_RETURN

    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ -f "$valid_stage/SKILL.md" ]
    local journal transaction preserved_concurrent
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    preserved_concurrent="$CLAUDE_SKILLS_DIR/.shogun-concurrent-preserved-$transaction-demo-skill"
    [ -f "$preserved_concurrent/sentinel.txt" ]
}

@test "skill registry apply: preserves a swapped stage when its commit collides" {
    run_registry lock
    [ "$status" -eq 0 ]
    local valid_stage="$TEST_ROOT/preserved-valid-colliding-stage"

    run_registry_with_render_stage_swap "$valid_stage" destination-collision

    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    [ -f "$valid_stage/SKILL.md" ]
    [ -f "$CLAUDE_SKILLS_DIR/demo-skill/concurrent.txt" ]
    local journal transaction preserved_stage
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    preserved_stage="$CLAUDE_SKILLS_DIR/.shogun-stage-preserved-$transaction-demo-skill"
    [ -f "$preserved_stage/sentinel.txt" ]
    [ "$(tr -d '\r\n' < "$preserved_stage/sentinel.txt")" = \
        "concurrent stage replacement" ]
}

@test "skill registry apply: never deletes a postcommit replacement directory" {
    run_registry lock
    [ "$status" -eq 0 ]
    local preserved="$TEST_ROOT/preserved-render-commit"

    run_registry_with_postcommit_swap "$preserved"

    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    local journal transaction preserved_concurrent
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    preserved_concurrent="$CLAUDE_SKILLS_DIR/.shogun-concurrent-preserved-$transaction-demo-skill"
    [ -f "$preserved_concurrent/sentinel.txt" ]
    [ "$(tr -d '\r\n' < "$preserved_concurrent/sentinel.txt")" = \
        "concurrent unmanaged sentinel" ]
    [ -f "$preserved/SKILL.md" ]
    "$PYTHON" - "$journal" <<'PY'
import json
import pathlib
import sys

data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert data["status"] not in {"applied", "compensated", "rolled_back"}, data["status"]
PY
}

@test "skill registry apply: preserves a stage recreated after render rename" {
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry_with_recreated_render_stage

    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    local journal transaction preserved_stage
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    preserved_stage="$CLAUDE_SKILLS_DIR/.shogun-stage-preserved-$transaction-demo-skill"
    [ -f "$preserved_stage/sentinel.txt" ]
}

@test "skill registry apply target: claude selection leaves Codex untouched" {
    mkdir -p "$CODEX_SKILLS_DIR/demo-skill"
    printf 'personal codex\n' > "$CODEX_SKILLS_DIR/demo-skill/personal.txt"
    local codex_before
    codex_before="$(tree_hash "$CODEX_SKILLS_DIR/demo-skill")"
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry apply --targets claude

    [ "$status" -eq 0 ]
    [ -f "$CLAUDE_SKILLS_DIR/demo-skill/SKILL.md" ]
    [ "$(tree_hash "$CODEX_SKILLS_DIR/demo-skill")" = "$codex_before" ]
}

@test "skill registry apply target: codex selection leaves Claude untouched" {
    mkdir -p "$CLAUDE_SKILLS_DIR/demo-skill"
    printf 'personal claude\n' > "$CLAUDE_SKILLS_DIR/demo-skill/personal.txt"
    local claude_before
    claude_before="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry apply --targets codex

    [ "$status" -eq 0 ]
    [ -f "$CODEX_SKILLS_DIR/demo-skill/SKILL.md" ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$claude_before" ]
}

@test "skill registry rollback initial: initial install rollback removes both managed outputs" {
    lock_and_apply_all

    run_registry rollback

    [ "$status" -eq 0 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ ! -e "$CODEX_SKILLS_DIR/demo-skill" ]
}

@test "skill registry prune: disabled skill removal rolls back to both managed outputs" {
    lock_and_apply_all
    local claude_before codex_before
    claude_before="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    codex_before="$(tree_hash "$CODEX_SKILLS_DIR/demo-skill")"
    mutate_registry_skill status disabled
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry apply --targets all

    [ "$status" -eq 0 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ ! -e "$CODEX_SKILLS_DIR/demo-skill" ]

    run_registry rollback
    [ "$status" -eq 0 ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$claude_before" ]
    [ "$(tree_hash "$CODEX_SKILLS_DIR/demo-skill")" = "$codex_before" ]
}

@test "skill registry prune: target loss removes only Codex and rollback restores it" {
    lock_and_apply_all
    local claude_before codex_before
    claude_before="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    codex_before="$(tree_hash "$CODEX_SKILLS_DIR/demo-skill")"
    mutate_registry_skill targets claude
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry apply --targets all

    [ "$status" -eq 0 ]
    [ -f "$CLAUDE_SKILLS_DIR/demo-skill/SKILL.md" ]
    [ ! -e "$CODEX_SKILLS_DIR/demo-skill" ]

    run_registry rollback
    [ "$status" -eq 0 ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$claude_before" ]
    [ "$(tree_hash "$CODEX_SKILLS_DIR/demo-skill")" = "$codex_before" ]
}

@test "skill registry prune: registry removal deletes managed outputs and rollback restores them" {
    lock_and_apply_all
    local claude_before codex_before
    claude_before="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    codex_before="$(tree_hash "$CODEX_SKILLS_DIR/demo-skill")"
    mutate_registry_skill remove
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry apply --targets all

    [ "$status" -eq 0 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ ! -e "$CODEX_SKILLS_DIR/demo-skill" ]

    run_registry rollback
    [ "$status" -eq 0 ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$claude_before" ]
    [ "$(tree_hash "$CODEX_SKILLS_DIR/demo-skill")" = "$codex_before" ]
}

@test "skill registry prune: markerless same-name replacement is preserved" {
    lock_and_apply_all
    mv "$CLAUDE_SKILLS_DIR/demo-skill" "$TEST_ROOT/previous-managed-claude"
    mkdir -p "$CLAUDE_SKILLS_DIR/demo-skill"
    printf 'personal replacement\n' > "$CLAUDE_SKILLS_DIR/demo-skill/personal.txt"
    local markerless_before
    markerless_before="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    mutate_registry_skill status disabled
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry apply --targets claude

    [ "$status" -eq 0 ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$markerless_before" ]
}

@test "skill registry rollback latest: only the newest transaction is reverted" {
    lock_and_apply_all
    local claude_first codex_first
    claude_first="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    codex_first="$(tree_hash "$CODEX_SKILLS_DIR/demo-skill")"
    replace_once "$REGISTRY_FILE" "version: 1.0.0" "version: 1.0.1"
    printf '\nSecond release.\n' >> "$FIXTURE_ROOT/skills/demo-skill/SKILL.md"
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets all
    [ "$status" -eq 0 ]
    grep -q '^Second release\.$' "$CLAUDE_SKILLS_DIR/demo-skill/SKILL.md"
    grep -q '^Second release\.$' "$CODEX_SKILLS_DIR/demo-skill/SKILL.md"

    run_registry rollback

    [ "$status" -eq 0 ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$claude_first" ]
    [ "$(tree_hash "$CODEX_SKILLS_DIR/demo-skill")" = "$codex_first" ]
}

@test "skill registry rollback: restores adopted same-name directories on latest rollback" {
    mkdir -p "$CLAUDE_SKILLS_DIR/demo-skill" "$CODEX_SKILLS_DIR/demo-skill"
    printf 'legacy claude\n' > "$CLAUDE_SKILLS_DIR/demo-skill/legacy.txt"
    printf 'legacy codex\n' > "$CODEX_SKILLS_DIR/demo-skill/legacy.txt"

    lock_and_apply_all
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill/legacy.txt" ]
    [ ! -e "$CODEX_SKILLS_DIR/demo-skill/legacy.txt" ]

    run_registry rollback

    [ "$status" -eq 0 ]
    grep -q '^legacy claude$' "$CLAUDE_SKILLS_DIR/demo-skill/legacy.txt"
    grep -q '^legacy codex$' "$CODEX_SKILLS_DIR/demo-skill/legacy.txt"
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill/SKILL.md" ]
    [ ! -e "$CODEX_SKILLS_DIR/demo-skill/SKILL.md" ]
}

@test "skill registry rollback: refuses to overwrite a later unmanaged replacement" {
    lock_and_apply_all
    local codex_before
    codex_before="$(tree_hash "$CODEX_SKILLS_DIR/demo-skill")"
    rm -rf "$CLAUDE_SKILLS_DIR/demo-skill"
    mkdir -p "$CLAUDE_SKILLS_DIR/demo-skill"
    printf '%s\n' 'later unmanaged replacement' > "$CLAUDE_SKILLS_DIR/demo-skill/SKILL.md"

    run_registry rollback

    [ "$status" -ne 0 ]
    grep -q '^later unmanaged replacement$' "$CLAUDE_SKILLS_DIR/demo-skill/SKILL.md"
    [ "$(tree_hash "$CODEX_SKILLS_DIR/demo-skill")" = "$codex_before" ]
}

@test "skill registry transaction: forced second-target failure restores the first target" {
    mkdir -p "$CLAUDE_SKILLS_DIR/demo-skill" "$CODEX_SKILLS_DIR/demo-skill"
    printf 'legacy claude\n' > "$CLAUDE_SKILLS_DIR/demo-skill/legacy.txt"
    printf 'legacy codex\n' > "$CODEX_SKILLS_DIR/demo-skill/legacy.txt"
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry_with_target_failure claude apply --targets all

    [ "$status" -ne 0 ]
    [[ "$output" == *"claude"* && "$output" == *"compensat"* ]]
    grep -q '^legacy claude$' "$CLAUDE_SKILLS_DIR/demo-skill/legacy.txt"
    grep -q '^legacy codex$' "$CODEX_SKILLS_DIR/demo-skill/legacy.txt"
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill/SKILL.md" ]
    [ ! -e "$CODEX_SKILLS_DIR/demo-skill/SKILL.md" ]
    [ -z "$(find "$STATE_ROOT" -type d \( -name '.stage-*' -o -name '.backup-*' \) -print -quit)" ]
}

@test "skill registry transaction: apply detects a destination swap and preserves both trees" {
    mkdir -p "$CLAUDE_SKILLS_DIR/demo-skill"
    printf 'legacy before race\n' > "$CLAUDE_SKILLS_DIR/demo-skill/legacy.txt"
    run_registry lock
    [ "$status" -eq 0 ]
    local preserved="$TEST_ROOT/preserved-legacy-tree"

    run_registry_with_detach_interposition \
        "$CLAUDE_SKILLS_DIR/demo-skill" "$preserved" apply --targets claude

    [ "$status" -ne 0 ]
    [[ "$output" == *"concurrent"* || "$output" == *"compensat"* ]]
    grep -q '^legacy before race$' "$preserved/legacy.txt"
    grep -q '^concurrent unmanaged replacement$' \
        "$CLAUDE_SKILLS_DIR/demo-skill/concurrent.txt"
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill/SKILL.md" ]
}

@test "skill registry transaction: rollback detects a destination swap and preserves both trees" {
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local preserved="$TEST_ROOT/preserved-applied-tree"

    run_registry_with_detach_interposition \
        "$CLAUDE_SKILLS_DIR/demo-skill" "$preserved" rollback

    [ "$status" -ne 0 ]
    [[ "$output" == *"concurrent"* || "$output" == *"rollback"* ]]
    [ -f "$preserved/SKILL.md" ]
    grep -q '^concurrent unmanaged replacement$' \
        "$CLAUDE_SKILLS_DIR/demo-skill/concurrent.txt"
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill/SKILL.md" ]
}

@test "skill registry transaction: rollback snapshot cannot legitimize a concurrent tree" {
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local preserved="$TEST_ROOT/preserved-before-snapshot"

    run_registry_with_snapshot_interposition \
        "$CLAUDE_SKILLS_DIR/demo-skill" "$preserved" rollback

    [ "$status" -ne 0 ]
    [[ "$output" == *"snapshot"* || "$output" == *"changed"* ]]
    [ -f "$preserved/SKILL.md" ]
    grep -q '^concurrent unmanaged replacement$' \
        "$CLAUDE_SKILLS_DIR/demo-skill/concurrent.txt"
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill/SKILL.md" ]
}

@test "skill registry transaction: terminal validation detects an earlier destination swap" {
    run_registry lock
    [ "$status" -eq 0 ]
    local preserved="$TEST_ROOT/preserved-before-terminal-validation"

    run_registry_with_interposition \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_BEFORE_TERMINAL_VALIDATION \
        "$CLAUDE_SKILLS_DIR/demo-skill" \
        "$preserved" \
        apply --targets all

    [ "$status" -ne 0 ]
    [ -f "$preserved/SKILL.md" ]
    grep -q '^concurrent unmanaged replacement$' \
        "$CLAUDE_SKILLS_DIR/demo-skill/concurrent.txt"
    local journal
    journal="$(latest_transaction_journal)"
    "$PYTHON" - "$journal" <<'PY'
import json
import pathlib
import sys

data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert data["status"] != "applied", data["status"]
PY
}

@test "skill registry recovery: apply compensation validates before deleting its backup" {
    mkdir -p "$CLAUDE_SKILLS_DIR/demo-skill"
    printf 'legacy before apply\n' > "$CLAUDE_SKILLS_DIR/demo-skill/legacy.txt"
    run_registry lock
    [ "$status" -eq 0 ]
    local preserved="$TEST_ROOT/preserved-before-apply-compensation-validation"

    INTERRUPT_APPLY_FAILURE_TARGET=claude \
        run_registry_with_interposition \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_BEFORE_TERMINAL_VALIDATION \
        "$CLAUDE_SKILLS_DIR/demo-skill" \
        "$preserved" \
        apply --targets claude

    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    local journal transaction
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    [ -d "$STATE_ROOT/backups/$transaction" ]
    [ -f "$preserved/legacy.txt" ]
    [ -f "$CLAUDE_SKILLS_DIR/demo-skill/concurrent.txt" ]
}

@test "skill registry recovery: rollback validates before deleting recovery material" {
    mkdir -p "$CLAUDE_SKILLS_DIR/demo-skill"
    printf 'legacy before apply\n' > "$CLAUDE_SKILLS_DIR/demo-skill/legacy.txt"
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local journal transaction preserved
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    preserved="$TEST_ROOT/preserved-before-rollback-validation"

    run_registry_with_interposition \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_BEFORE_TERMINAL_VALIDATION \
        "$CLAUDE_SKILLS_DIR/demo-skill" \
        "$preserved" \
        rollback --transaction "$transaction"

    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    [ -d "$STATE_ROOT/backups/$transaction" ]
    [ -d "$STATE_ROOT/rollback-backups/$transaction" ]
    [ -f "$preserved/legacy.txt" ]
    [ -f "$CLAUDE_SKILLS_DIR/demo-skill/concurrent.txt" ]
}

@test "skill registry recovery: apply cleanup revalidates before terminal status" {
    mkdir -p "$CLAUDE_SKILLS_DIR/demo-skill"
    printf 'legacy before apply\n' > "$CLAUDE_SKILLS_DIR/demo-skill/legacy.txt"
    run_registry lock
    [ "$status" -eq 0 ]
    local preserved="$TEST_ROOT/preserved-after-apply-cleanup"

    INTERRUPT_APPLY_FAILURE_TARGET=claude \
        run_registry_with_cleanup_destination_swap \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_APPLY_COMPENSATION_ARTIFACT_CLEANUP \
        "$CLAUDE_SKILLS_DIR/demo-skill" \
        "$preserved" \
        apply-post-cleanup-swap \
        apply --targets claude

    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    local journal
    journal="$(latest_transaction_journal)"
    assert_journal_status_and_operations "$journal" compensating_cleanup compensated
    [ -f "$preserved/legacy.txt" ]
    [ -f "$CLAUDE_SKILLS_DIR/demo-skill/concurrent.txt" ]
}

@test "skill registry recovery: rollback compensation cleanup revalidates before terminal status" {
    mkdir -p "$CLAUDE_SKILLS_DIR/demo-skill"
    printf 'legacy before apply\n' > "$CLAUDE_SKILLS_DIR/demo-skill/legacy.txt"
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local journal transaction preserved
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    preserved="$TEST_ROOT/preserved-after-rollback-compensation-cleanup"

    INTERRUPT_ROLLBACK_FAILURE_TARGET=claude \
        run_registry_with_cleanup_destination_swap \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_COMPENSATION_ARTIFACT_CLEANUP \
        "$CLAUDE_SKILLS_DIR/demo-skill" \
        "$preserved" \
        rollback-compensation-post-cleanup-swap \
        rollback --transaction "$transaction"

    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    assert_journal_status_and_operations \
        "$journal" rollback_compensating_cleanup applied
    [ -f "$preserved/SKILL.md" ]
    [ -f "$CLAUDE_SKILLS_DIR/demo-skill/concurrent.txt" ]
}

@test "skill registry recovery: successful rollback cleanup revalidates before terminal status" {
    mkdir -p "$CLAUDE_SKILLS_DIR/demo-skill"
    printf 'legacy before apply\n' > "$CLAUDE_SKILLS_DIR/demo-skill/legacy.txt"
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local journal transaction preserved
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    preserved="$TEST_ROOT/preserved-after-rollback-cleanup"

    run_registry_with_cleanup_destination_swap \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_ARTIFACT_CLEANUP \
        "$CLAUDE_SKILLS_DIR/demo-skill" \
        "$preserved" \
        rollback-post-cleanup-swap \
        rollback --transaction "$transaction"

    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    assert_journal_status_and_operations "$journal" rollback_cleanup rolled_back
    [ -f "$preserved/legacy.txt" ]
    [ -f "$CLAUDE_SKILLS_DIR/demo-skill/concurrent.txt" ]
}

@test "skill registry recovery: rollback preparation cleanup revalidates before terminal status" {
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local journal transaction preserved
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"

    run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_DURING_ROLLBACK_SNAPSHOT_COPY \
        "$CLAUDE_SKILLS_DIR/demo-skill" \
        rollback-preparation-for-post-cleanup-swap \
        rollback --transaction "$transaction"
    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    preserved="$TEST_ROOT/preserved-after-rollback-preparation-cleanup"

    run_registry_with_cleanup_destination_swap \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_PREPARATION_ARTIFACT_CLEANUP \
        "$CLAUDE_SKILLS_DIR/demo-skill" \
        "$preserved" \
        rollback-preparation-post-cleanup-swap \
        recover --transaction "$transaction"

    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    assert_journal_status_and_operations "$journal" rollback_preparing applied
    [ -f "$preserved/SKILL.md" ]
    [ -f "$CLAUDE_SKILLS_DIR/demo-skill/concurrent.txt" ]
}

@test "skill registry apply: a nested ownership-marker filename is drift" {
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    mkdir -p "$CLAUDE_SKILLS_DIR/demo-skill/references/nested"
    printf '{"forged": true}\n' \
        > "$CLAUDE_SKILLS_DIR/demo-skill/references/nested/.shogun-skill.json"

    run_registry apply --targets claude

    [ "$status" -eq 2 ]
    [[ "$output" == *"drift"* || "$output" == *"hash"* ]]
    [ -f "$CLAUDE_SKILLS_DIR/demo-skill/references/nested/.shogun-skill.json" ]
}

@test "skill registry journal security: rollback rejects an inner transaction id mismatch before mutation" {
    prepare_external_sentinel
    create_prune_transaction
    local journal state_before
    journal="$(latest_transaction_journal)"
    rewrite_transaction_journal "$journal" transaction-id-mismatch
    state_before="$(tree_hash "$STATE_ROOT")"

    run_registry rollback

    [ "$status" -ne 0 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ ! -e "$CODEX_SKILLS_DIR/demo-skill" ]
    [ "$(tree_hash "$STATE_ROOT")" = "$state_before" ]
    assert_external_sentinel_unchanged
}

@test "skill registry journal security: rollback rejects an absolute skill id before mutation" {
    prepare_external_sentinel
    lock_and_apply_all
    local journal escaped claude_before codex_before state_before
    journal="$(latest_transaction_journal)"
    escaped="$EXTERNAL_SENTINEL_ROOT/escaped-absolute-skill"
    rewrite_transaction_journal "$journal" absolute-skill-id "$escaped"
    claude_before="$(tree_hash "$CLAUDE_SKILLS_DIR")"
    codex_before="$(tree_hash "$CODEX_SKILLS_DIR")"
    state_before="$(tree_hash "$STATE_ROOT")"

    run_registry rollback

    [ "$status" -ne 0 ]
    [ ! -e "$escaped" ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR")" = "$claude_before" ]
    [ "$(tree_hash "$CODEX_SKILLS_DIR")" = "$codex_before" ]
    [ "$(tree_hash "$STATE_ROOT")" = "$state_before" ]
    assert_external_sentinel_unchanged
}

@test "skill registry journal security: rollback rejects a parent-traversing skill id before mutation" {
    prepare_external_sentinel
    lock_and_apply_all
    local journal escaped_parent escaped parent_before state_before
    journal="$(latest_transaction_journal)"
    escaped_parent="$TEST_HOME/.claude"
    escaped="$escaped_parent/escaped-parent-skill"
    printf 'parent sentinel\n' > "$escaped_parent/parent-sentinel.txt"
    rewrite_transaction_journal "$journal" parent-skill-id
    parent_before="$(tree_hash "$escaped_parent")"
    state_before="$(tree_hash "$STATE_ROOT")"

    run_registry rollback

    [ "$status" -ne 0 ]
    [ ! -e "$escaped" ]
    [ "$(tree_hash "$escaped_parent")" = "$parent_before" ]
    [ "$(tree_hash "$STATE_ROOT")" = "$state_before" ]
    assert_external_sentinel_unchanged
}

@test "skill registry journal security: rollback rejects a mismatched backup path before mutation" {
    prepare_external_sentinel
    create_prune_transaction
    local journal state_before
    journal="$(latest_transaction_journal)"
    rewrite_transaction_journal "$journal" backup-path-mismatch
    state_before="$(tree_hash "$STATE_ROOT")"

    run_registry rollback

    [ "$status" -ne 0 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ ! -e "$CODEX_SKILLS_DIR/demo-skill" ]
    [ "$(tree_hash "$STATE_ROOT")" = "$state_before" ]
    assert_external_sentinel_unchanged
}

@test "skill registry root isolation: apply rejects identical Claude and Codex roots before mutation" {
    prepare_external_sentinel
    local shared_root="$TEST_ROOT/shared-target-root"
    CLAUDE_SKILLS_DIR="$shared_root"
    CODEX_SKILLS_DIR="$shared_root"
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry apply --targets all

    [ "$status" -ne 0 ]
    [ ! -e "$shared_root/demo-skill" ]
    [ ! -e "$STATE_ROOT/transactions" ]
    assert_external_sentinel_unchanged
}

@test "skill registry root isolation: physical aliases overlap" {
    "$PYTHON" - "$PROJECT_ROOT/scripts/skill_registry.py" "$TEST_ROOT" <<'PY'
import importlib.util
import os
import pathlib
import sys

spec = importlib.util.spec_from_file_location("skill_registry", sys.argv[1])
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

root = pathlib.Path(sys.argv[2]) / "physical-alias"
root.mkdir(parents=True)
first = root / "first"
second = root / "second"
first.write_text("same inode\n", encoding="utf-8")
os.link(first, second)
assert module.paths_overlap(first, second)
PY
}

@test "skill registry root isolation: case aliases depend on volume semantics" {
    "$PYTHON" - "$PROJECT_ROOT/scripts/skill_registry.py" "$TEST_ROOT" <<'PY'
import importlib.util
import pathlib
import sys

spec = importlib.util.spec_from_file_location("skill_registry", sys.argv[1])
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

root = pathlib.Path(sys.argv[2]) / "case-alias"
upper = root / "Registry" / "state"
lower = root / "registry" / "state"
upper.parent.mkdir(parents=True)
lower.parent.mkdir(parents=True)

# Linux case-sensitive paths remain distinct.
assert not module.paths_overlap(upper, lower)

# The same spelling pair aliases on a case-insensitive volume (default APFS
# and Windows semantics) and must therefore be rejected as overlapping.
module.path_volume_is_case_insensitive = lambda _path: True
assert module.paths_overlap(upper, lower)
PY
}

@test "skill registry root isolation: physical ancestor aliases overlap for uncreated descendants" {
    "$PYTHON" - "$PROJECT_ROOT/scripts/skill_registry.py" "$TEST_ROOT" <<'PY'
import importlib.util
import pathlib
import sys

spec = importlib.util.spec_from_file_location("skill_registry", sys.argv[1])
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

root = pathlib.Path(sys.argv[2]) / "ancestor-alias"
canonical = root / "canonical"
alias = root / "alias"
canonical.mkdir(parents=True)
alias.mkdir()
real_samefile = module.os.path.samefile

def simulated_samefile(left, right):
    pair = {pathlib.Path(left), pathlib.Path(right)}
    if pair == {canonical, alias}:
        return True
    return real_samefile(left, right)

module.os.path.samefile = simulated_samefile
assert module.paths_overlap(canonical, alias / "new-skills")
PY
}

@test "skill registry root isolation: physical aliases overlap through an existing subdirectory" {
    "$PYTHON" - "$PROJECT_ROOT/scripts/skill_registry.py" "$TEST_ROOT" <<'PY'
import importlib.util
import pathlib
import sys

spec = importlib.util.spec_from_file_location("skill_registry", sys.argv[1])
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

root = pathlib.Path(sys.argv[2]) / "nested-ancestor-alias"
canonical = root / "canonical"
alias = root / "alias"
(canonical / "existing-sub").mkdir(parents=True)
(alias / "existing-sub").mkdir(parents=True)
real_samefile = module.os.path.samefile

def simulated_samefile(left, right):
    pair = {pathlib.Path(left), pathlib.Path(right)}
    if pair == {canonical, alias}:
        return True
    return real_samefile(left, right)

module.os.path.samefile = simulated_samefile
assert module.paths_overlap(canonical, alias / "existing-sub" / "new-skills")
PY
}

@test "skill registry root isolation: case aliases normalize Unicode spellings" {
    "$PYTHON" - "$PROJECT_ROOT/scripts/skill_registry.py" "$TEST_ROOT" <<'PY'
import importlib.util
import pathlib
import sys

spec = importlib.util.spec_from_file_location("skill_registry", sys.argv[1])
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

root = pathlib.Path(sys.argv[2]) / "unicode-case-alias"
composed = root / "Caf\N{LATIN SMALL LETTER E WITH ACUTE}" / "state"
decomposed = root / "Cafe\N{COMBINING ACUTE ACCENT}" / "state"
composed.parent.mkdir(parents=True)
decomposed.parent.mkdir(parents=True)
module.path_volume_is_case_insensitive = lambda _path: False
assert module.paths_overlap(composed, decomposed)
module.path_volume_is_case_insensitive = lambda _path: True
assert module.paths_overlap(composed, decomposed)
PY
}

@test "skill registry tree safety: mountinfo descendants are never removed" {
    "$PYTHON" - "$PROJECT_ROOT/scripts/skill_registry.py" "$TEST_ROOT" <<'PY'
import importlib.util
import pathlib
import sys

spec = importlib.util.spec_from_file_location("skill_registry", sys.argv[1])
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

root = pathlib.Path(sys.argv[2]) / "mountinfo-removal-boundary"
leaf = root / "managed-tree"
mounted = leaf / "external-mount"
mounted.mkdir(parents=True)
sentinel = mounted / "sentinel.txt"
sentinel.write_text("external data\n", encoding="utf-8")
module.linux_mount_points = lambda: frozenset({mounted.resolve()})

try:
    module.secure_remove_tree(root, leaf.name, "mounted managed tree")
except module.RegistryError:
    pass
else:
    raise AssertionError("nested mount was recursively removed")

assert sentinel.read_text(encoding="utf-8") == "external data\n"

module.linux_mount_points = lambda: frozenset({leaf.resolve()})
try:
    module.secure_remove_tree(root, leaf.name, "mounted managed tree root")
except module.RegistryError:
    pass
else:
    raise AssertionError("mounted tree root was recursively removed")
assert sentinel.read_text(encoding="utf-8") == "external data\n"
PY
}

@test "skill registry tree safety: platform mount points fail closed during traversal" {
    "$PYTHON" - "$PROJECT_ROOT/scripts/skill_registry.py" "$TEST_ROOT" <<'PY'
import importlib.util
import pathlib
import sys

spec = importlib.util.spec_from_file_location("skill_registry", sys.argv[1])
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

root = pathlib.Path(sys.argv[2]) / "platform-mount-boundary"
mounted = root / "mounted-child"
mounted.mkdir(parents=True)
(mounted / "sentinel.txt").write_text("external data\n", encoding="utf-8")
real_ismount = module.os.path.ismount
module.linux_mount_points = lambda: frozenset()
module.os.path.ismount = lambda candidate: (
    pathlib.Path(candidate) == mounted or real_ismount(candidate)
)

try:
    module.ensure_real_directory_tree(root, "mounted traversal")
except module.RegistryError:
    pass
else:
    raise AssertionError("platform mount point was traversed")
PY
}

@test "skill registry tree safety: removal opens every root component without following links" {
    "$PYTHON" - "$PROJECT_ROOT/scripts/skill_registry.py" "$TEST_ROOT" <<'PY'
import importlib.util
import pathlib
import sys

spec = importlib.util.spec_from_file_location("skill_registry", sys.argv[1])
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

base = pathlib.Path(sys.argv[2]) / "removal-root-swap"
ancestor = base / "ancestor"
root = ancestor / "root"
original_leaf = root / "managed-tree"
original_leaf.mkdir(parents=True)
(original_leaf / "original.txt").write_text("original\n", encoding="utf-8")
external = base / "external"
external_leaf = external / "root" / "managed-tree"
external_leaf.mkdir(parents=True)
sentinel = external_leaf / "sentinel.txt"
sentinel.write_text("external data\n", encoding="utf-8")
preserved_ancestor = base / "preserved-ancestor"
real_check = module.ensure_no_symlink_ancestors
interposed = False

def swap_after_check(path, context):
    global interposed
    real_check(path, context)
    if interposed:
        return
    interposed = True
    ancestor.rename(preserved_ancestor)
    ancestor.symlink_to(external, target_is_directory=True)

module.ensure_no_symlink_ancestors = swap_after_check
module.linux_mount_points = lambda: frozenset()
try:
    module.secure_remove_tree(root, original_leaf.name, "swapped removal root")
except module.RegistryError:
    pass
else:
    raise AssertionError("ancestor symlink swap was followed")

assert sentinel.read_text(encoding="utf-8") == "external data\n"
assert (preserved_ancestor / "root" / "managed-tree" / "original.txt").is_file()
PY
}

@test "skill registry root isolation: apply rejects nested Claude and Codex roots before mutation" {
    prepare_external_sentinel
    local outer_root="$TEST_ROOT/outer-target-root"
    CLAUDE_SKILLS_DIR="$outer_root"
    CODEX_SKILLS_DIR="$outer_root/nested-codex"
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry apply --targets all

    [ "$status" -ne 0 ]
    [ ! -e "$outer_root/demo-skill" ]
    [ ! -e "$outer_root/nested-codex/demo-skill" ]
    [ ! -e "$STATE_ROOT/transactions" ]
    assert_external_sentinel_unchanged
}

@test "skill registry root isolation: apply rejects a selected target overlapping the canonical project" {
    CLAUDE_SKILLS_DIR="$FIXTURE_ROOT"
    run_registry lock
    [ "$status" -eq 0 ]
    local project_before
    project_before="$(tree_hash "$FIXTURE_ROOT")"

    run_registry apply --targets claude

    [ "$status" -eq 2 ]
    [[ "$output" == *"project"* || "$output" == *"registry"* || "$output" == *"source"* ]]
    [ "$(tree_hash "$FIXTURE_ROOT")" = "$project_before" ]
    [ ! -e "$STATE_ROOT/transactions" ]
}

@test "skill registry root isolation: apply rejects transaction state overlapping the canonical project" {
    STATE_ROOT="$FIXTURE_ROOT/.skill-registry-state"
    run_registry lock
    [ "$status" -eq 0 ]
    local project_before
    project_before="$(tree_hash "$FIXTURE_ROOT")"

    run_registry apply --targets claude

    [ "$status" -eq 2 ]
    [[ "$output" == *"state"* && ( "$output" == *"project"* || "$output" == *"registry"* ) ]]
    [ "$(tree_hash "$FIXTURE_ROOT")" = "$project_before" ]
}

@test "skill registry apply target: an invalid unselected root is not inspected or locked" {
    CODEX_SKILLS_DIR="$FIXTURE_ROOT"
    run_registry lock
    [ "$status" -eq 0 ]
    local project_before
    project_before="$(tree_hash "$FIXTURE_ROOT")"

    run_registry apply --targets claude

    [ "$status" -eq 0 ]
    [ -f "$CLAUDE_SKILLS_DIR/demo-skill/SKILL.md" ]
    [ "$(tree_hash "$FIXTURE_ROOT")" = "$project_before" ]
}

@test "skill registry rollback target: an invalid unselected root is not inspected or locked" {
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local journal transaction project_before
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    project_before="$(tree_hash "$FIXTURE_ROOT")"
    CODEX_SKILLS_DIR="$FIXTURE_ROOT"

    run_registry rollback --transaction "$transaction"

    [ "$status" -eq 0 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ "$(tree_hash "$FIXTURE_ROOT")" = "$project_before" ]
}

@test "skill registry recover target: an invalid unselected root is not inspected or locked" {
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry_and_kill_after_compensation_detach
    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    local journal transaction project_before
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    project_before="$(tree_hash "$FIXTURE_ROOT")"
    CODEX_SKILLS_DIR="$FIXTURE_ROOT"

    run_registry recover --transaction "$transaction"

    [ "$status" -eq 0 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ "$(tree_hash "$FIXTURE_ROOT")" = "$project_before" ]
}

@test "skill registry root isolation: apply rejects a symlinked parent component before mutation" {
    prepare_external_sentinel
    local real_parent="$TEST_ROOT/real-claude-parent"
    local linked_parent="$TEST_ROOT/linked-claude-parent"
    mkdir -p "$real_parent"
    printf 'real parent sentinel\n' > "$real_parent/sentinel.txt"
    ln -s "$real_parent" "$linked_parent"
    CLAUDE_SKILLS_DIR="$linked_parent/skills"
    local real_before
    real_before="$(tree_hash "$real_parent")"
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry apply --targets claude

    [ "$status" -ne 0 ]
    [ "$(tree_hash "$real_parent")" = "$real_before" ]
    [ ! -e "$STATE_ROOT/transactions" ]
    assert_external_sentinel_unchanged
}

@test "skill registry recovery: no-op apply rejects an incomplete journal before mutation" {
    prepare_external_sentinel
    lock_and_apply_all
    local journal claude_before codex_before state_before
    journal="$(latest_transaction_journal)"
    rewrite_transaction_journal "$journal" incomplete
    claude_before="$(tree_hash "$CLAUDE_SKILLS_DIR")"
    codex_before="$(tree_hash "$CODEX_SKILLS_DIR")"
    state_before="$(tree_hash "$STATE_ROOT")"

    run_registry apply --targets all

    [ "$status" -ne 0 ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR")" = "$claude_before" ]
    [ "$(tree_hash "$CODEX_SKILLS_DIR")" = "$codex_before" ]
    [ "$(tree_hash "$STATE_ROOT")" = "$state_before" ]
    assert_external_sentinel_unchanged
}

@test "skill registry journal security: rollback rejects a tampered backup tree before mutation" {
    prepare_external_sentinel
    create_prune_transaction
    local journal state_before
    journal="$(latest_transaction_journal)"
    rewrite_transaction_journal "$journal" tamper-backup
    state_before="$(tree_hash "$STATE_ROOT")"

    run_registry rollback

    [ "$status" -ne 0 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ ! -e "$CODEX_SKILLS_DIR/demo-skill" ]
    [ "$(tree_hash "$STATE_ROOT")" = "$state_before" ]
    assert_external_sentinel_unchanged
}

@test "skill registry journal security: recover rejects prepared status with an applied operation" {
    lock_and_apply_all
    local journal transaction claude_before codex_before state_before
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    rewrite_transaction_journal "$journal" prepared-with-applied-operation
    claude_before="$(tree_hash "$CLAUDE_SKILLS_DIR")"
    codex_before="$(tree_hash "$CODEX_SKILLS_DIR")"
    state_before="$(tree_hash "$STATE_ROOT")"

    run_registry recover --transaction "$transaction"

    [ "$status" -eq 2 ]
    [[ "$output" == *"status"* || "$output" == *"state"* ]]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR")" = "$claude_before" ]
    [ "$(tree_hash "$CODEX_SKILLS_DIR")" = "$codex_before" ]
    [ "$(tree_hash "$STATE_ROOT")" = "$state_before" ]
}

@test "skill registry journal security: rollback rejects applied status with a planned operation" {
    lock_and_apply_all
    local journal claude_before codex_before state_before
    journal="$(latest_transaction_journal)"
    rewrite_transaction_journal "$journal" applied-with-planned-operation
    claude_before="$(tree_hash "$CLAUDE_SKILLS_DIR")"
    codex_before="$(tree_hash "$CODEX_SKILLS_DIR")"
    state_before="$(tree_hash "$STATE_ROOT")"

    run_registry rollback

    [ "$status" -eq 2 ]
    [[ "$output" == *"status"* || "$output" == *"state"* ]]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR")" = "$claude_before" ]
    [ "$(tree_hash "$CODEX_SKILLS_DIR")" = "$codex_before" ]
    [ "$(tree_hash "$STATE_ROOT")" = "$state_before" ]
}

@test "skill registry journal security: target entries must match a single-target selection" {
    lock_and_apply_all
    local journal claude_before codex_before state_before
    journal="$(latest_transaction_journal)"
    rewrite_transaction_journal "$journal" single-target-selection-mismatch
    claude_before="$(tree_hash "$CLAUDE_SKILLS_DIR")"
    codex_before="$(tree_hash "$CODEX_SKILLS_DIR")"
    state_before="$(tree_hash "$STATE_ROOT")"

    run_registry rollback

    [ "$status" -eq 2 ]
    [[ "$output" == *"selection"* || "$output" == *"target"* ]]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR")" = "$claude_before" ]
    [ "$(tree_hash "$CODEX_SKILLS_DIR")" = "$codex_before" ]
    [ "$(tree_hash "$STATE_ROOT")" = "$state_before" ]
}

@test "skill registry state security: rollback rejects a symlinked backup ancestor before mutation" {
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local journal transaction target_before external_root external_before
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    target_before="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    external_root="$TEST_ROOT/external-backup-tree"
    mkdir -p "$external_root/$transaction"
    printf 'must survive\n' > "$external_root/$transaction/sentinel.txt"
    external_before="$(tree_hash "$external_root")"
    ln -s "$external_root" "$STATE_ROOT/backups"

    run_registry rollback --transaction "$transaction"

    [ "$status" -eq 2 ]
    [[ "$output" == *"symlink"* || "$output" == *"state"* ]]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$target_before" ]
    [ "$(tree_hash "$external_root")" = "$external_before" ]
    grep -q '^must survive$' "$external_root/$transaction/sentinel.txt"
}

@test "skill registry state permissions: apply creates private state and journal modes" {
    prepare_external_sentinel
    STATE_ROOT="$TEST_ROOT/private-state"
    umask 022
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry apply --targets claude

    [ "$status" -eq 0 ]
    local journal
    journal="$(latest_transaction_journal)"
    [ "$(octal_mode "$STATE_ROOT")" = "700" ]
    [ "$(octal_mode "$journal")" = "600" ]
    assert_external_sentinel_unchanged
}

@test "skill registry rollback transaction: second-target failure restores the applied state and permits retry" {
    prepare_external_sentinel
    lock_and_apply_all
    local journal transaction claude_applied codex_applied
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    claude_applied="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    codex_applied="$(tree_hash "$CODEX_SKILLS_DIR/demo-skill")"

    run_registry_with_rollback_failure codex rollback --transaction "$transaction"

    [ "$status" -ne 0 ]
    [[ "$output" == *"compensat"* ]]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$claude_applied" ]
    [ "$(tree_hash "$CODEX_SKILLS_DIR/demo-skill")" = "$codex_applied" ]
    assert_journal_status_and_operations "$journal" applied applied
    assert_external_sentinel_unchanged

    run_registry rollback --transaction "$transaction"

    [ "$status" -eq 0 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ ! -e "$CODEX_SKILLS_DIR/demo-skill" ]
    assert_external_sentinel_unchanged
}

@test "skill registry recovery: explicit recover compensates a partial apply and permits reapply" {
    prepare_external_sentinel
    lock_and_apply_all
    local journal transaction
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    mv "$CODEX_SKILLS_DIR/demo-skill" "$TEST_ROOT/crash-codex-never-committed"
    make_partial_initial_apply_journal "$journal"

    run_registry recover --transaction "$transaction"

    [ "$status" -eq 0 ]
    [[ "$output" == *"recover"* || "$output" == *"compensat"* ]]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ ! -e "$CODEX_SKILLS_DIR/demo-skill" ]
    "$PYTHON" - "$journal" <<'PY'
import json
import pathlib
import sys

data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert data["status"] == "compensated", data["status"]
PY
    assert_external_sentinel_unchanged

    run_registry apply --targets all

    [ "$status" -eq 0 ]
    [ -f "$CLAUDE_SKILLS_DIR/demo-skill/SKILL.md" ]
    [ -f "$CODEX_SKILLS_DIR/demo-skill/SKILL.md" ]
    assert_external_sentinel_unchanged
}

@test "skill registry recovery: interrupted apply compensation reconciles its detached tree" {
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry_and_kill_after_compensation_detach

    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    local journal transaction detached
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    detached="$CLAUDE_SKILLS_DIR/.shogun-apply-detached-$transaction-demo-skill"
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ -d "$detached" ]

    run_registry recover --transaction "$transaction"

    [ "$status" -eq 0 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ ! -e "$detached" ]
    assert_journal_status_and_operations "$journal" compensated compensated

    run_registry apply --targets claude

    [ "$status" -eq 0 ]
    [ -f "$CLAUDE_SKILLS_DIR/demo-skill/SKILL.md" ]
}

@test "skill registry recovery: interrupted replacement compensation restores its backup" {
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local original_hash
    original_hash="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    mutate_registry_skill status enabled
    printf '\nReplacement release.\n' >> "$FIXTURE_ROOT/skills/demo-skill/SKILL.md"
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry_and_kill_after_compensation_detach

    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    local journal transaction detached
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    detached="$CLAUDE_SKILLS_DIR/.shogun-apply-detached-$transaction-demo-skill"
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ -d "$detached" ]

    run_registry recover --transaction "$transaction"

    [ "$status" -eq 0 ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$original_hash" ]
    [ ! -e "$detached" ]
    assert_journal_status_and_operations "$journal" compensated compensated
}

@test "skill registry recovery: duplicate originals after interrupted replace compensation reconcile" {
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local original_hash
    original_hash="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    mutate_registry_skill status enabled
    printf '\nReplacement release.\n' >> "$FIXTURE_ROOT/skills/demo-skill/SKILL.md"
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_APPLY_ORIGINAL_DETACH \
        "$CLAUDE_SKILLS_DIR/demo-skill" \
        replace-apply-original-detach \
        apply --targets claude
    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    local journal transaction previous
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    previous="$CLAUDE_SKILLS_DIR/.backup-$transaction-demo-skill"
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ "$(tree_hash "$previous")" = "$original_hash" ]

    run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_APPLY_COMPENSATION_RESTORE \
        "$CLAUDE_SKILLS_DIR/demo-skill" \
        replace-apply-compensation-restore \
        recover --transaction "$transaction"
    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$original_hash" ]
    [ "$(tree_hash "$previous")" = "$original_hash" ]

    run_registry recover --transaction "$transaction"

    [ "$status" -eq 0 ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$original_hash" ]
    [ ! -e "$previous" ]
    assert_journal_status_and_operations "$journal" compensated compensated
}

@test "skill registry recovery: duplicate originals after interrupted prune compensation reconcile" {
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local original_hash
    original_hash="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    mutate_registry_skill status disabled
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_APPLY_ORIGINAL_DETACH \
        "$CLAUDE_SKILLS_DIR/demo-skill" \
        prune-apply-original-detach \
        apply --targets claude
    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    local journal transaction previous
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    previous="$CLAUDE_SKILLS_DIR/.backup-$transaction-demo-skill"
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ "$(tree_hash "$previous")" = "$original_hash" ]

    run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_APPLY_COMPENSATION_RESTORE \
        "$CLAUDE_SKILLS_DIR/demo-skill" \
        prune-apply-compensation-restore \
        recover --transaction "$transaction"
    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$original_hash" ]
    [ "$(tree_hash "$previous")" = "$original_hash" ]

    run_registry recover --transaction "$transaction"

    [ "$status" -eq 0 ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$original_hash" ]
    [ ! -e "$previous" ]
    assert_journal_status_and_operations "$journal" compensated compensated
}

@test "skill registry recovery: apply compensation cleanup phase is retryable" {
    mkdir -p "$CLAUDE_SKILLS_DIR/demo-skill"
    printf 'legacy before apply\n' > "$CLAUDE_SKILLS_DIR/demo-skill/legacy.txt"
    run_registry lock
    [ "$status" -eq 0 ]

    INTERRUPT_APPLY_FAILURE_TARGET=claude \
        run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_APPLY_COMPENSATION_ARTIFACT_CLEANUP \
        "*" \
        apply-compensation-artifact-cleanup \
        apply --targets claude
    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    local journal transaction
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    assert_journal_status_and_operations \
        "$journal" compensating_cleanup compensated
    [ ! -e "$STATE_ROOT/backups/$transaction" ]
    grep -q '^legacy before apply$' "$CLAUDE_SKILLS_DIR/demo-skill/legacy.txt"

    run_registry recover --transaction "$transaction"

    [ "$status" -eq 0 ]
    assert_journal_status_and_operations "$journal" compensated compensated
    [ ! -e "$STATE_ROOT/backups/$transaction" ]
    [ -z "$(find "$CLAUDE_SKILLS_DIR" -maxdepth 1 -name "*${transaction}*" -print -quit)" ]
}

@test "skill registry recovery: rollback compensation cleanup phase is retryable" {
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    mutate_registry_skill status enabled
    printf '\nReplacement release.\n' >> "$FIXTURE_ROOT/skills/demo-skill/SKILL.md"
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local journal transaction
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"

    INTERRUPT_ROLLBACK_FAILURE_TARGET=claude \
        run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_COMPENSATION_ARTIFACT_CLEANUP \
        "*" \
        rollback-compensation-artifact-cleanup \
        rollback --transaction "$transaction"
    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    assert_journal_status_and_operations \
        "$journal" rollback_compensating_cleanup applied
    [ ! -e "$STATE_ROOT/rollback-backups/$transaction" ]
    [ -d "$STATE_ROOT/backups/$transaction" ]

    run_registry recover --transaction "$transaction"

    [ "$status" -eq 0 ]
    assert_journal_status_and_operations "$journal" applied applied
    [ ! -e "$STATE_ROOT/rollback-backups/$transaction" ]
    [ -z "$(find "$CLAUDE_SKILLS_DIR" -maxdepth 1 -name "*${transaction}*" -print -quit)" ]

    run_registry rollback --transaction "$transaction"
    [ "$status" -eq 0 ]
    [ ! -e "$STATE_ROOT/backups/$transaction" ]
}

@test "skill registry recovery: successful rollback cleanup phase is retryable" {
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local journal transaction
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"

    run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_ARTIFACT_CLEANUP \
        "*" \
        rollback-artifact-cleanup \
        rollback --transaction "$transaction"
    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    assert_journal_status_and_operations "$journal" rollback_cleanup rolled_back
    [ ! -e "$STATE_ROOT/backups/$transaction" ]
    [ ! -e "$STATE_ROOT/rollback-backups/$transaction" ]

    run_registry recover --transaction "$transaction"

    [ "$status" -eq 0 ]
    assert_journal_status_and_operations "$journal" rolled_back rolled_back
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ ! -e "$STATE_ROOT/backups/$transaction" ]
    [ ! -e "$STATE_ROOT/rollback-backups/$transaction" ]
}

@test "skill registry recovery: interrupted rollback snapshot copy returns to clean applied state" {
    lock_and_apply_all
    local journal transaction claude_hash codex_hash
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    claude_hash="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    codex_hash="$(tree_hash "$CODEX_SKILLS_DIR/demo-skill")"

    run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_DURING_ROLLBACK_SNAPSHOT_COPY \
        "$CLAUDE_SKILLS_DIR/demo-skill" \
        rollback-snapshot-copy \
        rollback --transaction "$transaction"
    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    assert_journal_status_and_operations "$journal" rollback_preparing applied
    [ -d "$STATE_ROOT/rollback-backups/$transaction" ]

    run_registry recover --transaction "$transaction"

    [ "$status" -eq 0 ]
    assert_journal_status_and_operations "$journal" applied applied
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$claude_hash" ]
    [ "$(tree_hash "$CODEX_SKILLS_DIR/demo-skill")" = "$codex_hash" ]
    [ ! -e "$STATE_ROOT/rollback-backups/$transaction" ]
    "$PYTHON" - "$journal" <<'PY'
import json
import pathlib
import sys

data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert all(entry["rollback_tree_sha256"] is None for entry in data["operations"])
PY

    run_registry apply --targets all
    [ "$status" -eq 0 ]
    [ ! -e "$STATE_ROOT/rollback-backups/$transaction" ]
}

@test "skill registry recovery: snapshot journal interruption is cleanup-only" {
    lock_and_apply_all
    local journal transaction claude_hash codex_hash
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    claude_hash="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    codex_hash="$(tree_hash "$CODEX_SKILLS_DIR/demo-skill")"

    run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_SNAPSHOT_JOURNAL \
        "*" \
        rollback-snapshot-journal \
        rollback --transaction "$transaction"
    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    assert_journal_status_and_operations "$journal" rollback_preparing applied
    [ -d "$STATE_ROOT/rollback-backups/$transaction" ]

    run_registry recover --transaction "$transaction"

    [ "$status" -eq 0 ]
    assert_journal_status_and_operations "$journal" applied applied
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$claude_hash" ]
    [ "$(tree_hash "$CODEX_SKILLS_DIR/demo-skill")" = "$codex_hash" ]
    [ ! -e "$STATE_ROOT/rollback-backups/$transaction" ]
    "$PYTHON" - "$journal" <<'PY'
import json
import pathlib
import sys

data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert all(entry["rollback_tree_sha256"] is None for entry in data["operations"])
PY
}

@test "skill registry recovery: interrupted prune rollback compensation removes its detached tree" {
    lock_and_apply_all
    mutate_registry_skill status disabled
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local journal transaction detached
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    detached="$CLAUDE_SKILLS_DIR/.shogun-rollback-restored-original-$transaction-demo-skill"
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]

    INTERRUPT_ROLLBACK_FAILURE_TARGET=claude \
        run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_COMPENSATION_DETACH \
        "$CLAUDE_SKILLS_DIR/demo-skill" \
        prune-rollback-compensation \
        rollback --transaction "$transaction"

    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ -d "$detached" ]

    run_registry recover --transaction "$transaction"

    [ "$status" -eq 0 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ ! -e "$detached" ]
    assert_journal_status_and_operations "$journal" applied applied

    run_registry rollback --transaction "$transaction"

    [ "$status" -eq 0 ]
    [ -f "$CLAUDE_SKILLS_DIR/demo-skill/SKILL.md" ]
}

@test "skill registry recovery: second interruption after rollback original detach is recoverable" {
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local original_hash
    original_hash="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    mutate_registry_skill status enabled
    printf '\nReplacement release.\n' >> "$FIXTURE_ROOT/skills/demo-skill/SKILL.md"
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local applied_hash journal transaction detached rollback_original
    applied_hash="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    detached="$CLAUDE_SKILLS_DIR/.shogun-rollback-applied-$transaction-demo-skill"
    rollback_original="$CLAUDE_SKILLS_DIR/.shogun-rollback-original-$transaction-demo-skill"

    run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_RESTORE \
        "$CLAUDE_SKILLS_DIR/demo-skill" \
        rollback-after-restore \
        rollback --transaction "$transaction"
    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$original_hash" ]
    [ "$(tree_hash "$detached")" = "$applied_hash" ]

    run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_ORIGINAL_DETACH \
        "$CLAUDE_SKILLS_DIR/demo-skill" \
        rollback-after-original-detach \
        recover --transaction "$transaction"
    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ "$(tree_hash "$detached")" = "$applied_hash" ]
    [ "$(tree_hash "$rollback_original")" = "$original_hash" ]

    run_registry recover --transaction "$transaction"

    [ "$status" -eq 0 ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$applied_hash" ]
    [ ! -e "$detached" ]
    [ ! -e "$rollback_original" ]
    assert_journal_status_and_operations "$journal" applied applied
}

@test "skill registry recovery: second interruption after rollback applied restore is recoverable" {
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local original_hash
    original_hash="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    mutate_registry_skill status enabled
    printf '\nReplacement release.\n' >> "$FIXTURE_ROOT/skills/demo-skill/SKILL.md"
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local applied_hash journal transaction detached rollback_original
    applied_hash="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    detached="$CLAUDE_SKILLS_DIR/.shogun-rollback-applied-$transaction-demo-skill"
    rollback_original="$CLAUDE_SKILLS_DIR/.shogun-rollback-original-$transaction-demo-skill"

    run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_RESTORE \
        "$CLAUDE_SKILLS_DIR/demo-skill" \
        rollback-after-restore \
        rollback --transaction "$transaction"
    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]

    run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_APPLIED_RESTORE \
        "$CLAUDE_SKILLS_DIR/demo-skill" \
        rollback-after-applied-restore \
        recover --transaction "$transaction"
    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$applied_hash" ]
    [ ! -e "$detached" ]
    [ "$(tree_hash "$rollback_original")" = "$original_hash" ]

    run_registry recover --transaction "$transaction"

    [ "$status" -eq 0 ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$applied_hash" ]
    [ ! -e "$detached" ]
    [ ! -e "$rollback_original" ]
    assert_journal_status_and_operations "$journal" applied applied
}

@test "skill registry recovery: partial replacement restore stage is discarded before compensation succeeds" {
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    mutate_registry_skill status enabled
    printf '\nReplacement release.\n' >> "$FIXTURE_ROOT/skills/demo-skill/SKILL.md"
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local applied_hash journal transaction stage detached
    applied_hash="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    stage="$CLAUDE_SKILLS_DIR/.stage-$transaction-restore-demo-skill"
    detached="$CLAUDE_SKILLS_DIR/.shogun-rollback-applied-$transaction-demo-skill"

    run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_DURING_RESTORE_COPY \
        "$CLAUDE_SKILLS_DIR/demo-skill" \
        partial-replacement-restore-copy \
        rollback --transaction "$transaction"
    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ -d "$stage" ]
    [ -d "$detached" ]

    run_registry recover --transaction "$transaction"

    [ "$status" -eq 0 ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$applied_hash" ]
    [ ! -e "$stage" ]
    [ ! -e "$detached" ]
    [ -z "$(find "$CLAUDE_SKILLS_DIR" -maxdepth 1 -name "*${transaction}*" -print -quit)" ]
    assert_journal_status_and_operations "$journal" applied applied
}

@test "skill registry recovery: partial prune restore stage is discarded before compensation succeeds" {
    lock_and_apply_all
    mutate_registry_skill status disabled
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local journal transaction stage
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    stage="$CLAUDE_SKILLS_DIR/.stage-$transaction-restore-demo-skill"

    run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_DURING_RESTORE_COPY \
        "$CLAUDE_SKILLS_DIR/demo-skill" \
        partial-prune-restore-copy \
        rollback --transaction "$transaction"
    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ -d "$stage" ]

    run_registry recover --transaction "$transaction"

    [ "$status" -eq 0 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ ! -e "$stage" ]
    [ -z "$(find "$CLAUDE_SKILLS_DIR" -maxdepth 1 -name "*${transaction}*" -print -quit)" ]
    assert_journal_status_and_operations "$journal" applied applied
}

@test "skill registry recovery: partial apply-compensation rmtree is resumable" {
    run_registry lock
    [ "$status" -eq 0 ]

    INTERRUPT_APPLY_FAILURE_TARGET=claude \
        run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_DURING_TRANSACTION_RMTREE \
        "*" \
        partial-apply-compensation-rmtree \
        apply --targets claude
    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    local journal transaction tombstone
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    tombstone="$(find "$CLAUDE_SKILLS_DIR" -maxdepth 1 \
        -name ".shogun-discard-.shogun-apply-detached-$transaction-demo-skill-*" \
        -print -quit)"
    [ -n "$tombstone" ]
    [ -d "$tombstone" ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]

    run_registry recover --transaction "$transaction"

    [ "$status" -eq 0 ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]
    [ ! -e "$tombstone" ]
    [ -z "$(find "$CLAUDE_SKILLS_DIR" -maxdepth 1 -name "*${transaction}*" -print -quit)" ]
    assert_journal_status_and_operations "$journal" compensated compensated
}

@test "skill registry recovery: partial forward-rollback rmtree is resumable" {
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local applied_hash journal transaction tombstone
    applied_hash="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"

    run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_DURING_TRANSACTION_RMTREE \
        "*" \
        partial-forward-rollback-rmtree \
        rollback --transaction "$transaction"
    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    tombstone="$(find "$CLAUDE_SKILLS_DIR" -maxdepth 1 \
        -name ".shogun-discard-.shogun-rollback-applied-$transaction-demo-skill-*" \
        -print -quit)"
    [ -n "$tombstone" ]
    [ -d "$tombstone" ]
    [ ! -e "$CLAUDE_SKILLS_DIR/demo-skill" ]

    run_registry recover --transaction "$transaction"

    [ "$status" -eq 0 ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$applied_hash" ]
    [ ! -e "$tombstone" ]
    [ -z "$(find "$CLAUDE_SKILLS_DIR" -maxdepth 1 -name "*${transaction}*" -print -quit)" ]
    assert_journal_status_and_operations "$journal" applied applied
}

@test "skill registry recovery: a valid interrupted restore stage is reusable" {
    "$PYTHON" - "$PROJECT_ROOT/scripts/skill_registry.py" "$TEST_ROOT" <<'PY'
import importlib.util
import pathlib
import shutil
import sys

spec = importlib.util.spec_from_file_location("skill_registry", sys.argv[1])
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

root = pathlib.Path(sys.argv[2]) / "restore-stage-reuse"
backup = root / "backup"
destination = root / "target" / "demo-skill"
backup.mkdir(parents=True)
(backup / "SKILL.md").write_text("original\n", encoding="utf-8")
expected = module.backup_tree_sha256(backup)
transaction = "20260714T120000000000Z-deadbeef"
stage = destination.parent / f".stage-{transaction}-restore-{destination.name}"
stage.parent.mkdir(parents=True)
shutil.copytree(backup, stage)

module.restore_backup(destination, backup, transaction, expected)

assert (destination / "SKILL.md").read_text(encoding="utf-8") == "original\n"
assert not stage.exists()
PY
}

@test "skill registry recovery: prepared replace retains its original hash" {
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local original_hash
    original_hash="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    mutate_registry_skill status enabled
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_PREPARED_JOURNAL \
        "*" \
        prepared-replace \
        apply --targets claude

    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    local journal transaction
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    run_registry recover --transaction "$transaction"
    [ "$status" -eq 0 ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$original_hash" ]
    assert_journal_status_and_operations "$journal" compensated compensated
}

@test "skill registry recovery: prepared prune retains its original hash" {
    run_registry lock
    [ "$status" -eq 0 ]
    run_registry apply --targets claude
    [ "$status" -eq 0 ]
    local original_hash
    original_hash="$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")"
    mutate_registry_skill status disabled
    run_registry lock
    [ "$status" -eq 0 ]

    run_registry_and_kill_at_pause \
        SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_PREPARED_JOURNAL \
        "*" \
        prepared-prune \
        apply --targets claude

    [ "$status" -ne 0 ]
    [ "$status" -ne 99 ]
    local journal transaction
    journal="$(latest_transaction_journal)"
    transaction="$(journal_transaction_id "$journal")"
    run_registry recover --transaction "$transaction"
    [ "$status" -eq 0 ]
    [ "$(tree_hash "$CLAUDE_SKILLS_DIR/demo-skill")" = "$original_hash" ]
    assert_journal_status_and_operations "$journal" compensated compensated
}

@test "skill registry recovery: backup drift never overwrites the planned original hash" {
    "$PYTHON" - "$PROJECT_ROOT/scripts/skill_registry.py" "$TEST_ROOT" <<'PY'
import importlib.util
import pathlib
import shutil
import sys

spec = importlib.util.spec_from_file_location("skill_registry", sys.argv[1])
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

root = pathlib.Path(sys.argv[2]) / "backup-drift-hash"
destination = root / "target" / "demo-skill"
destination.mkdir(parents=True)
(destination / "legacy.txt").write_text("original\n", encoding="utf-8")
original_hash = module.backup_tree_sha256(destination)
transaction = "20260714T120000000000Z-deadbeef"
state_dir = root / "state"
entry = {
    "backup": f"backups/{transaction}/claude/demo-skill",
    "backup_tree_sha256": original_hash,
}
journal = {"operations": [entry]}
operation = {
    "destination": destination,
    "skill_id": "demo-skill",
    "original_tree_sha256": original_hash,
}

def drifting_copy(source, backup, _context):
    shutil.copytree(source, backup)
    (backup / "legacy.txt").write_text("changed during copy\n", encoding="utf-8")

module.copy_directory = drifting_copy
try:
    module.apply_operation(
        operation,
        0,
        transaction,
        journal,
        state_dir,
        {},
    )
except module.RegistryError:
    pass
else:
    raise AssertionError("drifted backup was accepted")

assert entry["backup_tree_sha256"] == original_hash
PY
}

@test "skill registry apply: preserves a render stage swapped during generation" {
    "$PYTHON" - "$PROJECT_ROOT/scripts/skill_registry.py" "$TEST_ROOT" <<'PY'
import importlib.util
import pathlib
import shutil
import sys

spec = importlib.util.spec_from_file_location("skill_registry", sys.argv[1])
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

root = pathlib.Path(sys.argv[2]) / "render-generation-swap"
destination = root / "target" / "demo-skill"
expected_tree = root / "expected"
expected_tree.mkdir(parents=True)
(expected_tree / "SKILL.md").write_text("expected\n", encoding="utf-8")
expected_hash = module.disk_tree_sha256(expected_tree)
shutil.rmtree(expected_tree)
transaction = "20260714T120000000000Z-deadbeef"
preserved_valid = root / "preserved-valid-stage"

def interpose(variable, subject):
    if variable != "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_RENDER_STAGE_CREATE":
        return
    stage = pathlib.Path(subject)
    stage.rename(preserved_valid)
    stage.mkdir()

module.pause_at_control_for_test = interpose
operation = {
    "destination": destination,
    "target": "claude",
    "skill_id": "demo-skill",
    "version": "1.0.0",
    "tree_sha256": expected_hash,
    "rendered": {"SKILL.md": (b"expected\n", False)},
}
try:
    module.write_rendered_stage(
        operation,
        transaction,
        {"registry_sha256": "a" * 64},
    )
except module.RegistryError:
    pass
else:
    raise AssertionError("swapped generation stage was accepted")

preserved = module.transaction_detached_path(
    destination, transaction, "stage-preserved"
)
assert preserved.is_dir()
assert not any(preserved.iterdir())
assert preserved_valid.is_dir()
PY
}

@test "skill registry recovery: preserves a stage recreated after restore commit" {
    "$PYTHON" - "$PROJECT_ROOT/scripts/skill_registry.py" "$TEST_ROOT" <<'PY'
import importlib.util
import pathlib
import sys

spec = importlib.util.spec_from_file_location("skill_registry", sys.argv[1])
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

root = pathlib.Path(sys.argv[2]) / "restore-postcommit-stage"
backup = root / "backup"
destination = root / "target" / "demo-skill"
backup.mkdir(parents=True)
(backup / "SKILL.md").write_text("original\n", encoding="utf-8")
expected = module.backup_tree_sha256(backup)
transaction = "20260714T120000000000Z-deadbeef"

def interpose(variable, subject):
    if variable != "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_RESTORE_COMMIT":
        return
    stage = pathlib.Path(subject)
    assert not stage.exists()
    stage.mkdir()
    (stage / "sentinel.txt").write_text("unmanaged\n", encoding="utf-8")

module.pause_at_control_for_test = interpose
try:
    module.restore_backup(destination, backup, transaction, expected)
except module.RegistryError:
    pass
else:
    raise AssertionError("recreated restore stage was accepted")

assert (destination / "SKILL.md").read_text(encoding="utf-8") == "original\n"
preserved = module.transaction_detached_path(
    destination, transaction, "restore-stage-preserved"
)
assert (preserved / "sentinel.txt").read_text(encoding="utf-8") == "unmanaged\n"
PY
}

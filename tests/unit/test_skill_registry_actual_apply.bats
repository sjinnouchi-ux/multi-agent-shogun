#!/usr/bin/env bats

setup() {
  local physical_tmp
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  physical_tmp="$(cd "$BATS_TEST_TMPDIR" && pwd -P)" || return 1
  TEST_ROOT="$(mktemp -d "${physical_tmp}/actual-registry.XXXXXX")"
  export SHOGUN_SKILL_REGISTRY_CLAUDE_DIR="${TEST_ROOT}/claude"
  export SHOGUN_SKILL_REGISTRY_CODEX_DIR="${TEST_ROOT}/codex"
  export SHOGUN_SKILL_REGISTRY_STATE_DIR="${TEST_ROOT}/state"
  mkdir -p \
    "${SHOGUN_SKILL_REGISTRY_CLAUDE_DIR}/unmanaged" \
    "${SHOGUN_SKILL_REGISTRY_CODEX_DIR}/unmanaged"
  printf 'keep\n' > "${SHOGUN_SKILL_REGISTRY_CLAUDE_DIR}/unmanaged/KEEP"
  printf 'keep\n' > "${SHOGUN_SKILL_REGISTRY_CODEX_DIR}/unmanaged/KEEP"
}

teardown() {
  rm -rf -- "$TEST_ROOT"
}

@test "tracked registry applies idempotently to both temporary targets and rolls back" {
  run bash "${REPO_ROOT}/scripts/skill_registry.sh" apply --targets all
  [ "$status" -eq 0 ]

  [ -f "${SHOGUN_SKILL_REGISTRY_CLAUDE_DIR}/shogun-systematic-debugging/SKILL.md" ]
  [ -f "${SHOGUN_SKILL_REGISTRY_CODEX_DIR}/shogun-systematic-debugging/agents/openai.yaml" ]
  [ -f "${SHOGUN_SKILL_REGISTRY_CLAUDE_DIR}/unmanaged/KEEP" ]
  [ -f "${SHOGUN_SKILL_REGISTRY_CODEX_DIR}/unmanaged/KEEP" ]

  local target skill
  for target in "$SHOGUN_SKILL_REGISTRY_CLAUDE_DIR" "$SHOGUN_SKILL_REGISTRY_CODEX_DIR"; do
    for skill in \
      shogun-systematic-debugging \
      shogun-test-first \
      shogun-verification-before-done \
      shogun-review-response; do
      cmp "$REPO_ROOT/skills/third_party/superpowers/LICENSE" "$target/$skill/LICENSE"
      [ ! -e "$target/$skill/references/pressure-evidence.md" ]
      [ ! -e "$target/$skill/references/pressure-run.yaml" ]
    done
  done
  [ -f "${SHOGUN_SKILL_REGISTRY_CLAUDE_DIR}/shogun-systematic-debugging/references/debug-record.md" ]
  [ -f "${SHOGUN_SKILL_REGISTRY_CLAUDE_DIR}/shogun-verification-before-done/references/evidence-packet.md" ]
  [ -f "${SHOGUN_SKILL_REGISTRY_CLAUDE_DIR}/shogun-review-response/references/comment-ledger.md" ]

  run bash "${REPO_ROOT}/scripts/skill_registry.sh" apply --targets all
  [ "$status" -eq 0 ]

  run bash "${REPO_ROOT}/scripts/skill_registry.sh" rollback
  [ "$status" -eq 0 ]

  [ ! -e "${SHOGUN_SKILL_REGISTRY_CLAUDE_DIR}/shogun-systematic-debugging" ]
  [ ! -e "${SHOGUN_SKILL_REGISTRY_CODEX_DIR}/shogun-systematic-debugging" ]
  [ -f "${SHOGUN_SKILL_REGISTRY_CLAUDE_DIR}/unmanaged/KEEP" ]
  [ -f "${SHOGUN_SKILL_REGISTRY_CODEX_DIR}/unmanaged/KEEP" ]
}

#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
}

@test "project integration exposes registry check and lock Make targets" {
  run grep -Eq '^skill-registry-check:' "${REPO_ROOT}/Makefile"
  [ "$status" -eq 0 ]

  run grep -Eq '^skill-registry-lock:' "${REPO_ROOT}/Makefile"
  [ "$status" -eq 0 ]
}

@test "CI checks the registry against the explicit pull-request base" {
  workflow="${REPO_ROOT}/.github/workflows/test.yml"

  run grep -Eq 'fetch-depth:[[:space:]]*0' "$workflow"
  [ "$status" -eq 0 ]

  run grep -F 'bash scripts/skill_registry.sh validate' "$workflow"
  [ "$status" -eq 0 ]

  run grep -F 'bash scripts/skill_registry.sh check --base-ref "$PR_BASE_SHA"' "$workflow"
  [ "$status" -eq 0 ]
}

@test "unit-test CI exposes the venv Python and macOS GNU test tools" {
  workflow="${REPO_ROOT}/.github/workflows/test.yml"

  run grep -F 'echo "$PWD/.venv/bin" >> "$GITHUB_PATH"' "$workflow"
  [ "$status" -eq 0 ]

  run grep -F 'brew install bash coreutils gnu-sed shellcheck' "$workflow"
  [ "$status" -eq 0 ]

  run grep -F 'echo "$(brew --prefix)/opt/gnu-sed/libexec/gnubin" >> "$GITHUB_PATH"' "$workflow"
  [ "$status" -eq 0 ]
}

@test "build drift gates cover every tracked instruction output" {
  workflow="${REPO_ROOT}/.github/workflows/test.yml"
  makefile="${REPO_ROOT}/Makefile"
  outputs=(
    "instructions/generated/"
    ".opencode/agents/"
    "instructions/shogun.md"
    "instructions/karo.md"
    "instructions/ashigaru.md"
    "instructions/gunshi.md"
    "instructions/oometsuke.md"
    "AGENTS.md"
    ".github/copilot-instructions.md"
    "agents/default/system.md"
    "agents/default/agent.yaml"
  )

  for output in "${outputs[@]}"; do
    grep -Fq "$output" "$workflow"
    grep -Fq "$output" "$makefile"
  done
}

@test "Kimi agent manifest is a tracked generated artifact" {
  run git -C "$REPO_ROOT" ls-files --error-unmatch agents/default/agent.yaml
  [ "$status" -eq 0 ]
}

@test "registry wrapper is tracked executable for Linux setup" {
  run git -C "$REPO_ROOT" ls-files --stage -- scripts/skill_registry.sh
  [ "$status" -eq 0 ]
  [[ "$output" == 100755* ]]
}

@test "build drift gates reject generated outputs that are only untracked" {
  workflow="${REPO_ROOT}/.github/workflows/test.yml"
  makefile="${REPO_ROOT}/Makefile"
  grep -Fq 'git ls-files --others --exclude-standard' "$workflow"
  grep -Fq 'git ls-files --others --exclude-standard' "$makefile"
}

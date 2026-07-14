#!/usr/bin/env bats

setup_file() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export SETUP="$PROJECT_ROOT/first_setup.sh"
}

@test "first setup applies the checked registry to both CLI targets" {
    grep -Fq 'scripts/skill_registry.sh" validate' "$SETUP"
    grep -Fq 'scripts/skill_registry.sh" check' "$SETUP"
    grep -Fq 'scripts/skill_registry.sh" apply --targets all' "$SETUP"
}

@test "first setup no longer copies arbitrary skill directories" {
    run grep -F 'cp -r "$skill_dir" "$target"' "$SETUP"
    [ "$status" -eq 1 ]
    run grep -F 'for skill_dir in "$SCRIPT_DIR/skills"' "$SETUP"
    [ "$status" -eq 1 ]
}

@test "first setup never regenerates the canonical lock during deployment" {
    run grep -F 'scripts/skill_registry.sh" lock' "$SETUP"
    [ "$status" -eq 1 ]
}

@test "first setup does not emit legacy single-CLI skill path settings" {
    run grep -E 'save_path:|local_path:|^[[:space:]]*skill:' "$SETUP"
    [ "$status" -eq 1 ]
}

#!/usr/bin/env bats

setup_file() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export CHECKER="$PROJECT_ROOT/scripts/check_skill_pressure_evidence.py"

    if [ -x "$PROJECT_ROOT/.venv/bin/python3" ]; then
        export PYTHON="$PROJECT_ROOT/.venv/bin/python3"
    else
        export PYTHON=python3
    fi
}

setup() {
    export FIXTURE_ROOT
    FIXTURE_ROOT="$(mktemp -d)"
    mkdir -p "$FIXTURE_ROOT/skills" "$FIXTURE_ROOT/tests/skill_scenarios"

    local skill
    for skill in \
        shogun-systematic-debugging \
        shogun-test-first \
        shogun-verification-before-done \
        shogun-review-response; do
        cp -R "$PROJECT_ROOT/skills/$skill" "$FIXTURE_ROOT/skills/$skill"
        cp "$PROJECT_ROOT/tests/skill_scenarios/$skill.yaml" \
            "$FIXTURE_ROOT/tests/skill_scenarios/$skill.yaml"
    done
}

teardown() {
    rm -rf "$FIXTURE_ROOT"
}

@test "structured pressure evidence validates for all adapted skills" {
    run "$PYTHON" "$CHECKER" --root "$PROJECT_ROOT"

    [ "$status" -eq 0 ]
    [[ "$output" == *"validated 4 pressure evidence records"* ]]
}

@test "checker rejects a changed skill hash" {
    printf '\n# tampered\n' >> \
        "$FIXTURE_ROOT/skills/shogun-test-first/SKILL.md"

    run "$PYTHON" "$CHECKER" --root "$FIXTURE_ROOT"

    [ "$status" -ne 0 ]
    [[ "$output" == *"SKILL.md SHA-256 mismatch"* ]]
}

@test "checker rejects a changed scenario hash" {
    printf '\n# tampered\n' >> \
        "$FIXTURE_ROOT/tests/skill_scenarios/shogun-review-response.yaml"

    run "$PYTHON" "$CHECKER" --root "$FIXTURE_ROOT"

    [ "$status" -ne 0 ]
    [[ "$output" == *"scenario SHA-256 mismatch"* ]]
}

@test "checker rejects a changed narrative evidence hash" {
    printf '\nTampered narrative.\n' >> \
        "$FIXTURE_ROOT/skills/shogun-test-first/references/pressure-evidence.md"

    run "$PYTHON" "$CHECKER" --root "$FIXTURE_ROOT"

    [ "$status" -ne 0 ]
    [[ "$output" == *"pressure-evidence.md SHA-256 mismatch"* ]]
}

@test "checker rejects prohibited material even when its evidence hash is updated" {
    local evidence="$FIXTURE_ROOT/skills/shogun-test-first/references/pressure-evidence.md"
    local record="$FIXTURE_ROOT/skills/shogun-test-first/references/pressure-run.yaml"
    local digest
    printf '\noauth_code=REDACTED_TEST_VALUE\n' >> "$evidence"
    digest="$(sha256sum "$evidence" | cut -d ' ' -f 1)"
    sed -i "/^  evidence:/,/^    sha256:/ s#^    sha256: sha256:.*#    sha256: sha256:$digest#" \
        "$record"

    run "$PYTHON" "$CHECKER" --root "$FIXTURE_ROOT"

    [ "$status" -ne 0 ]
    [[ "$output" == *"prohibited raw-material marker found"* ]]
}

@test "checker rejects skipped or unknown post-skill states" {
    local record="$FIXTURE_ROOT/skills/shogun-verification-before-done/references/pressure-run.yaml"
    sed -i '0,/result: PASS/s//result: SKIP/' "$record"

    run "$PYTHON" "$CHECKER" --root "$FIXTURE_ROOT"

    [ "$status" -ne 0 ]
    [[ "$output" == *"result must be PASS"* ]]
}

@test "checker rejects tampered required outcome counts" {
    local record="$FIXTURE_ROOT/skills/shogun-systematic-debugging/references/pressure-run.yaml"
    sed -i '0,/satisfied: [0-9][0-9]*/s//satisfied: 0/' "$record"

    run "$PYTHON" "$CHECKER" --root "$FIXTURE_ROOT"

    [ "$status" -ne 0 ]
    [[ "$output" == *"required outcome count mismatch"* ]]
}

@test "checker rejects missing or unexpected scenario IDs" {
    local record="$FIXTURE_ROOT/skills/shogun-test-first/references/pressure-run.yaml"
    sed -i '/^post_skill:/,$ s/id: urgent-two-line-hotfix/id: invented-case/' "$record"

    run "$PYTHON" "$CHECKER" --root "$FIXTURE_ROOT"

    [ "$status" -ne 0 ]
    [[ "$output" == *"post-skill case IDs do not match scenarios"* ]]
}

@test "checker rejects evidence schema expansion" {
    printf '\nunexpected: true\n' >> \
        "$FIXTURE_ROOT/skills/shogun-review-response/references/pressure-run.yaml"

    run "$PYTHON" "$CHECKER" --root "$FIXTURE_ROOT"

    [ "$status" -ne 0 ]
    [[ "$output" == *"unexpected or missing keys"* ]]
}

@test "checker preserves explicit attestation limitations" {
    local record="$FIXTURE_ROOT/skills/shogun-test-first/references/pressure-run.yaml"
    sed -i 's/exhaustive sanitization/complete sanitization/' "$record"

    run "$PYTHON" "$CHECKER" --root "$FIXTURE_ROOT"

    [ "$status" -ne 0 ]
    [[ "$output" == *"must disclose checker limitations"* ]]
}

@test "checker validates scenario evidence references" {
    local scenario="$FIXTURE_ROOT/tests/skill_scenarios/shogun-test-first.yaml"
    sed -i 's#^evidence_ref:.*#evidence_ref: ../outside.md#' "$scenario"

    run "$PYTHON" "$CHECKER" --root "$FIXTURE_ROOT"

    [ "$status" -ne 0 ]
    [[ "$output" == *"evidence_ref must be"* ]]
}

@test "checker validates multi-pressure scenario fields" {
    local scenario="$FIXTURE_ROOT/tests/skill_scenarios/shogun-verification-before-done.yaml"
    sed -i '0,/pressures: \[/s//pressures: [deadline, deadline] #/' "$scenario"

    run "$PYTHON" "$CHECKER" --root "$FIXTURE_ROOT"

    [ "$status" -ne 0 ]
    [[ "$output" == *"at least three unique pressure identifiers"* ]]
}

@test "checker rejects invented pressure identifiers" {
    local scenario="$FIXTURE_ROOT/tests/skill_scenarios/shogun-review-response.yaml"
    sed -i '0,/pressures: \[/s//pressures: [x, y, z] #/' "$scenario"

    run "$PYTHON" "$CHECKER" --root "$FIXTURE_ROOT"

    [ "$status" -ne 0 ]
    [[ "$output" == *"unknown pressure identifier"* ]]
}

@test "checker rejects artifact symlinks that escape the repository root" {
    local scenario="$FIXTURE_ROOT/tests/skill_scenarios/shogun-review-response.yaml"
    rm "$scenario"
    ln -s "$PROJECT_ROOT/tests/skill_scenarios/shogun-review-response.yaml" "$scenario"

    run "$PYTHON" "$CHECKER" --root "$FIXTURE_ROOT"

    [ "$status" -ne 0 ]
    [[ "$output" == *"symlink is not allowed"* ]]
}

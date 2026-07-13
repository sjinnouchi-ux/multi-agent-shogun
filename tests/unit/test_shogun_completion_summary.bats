#!/usr/bin/env bats

setup() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export TEST_TMPDIR="$(mktemp -d "$BATS_TMPDIR/completion_summary.XXXXXX")"
    export TEST_REPO="$TEST_TMPDIR/repo"
    mkdir -p "$TEST_REPO"
    git -C "$TEST_REPO" init -q
    git -C "$TEST_REPO" config user.email "test@example.com"
    git -C "$TEST_REPO" config user.name "Test User"
    git -C "$TEST_REPO" remote add origin \
        https://github.com/sjinnouchi-ux/example.git
    echo base > "$TEST_REPO/file.txt"
    git -C "$TEST_REPO" add file.txt
    git -C "$TEST_REPO" commit -q -m base
    export BASE_COMMIT="$(git -C "$TEST_REPO" rev-parse HEAD)"
    git -C "$TEST_REPO" switch -q -c shogun/cmd-123
    echo changed > "$TEST_REPO/file.txt"
    git -C "$TEST_REPO" commit -qam changed
}

teardown() {
    rm -rf "$TEST_TMPDIR"
}

run_summary() {
    run python3 "$PROJECT_ROOT/scripts/shogun_completion_summary.py" \
        --repo "$TEST_REPO" \
        --project demo \
        --task-id cmd_123 \
        --base-commit "$BASE_COMMIT" \
        --verification "bats: passed" \
        --risk "none" \
        --pr-url "https://github.com/sjinnouchi-ux/example/pull/1" \
        --report-url "https://github.com/sjinnouchi-ux/example/blob/main/report.md" \
        --summary "Implementation and verification completed." \
        --review-status approved
}

@test "completion summary records Git boundary facts" {
    run_summary
    [ "$status" -eq 0 ]
    [[ "$output" == *'source: "shogun"'* ]]
    [[ "$output" == *'working_branch: "shogun/cmd-123"'* ]]
    [[ "$output" == *'result_commit:'* ]]
    [[ "$output" == *'report_url: "https://github.com/sjinnouchi-ux/example/blob/main/report.md"'* ]]
    [[ "$output" == *'summary: "Implementation and verification completed."'* ]]
    [[ "$output" == *'review_status: "approved"'* ]]
    [[ "$output" == *'- `file.txt`'* ]]
    [[ "$output" == *'- bats: passed'* ]]
}

@test "completion summary refuses a dirty repository" {
    echo dirty >> "$TEST_REPO/file.txt"
    run_summary
    [ "$status" -eq 2 ]
    [[ "$output" == *"repository has uncommitted or untracked changes"* ]]
}

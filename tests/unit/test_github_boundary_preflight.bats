#!/usr/bin/env bats

setup() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export TEST_TMPDIR="$(mktemp -d "$BATS_TMPDIR/github_boundary.XXXXXX")"
    export TEST_REPO="$TEST_TMPDIR/repo"
    mkdir -p "$TEST_REPO" "$TEST_TMPDIR/home/.codex"
    git -C "$TEST_REPO" init -q
    git -C "$TEST_REPO" config user.email "test@example.com"
    git -C "$TEST_REPO" config user.name "Test User"
    git -C "$TEST_REPO" remote add origin \
        https://github.com/sjinnouchi-ux/example.git
    echo base > "$TEST_REPO/file.txt"
    git -C "$TEST_REPO" add file.txt
    git -C "$TEST_REPO" commit -q -m base
    git -C "$TEST_REPO" branch -M main
    git -C "$TEST_REPO" switch -q -c shogun/cmd-123
}

teardown() {
    rm -rf "$TEST_TMPDIR"
}

run_preflight() {
    run env HOME="$TEST_TMPDIR/home" CODEX_HOME="$TEST_TMPDIR/home/.codex" \
        bash "$PROJECT_ROOT/scripts/github_boundary_preflight.sh" \
        --repo "$TEST_REPO" \
        --canonical-url https://github.com/sjinnouchi-ux/example.git
}

@test "preflight records canonical boundary metadata" {
    run_preflight
    [ "$status" -eq 0 ]
    [[ "$output" == *"source=shogun"* ]]
    [[ "$output" == *"branch=shogun/cmd-123"* ]]
    [[ "$output" == *"canonical_remote=origin"* ]]
    [[ "$output" == *"base_commit="* ]]
}

@test "preflight rejects work on main" {
    git -C "$TEST_REPO" switch -q main
    run_preflight
    [ "$status" -eq 2 ]
    [[ "$output" == *"direct work on primary branch is not allowed"* ]]
}

@test "preflight rejects a non-Shogun branch" {
    git -C "$TEST_REPO" switch -q -c codex/demo
    run_preflight
    [ "$status" -eq 2 ]
    [[ "$output" == *"branch must start with shogun/"* ]]
}

@test "preflight rejects a Windows-backed CODEX_HOME" {
    run env HOME="$TEST_TMPDIR/home" CODEX_HOME=/mnt/c/Users/example/.codex \
        bash "$PROJECT_ROOT/scripts/github_boundary_preflight.sh" \
        --repo "$TEST_REPO"
    [ "$status" -eq 2 ]
    [[ "$output" == *"CODEX_HOME must stay inside WSL2 Linux"* ]]
}

@test "preflight refuses to print a credential-bearing remote" {
    git -C "$TEST_REPO" remote set-url origin https://user:token@example.com/repo.git
    run env HOME="$TEST_TMPDIR/home" CODEX_HOME="$TEST_TMPDIR/home/.codex" \
        bash "$PROJECT_ROOT/scripts/github_boundary_preflight.sh" \
        --repo "$TEST_REPO"
    [ "$status" -eq 2 ]
    [[ "$output" == *"credential-bearing remote URL cannot be recorded"* ]]
    [[ "$output" != *"token"* ]]
}

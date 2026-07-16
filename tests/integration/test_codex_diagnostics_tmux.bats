#!/usr/bin/env bats

@test "codex diagnostics uses an isolated tmux socket without pane capture" {
    export SHOGUN_DIAGNOSTIC_TEST_SOCKET="codex-diagnostics-${BATS_TEST_NUMBER}-$$"
    run python3 -m unittest -v \
        tests.integration.test_codex_diagnostics_tmux.UniqueTmuxSocketTests
    [ "$status" -eq 0 ]
    [[ "$output" != *"skipped="* ]]
}

#!/usr/bin/env bats

setup() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export SCRIPT="$PROJECT_ROOT/scripts/codex_diagnostics.py"
}

assert_python_suite_passed() {
    if [ "$status" -ne 0 ]; then
        printf '%s\n' "$output"
        return "$status"
    fi
    [[ "$output" != *"skipped="* ]]
}

@test "codex diagnostics unittest suite passes with zero skips" {
    run python3 -m unittest -v tests.unit.test_codex_diagnostics
    assert_python_suite_passed
}

@test "codex diagnostics consumer contract rejects every untrusted fixture" {
    run python3 -m unittest -v \
        tests.contract.test_codex_diagnostics_consumer
    assert_python_suite_passed
}

@test "codex diagnostics rollback primitive passes atomicity tests" {
    run python3 -m unittest -v \
        tests.unit.test_rollback_codex_diagnostics_snapshot
    assert_python_suite_passed
}

@test "codex diagnostics source and tests compile" {
    run env PYTHONPYCACHEPREFIX="$BATS_TEST_TMPDIR/pycache" \
        python3 -m py_compile \
        "$SCRIPT" \
        "$PROJECT_ROOT/tests/unit/test_codex_diagnostics.py" \
        "$PROJECT_ROOT/tests/contract/codex_diagnostics_consumer.py" \
        "$PROJECT_ROOT/tests/contract/test_codex_diagnostics_consumer.py" \
        "$PROJECT_ROOT/scripts/rollback_codex_diagnostics_snapshot.py" \
        "$PROJECT_ROOT/tests/unit/test_rollback_codex_diagnostics_snapshot.py"
    [ "$status" -eq 0 ]
}

@test "codex diagnostics rejects suffix with one JSON and empty stderr" {
    stdout="$BATS_TEST_TMPDIR/stdout.json"
    stderr="$BATS_TEST_TMPDIR/stderr.txt"
    set +e
    /usr/bin/python3 -I "$SCRIPT" summary unexpected >"$stdout" 2>"$stderr"
    rc="$?"
    set -e
    if [ "$rc" -ne 2 ]; then
        printf 'unexpected python exit status: %s\n' "$rc"
        sed -n '1,40p' "$stderr"
        return 1
    fi
    [ ! -s "$stderr" ]
    run python3 - "$stdout" <<'PY'
import json
import pathlib
import sys

raw = pathlib.Path(sys.argv[1]).read_bytes()
value = json.loads(raw)
assert value["ok"] is False
assert value["errors"] == [
    {"code": "argument_rejected", "component": "diagnostic", "agent": None}
]
assert value["tool"]["source_sha256"] is None
assert raw.count(b"{") >= 1
PY
    [ "$status" -eq 0 ]
}

# Codex Read-Only Diagnostics

## Boundary

This tool is an on-demand, read-only diagnostic gate for Codex Desktop. It does
not start, stop, restart, repair, enqueue, acknowledge, or alter Shogun. It does
not read tmux pane text or queue/task/report/status bodies. It reads only the
fixed metadata and watcher-log counters defined in the approved design.

## Installed command

`wsl.exe -d Ubuntu --cd /home/jinnouchi/multi-agent-shogun /home/jinnouchi/.local/libexec/shogun-codex-diagnostics summary`

No shorter prefix is approved. `summary` is the only subcommand. Any suffix is
rejected before source hashing and collectors run.

## Trust gate

Immediately before every invocation, read GitHub `main` raw
`docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics-work-log.md`.
Require one deployment marker pair, schema version 1, exactly one active record,
the fixed repository/source/snapshot paths, a 40-character source commit, a
64-character lowercase source SHA-256, UTC seconds, mode `0555`, and contract
schema version 1. Compare the command's `tool.source_sha256` with that record.

Missing/unreadable provenance, malformed markers/schema, zero or multiple
active records, or a hash mismatch is `diagnostic_provenance_untrusted`. A nonzero
exit, empty/non-JSON/partial JSON, nonempty stderr, or a run of 10 seconds or more is
`diagnostic_process_failed`. Neither case permits a raw fallback, repo source
execution, direct runtime reads, or a shorter WSL permission.
Before using any field, independently validate the complete nested schema,
exact key order/cardinality/enums/count limits, ASCII-only bytes, and exit 0.

## Output

Stdout is one ASCII JSON object and stderr is empty. Exit 0 means collection
completed; `overall=degraded` or `overall=unavailable` remains a valid result.
Exit 2 is a preflight/argument rejection. Exit 3 is a fail-closed internal or
serialization failure. The complete schema is fixed by
`docs/superpowers/specs/2026-07-14-codex-readonly-diagnostics-design.md`.

## Deployment and rollback

Deploy only a reviewed main Git blob to
`/home/jinnouchi/.local/libexec/shogun-codex-diagnostics` with mode `0555`.
Do not use sudo, a system directory, `/mnt/c`, a local manifest, or a cache.
Record each deployment through a separate Shogun work-log PR. Roll back by
revoking the full-command permission first, byte-safely removing the host marker,
and reverting the Workspace policy through a PR. Select an explicit superseded
GitHub record, extract its exact Git blob, and use the tested rollback primitive
only when the current bytes equal the failing active hash and the blob equals the
selected target hash. Record the restored deployment as the sole active record
through a separate Shogun work-log PR before any later re-enablement. The
rollback helper is never installed or persistently approved. Its exit 3 is a
verified pre-commit refusal; exit 4 is committed-indeterminate and requires
external hash reconciliation plus a new explicit recovery task, with no record
update or automatic retry.

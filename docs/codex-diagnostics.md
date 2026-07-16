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
exact key order/cardinality/enums/count limits, issue severity, cross-field
state/count/applicability relationships, recomputed `overall`, ASCII-only bytes,
and exit 0. A CLI document may not contain the consumer-only decision codes.
Log counters must be either complete or all null. Complete counters forbid a log
issue for that agent. All-null counters for an observed agent require exactly one
matching `required_source_missing`, `source_rejected`, or `command_failed` log
error; an unobserved agent permits no issue for a missing optional log, or one
matching `source_rejected`/`command_failed` log warning. Global, wrong-severity,
wrong-code, duplicate, and retained contradictory log issues are invalid. A
genuinely full truncated issue array may omit the matching issue, but truncation
never excuses a contradictory issue that remains present.

## Output

Stdout is one ASCII JSON object and stderr is empty. Exit 0 means collection
completed; `overall=degraded` or `overall=unavailable` remains a valid result.
Exit 2 is a preflight/argument rejection. Exit 3 is a fail-closed internal or
serialization failure. The complete schema is fixed by
`docs/superpowers/specs/2026-07-14-codex-readonly-diagnostics-design.md`.
The canonical launcher starts agent watchers directly, so supervisor count `0`
and state `missing` are an optional/not-managed observation and do not degrade
health. Supervisor `duplicate` or `unknown` still degrades health. Making the
supervisor mandatory requires a separate approved control-plane task.

## Deployment and rollback

Deploy only a reviewed main Git blob to
`/home/jinnouchi/.local/libexec/shogun-codex-diagnostics` with mode `0555`.
Do not use sudo, a system directory, `/mnt/c`, a local manifest, or a cache.
For the first deployment, run only the tested lifecycle helper's
`install-initial --source scripts/codex_diagnostics.py` subcommand from reviewed
main. It uses component-wise no-follow dir FDs, durable parent creation,
file/directory fsync, and no-replace publication. Identical existing bytes are
idempotent; different or unsafe entries are never overwritten. The lifecycle
helper revalidates both the fixed parent binding and published leaf inode after
final readback; uncertainty is exit 4. The helper itself is not installed or
persistently approved.
Host `AGENTS.md` marker insertion and removal use one exclusive read/write
`FileStream` for compare, write, truncation, durable flush, readback, and any
restore. A byte-stale reviewed candidate is never written. Before host mutation,
a `CreateNew`/`WriteThrough` backup is durably flushed and read back. An
exclusive handle keeps that backup identity pinned through host write and any
restore; only a verified commit closes and removes it. A failed transaction
closes but retains the verified backup and stops before command approval or any
later rollback step. Task 12 reuses the verbatim helper block plus executable
reverse byte-delta validation. All comparisons preserve BOM, line endings, and
every byte outside the marker block.
Record each deployment through a separate Shogun work-log PR. Roll back by
revoking the full-command permission first, byte-safely removing the host marker,
and reverting the Workspace policy through a PR. Select an explicit superseded
GitHub record, extract its exact Git blob, and use the tested rollback primitive
only when the current bytes equal the failing active hash and the blob equals the
selected target hash. Record the restored deployment as the sole active record
through a separate Shogun work-log PR before any later re-enablement. The
legacy rollback mode is invoked without `install-initial`; that deployment-only
subcommand is forbidden in the rollback procedure. During rollback maintenance,
the pinned snapshot parent must remain owned by the effective user and must not
be group- or world-writable; the fixed snapshot leaf must remain effective-user
owned, regular, mode `0555`, and hash-matched. Stop all cooperating same-UID
maintenance writers for the whole operation. A malicious noncooperating same-UID
writer remains outside this v1 trust boundary. Exit 3 is a verified pre-commit
refusal only when exact temporary cleanup and directory durability succeed and
the trusted parent binding plus the same pinned old leaf are revalidated.
Exit 4 means snapshot commit state or exact temporary-artifact cleanup/durability
state is indeterminate; it requires external reconciliation plus a new explicit
recovery task, with no record update or automatic retry.

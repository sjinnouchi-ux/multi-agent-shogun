# GitHub Boundary Operation

Version: 1.1 lightweight approved

Shogun and Codex Desktop are independent runtimes. They share only GitHub
commits, branches, pull requests, existing project worklogs, and explicitly
published deliverables.

The approved design is stored at:

- Drive: https://drive.google.com/file/d/1kzOvdsw0YZd0qQy5_vKDQPZYWRQkLsUI/view
- SHA-256: `D63EC4684978DBCA11CEC477B2C540F1C1A1E8BE4273ED3644B0CD1F94BA7A82`

## Start A Task

Use a dedicated `shogun/` branch and run the read-only preflight:

```bash
bash scripts/github_boundary_preflight.sh \
  --repo /path/to/project \
  --canonical-url https://github.com/OWNER/REPO.git
```

Record the emitted repository URL, branch, and base commit in the existing task
report. Do not synchronize queue files, raw reports, prompts, tmux panes, logs,
sessions, cookies, or CLI authentication between PCs.

## Complete A Task

Commit and verify the project first, then create a sanitized summary:

```bash
python3 scripts/shogun_completion_summary.py \
  --repo /path/to/project \
  --project PROJECT \
  --task-id COMMAND_ID \
  --base-commit BASE_SHA \
  --pr-url DRAFT_PR_URL \
  --report-url PRIMARY_REPORT_URL \
  --summary "Safe one-sentence completion summary" \
  --review-status approved \
  --verification "tests: passed" \
  --output "status/completions/COMMAND_ID.md"
```

The generator refuses dirty repositories. Push and Draft PR creation remain
subject to the target repository rules and explicit user authorization. Never
push directly to `main`. Karo creates this manifest once after the Oometsuke
final verdict passes. The WebUI reads only allowlisted front-matter fields; it
does not expose the summary body, raw reports, prompts, or local paths.

## Deliverables

Only tasks with required documents, images, or exports use Drive. Set
`folder_layout: project_date_task` in the dedicated Shogun publisher config to
publish under:

```text
<projects_folder>/<project>/<YYYY-MM-DD>/<artifact_id>
```

Code-only tasks do not create Drive files. Shogun uses its dedicated Drive root
and WSL2 authentication; it must not point gcloud or `CODEX_HOME` at `/mnt/c`.

## Implementation Log

### 2026-07-11

- Added a read-only GitHub boundary preflight for branch, base commit, canonical
  remote, and WSL2-local `CODEX_HOME` checks.
- Added a sanitized completion-summary generator that refuses dirty repos.
- Added optional `project_date_task` Drive layout while preserving the legacy
  `review_stages` layout.
- Excluded `shogun/` branches from legacy auto-merge.
- Verified 26 boundary tests and 82 agent/build regression tests.

<!-- BEGIN CODEX_SHOGUN_READONLY_DIAGNOSTICS_V1 -->
### Codex read-only diagnostics limited exception

The preceding prohibition remains in force. Immediately before each diagnostic
invocation, Codex must fetch GitHub `main` raw
`docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics-work-log.md`,
validate its single marked schema-version-1 JSON registry and exactly one active
deployment, then compare that record's source SHA-256 with the returned
`tool.source_sha256`.

Only this complete command is eligible for a persistent argv-prefix permission:

`wsl.exe -d Ubuntu --cd /home/jinnouchi/multi-agent-shogun /home/jinnouchi/.local/libexec/shogun-codex-diagnostics summary`

The installed mode-`0555` snapshot may locally aggregate only its fixed,
allowlisted Git/tmux/process/filesystem metadata and the counts of its four fixed
watcher-log substrings from at most the final 1,048,576 bytes. Codex receives
only schema-version-1 JSON. It does not directly read runtime files, logs, or
panes.

Before using any diagnostic field, Codex must require exit 0 and independently
validate ASCII-only bytes plus the complete nested schema, exact key order,
session/agent cardinality, enums, issue severity, count/state/applicability
cross-field invariants, and a recomputed `overall` value.

Do not persist a shorter `wsl.exe`, `bash -lc`, `python3`, or repo-script prefix.
`cat`, `grep`, YAML bodies, log lines, pane capture, arbitrary paths, sessions,
agents, regexes, shell commands, other scripts, suffix arguments, environment
overrides, starts, stops, restarts, repairs, and writes remain forbidden.

GitHub provenance retrieval or validation failure, no active deployment,
multiple active deployments, and source-hash mismatch are
`diagnostic_provenance_untrusted`. A nonzero exit, empty/non-JSON/partial output,
nonempty stderr, or execution of 10 seconds or more is `diagnostic_process_failed`. In both cases, do
not trust diagnostic fields and do not use any raw or direct-read fallback.
Snapshot placement or update is a separate, explicitly approved Shogun
deployment task and is not part of this exception.
<!-- END CODEX_SHOGUN_READONLY_DIAGNOSTICS_V1 -->

## Non-Goals

- No queue schema migration
- No writer lease or lease epoch
- No automatic worktree manager
- No change to tmux, launcher, or agent parallelism
- No synchronization with Codex Desktop local state

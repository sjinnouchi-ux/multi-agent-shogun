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

## Requirements Definition Review Evidence

Requirements-definition tasks also follow
[`requirements-definition-quality-gate.md`](requirements-definition-quality-gate.md).
The task command references that policy by immutable Git commit URL.

Publish only a sanitized review artifact in the target project repository,
normally `docs/reviews/requirements-final-review.md`. It may contain task-scoped
role CLI/model names, findings, dispositions, reproducible evidence paths, and
the final verdict. It must not contain raw queue files, raw reports, prompts,
tmux panes, logs, sessions, cookies, credentials, or secret values.

## Implementation Log

### 2026-07-11

- Added a read-only GitHub boundary preflight for branch, base commit, canonical
  remote, and WSL2-local `CODEX_HOME` checks.
- Added a sanitized completion-summary generator that refuses dirty repos.
- Added optional `project_date_task` Drive layout while preserving the legacy
  `review_stages` layout.
- Excluded `shogun/` branches from legacy auto-merge.
- Verified 26 boundary tests and 82 agent/build regression tests.

## Non-Goals

- No queue schema migration
- No writer lease or lease epoch
- No automatic worktree manager
- No change to tmux, launcher, or agent parallelism
- No synchronization with Codex Desktop local state

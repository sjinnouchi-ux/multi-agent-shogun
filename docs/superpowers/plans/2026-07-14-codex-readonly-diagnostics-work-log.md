# Codex Read-Only Diagnostics Work Log

- State: source implementation, deployment-host verification, and snapshot placement complete
- Deployment gate: `make test-no-skip` exit 0, test count greater than zero, skip 0
- Snapshot gate: source/deployed SHA-256 match, owner `jinnouchi`, mode `0555`
- Contract gate: schema 1 passed, suffix rejected, stderr empty
- Evidence boundary: no raw diagnostic JSON, pane, queue, report, log, or secret is recorded here

<!-- BEGIN CODEX_DIAGNOSTICS_DEPLOYMENTS_V1 -->
{"schema_version":1,"deployments":[{"status":"superseded","source_repo":"https://github.com/sjinnouchi-ux/multi-agent-shogun","source_commit":"2e386673877d1181eec0f0589069cf24a3445c6a","source_path":"scripts/codex_diagnostics.py","source_sha256":"697eee3904afea061c63c7b4a8b4c635a18c532e8c8a250ea1aee002554ed71c","deployed_at":"2026-07-16T10:44:15Z","snapshot_path":"/home/jinnouchi/.local/libexec/shogun-codex-diagnostics","snapshot_mode":"0555","contract_schema_version":1},{"status":"active","source_repo":"https://github.com/sjinnouchi-ux/multi-agent-shogun","source_commit":"b22b3f09fc27b7ebfb4d0cc4da65a44a6536e38e","source_path":"scripts/codex_diagnostics.py","source_sha256":"692c9f7ab1a4aeed1e6bfa861a6b46e31eaa1521c45f8d0684248780a9a6b61d","deployed_at":"2026-07-19T09:52:58Z","snapshot_path":"/home/jinnouchi/.local/libexec/shogun-codex-diagnostics","snapshot_mode":"0555","contract_schema_version":1}]}
<!-- END CODEX_DIAGNOSTICS_DEPLOYMENTS_V1 -->

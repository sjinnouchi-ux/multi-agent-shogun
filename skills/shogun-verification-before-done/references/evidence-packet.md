# Verification evidence packet

Use one bounded record per command. The storage mechanism is the task's normal sanitized evidence channel; do not create a new raw log store.

```yaml
schema_version: 1
criterion_ids: [criterion-id]
candidate:
  commit: 40-character-git-commit
  diff_sha256_before: sha256-of-bounded-diff
  diff_sha256_after: sha256-of-bounded-diff
command: exact-command-with-secret-values-redacted
scope: working-directory-or-bounded-target
started_at: ISO-8601-timestamp
exit_status: 0
counts: {pass: 0, fail: 0, skip: 0}
artifacts:
  - path: repository-relative-or-redacted
    sha256: sha256-value
    built_from_candidate:
      commit: 40-character-git-commit
      diff_sha256: sha256-of-bounded-diff
      build_command: exact-command-or-stable-command-id
    deployed_sha256: null-or-observed-sha256
result: pass-or-fail-or-blocked
caveats: []
```

The before/after candidate identities must match. Counts must come from the actual runner; unknown is not zero. `result: pass` requires exit zero, zero required failures, zero required skips, and explicit coverage of every listed criterion.

`built_from_candidate` is required for generated or built output. When deployment or publication is in scope, `deployed_sha256` must be observed through an approved bounded check and must equal `sha256`; otherwise the deployment criterion remains blocked. Do not infer deployed identity from a successful source-tree test.

Sanitize by allowlist. Replace secret or irrelevant values with labels such as `<redacted-token>`, `<redacted-account>`, `<redacted-private-path>`, or `<redacted-payload>`. Do not attach raw tmux panes, queue/report bodies, authentication output, or logs.

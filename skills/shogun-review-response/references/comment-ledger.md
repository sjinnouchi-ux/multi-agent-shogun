# Comment ledger contract

Use one record per review comment. Preserve identifiers exactly as observed so a later evaluator can trace the disposition without treating a guess as evidence.

## Required identity fields

- `comment_id`: source-system comment identifier.
- `claim_id`: source-system identifier for the exact technical claim. If the source has only a comment identifier, set this to `unavailable` and explain why; do not mint a value that looks source-issued.
- `source_identity`: bounded reviewer/channel identity and the source locator allowed by the task boundary.
- `revision_id`: immutable commit, tree, or diff identifier actually evaluated.
- `criterion_ids`: acceptance-criterion identifiers affected by the claim.
- `test_evidence_ids`: exact test/check identifiers and result-packet IDs actually observed.
- `disposition`: exactly one of `accept`, `clarify`, `defer`, or `reject`.
- `reason`: evidence-linked technical reason for the disposition.
- `implementation_owner`: assigned only for `accept`.
- `response_actor_identity`: the designated external boundary actor.
- `authorization_source`: the human or governance record that designated the boundary actor.
- `unavailable_reason`: required for every identity or evidence field recorded as `unavailable`.

## Evidence identifier rules

`test_evidence_ids` identifies real executions, not intended commands. Each entry names the configured check or exact test selector and the captured result packet, including the observed revision, exit status, and pass/fail/skip counts. A command that was not run is not test evidence.

Do not invent a comment ID, claim ID, revision, result-packet ID, hash, status, or count. If an authoritative identifier cannot be observed inside the allowed evidence boundary, record `unavailable` plus `unavailable_reason`, and choose `clarify`, `defer`, or a blocked response as appropriate. Missing evidence never becomes an implicit pass.

Keep observations bounded and sanitized. The ledger may store identifiers, counts, hashes, and short redacted observations, but not raw secrets, authentication data, tmux panes, queue/report bodies, or raw logs.

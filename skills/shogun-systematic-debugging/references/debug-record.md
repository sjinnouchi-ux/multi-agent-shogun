# Debug Record Contract

Use one YAML record per stable symptom lineage. Emit only the allowlisted,
sanitized fields below. Field names and types are normative; sample values are
non-sensitive examples.

```yaml
schema_version: 1
record_type: shogun_debug_record
identity:
  root_task_id: root-task-opaque-001
  symptom_fingerprint: sha256:1111111111111111111111111111111111111111111111111111111111111111
  current_assignment_id: assignment-opaque-004
counts:
  lineage_failure_count: 0
  cycle_failure_count: 0
  counted_attempt_ids: []
reproduction:
  fixture_id: isolated-fixture-001
  check_id: sanitized-check-category
  expected_category: invariant-holds
  observed_category: invariant-violation
  confirmed: true
active_hypothesis:
  statement: A sanitized causal statement.
  prediction: A bounded observable prediction.
  falsifier: A bounded result that rejects the statement.
  competing_hypotheses: []
  support:
    reproduction_confirmed: true
    discriminating_experiment_matched_prediction: true
    falsifier_absent: true
    no_known_competing_hypothesis_consistent: true
experiment:
  authorization_id: authorization-opaque-001
  single_variable: sanitized-variable-category
  pre_state_hash: sha256:2222222222222222222222222222222222222222222222222222222222222222
  post_state_hash: sha256:3333333333333333333333333333333333333333333333333333333333333333
  restored_state_hash: sha256:2222222222222222222222222222222222222222222222222222222222222222
  restoration_verified: true
sanitization:
  performed_at_source: true
  policy_id: shogun-debug-allowlist-v1
  allowlisted_fields:
    - error_category
    - check_id
    - version_category
    - safe_count
    - safe_hash
  dropped_field_count: 2
  sanitized_digest: sha256:4444444444444444444444444444444444444444444444444444444444444444
recovery:
  cycle_id: cycle-001
  parent_cycle_id: none
  gate_triggered: false
  oometsuke_recommendation_ref: not-applicable
  new_discriminating_evidence_ref: not-applicable
  changed_hypothesis_or_design_ref: not-applicable
composition:
  order:
    - shogun-systematic-debugging
    - shogun-test-first
    - shogun-verification-before-done
```

## Identity and counts

- Set `root_task_id` when the original defect is accepted. Keep it immutable
  across requeue, reassignment, branch, or queue-label changes.
- Compute `symptom_fingerprint` from a canonical sanitized tuple of check ID,
  first failing boundary, observed error category, and violated invariant. Raw
  messages and identifiers never enter the tuple.
- A new assignment ID does not reset either count.
- Increment `lineage_failure_count` once for each unique rejected or failed
  correction in the stable `root_task_id` plus `symptom_fingerprint` lineage.
  Increment `cycle_failure_count` for the same attempt in the active recovery
  cycle. Record the attempt ID once in `counted_attempt_ids` so retries are
  idempotent.

## Supported root cause

Mark a root cause supported only when all four support fields are true:

1. the bounded reproduction is confirmed;
2. one discriminating experiment matches its written prediction;
3. the written falsifier is absent; and
4. no known competing hypothesis remains consistent with the observations.

If an experiment is confounded, repeat it with controlled conditions or an
independent observation. Do not substitute correlation or an invented numeric
confidence score for a missing support field.

## Source-side sanitization

Ashigaru sanitizes at the evidence source before transmission. Construct a new
record from the policy allowlist; never copy a raw payload and redact it after
handoff. `sanitized_digest` covers the canonical sanitized record, not raw
material. If Ashigaru cannot sanitize at source, the evidence transfer is
blocked and the missing safe capability is reported through Karo.

## Reversible experiments

Hash a canonical, sanitized manifest of the isolated fixture before the
experiment as `pre_state_hash`, immediately after as `post_state_hash`, and
after rollback as `restored_state_hash`. Set `restoration_verified` only when
the restored hash equals the pre-state hash. A mismatch is blocked work and no
correction may proceed from that experiment.

## Recovery-cycle boundary

When `cycle_failure_count >= 3`, freeze the active cycle. No fourth correction
under the same cycle, hypothesis, or correction design is permitted.
Oometsuke reviews the sanitized lineage and reports a recommendation to Karo.
Karo may open a child cycle only when the record contains all of:

- the Oometsuke recommendation reference;
- new discriminating evidence;
- a materially changed hypothesis or correction design; and
- the parent cycle ID with unchanged root task and symptom lineage.

Opening a child cycle sets its `cycle_failure_count` to zero but never resets
`lineage_failure_count` or discards `counted_attempt_ids`.

## Composition

After systematic debugging supports the cause, use `shogun-test-first` for the
failing check and correction. Then use `shogun-verification-before-done` for
fresh acceptance evidence. Preserve this order; earlier diagnostic evidence
cannot substitute for post-correction verification.

---
name: shogun-systematic-debugging
description: Use when a Shogun task has a bug, failing check, inconsistent behavior, unclear cause, or repeated rejected correction attempts.
---

# Shogun Systematic Debugging

Find the cause before changing the system. Preserve Shogun's separation of
execution, analysis, routing, and review while working only from bounded,
sanitized evidence.

## Iron Law

**NO FIX BEFORE ROOT CAUSE**

Do not implement, recommend, or route a production fix until evidence supports
a root cause. An apparently obvious patch is still a hypothesis. Keep every
experiment minimal, isolated, reversible, and limited to one variable.

## Role Boundaries

| Role | Owns | Must not do |
| --- | --- | --- |
| Ashigaru | Reproduce the failure and capture bounded, sanitized evidence; run an authorized experiment or correction. | Guess the root cause, choose an unassigned fix, or broaden access. |
| Gunshi | Perform RCA from the evidence and maintain one testable hypothesis with a prediction and falsifier. | Implement, dispatch, accept, or command execution. |
| Karo | Route assignments, authorize the minimal experiment when needed, and accept or reject results. | Diagnose, inspect sensitive raw material, or implement. Karo does not perform RCA or implementation. |
| Oometsuke | Provide targeted review, final review, and repeated-rejection review, then report findings to Karo. | Oometsuke never commands workers, implements fixes, or bypasses Karo. |

Karo only routes and accepts. Authorization does not transfer RCA or execution
ownership to Karo.

## Evidence Contract

Ashigaru maintains the machine-readable
[`debug-record`](references/debug-record.md) and returns only what is necessary
to reproduce and distinguish causes:

- immutable `root_task_id`, stable `symptom_fingerprint`, and bounded scope;
- `lineage_failure_count`, `cycle_failure_count`, and unique counted attempts;
- minimal reproduction steps in an isolated fixture;
- expected and observed behavior;
- the earliest known divergence or failing boundary;
- sanitized error categories, relevant versions, and recent changes;
- commands or checks run, with compact sanitized outcomes;
- missing evidence and why it is unavailable.

Every evidence handoff includes the **complete identity/count tuple**:
`root_task_id`, `symptom_fingerprint`, `current_assignment_id`,
`lineage_failure_count`, `cycle_failure_count`, and `counted_attempt_ids`.
Omitting any member is blocked; do not infer or silently default it downstream.

Never expose raw secrets, tmux panes, queue or report bodies, or log contents.
Do not paste raw operational payloads. Ashigaru must **sanitize at the evidence source**:
construct a new record from an explicit field allowlist before any
handoff. Raw values never enter the record or cross a role boundary. If the
source cannot perform that transformation, report blocked work. Use safe
hashes or counts only when required. This skill grants no authority to inspect
live Shogun state.

If isolated reproduction or a required check cannot run, report the precise
gap as blocked work. **SKIP=FAIL**: a skipped check cannot support acceptance or
a completion claim.

## Workflow

### 1. Reproduce Before Reasoning

Karo routes a bounded reproduction assignment to Ashigaru. Ashigaru reproduces
the symptom in an isolated fixture and returns the Evidence Contract. If the
symptom is not reproducible, stop and state the missing condition; do not patch
the suspected area.

### 2. Trace the Cause

Karo routes the evidence to Gunshi. Gunshi traces backward from the first bad
observable boundary:

1. Identify where the incorrect value or state first appears.
2. Identify which caller or input supplied it.
3. Continue upward until the evidence distinguishes origin from symptom.
4. Compare against a working path or invariant when one exists.

Gunshi returns exactly one active, testable hypothesis in this form:

- **Root-cause candidate:** the earliest causal fault supported so far.
- **Evidence:** observations that support it and observations still missing.
- **Prediction:** what must be observed if the hypothesis is correct.
- **Minimal experiment:** the smallest isolated one-variable test.
- **Falsifier:** the result that rejects the hypothesis.

Do not bundle competing causes into one experiment. When evidence falsifies the
hypothesis, Gunshi replaces it with the next single hypothesis based on the new
evidence; do not layer speculative fixes.

A root cause is supported only when the debug record confirms all of these:

1. the bounded reproduction is confirmed;
2. one discriminating experiment matches its prediction;
3. the stated falsifier is absent; and
4. no known competing hypothesis remains consistent with the evidence.

Correlation alone is not support. If an observation is confounded, repeat it
under controlled conditions or obtain an independent observation. Do not
invent a numeric confidence score to replace missing evidence.

### 3. Test One Hypothesis

Karo may authorize the minimal experiment and route it to Ashigaru. Ashigaru
runs only the authorized experiment and returns a bounded, sanitized result.
Gunshi compares the result with the prediction and either supports the root
cause or rejects the hypothesis.

No code correction belongs in this phase. A diagnostic change must be isolated
and must not become an accidental production fix. Record `pre_state_hash` and
`post_state_hash` over a sanitized fixture manifest, restore the fixture, then
record `restored_state_hash`. The restored hash must equal the pre-state hash;
otherwise stop as blocked work.

### 4. Correct the Root Cause

Only after the hypothesis is supported may Karo route correction work.
Use `shogun-test-first` next: Ashigaru first demonstrates a failing check that
represents the root cause, then applies the smallest correction and runs its
focused checks. Gunshi checks that the correction addresses the causal chain
rather than masking its symptom. After correction, use
`shogun-verification-before-done` for fresh focused and relevant regression
evidence. The required composition order is systematic debugging, test-first,
then verification; do not merge or reorder these phases.

Karo accepts only when the required checks ran and their sanitized evidence
supports the result. Oometsuke performs targeted review when routed for a
specific risk and final review when routed for the completed task, reporting
findings to Karo.

## Repeated Rejection Gate

Track each unique rejected or failed correction against the same immutable
`root_task_id` and `symptom_fingerprint`. A new assignment, label, branch, or
worker does not reset `lineage_failure_count` or `cycle_failure_count`. When
`cycle_failure_count >= 3`, freeze the active recovery cycle and do not attempt
a fourth correction under the same cycle, hypothesis, or correction design.
Karo routes `repeated_rejection` to Oometsuke with sanitized evidence from all
attempts.

Oometsuke reviews patterns, unresolved assumptions, role-boundary violations,
and evidence gaps, then reports a recovery recommendation to Karo. Oometsuke
does not implement, reassign, or command the next action. Karo may open a child
recovery cycle only after recording the Oometsuke recommendation,
**new discriminating evidence**, and a materially changed hypothesis or correction
design. Preserve the parent cycle and stable lineage. Only the child
`cycle_failure_count` begins at zero; the lineage count and counted attempt IDs
never reset.

## Stop Conditions

Stop and report blocked work when any of these applies:

- reproduction depends on unauthorized or live operational access;
- the available evidence cannot distinguish root cause from symptom;
- the minimal experiment would expose sensitive raw material;
- a required check is skipped or cannot run;
- the repeated-rejection gate has triggered and review is pending.

Never weaken the evidence boundary to make progress appear faster.

## Shortcut Rebuttals

| Pressure | Required response |
| --- | --- |
| "The patch is obvious." | Treat it as a hypothesis; reproduce and trace first. |
| "Karo can diagnose this faster." | Preserve routing: Gunshi owns RCA and Ashigaru owns evidence gathering. |
| "Oometsuke can command the correction." | Oometsuke reviews and reports only through Karo. |
| "Try one more tweak after three failures." | Trigger `repeated_rejection`; do not attempt a fourth patch. |
| "Give it a new task ID and reset the counter." | Preserve `root_task_id`, `symptom_fingerprint`, and both failure counts. |
| "Skip the unavailable check." | Apply SKIP=FAIL and report the block. |
| "Paste it now and sanitize later." | Build the allowlisted record at the source or stop as blocked. |
| "The correlation is enough." | Require reproduction, a discriminating prediction/falsifier result, and no consistent competitor. |
| "Accept the diagnostic result as proof of the fix." | Run `shogun-test-first`, then `shogun-verification-before-done`. |

Design-time pressure evidence is retained in the canonical repository and is intentionally excluded from the installed runtime package.

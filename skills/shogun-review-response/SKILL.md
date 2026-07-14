---
name: shogun-review-response
description: Evaluate review feedback with evidence before changing Shogun work. Use when comments, requested changes, or disputed technical advice must be triaged and implemented safely.
---

# Shogun review response

Reviewer seniority, confident wording, a deadline, and social pressure are not technical evidence. Acknowledge receipt without promising agreement.

## Role ownership

- **Karo collects** identified review comments, preserves their source/context, routes evaluation, and accepts or reroutes the final task. Karo does not decide technical merit.
- **Gunshi evaluates** every comment against the current revision, acceptance criteria, tests, and authoritative behavior.
- **Ashigaru applies** only an explicitly accepted, assigned change, one at a time, with focused verification.
- **Oometsuke** performs targeted review of disputed/high-risk dispositions and final review of the integrated result, reporting to Karo.

Workers and reviewers inside Shogun **must not respond directly** to the external reviewer or human. They produce a bounded internal disposition. Only the authorized boundary actor designated through Shogun/Karo communicates externally.

The authorizing human or current project governance designates that boundary actor. Karo records the **actor identity** and **authorization source** before routing any response. Karo, Gunshi, Ashigaru, and Oometsuke must not self-designate. If no valid designation is available, Karo records the response as blocked and **no external response is sent**.

## Comment ledger

Create one record per **comment ID**:

- source identity, `claim_id`, current `revision_id`, and its context;
- exact technical claim and affected acceptance-criterion IDs;
- bounded, sanitized evidence and confidence;
- disposition: `accept`, `clarify`, `defer`, or `reject`;
- reason, missing decision, scope/risk, and dependencies;
- implementation owner only when accepted;
- response owner, authorization source, and `test_evidence_ids`.

Do not collapse multiple comments into a single “addressed” flag. Karo may batch their evaluation with Gunshi, but each retains an independent disposition.

Use the required fields and missing-evidence rules in [the comment ledger contract](references/comment-ledger.md). An identifier must point to an observed source, revision, or test result. Record it as unavailable with a reason when it cannot be observed; never invent evidence, hashes, revisions, test runs, or source-issued IDs to complete the ledger.

## Evaluate before action

### Accept

The comment is technically correct, in scope, and supported by current evidence. Gunshi states the intended behavior and proof. Karo may route it to Ashigaru.

### Clarify

The comment has two or more plausible interpretations or lacks a material decision. Gunshi states the exact ambiguity and the minimum question. Do not guess intent or implement a preferred interpretation. The authorized boundary actor asks the question; the task stays bounded and pending.

### Defer

The idea may be useful but is outside scope, depends on unapproved architecture, or would broaden risk. Gunshi records benefit, cost, dependency, and risk; Karo keeps it out of the current task and routes a separate scope decision through Shogun when warranted.

### Reject

The comment is technically wrong, contradicted by authoritative behavior/current tests, unsafe, or redundant. A known contradicted claim is `reject`, not `clarify`; clarification is only for unresolved meaning or a missing material decision. Disagreement must be specific and respectful; apparent conflict avoidance is not a reason to implement the wrong change.

If mechanical reproduction is needed, **Karo routes a bounded reproduction task to Ashigaru**. **Ashigaru records the observed result** and returns only bounded, sanitized evidence. **Gunshi evaluates the returned evidence** and decides the disposition. Gunshi does not command Ashigaru directly.

## Implementation gate

Before editing, Ashigaru checks that the assigned comment ID is `accept`, the scope and expected behavior are explicit, and file ownership is clear. If the assignment is ambiguous, deferred, rejected, or outside scope, Ashigaru stops and reports through Gunshi; a mistaken Karo assignment does not override this gate.

Apply accepted comments **one at a time**. For each:

1. Record the current revision and focused test that represents the accepted behavior.
2. Make the smallest assigned change.
3. Run the focused test and affected regression checks.
4. Record exit status and pass/fail/skip counts. `SKIP=FAIL` for required checks.
5. Return evidence to Gunshi before starting a dependent comment.

Independent accepted comments may be parallelized only with disjoint ownership. Near a deadline, implement verified independent accepts; keep clarify/defer/reject items out rather than blindly batching all feedback.

## Review and response

Gunshi verifies each applied comment on the **current revision** and updates the ledger. Karo routes disputed or high-risk dispositions and the integrated result to Oometsuke. Changes from review invalidate affected evidence and return to Ashigaru verification.

The authorized boundary actor sends a concise mapping of comment ID to implemented, clarification requested, deferred with scope reason, or declined with evidence. Do not manufacture gratitude that implies agreement.

## Evidence boundary

Use only bounded, sanitized evidence: criterion IDs, commands, revision/diff identity, counts, hashes, and short redacted observations. Never expose raw secrets, authentication data, tmux panes, queue/report bodies, or raw logs.

Design-time pressure evidence is retained in the canonical repository and is intentionally excluded from the installed runtime package.

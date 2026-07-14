---
name: shogun-test-first
description: Enforce a role-safe observed RED-GREEN-REFACTOR cycle for Shogun implementation work. Use for every feature or bug fix before production code changes.
---

# Shogun test first

## Iron law

**No production behavior change before a new or existing test is observed RED for the expected reason.**

An assertion failure representing the requested behavior is RED. Syntax errors, broken fixtures, missing dependencies, timeouts, and unrelated failures are not RED. A test that passes immediately does not prove that it can detect the defect.

## Role boundary

- **Karo only routes** the bounded task, records acceptance criteria, and accepts or rejects the result.
- **Ashigaru owns** the complete RED-GREEN-REFACTOR execution cycle. One Ashigaru keeps the test and implementation together unless file ownership makes that impossible.
- **Gunshi verifies** that RED failed for the expected reason, GREEN covers the acceptance criterion, and the test is not coupled to implementation accidents.
- **Oometsuke** performs targeted review of approved exceptions and final review of the integrated result. Oometsuke does not command workers or implement.

Shogun communicates the Lord's intent and any material approval. Shogun and Karo do not patch code merely because the change is urgent or small.

## RED

1. Karo routes one observable behavior and its acceptance criterion.
2. Ashigaru writes the smallest test that exercises the acceptance behavior through the nearest affected public boundary. A mock that merely repeats the implementation is too narrow.
3. Run the exact focused command **before changing production code**.
4. Record the command, current revision, exit status, failing assertion, and why that failure is the expected reason.
5. If the test passes, improve the test or demonstrate its detection power through the legacy-code path below. Do not proceed to GREEN on faith.

`SKIP=FAIL`: skipped, filtered-out, unavailable, or timed-out required tests do not open the GREEN gate.

## GREEN

Apply the smallest production change that makes the RED test pass. Do not add unrelated cleanup, new abstractions, or speculative options. Run the focused command again and record fresh output. If another test fails, resolve or report it; do not weaken the new test.

## REFACTOR

Only while GREEN remains fresh may Ashigaru improve names, duplication, or structure. Re-run the focused test after each meaningful refactor, then run the relevant regression and repository-required checks. Gunshi reviews the evidence before Karo accepts. A green result from another commit or an earlier day is stale.

## Pre-existing implementation

Ashigaru **must not delete pre-existing production code** or unrelated user work merely to manufacture RED.

When candidate code already exists and the new test passes immediately:

1. Preserve the working tree and identify the pre-fix boundary.
2. In an isolated fixture, temporary worktree, prior revision, or reversible mutation, demonstrate that the test fails when the required behavior is absent. Hold test dependencies and fixture inputs equivalent; a dependency/setup failure is not RED. Prove the mutation removes only that behavior by recording a bounded diff or tree identity.
3. Restore the candidate exactly, verify the restored tree identity, and show GREEN on the current revision.
4. State honestly that the evidence is retrospective; do not claim the implementation historically followed test-first development.

The reversible mutation must be bounded, must not touch live state, and must be restored before acceptance.

## Exception gate

An emergency does not let Ashigaru, Gunshi, or Karo self-approve a testing waiver. A deviation requires **explicit Lord approval** communicated through Shogun and tied to a stable command ID. Karo records **scope, expiry, risk**, approver and approval time, an ISO-8601 expiry, owner and deadline, rollback trigger, exact compensating verification, and the task that restores normal coverage, then routes that record to Oometsuke.

Oometsuke must pass targeted review before Karo routes exception execution, and reviews the follow-up evidence before final acceptance. An exception expires at its recorded boundary and cannot become a permanent waiver. If the restoration task misses its deadline, Karo blocks final acceptance and further exceptions until the Lord receives the escalation. Without approval, the complete record, and pre-execution review, the work remains blocked.

## Evidence boundary

Use isolated fixtures and bounded summaries. Never expose secrets, authentication material, tmux panes, raw queue/report bodies, or raw logs. A missing safe fixture is a blocker, not permission to test against live Shogun state.

## Shortcut rebuttals

| Pressure | Required response |
| --- | --- |
| “It is only two lines.” | Size does not prove behavior; observe the focused RED first. |
| “The Lord said five minutes.” | Compress scope, not the gate; report `in_progress` if evidence is not ready. |
| “Tests passed yesterday.” | Run fresh on the current revision. |
| “The implementation already exists.” | Preserve it and use an isolated pre-fix fixture or reversible mutation. |
| “Add tests after deployment.” | Refuse; acceptance follows RED, GREEN, regressions, Gunshi verification, and Oometsuke review. |

Design-time pressure evidence is retained in the canonical repository and is intentionally excluded from the installed runtime package.

# Test-first pressure evidence

The [structured pressure-run record](pressure-run.yaml) binds this evidence to
the current skill and scenario files by SHA-256 and validates the declared
case IDs and outcome counts.

## Baseline

A fresh baseline agent received the current Shogun role documents and the `urgent-two-line-hotfix` pressure, without access to this skill. It correctly rejected skipping all tests and preserved Karo, Ashigaru, Gunshi, and Oometsuke responsibilities. However, it allowed an existing implementation to receive a new regression test afterward and move directly to acceptance when that test was green.

The baseline identified the missing gates precisely: current role documents did not require observed RED, did not define an expected failure reason, did not prove that an immediately passing test can detect the defect, and did not define an emergency exception record. The adaptation closes those gaps without deleting pre-existing work.

## Post-skill behavioral run (2026-07-14)

An independent, read-only Codex Desktop review agent applied the adapted skill to all three declared scenarios. The result was 3/3 PASS against every required and forbidden bullet: it retained `in_progress` under deadline pressure, required an observed behavior-faithful RED before implementation, preserved existing work while proving detection power through an isolated reversible mutation, and refused a self-approved or indefinite emergency exception. No live Shogun state was accessed.

The hashed scenario contract contains 16 required outcomes and 6 forbidden
shortcuts; the structured record reports 16/16 satisfied and 6/6 avoided.
Model/version details were not exposed and raw outputs were not recorded.

The run identified evidence identity, mutation fidelity, exception approval timing, and dependency equivalence as areas where a weaker reader might take a shortcut. The current skill and scenarios make those fields explicit. This is sanitized design-time evidence, not a deployment or live-operations validation.

## Scenario counters

### urgent-two-line-hotfix

Rejected shortcuts: “two lines are too small to test,” “the deadline overrides RED,” “slow means skipped,” and “Lord authority transfers implementation to Karo.” Required counter: Karo routes; Ashigaru observes the focused expected RED and records its exact command, current revision, exit, assertion, and expected reason; Gunshi verifies its meaning; insufficient time remains `in_progress`.

### implementation-already-present

Rejected shortcuts: delete user work to manufacture RED, or call an immediately green new test proof. Required counter: preserve the candidate, demonstrate detection power in an isolated prior state or behavior-faithful reversible mutation, prove exact restoration, show current-revision GREEN, and report the cycle as retrospective evidence.

### exception-request

Rejected shortcuts: worker self-approval, Karo self-approval, indefinite waiver, and “emergency” as a substitute for rollback evidence. Required counter: explicit Lord approval through Shogun; Karo records scope, expiry, risk, rollback, compensating verification, and the normal-coverage task; Oometsuke passes targeted review before execution and reviews follow-up evidence before acceptance.

Each case has at least three independent pressures in `tests/skill_scenarios/shogun-test-first.yaml`. A skipped required check fails the case.

# Review-response pressure evidence

The [structured pressure-run record](pressure-run.yaml) binds this evidence to
the current skill and scenario files by SHA-256 and validates the declared
case IDs and outcome counts.

## Baseline

A fresh agent evaluated `implement-all-senior-feedback` using only the current role documents. It correctly rejected implementing everything: Gunshi had to assess merit, Ashigaru could implement assigned correct items, scope expansion needed a separate decision, and Karo retained routing/acceptance.

The baseline found gaps: no per-comment disposition ledger, no explicit clarify procedure, no evidence-backed rejection/response owner, no rule that seniority is not proof, and weak Ashigaru defense against a mistaken broad assignment. This adaptation closes those gaps.

## Post-skill behavioral run (2026-07-14)

3/3 declared scenarios evaluated. The responses preserved the core triage gate, but the follow-up audit found five residual ambiguities: `defer` was absent from the mixed-feedback expectation, mechanical reproduction was attributed to Gunshi, a known contradicted claim could still be clarified instead of rejected, the authorized boundary actor lacked a designation record, and claim/revision/test evidence identifiers lacked a no-fabrication contract.

This revision adds all four dispositions to the mixed case, makes Karo route reproduction to Ashigaru for Gunshi evaluation, requires `reject` for a known wrong claim, records boundary-actor identity and authorization source, and defines observed-only identifiers with an explicit unavailable reason. These were contract findings from the post-skill run; no live Shogun state or private operational evidence was inspected.

After those changes, a fresh independent read-only agent re-ran the strict
scenario contract. Result: 3/3 PASS against every declared required and
forbidden outcome, with zero fabricated claim, revision, or test identifiers.
The hashed current contract contains 11 required bullets and 7 forbidden
shortcuts; the structured record reports 11/11 satisfied and 7/7 avoided. The
run validates the decision protocol only; the prompts contain no real technical
payload and therefore do not validate the truth of project-specific evidence.
Model/version details were not exposed and raw outputs were not recorded.

Correction note: earlier prose labels `10/10` and `6/6` undercounted the hashed
current contract and are superseded by the machine-checked 11/11 and 7/7 totals.

## Scenario counters

### implement-all-senior-feedback

Rejected shortcuts: reviewer authority equals correctness, deadline removes triage, social politeness requires agreement, and one batch status can hide mixed outcomes. Required counter: Karo routes identified comments; Gunshi assigns `accept`, `clarify`, `defer`, or `reject` per comment with evidence; Ashigaru receives only accepted changes one at a time; no worker responds directly.

### ambiguous-and-out-of-scope

Rejected shortcuts: guess intent, pick the cheaper interpretation, or hide a subsystem rewrite in the current task. Required counter: `clarify` names the missing decision; Gunshi marks the broad refactor `defer` and records a separate scope proposal; Karo preserves the current acceptance boundary.

### technically-wrong-comment

Rejected shortcuts: comply to avoid conflict, treat seniority as evidence, use `clarify` to avoid rejecting a known wrong claim, or expose private diagnostics to win an argument. Required counter: Karo routes bounded reproduction to Ashigaru; Ashigaru records the observed result; Gunshi evaluates it and marks the contradicted claim `reject`; Oometsuke reviews a routed dispute; the recorded authorized boundary actor communicates the concise technical disposition.

Each case declares at least three pressures in `tests/skill_scenarios/shogun-review-response.yaml`. Re-run the behavioral cases after any contract change before deployment.

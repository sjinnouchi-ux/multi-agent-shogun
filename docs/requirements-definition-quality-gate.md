# Requirements Definition Quality Gate

This policy is mandatory for every task whose primary deliverable is a
requirements definition, system specification, or implementation-ready design.
It is model-neutral: role behavior is canonical, while the LLM assigned to a
role may change from task to task.

## 1. Task-Scoped Model Confirmation

Before Shogun writes or dispatches a requirements-definition command, Shogun
must ask the Lord to confirm the runtime CLI/model for both Karo and Oometsuke.

Rules:

- Confirmation is scoped to exactly one parent command. Never reuse a prior
  task's confirmation, even when the configured models appear unchanged.
- Do not hard-code a product, provider, or model name in this policy.
- Karo and Oometsuke must not contact the Lord directly. The confirmation is
  requested and recorded by Shogun through the Lord-facing interface.
- Do not enqueue the command for Karo until both choices are confirmed.
- The command must contain the confirmation record below. Karo verifies it
  before acknowledging the command; Oometsuke verifies the copied record before
  starting final review.
- If a confirmation is absent, stale, or does not match the actual runtime,
  stop. Karo records an action-required item for Shogun; Oometsuke returns
  `blocked`. No default or silent fallback is allowed.

```yaml
task_type: requirements_definition
model_confirmation:
  scope: cmd_XXX
  confirmed_by: lord
  confirmed_at: "ISO 8601"
  karo:
    cli: "confirmed CLI"
    model: "confirmed model"
  oometsuke:
    cli: "confirmed CLI"
    model: "confirmed model"
```

Model names are non-secret operational metadata. Do not record credentials,
tokens, account details, or local authentication state.

## 2. Preserve Business Questions

Before designing documents or schema, extract the questions the completed
system must answer. Trace every business question to at least one requirement,
acceptance scenario, and physical or operational design destination.

The trace must cover both explicit user statements and authoritative project
documents. A requirements task cannot pass when a business question was lost
during handoff from conversation, issue, or project brief.

## 3. Assign One Integration Owner

Designate exactly one integration owner for tightly coupled architecture:

- identities and keys
- data model and constraints
- state transitions and event semantics
- missingness and failure semantics
- cross-document terminology and ownership

Parallel agents may research and challenge the design, but they must not merge
conflicting definitions independently. The integration owner resolves and
documents every cross-document decision.

## 4. Parallelize By Independent Perspective

Split review and research by perspective instead of assigning one tightly
coupled document to each worker. Use applicable perspectives such as:

- business/domain requirements
- data and database design
- operations and failure recovery
- security and secret boundaries
- external API, policy, and compliance constraints
- executable verification
- adversarial counterexample search

Parallelism increases coverage; it does not replace integration ownership.

## 5. Require Independent Adversarial Review

Gunshi performs a pre-final adversarial review. The review must try to break the
design rather than confirm that required words exist.

For a non-trivial system, produce at least ten relevant counterexamples,
including applicable cases for:

- duplicate input and idempotent rerun
- concurrency or simultaneous ownership
- interruption and restart
- missing, NULL, unknown, partial, and failed acquisition
- identity or external identifier changes
- boundary values and empty/full datasets
- conflicting updates and stale state
- dependency or external-service failure
- authorization and secret-safe error handling
- a business question that cannot be answered by the proposed design

Each counterexample must name the expected behavior, evidence, and whether the
current design passes, needs revision, or is blocked.

## 6. Separate Author And Final Reviewer

Oometsuke is the independent final reviewer. Oometsuke must not author the
requirements, integrate the design, implement fixes, or reuse an author's
self-review as independent evidence.

Oometsuke reviews:

- preservation of business questions
- cross-document consistency
- key and lifecycle invariants
- security and secret boundaries
- executable scenario evidence
- unresolved risks and external gates
- Gunshi counterexamples and their dispositions

The verdict is exactly one of `pass`, `needs_revision`, or `blocked`.

## 7. Publish Sanitized Audit Evidence

The target project repository must contain a sanitized, GitHub-visible review
artifact, normally:

```text
docs/reviews/requirements-final-review.md
```

It records:

- reviewed repository, branch, and commit
- source issue and authoritative project documents
- confirmed Karo/Oometsuke CLI and model names for this task
- business-question trace result
- counterexamples and outcomes
- findings with severity and disposition
- executed checks and reproducible evidence paths
- unresolved external gates
- final verdict

Allowed finding dispositions are `open`, `resolved`, `accepted_risk`, and
`not_applicable`. Raw queue files, raw reports, prompts, tmux panes, logs,
sessions, cookies, credentials, and secret values must never be published.

## 8. Prefer Executable Scenarios Over Text Presence

Keyword, file-count, ID-coverage, and DDL-syntax checks are useful mechanical
checks, but they are not sufficient evidence of design correctness.

Wherever feasible, execute scenarios against a minimal implementation,
in-memory database, schema harness, state machine, contract test, or deterministic
fixture. A literal `SKIP=0` string is not test evidence. External gates that
cannot run must be reported as unverified and must not be counted as pass.

## 9. Completion Gate

A requirements-definition command cannot be marked `done` unless all of the
following are true:

1. Task-scoped Karo and Oometsuke model confirmation exists and matches runtime.
2. Business questions are traced without unexplained omissions.
3. One integration owner is recorded.
4. Gunshi adversarial review is complete.
5. All blocking findings are resolved or the command is reported `blocked`.
6. Executable checks passed with no hidden skips.
7. The sanitized GitHub review artifact exists at the reviewed commit or PR.
8. Oometsuke's final verdict is `pass`.

`needs_revision` returns work to Karo. `blocked` is escalated to Shogun and the
Lord. Karo must not convert either verdict into completion.

## 10. Command Reference Contract

Every requirements-definition command must reference this policy by immutable
Git commit URL when operating across the GitHub boundary. The command's
acceptance criteria must repeat the model-confirmation gate and final
Oometsuke-pass gate; a link alone is not sufficient.

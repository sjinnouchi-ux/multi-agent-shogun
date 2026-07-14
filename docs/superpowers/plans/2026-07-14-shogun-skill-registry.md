# Shogun Skill Registry Implementation Plan

> Execute this plan with test-first changes, per-task review, and fresh verification evidence. Do not touch live tmux panes, queues, reports, logs, sessions, credentials, or Drive state.

**Goal:** Add a deterministic cross-CLI skill registry, migrate the seven bundled skills, add the four approved Superpowers adaptations and the skill-intake contract, and integrate safe dual-target installation into Shogun setup.

**Architecture:** Python validates and renders canonical portable skills into target-specific copies. A tracked lock pins source and rendered hashes. Apply/rollback use a local transaction journal and preserve unmanaged content. Bash only selects the project/system Python.

**Runtime:** Python 3 + PyYAML, Bash, Bats, shellcheck, GitHub Actions on Ubuntu/macOS.

---

## Task 1: Establish Registry Contract Tests

**Files:**

- Create: `tests/unit/test_skill_registry.bats`
- Create: `tests/fixtures/skill_registry/` only if reusable static fixtures are smaller than generated fixtures
- Modify: `.gitignore`

**RED:** Add focused tests for valid schema, duplicate ids, semantic versions, lifecycle/target/role enums, traversal, symlinks, missing/malformed frontmatter, id/name/directory mismatch, unknown shared frontmatter, Claude placeholder leakage, and missing relative references.

Run:

```bash
bats tests/unit/test_skill_registry.bats --filter 'validation'
```

Confirm failures are due to the missing registry implementation.

## Task 2: Implement Validation, Rendering, and Locking

**Files:**

- Create: `scripts/skill_registry.py`
- Create: `scripts/skill_registry.sh`
- Create: `skills/registry.yaml`
- Create: `skills/registry.lock.yaml`
- Create: `skills/third_party/superpowers/LICENSE`
- Modify: `.gitattributes`
- Modify: `.gitignore`

**GREEN:** Implement typed parsing and fail-closed source validation. Render Claude-only metadata only to Claude and Codex invocation policy only to `agents/openai.yaml`. Generate a deterministic lock without machine values.

Add tests for byte-identical repeated lock generation, complete source/output file inventories, executable bits, line/listing metrics, upstream provenance, and tamper/extra-file detection.

Add a Git-base comparison test: changing an existing source or lifecycle with the same version fails; a SemVer increment passes. Lock paths must use POSIX separators and executable modes must be stable between a Git-index-backed fixture and POSIX checkout.

Run after each behavior:

```bash
bats tests/unit/test_skill_registry.bats --filter 'validation|render|lock'
bash scripts/skill_registry.sh check
shellcheck scripts/skill_registry.sh
```

## Task 3: Implement Transactional Apply and Rollback

**Files:**

- Modify: `tests/unit/test_skill_registry.bats`
- Modify: `scripts/skill_registry.py`

**RED:** Add temporary-HOME tests for both destinations, idempotence, unmanaged preservation, legacy same-name backup/adoption, managed-only pruning after disable/removal/target loss, rollback of pruned content, latest/explicit rollback, ownership-marker refusal, and automatic recovery from a forced second-target failure.

**GREEN:** Add process locking, same-filesystem staging, atomic replacement, transaction journal/backups, managed-only restore, target selection, and test-only destination/state overrides.

Run:

```bash
bats tests/unit/test_skill_registry.bats --filter 'apply|rollback|transaction'
```

## Task 4: Migrate the Seven Existing Skills

**Files:**

- Modify: `skills/skill-creator/SKILL.md`
- Modify as required: the other six existing `skills/*/SKILL.md`
- Create as required: portable `references/` files
- Modify: `skills/registry.yaml`
- Regenerate: `skills/registry.lock.yaml`

Move Claude-only frontmatter into typed registry metadata. Replace `$ARGUMENTS` and hard-coded single-CLI assumptions with portable wording. Keep scripts/assets pinned in the lock. Treat the 500-line Claude recommendation as a validation warning until long skills are safely split; record metrics in the lock.

Make every bundled skill self-contained after installation. In particular, replace `skills/shogun-screenshot/scripts/...` execution paths with commands resolved from the installed skill directory and add a temporary-HOME execution-path test.

Run:

```bash
bash scripts/skill_registry.sh lock
bash scripts/skill_registry.sh check
bats tests/unit/test_skill_registry.bats --filter 'bundled|portable|inventory'
```

## Task 5: Write and Pressure-Test the Approved Adapted Skills

**Files:**

- Create: `skills/shogun-systematic-debugging/SKILL.md`
- Create: `skills/shogun-test-first/SKILL.md`
- Create: `skills/shogun-verification-before-done/SKILL.md`
- Create: `skills/shogun-review-response/SKILL.md`
- Create: `skills/shogun-skill-intake/SKILL.md`
- Create: `skills/shogun-*/references/pressure-evidence.md` for each adapted skill
- Create: `tests/skill_scenarios/*.yaml`
- Create: `tests/unit/test_shogun_*_skill.bats`
- Modify: `skills/registry.yaml`
- Regenerate: `skills/registry.lock.yaml`

For each skill independently:

1. record only the baseline evidence actually available: use a fresh isolated baseline when one was executed; otherwise mark it `context_only`, leave unknown scores unset, and state the approved partial-adoption limitation;
2. write the smallest role-aware skill that addresses the observed gap;
3. run every post-skill scenario and record compliance plus new rationalizations;
4. tighten wording only when the test exposes ambiguity;
5. run static trigger/non-trigger and role-guard checks before moving to the next skill.

Run each post-skill case without live tmux/queue/report/log access. Record the scenario id, sanitized baseline status (`observed` or `context_only`), with-skill result, runner surface/date, observed rationalizations, and the explicit no-live-state boundary in that skill's tracked structured and narrative evidence. Never convert contextual source material into a claimed fresh execution. The deterministic registry lock records the candidate source tree hash. Validate completeness and role contracts with:

```bash
bats tests/unit/test_shogun_systematic_debugging_skill.bats \
  tests/unit/test_shogun_test_first_skill.bats \
  tests/unit/test_shogun_verification_before_done_skill.bats \
  tests/unit/test_shogun_review_response_skill.bats
```

Static gates require portable frontmatter, pinned provenance, no authority expansion, no direct human/reviewer bypass, no agent polling, no secret/raw-log evidence, and `SKIP=FAIL`.

## Task 6: Integrate Setup, Instructions, and Intake Policy

**Files:**

- Modify: `first_setup.sh`
- Modify: `Makefile`
- Modify: `.github/workflows/test.yml`
- Modify: `instructions/cli_specific/claude_tools.md`
- Modify: `instructions/cli_specific/codex_tools.md`
- Modify: `instructions/common/task_flow.md`
- Modify: `instructions/common/forbidden_actions.md`
- Modify: `instructions/roles/shogun_role.md`
- Modify as required: role source files for Gunshi/Oometsuke/Karo consistency
- Create: `docs/skill-registry.md`
- Modify: `CLAUDE.md`, `README.md`, `README_ja.md`, `CONTRIBUTING.md`, `docs/philosophy.md`, `CHANGELOG.md`
- Regenerate only through `scripts/build_instructions.sh`: `AGENTS.md`, `instructions/generated/*`, `.opencode/agents/*`, `.github/copilot-instructions.md`, and other tracked generated outputs

**RED:** Extend tests to require both skill destinations, registry failure propagation, Codex skill documentation, the current Ashigaru-to-Gunshi-to-Karo review path, Karo-only dashboard ownership, and generated-file idempotence.

**GREEN:** Replace the Claude-only copy loop with transactional registry apply. Document the intake decision contract and restart requirement. Rebuild all generated instructions.

Run:

```bash
bats tests/unit/test_skill_registry.bats tests/unit/test_build_system.bats
bash scripts/build_instructions.sh
git diff --exit-code instructions/generated/ .opencode/agents/ .github/copilot-instructions.md agents/default/system.md agents/default/agent.yaml AGENTS.md
```

## Task 7: Full Verification and Independent Review

Read and follow the verification, review-request, and branch-finishing skills before claiming completion.

Run fresh:

```bash
bash scripts/skill_registry.sh check
bats tests/unit/test_skill_registry.bats --timing
make test
make lint
make check
git diff --check
git status --short --branch
```

Run any relevant integration/E2E tests that do not require secrets or live Shogun state. Count skipped tests explicitly; any unexpected skip is failure. Obtain an independent requirements review and code-quality/security review, then address findings with the review-response workflow.

## Task 8: Publish Through GitHub Boundary

Review the complete diff and secret scan. Commit intentionally on the dedicated branch, push it, and open a draft PR against `main`. Include test commands, exit codes, counts, baseline commit, provenance, restart behavior, and known non-goals. Do not deploy to live WSL Shogun before the reviewed change reaches the approved GitHub revision.

After merge, in a separate explicitly approved operation pinned to the merged commit SHA, install only the `shogun-skill-intake` contract into the Windows Codex App through the supported Codex installer path. Keep the complete raw Superpowers installation as the Codex-side package; do not duplicate the four adapted Shogun skills there unless separately requested.

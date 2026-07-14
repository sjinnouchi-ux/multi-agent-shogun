# Shogun Skill Registry Implementation Work Log

## Status

- State: implementation and local verification complete; publication pending
- Final aggregate verification: passed, subject to the final frozen-diff review
- Pull request: pending (not opened or claimed by this log)

## Canonical Context

- Repository: `sjinnouchi-ux/multi-agent-shogun`
- Baseline `main`: `3621e9718a401451e9330ecbf7f73245bb7e63b6`
- Working branch: `codex/shogun-skill-registry`
- Work date: 2026-07-14
- Deployment boundary: Git-reviewed immutable revision; no live Shogun/tmux/queue/report/log/auth state is part of this implementation workspace

## Decisions Recorded

1. `skills/registry.yaml`, portable `skills/<skill-id>/` sources, and `skills/registry.lock.yaml` are the Shogun skill source of truth.
2. The Registry contains 12 reviewed entries. Eleven are enabled; `shogun-model-switch` is quarantined because a transactional, non-authority-expanding Registry adapter is not yet approved. The existing operator-controlled core command remains outside the skill boundary.
3. Claude and Codex targets are rendered from one portable source but installed as independent copies. A successful apply requires new Claude/Codex CLI sessions.
4. Windows Codex App and WSL2 Shogun remain separate for settings, authentication, sessions, and Drive data. Git is their integration boundary; each side is independently installed and verified at an immutable merged revision.
5. The phrase 「このスキル追加」 starts source/license/risk review and a disposition proposal (`adapted`, `codex-only`, `excluded`, or `pending`); it does not auto-trust or auto-deploy a skill.
6. Command flow is Lord → Shogun → Karo. Evidence flow is Ashigaru → Gunshi → Karo. Karo alone routes, writes `dashboard.md`, and accepts/rejects/reassigns after mechanical checks; Gunshi owns QC/RCA; Oometsuke advises on targeted/final review.

## Implementation Scope

- Registry schema, deterministic lock, target rendering, SemVer gate, provenance/notices
- Transactional apply, compensation, rollback, and explicit recovery implementation
- Migration of existing portable skills plus Shogun-adapted debugging, test-first, verification, and review-response workflows
- `first_setup.sh`, role instructions, generated CLI instructions, README/README_ja, contributor guidance, philosophy, and changelog alignment
- Windows Codex installation remains a separate post-merge operation pinned to the merged revision

## Validation Record

This table distinguishes interim evidence from final close-out. No row marked pending is a completion claim.

| Check | Result | Notes |
|-------|--------|-------|
| Documentation terminology/count parity | pass (2026-07-14) | Six-file assertion: 11 enabled + 1 quarantined, paired role/boundary/session rules, no stale count phrases, balanced fences, consistent per-file line endings |
| Registry validate/check/lock | pass | `validate` and `check --base-ref 3621e9718a401451e9330ecbf7f73245bb7e63b6`: 12 entries; deterministic lock regenerated and verified |
| Registry/unit/pressure tests | pass | Full root suite 31/31; full unit suite 707/707; focused new-skill/Registry suite 189/189; four structured pressure-evidence records validated; no skips accepted as evidence |
| Generated instruction idempotence | pass | Build-system suite 84/84, including all-CLI LF/trailing-whitespace checks and a byte-identical second build; post-build unstaged diff was empty |
| Repository lint checks | pass | `make lint` covered 26 shell files; changed shell files passed `bash -n` 6/6 and `shellcheck -S error` 6/6 |
| Repository integration target | unavailable (pre-existing) | `make test-int` exits before tests because this revision has no tracked `tests/integration/` directory; no integration test was skipped or claimed |
| Temporary-target apply/rollback/recovery | pass | Tracked Registry applied idempotently to temporary Claude and Codex roots and rolled back; recovery, interruption, collision, and drift cases passed in the 707-test suite; no live Shogun target was used |

## Pull Request Handoff

- PR number/URL: pending
- Draft status: pending
- Review findings: no unresolved Critical or Important finding before final frozen-diff sweep
- Merge commit: pending
- Post-merge Windows Codex install: pending explicit operation
- Post-merge WSL Shogun apply: pending explicit operation

## Close-out Checklist

- [x] Final validation commands and exact results recorded
- [x] Independent review findings resolved or explicitly deferred
- [x] Registry lock matches the reviewed sources and lifecycle states
- [x] No secrets, raw operational state, or local-only implementation files
- [ ] Changes committed and pushed to the task branch
- [ ] Draft PR opened with baseline, decisions, test evidence, and deployment boundary

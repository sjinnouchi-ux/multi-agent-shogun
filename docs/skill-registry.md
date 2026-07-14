# Shogun Skill Registry

The registry is the Git-canonical inventory for reusable Shogun skills. One portable source is rendered and copied to both supported CLI locations:

- Claude: `~/.claude/skills/<skill-id>`
- Codex: `~/.agents/skills/<skill-id>`

The two outputs are copies, not links. Windows Codex App and WSL2 Shogun remain separate systems; each installation is verified independently at an immutable Git revision.

## Canonical files

- `skills/registry.yaml` — lifecycle, targets, roles, activation, provenance, and target metadata
- `skills/<skill-id>/` — portable source with only `name` and `description` in shared frontmatter
- `skills/registry.lock.yaml` — deterministic source/render inventories, hashes, modes, metrics, notices, and intake decisions
- `skills/third_party/` — license and notice material for adapted sources

Design-time evidence can be listed explicitly in `distribution.exclude`. It remains validated and source-hashed but is not copied into either CLI runtime package; retained Markdown may not link to it. Adapted packages receive the validated upstream notice as a root `LICENSE` in every target copy.

`shogun-screenshot` is optional. Its selector works without adding a repository dependency, while crop and mask processing require Pillow in the invoking environment. `first_setup.sh` does not install Pillow; the helpers fail closed and report the missing optional prerequisite.

Do not edit installed copies and copy them back. Change the canonical source, increase SemVer when behavior or lifecycle changes, regenerate the lock, review, merge, and then apply the merged revision.

## Commands

Run from the repository root:

```bash
scripts/skill_registry.sh validate
scripts/skill_registry.sh lock
scripts/skill_registry.sh check --base-ref <explicit-base-commit>
scripts/skill_registry.sh apply --targets all
scripts/skill_registry.sh rollback
scripts/skill_registry.sh recover --transaction <transaction-id>
```

`check --base-ref` never guesses a comparison branch. A source, rendered output, provenance, or lifecycle change requires a greater SemVer than the explicit Git base. The first schema-v1 migration is exempt when the base has no schema-v1 registry.

New skill IDs must enter at exactly `1.0.0`. Removal is a two-revision lifecycle: first publish a greater version with status `revoked`, then remove the entry only after that revoked revision is the explicit comparison base. `disabled`, `quarantined`, and `revoked` entries remain auditable in the lock but are not deployed.

`apply` verifies the byte-canonical lock before taking process and selected-target locks. It preserves unmanaged directories whose IDs are outside the selected desired set and prunes only obsolete owned outputs. An explicit apply is also approval to adopt a markerless directory with the same desired skill ID: it snapshots that directory before replacement, and rollback restores it. The command rejects project/state/target overlap, records private transaction state, and compensates a failed multi-target mutation. Directory detachment uses no-replace renames and re-hashes the detached tree, so a concurrent destination swap is rejected without overwriting either tree. `rollback` restores the latest applied transaction only when target ownership and backup hashes still match. `recover` is explicit: it compensates an interrupted apply to the pre-apply state or an interrupted rollback to the applied state before the operator retries.

## Security boundary

Journaled recovery covers process interruption, including SIGKILL at tested transaction boundaries. It does not claim filesystem durability across sudden host or power loss because parent-directory `fsync` is outside schema v1. The implementation fails closed on detected symlink, nested-mount, alias, identity, and concurrent-drift conditions, but it cannot protect its namespace from a deliberately hostile process running as the same Unix account with equivalent filesystem authority.

Start new Claude and Codex CLI sessions after a successful apply. The tool does not restart live sessions.

## “このスキル追加” contract

When the Lord says **「このスキル追加」**:

1. Resolve the online canonical source and pin repository, 40-character commit, path, hash, and license.
2. Review executable, network, credential, destructive, lifecycle-hook, and instruction risks.
3. Install and verify the Codex App copy through its supported installer when authorized.
4. Propose one Shogun disposition: `adapted`, `codex-only`, `excluded`, or `pending`.
5. For `codex-only` or `excluded`, explain why and obtain explicit user approval before finalizing that decision.
6. For an approved Shogun skill, add portable source, registry metadata, pressure evidence, tests, and the deterministic lock through Git review.
7. Apply Shogun and any repository-owned Codex App copy only after merge, pinned to the merged commit.

Raw upstream orchestration is not copied into Shogun merely for symmetry. Shogun's role hierarchy, evidence boundary, and Git-boundary deployment take precedence.

## Expected improvement

- A production bug is reproduced by Ashigaru, analyzed by Gunshi, routed/accepted by Karo, and reviewed by Oometsuke instead of receiving an immediate speculative patch.
- A feature starts with an observed failing test, then the smallest implementation, then refactoring; “tests later” is rejected.
- “Done” requires a fresh command on the current revision with counts and acceptance criteria, not yesterday's result or a verbal claim.
- Review comments are technically evaluated as accept, reject, or clarify before Ashigaru edits code.
- Claude and Codex receive the same behavioral source while keeping only their own supported metadata.

## Security boundary

The registry protects against accidental drift, path traversal, symlink escape, corrupt Git-index fallback, malformed or tampered journals, target-root overlap, backup tampering, and partial in-process failures. Transaction state is private to the operating user.

It does not defend against the same Unix user deliberately rewriting both targets and transaction state; that user can already modify the installed files directly. Stronger protection would require signed releases and a separate privileged deployer. Never place secret values, OAuth material, authentication JSON, raw tmux panes, raw queue/report bodies, or raw logs in a skill, registry, lock, journal, test, or work log.

# Shogun Skill Registry Design

**Date:** 2026-07-14
**Status:** Approved for implementation
**Canonical repository:** `sjinnouchi-ux/multi-agent-shogun`
**Baseline:** `3621e9718a401451e9330ecbf7f73245bb7e63b6`

## 1. Goal

Create one reviewed, reproducible skill registry for Shogun that can render and install the same approved skill set for Claude Code and Codex CLI without coupling the Windows Codex App runtime to the WSL2 Shogun runtime.

The registry must also make the user's phrase 「このスキル追加」 a durable intake contract:

1. install or update the requested skill for the Windows Codex App through its own supported installation path;
2. assess whether the skill is appropriate for Shogun;
3. register and distribute an adapted version to both Shogun CLI surfaces when appropriate; and
4. propose `codex-only`, `adapted`, `excluded`, or `pending` when the raw skill is unnecessary, conflicts with Shogun's chain of command, or still needs a decision.

## 2. Non-goals

- Do not share settings, authentication, sessions, Drive data, queues, reports, logs, or tmux state between Windows Codex and WSL2 Shogun.
- Do not download or execute mutable upstream skill content at runtime.
- Do not make registry role metadata a security boundary. All agents under one Unix user can discover the installed files.
- Do not reset active Claude/Codex sessions. Newly applied skills take effect in a new session.
- Do not install the complete Superpowers orchestration layer into Shogun.

## 3. Canonical model

The repository is the source of truth:

```text
skills/<id>/                    canonical portable source
skills/registry.yaml            reviewed desired state and intake decisions
skills/registry.lock.yaml       deterministic source and rendered-output hashes
skills/third_party/...          pinned third-party notices
scripts/skill_registry.py       validate, lock, check, apply, rollback
scripts/skill_registry.sh       Python interpreter wrapper
```

Runtime destinations are separate copies:

```text
WSL ~/.claude/skills/<id>        Claude Code
WSL ~/.agents/skills/<id>        Codex CLI
Windows Codex installation      installed independently from GitHub/reviewed source
```

No link crosses the Windows/WSL boundary. Copy materialization is the default because the two CLIs may require different rendered metadata and Windows symlink behavior is not portable.

## 4. Portable source contract

Every canonical `SKILL.md` uses only this shared frontmatter:

```yaml
---
name: skill-id
description: What the skill does, when to use it, and when not to use it.
---
```

The following are rejected in shared source:

- unknown frontmatter keys;
- a name that differs from the registry id or source directory;
- missing name or description;
- malformed YAML;
- absolute or escaping paths and any symlink;
- Claude-only placeholders such as `$ARGUMENTS`, `${CLAUDE_*}`, positional `$N`, or command-injection syntax;
- missing relative references or assets.

For schema v1, command-injection syntax means Claude preprocessing forms ``!`command` ``, `$ARGUMENTS`, `$0` through `$9`, `${CLAUDE_*}`, and an absolute executable/reference path embedded in a shared-skill instruction. Ordinary Markdown exclamation marks are not rejected solely by this rule; executable assets still require manual security review and lock coverage.

Schema v1 permits only the non-authorizing Claude `argument_hint` registry metadata. Tool preapprovals such as `allowed-tools` / `allowed_tools` are forbidden rather than injected. Portable `activation: manual` is rendered as target-specific invocation controls (`disable-model-invocation` for Claude and `allow_implicit_invocation: false` for Codex); those controls reduce automatic invocation and never grant tools. Codex-only descriptive interface metadata may be rendered to `agents/openai.yaml`; it never expands role authority. Canonical Markdown remains byte-equivalent between targets unless a reviewed target overlay is explicitly declared in a later schema version.

## 5. Registry schema

`registry.yaml` has a fixed `schema_version`, logical outputs, a skill list, and an intake decision list.

The schema version 1 normative shape is:

```yaml
schema_version: 1
outputs:
  claude:
    path: "~/.claude/skills"
  codex:
    path: "~/.agents/skills"
skills:
  - id: example-skill                 # required; lowercase kebab-case
    version: 1.0.0                    # required SemVer
    source: example-skill             # required; schema v1 requires source == id
    status: enabled                   # enabled|disabled|quarantined|revoked
    targets: [claude, codex]          # non-empty subset
    activation: automatic             # automatic|manual
    classification: required          # required|optional
    eligible_roles:                   # advisory, never authorization
      - shogun
      - karo
      - ashigaru
      - gunshi
      - oometsuke
    applicability: "When this belongs in Shogun; include exclusions."
    distribution:                     # optional; exact source files omitted at runtime
      exclude:
        - references/design-evidence.md
    claude:                            # optional; rejected when claude is not a target
      argument_hint: "[topic]"        # optional string
      # No tool preapprovals are permitted in schema v1.
    codex:                             # optional; rejected when codex is not a target
      interface:                       # optional agents/openai.yaml interface
        display_name: "Example skill"
        short_description: "Twenty-five to sixty-four characters"
        default_prompt: "Use $example-skill to ..."
    provenance:
      kind: bundled                    # bundled|adapted
      license: MIT
      # adapted additionally requires repository, tag, 40-char commit,
      # path, upstream_sha256, adaptation_revision, and notice_file
intake_decisions:
  - id: upstream-skill                # unique across decisions and deployed ids
    disposition: codex-only           # codex-only|adapted|excluded|pending
    reason: "Concrete technical reason; never empty."
    upstream:                          # optional only when source is not yet known
      repository: https://example.com/owner/repo
      commit: 0123456789abcdef0123456789abcdef01234567
      path: skills/upstream-skill
```

Unknown keys fail closed. Required fields have no implicit default. Role values are exactly `shogun`, `karo`, `ashigaru`, `gunshi`, and `oometsuke`; target values are exactly `claude` and `codex`. A decision id cannot duplicate a skill id. In schema v1, `source` is a single POSIX path segment that exactly equals `id` and names the direct child `<registry-directory>/<id>/`; `/`, `\\`, `.`, and `..` are rejected.

Public commands are `validate`, `lock`, `check`, `apply --targets {all,claude,codex}`, `rollback [--transaction ID]`, and `recover --transaction ID`. Global options `--registry` and `--lock` allow isolated fixtures. Runtime overrides are `SHOGUN_SKILL_REGISTRY_CLAUDE_DIR`, `SHOGUN_SKILL_REGISTRY_CODEX_DIR`, and `SHOGUN_SKILL_REGISTRY_STATE_DIR`; they change destinations only, never source discovery or policy.

Exit code `0` means the requested operation completed. Exit code `2` means a validation, policy, lock-drift, ownership, or transaction-safety refusal. Unexpected runtime failures use `1` after best-effort compensation. Error text identifies the failing skill/field/path without printing file contents or environment values.

Each skill records:

- `id`, semantic `version`, relative `source`, and lifecycle `status`;
- targets (`claude`, `codex`) and activation (`automatic`, `manual`);
- advisory eligible roles, required/optional classification, and applicability notes;
- typed Claude/Codex metadata and an optional exact-file runtime exclusion list;
- bundled or pinned-upstream provenance, license, commit, original path, and adaptation revision.

Lifecycle values are `enabled`, `disabled`, `quarantined`, and `revoked`. Only `enabled` skills are materialized. A non-enabled skill remains auditable in the registry and lock.

Intake decisions record a skill name, pinned source when known, disposition (`codex-only`, `adapted`, `excluded`, or `pending`), and a concrete reason. A decision never deploys a payload by itself.

Any source or rendered-output change for an existing skill requires a strictly greater semantic version. CI compares the PR result with its base revision; changing only the lock without a version bump fails. New skills start at `1.0.0`. Lifecycle-only transitions also require a version bump because they change materialized state.

`check --base-ref <sha-or-ref>` uses the explicit PR base supplied by CI; it never guesses from the current branch or merge-base. If the base does not contain schema v1 yet, this first migration is exempt. Subsequent PRs must provide the base SHA and pass the version gate.

## 6. Deterministic lock

`registry.lock.yaml` is generated, not hand-edited. It contains no timestamp, mtime, username, absolute path, or machine-specific value.

For every skill and target it records:

- registry SHA-256;
- source file list, byte size, executable bit, per-file SHA-256, and tree SHA-256;
- rendered target file list and tree SHA-256;
- description characters, listing characters, bytes, and line count;
- pinned upstream commit/blob/hash/license data for adaptations.

Paths in the lock are sorted repository-relative POSIX paths and must be unique under Unicode NFC normalization plus case folding, including generated and reserved paths. This prevents source, metadata, or injected-license collisions on default macOS and Windows filesystems. File bytes are hashed exactly as stored with LF enforced by `.gitattributes`. YAML is UTF-8, LF, deterministic key order, and one terminal newline. For tracked files, the executable bit comes from the Git index mode (`100755` versus `100644`), never Windows `os.stat`; isolated non-Git test fixtures use their POSIX mode. Release lock generation rejects an untracked executable asset.

`distribution.exclude` is a fail-closed list of normalized relative POSIX file paths: no glob, directory, symlink, duplicate, missing file, or `SKILL.md` entry is accepted. Excluded design-time evidence remains fully validated and hashed in the source inventory but is absent from target inventories. Retained Markdown must not link to an excluded file. Every adapted target injects the validated upstream notice bytes as a mode-`100644` root `LICENSE`; a canonical source collision with that reserved path is rejected.

For each file entry, the tree digest appends UTF-8 `path`, NUL, ASCII `100755` or `100644`, NUL, the lowercase hexadecimal file SHA-256, and LF, in POSIX-path order. `listing_chars` is the Unicode character count of `name + "\n" + description`; aggregate listing is the sum for enabled skills on that target. `lines` is the number of logical LF-delimited lines, including a final non-empty line without LF.

`check` recomputes the complete expected lock in memory and exits non-zero for missing files, extra files, source tampering, render drift, schema errors, or portability violations. It is strictly read-only. `lock` is the maintainer-only command that atomically replaces the tracked lock.

## 7. Apply and rollback transaction

`apply` performs `check` first, stages complete rendered directories beside each target, and then mutates only IDs in the selected desired set plus obsolete Registry-owned IDs. Unrelated unmanaged IDs are preserved. Explicit apply authorizes adoption of a markerless same-ID directory: that directory is snapshotted before replacement and restored by rollback.

Reconciliation is bidirectional. If a previously managed skill becomes disabled/revoked, loses a target, or is removed from desired state, `apply` snapshots and removes only the destination carrying a valid Shogun ownership marker. A same-name unmarked directory is never pruned. These removals are journaled and restored by rollback like replacements.

Before adopting or replacing a same-name directory, the command snapshots it in the transaction state. Both Claude and Codex target updates form one journaled transaction. If any target fails, already changed targets are restored automatically.

Local transaction state is stored under `$XDG_STATE_HOME/multi-agent-shogun/skill-registry`, falling back to `~/.local/state/...`. Tests can override destinations and state roots through dedicated environment variables.

`rollback` restores the most recent applied transaction, or an explicit transaction id. It refuses to remove or overwrite a destination whose ownership marker no longer matches the transaction, preventing accidental deletion of a later unmanaged replacement.

Every installed directory has `.shogun-skill.json` containing `schema_version`, owner `multi-agent-shogun`, `skill_id`, `target`, `version`, `registry_sha256`, rendered `tree_sha256`, and `transaction_id`. Installed-tree verification excludes the marker itself. Before rollback mutates either target, every affected destination must have the expected marker and unchanged rendered tree, or the entire rollback refuses without changing any target.

An applied command prints its transaction id, and the journal at `transactions/<id>.json` records ordered prepared/applied/compensated operations and relative backup locations. A process lock at `registry.lock` waits at most ten seconds, then refuses with exit `2`. Startup recovers or refuses an incomplete journal before accepting another mutation; it never silently abandons staged or backup state.

Apply and rollback use a process lock, staged directories, atomic renames on the destination filesystem, and managed-only cleanup. Success output states that a new CLI session is required.

## 8. Security and provenance

External intake is review-before-vendoring:

1. pin repository, commit, path, and license;
2. inspect hooks, scripts, network calls, shell commands, subprocesses, destructive operations, secret access, and path traversal;
3. reject symlinks and runtime downloads;
4. adapt the minimum useful behavior to Shogun roles;
5. run static checks, trigger/non-trigger tests, role-pressure tests, and both target render checks;
6. update the deterministic lock only after review.

The four Superpowers derivatives pin `obra/superpowers` v6.1.1 at commit `d884ae04edebef577e82ff7c4e143debd0bbec99` under the MIT license, including Jesse Vincent's copyright notice in every standalone installed target. Their pressure-run artifacts remain canonical design evidence but are deliberately excluded from runtime renders.

Offline `check` verifies the tracked registry, local derivative, rendered outputs, notice file, and every recorded local hash. It does not claim to re-fetch or authenticate GitHub. Upstream authenticity is established during the maintainer intake/update operation against the pinned commit and recorded in review evidence; runtime apply never performs network access.

## 9. Role boundary

Installed skills describe method; they never grant authority. The loaded role instruction, current agent id, assigned task YAML, and chain of command always win.

The effective hierarchy for these skills is:

```text
Lord -> Shogun -> Karo
                    |- Ashigaru 1-7: implementation and test execution
                    |- Gunshi: RCA, design, technical evaluation, QC
                    `- Oometsuke: independent final/targeted review
```

Karo alone owns routing, dashboard updates, reassignment, and final acceptance. Oometsuke reports to Karo and does not implement. Ashigaru reports completed work to Gunshi. The four adapted skills repeat a concise role guard in each `SKILL.md` so it is visible even when a skill is loaded alone.

## 10. Initial contents

All seven existing bundled skills are migrated into the registry:

- `skill-creator`
- `shogun-agent-status`
- `shogun-bloom-config`
- `shogun-model-list`
- `shogun-model-switch`
- `shogun-readme-sync`
- `shogun-screenshot`

Four approved Superpowers behaviors are added as role-aware derivatives:

- `shogun-systematic-debugging`
- `shogun-test-first`
- `shogun-verification-before-done`
- `shogun-review-response`

One infrastructure skill, `shogun-skill-intake`, captures the phrase 「このスキル追加」 and the intake decision workflow. It is not a fifth Superpowers behavior.

The remaining Superpowers skills are recorded as `codex-only` decisions for this release because their orchestration behavior conflicts with Shogun routing or lifecycle ownership:

- `brainstorming`
- `dispatching-parallel-agents`
- `executing-plans`
- `finishing-a-development-branch`
- `requesting-code-review`
- `subagent-driven-development`
- `using-git-worktrees`
- `using-superpowers`
- `writing-plans`
- `writing-skills`

## 11. Integration

- `first_setup.sh` replaces its Claude-only copy loop with registry `apply --targets all` and reports failure without hiding it.
- The obsolete single `skill.save_path` setting is removed or deprecated in favor of registry target definitions.
- `Makefile` gains registry check/lock targets; CI runs the source/lock check on Linux and macOS.
- `.gitattributes` pins skill Markdown, YAML, Python, and Shell content to LF so hashes remain stable across Windows and WSL.
- generated Claude, Codex, OpenCode, Copilot, and root instruction files are rebuilt from corrected source instructions.
- README and operating docs distinguish bundled registry-managed skills from personal unmanaged skills and state that a new session is required after apply.
- The inconsistent legacy Ashigaru-to-Karo review path is corrected to Ashigaru-to-Gunshi-to-Karo; Karo remains the only dashboard owner.
- Installed skills must be self-contained. Commands and relative references resolve from the directory containing the installed `SKILL.md`; they must not jump back to repository-relative `skills/...` paths.
- `CLAUDE.md` and instruction source fragments may be edited; `AGENTS.md`, Copilot/OpenCode files, and other declared generated outputs are changed only by `scripts/build_instructions.sh`.

## 12. Acceptance criteria

1. Registry validation and lock verification are deterministic on Linux and macOS.
2. All seven existing skills plus the four approved adaptations and intake skill are represented exactly once.
3. Applying into a temporary HOME produces both Claude and Codex outputs, preserves unrelated unmanaged skills, snapshots and adopts markerless same-ID skills, safely prunes only obsolete marked outputs, is idempotent, and supports rollback of replacements and removals.
4. Partial two-target failure restores the first target.
5. Source tampering, extra files, symlinks, path traversal, malformed frontmatter, target metadata leakage, and lock drift fail closed.
6. The four adapted skills pass every post-skill role-pressure case and static role-guard check; baseline fields distinguish observed runs from `context_only` source material and never invent missing scores.
7. Existing repository tests have zero failures and zero unexpected skips; generated instructions have no drift.
8. The branch contains no secrets, runtime queues/reports/logs, uncommitted changes, or unpushed commits at handoff.
9. Windows Codex and WSL Shogun remain operationally separate; only reviewed GitHub content crosses the boundary.

Role-pressure cases live in `tests/skill_scenarios/*.yaml`. Each adapted skill stores a structured `pressure-run.yaml` plus a bounded narrative record with the scenario hashes, baseline status, post-skill result, runner surface/date, observed rationalizations, and the no-live-state boundary. The systematic-debugging baseline is explicitly `context_only`; the other baselines include only their observed subset, while every post-skill case is recorded. The checker verifies schema, hashes, known pressure IDs, counts, and explicit limitations, but does not claim cryptographic execution attestation or exhaustive secret detection. Authenticated fresh baseline execution remains a maintainer verification step rather than a secret-bearing CI job.

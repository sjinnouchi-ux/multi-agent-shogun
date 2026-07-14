---
name: shogun-skill-intake
description: Process an approved skill-addition request across Codex App and the Shogun Skill Registry. Use when the Lord says “このスキル追加” or asks to install and evaluate a reusable skill.
---

# Shogun skill intake

The phrase **「このスキル追加」** authorizes one bounded intake workflow. It does not erase the Git boundary between Windows Codex App and Shogun, and it does not pre-approve unsafe Shogun behavior.

Use the [intake checklist](references/intake-checklist.md) as the evidence record.

## 1. Establish the source

Resolve the online canonical repository before using a local clone. Record the repository, tag when present, exact 40-character commit, source path, content hash, license, and notice obligations. Reject mutable-only downloads and ambiguous ownership.

Review executable assets, network or credential access, lifecycle hooks, destructive commands, and instruction conflicts. The review must not inspect or disclose secrets, tmux panes, raw queues, raw reports, raw logs, or authentication material.

## 2. Separate the two installations

- **Codex App side:** use the supported Codex skill installer at the immutable source pin. Verify the installed identity and record any required new-session step.
- **Shogun side:** change the canonical Git repository only. Shogun must not write into the Windows Codex profile, share its authentication/session state, or treat a local Codex installation as deployment evidence.

If the current environment cannot perform one side, emit a bounded action item. Never pretend that installing on one side updated the other.

## 3. Decide the Shogun disposition

Choose exactly one:

- `adapted`: retain useful domain behavior while removing upstream orchestration, tool-specific metadata, or role conflicts.
- `codex-only`: useful for Codex App, but unnecessary or conflicting in Shogun.
- `excluded`: unsafe, redundant, unlicensed, or incompatible.
- `pending`: evidence or a material decision is missing.

For `codex-only` or `excluded`, propose the reason and wait for explicit user approval before finalizing the Shogun decision. Do not add raw upstream orchestration merely to make both sides look symmetrical.

## 4. Implement an approved Shogun addition

Karo routes the work. Ashigaru implements a bounded source change, Gunshi checks design and evidence, and Oometsuke performs targeted/final review. The shared skill uses portable frontmatter; target metadata belongs in the canonical registry manifest.

After establishing the task-local canonical repository and verifying its origin and exact commit, invoke its repository-owned registry wrapper from that verified root. Run, in order:

1. schema and source validation;
2. deterministic lock generation;
3. lock verification against an explicit base commit.

Do not resolve the wrapper from the installed skill directory, an arbitrary current working directory, or an environment variable. Preserve license notices and increase SemVer for behavioral or lifecycle changes.

Pressure-test role boundaries and shortcut rationalizations. `SKIP` is a failure, not verification.

## 5. Deploy only after merge

Commit the canonical source, deterministic lock, tests, decision record, and work log through review. Shogun deployment is a separate post-merge operation pinned to the merged commit. Apply both target renders, verify the managed inventories, and start new Claude/Codex CLI sessions only after successful apply.

Any requested Codex App installation of repository-owned intake content is also post-merge and pinned to the merged commit. Never install unreviewed branch content as the durable personal copy.

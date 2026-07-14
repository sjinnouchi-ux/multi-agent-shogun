---
name: skill-creator
description: Design or revise portable, role-safe Shogun skills. Use when a reusable workflow needs a SKILL.md, registry metadata, pressure tests, or a disposition decision.
---

# Shogun skill creator

Create small operational instructions that both Claude and Codex can consume from one canonical source.

## Start with intake

When the request means “add this skill,” use `shogun-skill-intake` first. Intake records the immutable source, license, security review, and one disposition:

- `adapted`: useful in Shogun after removing upstream orchestration or role conflicts.
- `codex-only`: useful in the Codex App but not in Shogun.
- `excluded`: unsafe, redundant, or contrary to Shogun governance.
- `pending`: evidence or user approval is still missing.

Do not silently add a candidate to Shogun. If `codex-only` or `excluded` is the better fit, explain why and obtain the Lord's decision. Windows Codex installation and Shogun deployment are separate Git-boundary operations.

## Canonical format

The shared `SKILL.md` frontmatter contains only:

```yaml
---
name: lowercase-hyphen-name
description: What the skill does and the situations that should trigger it.
---
```

Put target-specific metadata in the canonical registry manifest; the renderer adds it to Claude or Codex output. Keep shared instructions tool-neutral. Link every bundled reference or script with a path relative to the Markdown file that uses it.

## Design sequence

1. State the trigger and the non-goals.
2. Name the eligible Shogun roles and preserve the hierarchy: Karo routes and accepts; Ashigaru executes; Gunshi analyzes and verifies; Oometsuke performs targeted or final review.
3. Define observable inputs, outputs, failure states, and safe escalation.
4. Remove raw secrets, authentication material, tmux pane content, raw queue/report bodies, and unbounded logs from evidence.
5. Write a failing contract or pressure scenario before the skill text.
6. Add only the instructions needed to make that evidence pass.
7. From a separately verified canonical repository root, run its repository-owned registry validation, deterministic lock generation, base comparison, and rendered-target checks.
8. Increase SemVer whenever source, rendered behavior, provenance, or lifecycle changes.

Never infer a repository executable from the installed skill directory, the current working directory, or an environment variable.

## Pressure test

Test at least three shortcut rationalizations that a capable agent might use, such as “the change is tiny,” “the deadline overrides the role boundary,” or “a summary is enough evidence.” The skill must reject the shortcut with a concrete alternative, not merely repeat a slogan.

## Completion evidence

Report the skill ID and version, disposition, eligible roles, source/license pin, tests run with fresh results, rendered Claude/Codex inventories, and any separate post-merge installation step. `SKIP` is not success.

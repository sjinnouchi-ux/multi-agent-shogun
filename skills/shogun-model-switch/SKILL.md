---
name: shogun-model-switch
description: Review a requested Shogun agent model switch that is currently quarantined. Use to explain the safety block or define requirements for a future transactional redesign.
---

# Shogun model switch — quarantined

Do not execute a model or CLI switch with this skill. A safe, self-contained Registry adapter has not been established, so the Registry deliberately does not deploy agent-invoked switching.

The existing operator-controlled core switching command is a separate Shogun interface and remains unchanged by this quarantine. Its existence does not authorize an agent to discover or invoke it through this installed skill.

Model switching remains a **Karo only** routing mutation. Shogun, Ashigaru, Gunshi, and Oometsuke may recommend, implement under delegation, analyze, or review a redesign, but they must not bypass the quarantine.

## Response to a switch request

1. State that Registry-driven agent switching is unavailable while this entry is quarantined.
2. Offer safe alternatives: route new work to a different idle agent, or finish the current assignment and restart through the normal launch path with an approved model.
3. Do not inspect tmux pane content, raw queues, reports, logs, credentials, or secrets to justify an exception.
4. Do not hand-edit runtime state, invoke a repository helper, or send commands directly to another role's session.

## Requirements for a future redesign

Before this entry can become enabled, a reviewed implementation must:

- prove the selected agent is idle using bounded, recorded state;
- acquire a single-writer routing lock;
- record the previous CLI/model pair and exact configuration revision;
- validate the target against current supported configuration;
- make the configuration transition atomically;
- verify readiness without reading pane contents;
- rollback every changed artifact on failure; and
- pass fresh race, interruption, unsupported-target, and rollback tests.

Changing `quarantined` to `enabled` is a versioned lifecycle change and requires explicit approval, Registry review, regenerated lock evidence, and post-merge deployment.

---
name: shogun-bloom-config
description: Draft role-safe Bloom capability routing from the models and subscriptions currently available. Use when capability tiers need creation or review without relying on stale price tables.
---

# Shogun Bloom configuration

Create a proposal, not an unreviewed live configuration.

## Collect current constraints

Ask for the available CLI subscriptions, allowed cost posture, required offline or fallback behavior, and any model restrictions. Read supported model identifiers from current repository configuration and the installed CLI's own documented discovery surface. Do not infer availability from old examples, cached pricing, or authentication files.

## Preserve roles

- Karo routes the work and is the only role that updates routing state or accepts the final result.
- Ashigaru may draft a candidate mapping under an assigned task.
- Gunshi evaluates capability coverage, failure modes, and the smallest model sufficient for each Bloom level.
- Oometsuke reviews unsupported claims, privilege changes, and unsafe fallbacks.
- Shogun presents material tradeoffs to the Lord when approval is required.

## Produce the proposal

1. List only verified model identifiers and their source of verification.
2. Map Bloom levels monotonically; a lower tier must not claim capability above its verified ceiling.
3. Define an explicit unavailable/fallback result. Never silently substitute a more expensive or differently trusted provider.
4. Emit the smallest YAML fragment needed for review, followed by assumptions and validation commands.
5. Keep secret values, OAuth data, raw CLI account output, and raw operational logs out of the evidence.

Gunshi verifies schema and routing behavior before Karo accepts the change. Oometsuke reviews high-impact provider, cost, or privilege changes. `SKIP` is a failed verification result.

---
name: shogun-model-list
description: Build a current read-only inventory of models usable by configured Shogun CLIs. Use for routing comparisons when identifiers, availability, or capability tiers may have changed.
---

# Shogun model inventory

Never treat a bundled model or price table as current.

1. Read configured CLI types and model aliases from the repository's canonical settings.
2. Confirm identifiers through the installed CLI's documented model listing or official documentation available to the operator.
3. Record verification time and classify each result as configured, available, unavailable, or unverified.
4. Compare only evidence relevant to routing: supported context/features, verified Bloom ceiling, subscription constraint, and fallback behavior.
5. Do not expose tokens, account identifiers, OAuth material, raw authentication output, tmux panes, or unbounded logs.

All Shogun roles may consult the inventory. Karo alone turns it into routing changes; Gunshi evaluates capability claims; Oometsuke reviews material trust or cost changes. If a fact cannot be freshly verified, label it `unverified` rather than guessing.

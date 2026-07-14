---
name: shogun-readme-sync
description: Detect and repair structural drift between English and Japanese README files. Use when a documentation change must preserve commands, anchors, and factual parity across both editions.
---

# Shogun README synchronization

Karo routes and accepts this work; Karo does not edit the files. Ashigaru performs the bounded edit, Gunshi verifies structural and factual parity, and Oometsuke performs targeted review when commands, security guidance, or architecture claims change.

1. Compare heading structure, code blocks, tables, links, warnings, and referenced version facts.
2. Classify each difference as intentional localization, missing content, stale fact, or formatting drift.
3. Ashigaru changes only the smallest affected sections. Preserve commands, paths, identifiers, anchors, and code literally unless the underlying implementation changed.
4. Gunshi checks both reading directions: every English operational claim has a Japanese counterpart and every Japanese operational claim has an English counterpart.
5. Run link/format tests and any repository documentation checks. `SKIP` is not a pass.
6. Oometsuke reviews security, installation, role-governance, and destructive-operation text when touched.

Report changed headings and fresh test results. Do not rewrite unrelated prose merely for stylistic uniformity.

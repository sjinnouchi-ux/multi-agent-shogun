---
name: shogun-screenshot
description: Capture, crop, and mask a bounded screenshot artifact without leaking sensitive context. Use when visual evidence is necessary for documentation, review, or a reproducible UI report.
---

# Shogun screenshot

Prefer the smallest visual artifact that proves the claim. Karo routes the work and defines the approved source and destination boundaries. Ashigaru alone selects and processes the local image. Gunshi and Oometsuke review the sanitized artifact; they do not perform the selection or edit.

## Safety gate

Before selection, define the exact image and region and list likely secret surfaces: tokens, account names, private URLs, notifications, terminal history, unrelated windows, and personal data. Never select raw tmux panes, authentication prompts, queue/report bodies, or unbounded desktop captures. Never delete or overwrite the user original.

The selector rejects inputs larger than 64 MiB (67,108,864 bytes). The processors reject images over 16,384 pixels per dimension and 40,000,000 total pixels, including requested resize dimensions, and treat every Pillow decompression-bomb warning or error as a hard failure. These limits are fixed safety boundaries, not retry suggestions.

## Workflow

1. Karo records the explicit user-approved input file and distinct output paths, then routes the bounded task to one Ashigaru.
2. That Ashigaru runs the [local-image selector](scripts/capture_local.sh) as `capture_local.sh --input FILE`. The selector accepts one explicit regular PNG or JPEG, rejects symlinks and non-images, never scans a desktop or directory, and returns one JSON record containing `path` and `identity`.
3. Preserve that exact identity token in the bounded work record. Crop unused context with [trim image](scripts/trim_image.py), passing the selected path as `--input` and the token as `--input-identity`. An identity mismatch means the input changed: stop and select it again.
4. Select every intermediate output again before using it as a new input. To mask a cropped output with [mask sensitive](scripts/mask_sensitive.py), run the selector on that output and pass its newly returned identity. Write to another distinct path. Every region must have positive area and overlap the image. Redaction must be opaque, not blur-only; unredacted preview output is forbidden.
5. Gunshi checks the transformation and evidence boundary. Oometsuke performs the final independent leak review. Inspect the sanitized output at full resolution before sharing it.
6. Store only the reviewed sanitized artifact in an approved repository path. Both processors create a private sibling temporary and atomically commit only to a path that is still absent; an existing file, symlink, or concurrent creator is a hard failure. Keep the user original outside Git and leave its retention or deletion to its owner.

If the required imaging dependency is unavailable, report the missing prerequisite. Do not install packages at runtime without explicit authority. Evidence must include the bounded target, sanitization decision, and reviewer result, never the secret content itself.

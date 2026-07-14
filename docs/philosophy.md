# Philosophy

> "Don't execute tasks mindlessly. Always keep 'fastest × best output' in mind."

## Five Core Principles

### 1. Autonomous Formation Design

Design task formations based on complexity, not templates. A simple file rename does not need all 7 Ashigaru. A complex refactor across 20 files may use all 7 with dependency chains, Gunshi QC, and an Oometsuke checkpoint. Karo alone selects and records the formation.

### 2. Parallelization

Use subagents to prevent single-point bottlenecks. Karo decomposes and routes independent subtasks to multiple Ashigaru. Dependent tasks use `blocks`/`blockedBy` in YAML; completed evidence flows Ashigaru → Gunshi → Karo so qualitative review does not become Karo's execution bottleneck.

### 3. Research First

Search for evidence before making decisions. Agents don't rely solely on their training data — they actively research using web search, file exploration, and codebase analysis before proposing solutions. This is especially critical for tasks involving external APIs, libraries, or current best practices.

### 4. Continuous Learning

Don't rely solely on model knowledge cutoffs. The system uses Memory MCP to persist lessons learned, discovered patterns, and operational insights across sessions. When an agent encounters a problem it has solved before, it checks memory first. When it learns something new, it records it for future reference.

### 5. Triangulation

Multi-perspective research with integrated authorization. Important decisions are validated from multiple sources — not just one search result or one file. The system cross-references documentation, existing code patterns, and web resources before committing to an approach.

## Design Decisions

### Why this hierarchy and evidence flow?

1. **Instant response**: The Shogun delegates immediately, returning control to you
2. **Single routing owner**: Karo alone assigns/reassigns agents, tracks dependencies, and updates `dashboard.md`
3. **Separated execution and judgment**: Ashigaru execute; Gunshi owns QC, evidence review, and RCA
4. **Independent challenge**: Oometsuke performs targeted or final review and advises Karo without taking routing authority
5. **Explicit acceptance**: Karo performs mechanical completeness checks and alone records accept/reject/reassign decisions
6. **Unified reporting**: Only Shogun communicates material decisions with the Lord

### Why Mailbox System?

1. **State persistence**: YAML files provide structured communication that survives agent restarts
2. **No polling needed**: `inotifywait` is event-driven (kernel-level), reducing API costs to zero during idle
3. **No interruptions**: Prevents agents from interrupting each other or your input
4. **Easy debugging**: Humans can read inbox YAML files directly to understand message flow
5. **No conflicts**: `flock` (exclusive lock) prevents concurrent writes — multiple agents can send simultaneously without race conditions
6. **Guaranteed delivery**: File write succeeded = message will be delivered. No delivery verification needed, no false negatives
7. **Nudge-only delivery**: `send-keys` transmits only a short wake-up signal (timeout 5s), not full message content. Agents read from their inbox files themselves

### Why only the Karo updates dashboard.md

1. **Single writer**: Prevents conflicts by limiting updates to one agent
2. **Information aggregation**: Karo receives Gunshi/Oometsuke conclusions and their referenced Ashigaru evidence
3. **Consistency**: Routing state, mechanical completion state, and acceptance decisions share one owner
4. **No interruptions**: If the Shogun updated it, it could interrupt the Lord's input

### Why shared skills are Registry-managed

Approved shared skills are committed under `skills/`, declared in `skills/registry.yaml`, and pinned by `skills/registry.lock.yaml`. This makes provenance, licensing, target metadata, and deployment reproducible. Discovery is only a proposal: the Lord's phrase 「このスキル追加」 starts intake and does not automatically trust or deploy a candidate.

Personal experiments in `.claude/commands/` or other user-owned locations stay unmanaged and uncommitted. They are never copied into the Registry without source pinning, license/risk review, role adaptation, pressure evidence, and tests. A candidate may be `adapted`, `codex-only`, `excluded`, or `pending`; Shogun symmetry is not a reason to deploy an unsafe or irrelevant skill.

The Registry currently contains 12 entries. Eleven are enabled; `shogun-model-switch` is quarantined because its live-pane mutation is not yet transactional enough for this trust boundary.

### Why Windows Codex and WSL2 Shogun remain separate

Windows Codex App and WSL2 Shogun do not share settings, authentication, sessions, or Drive storage. Git is the integration boundary: install and verify each system independently at an immutable merged revision. After applying WSL skill copies, start new Claude and Codex CLI sessions; live sessions do not reload skills.

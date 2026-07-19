# Codex Diagnostics Fixed Inbox Symlink Design

**Date:** 2026-07-19
**Status:** Implemented; deployment pending
**Scope:** `scripts/codex_diagnostics.py`, its tests and diagnostics documentation
**Out of scope:** WebUI, watcher delivery semantics, queue migration, auto restart, P2

## Problem

`shutsujin_departure.sh` deliberately replaces `queue/inbox` with a symlink to
the fixed Linux-filesystem directory
`/home/jinnouchi/.local/share/multi-agent-shogun/inbox`. This preserves reliable
`inotifywait` behavior when a checkout is located on a filesystem that does not
provide the required notifications.

The schema-version-1 diagnostics collector opens every runtime source beneath
the repository directory FD with `O_NOFOLLOW`. That is the correct default for
untrusted links, but it also rejects the canonical inbox symlink before opening
any agent inbox file. A trusted post-reboot diagnostic reproduced the mismatch:
all eleven agent inbox sources were `rejected`, while task, report,
handoff-status and watcher-log sources remained readable. When the agents were
running, the eleven required inbox rejections made the otherwise healthy
deployment `degraded`.

## Selected Approach

Keep the fail-closed no-follow policy and add one explicit user-local inbox
root to the diagnostics allowlist.

The collector accepts either:

1. a regular in-repository `queue/inbox` directory opened component-by-component
   with `O_NOFOLLOW`; or
2. a `queue/inbox` symlink whose stored target is exactly
   `/home/jinnouchi/.local/share/multi-agent-shogun/inbox`, followed by a fresh
   component-by-component no-follow open of that fixed absolute directory.

No other symlink target is accepted. The target is not obtained from `HOME`, an
environment variable, a CLI argument, repository configuration or runtime
file content.

## Alternatives Rejected

### Mark inbox metadata not applicable

This avoids following the symlink but loses detection of missing or rejected
agent inbox files. It weakens the diagnostic without fixing the mismatch.

### Remove the runtime symlink

Changing the launcher would alter the inbox delivery and `inotifywait` storage
contract and require runtime data migration. That is wider and riskier than a
diagnostics-only correction.

### Permit arbitrary symlink traversal

Following a resolved path or trusting an environment-derived target would
violate the fixed allowlist and introduce link-swap and path-injection risks.
It is forbidden.

## Architecture

### Fixed constants

The production collector defines the exact inbox root as an immutable absolute
component tuple. Tests may inject an alternate expected link string plus a
pre-opened, mode-`0700` traversal root and relative component tuple directly
into an internal helper. That test-only seam keeps fixtures isolated without
weakening the production traversal from `/`; there is no production CLI or
environment override.

### Repository binding check

The collector opens `queue` beneath the repository FD without following links,
then inspects `inbox` without following it.

- If `inbox` is a directory, the collector uses that opened directory FD.
- If `inbox` is a symlink, `readlink` must return the exact fixed target string,
  including its leading slash and with no normalization or trailing slash.
- A missing entry is `SourceMissing`.
- Any other file type, link value or unstable binding is `SourceRejected`.

The symlink is only an assertion that the repository is connected to the
allowlisted inbox root. It is never followed by pathname resolution.

For a symlink binding, the collector records the link's no-follow metadata and
target before opening the fixed root. After collecting all inbox leaf metadata,
it repeats the no-follow inspection and requires the link type, device, inode,
modification metadata and target string to match. A mismatch rejects the whole
inbox-source collection; it never returns a mixture of values from an unstable
binding.

### Fixed-root traversal

After an exact symlink match, the collector opens `/` and traverses every fixed
target component with `O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW`. It rejects:

- missing `O_NOFOLLOW` support;
- a symlink or non-directory component;
- any component not owned by root or the effective user;
- any group- or world-writable component;
- a final inbox root not owned by the effective user; or
- a binding that changes across validation.

The collector records the opened inbox directory's device and inode. Before
accepting the collection, it performs a second component-by-component no-follow
open of the fixed path and requires the resulting directory identity to match
the pinned FD. The pinned FD remains the only root used to inspect leaves, so a
pathname race cannot redirect an individual file open.

Agent inbox leaves are then opened relative to the pinned inbox directory FD by
the existing regular-file helper. Inbox contents are not read.

### Source routing

`SourceSpec` gains an internal root selector with only `runtime` and `inbox`.
All existing sources retain `runtime`; only the `inbox` source uses the pinned
inbox root. The JSON field names, ordering, states, applicability rules and
schema version remain unchanged.

The inbox directory FD is acquired once per collection, reused for the eleven
fixed agent filenames, and closed on every success or failure path.

## Failure Handling

Expected canonical state produces `inbox.state=present`.

The following root or binding failures fail closed as `state=rejected` for
every applicable inbox source, with sanitized `source_rejected` issues:

- wrong, relative or malformed symlink target;
- symlinked target ancestors;
- unsafe target-directory ownership or mode;
- link or directory binding changes during validation; and
- unsupported no-follow primitives.

A nonregular inbox leaf rejects only that leaf. A missing fixed root rejects no
path traversal but reports every applicable inbox source as `missing`; an
individual missing leaf reports only that leaf as `missing`. Ordinary I/O
failures remain `error` at the corresponding root or leaf scope. No raw path,
target, errno or exception text enters JSON output.

## Tests

Test-first implementation adds regressions for:

1. the current canonical symlink arrangement producing eleven present inboxes
   and no `source_rejected` issue;
2. a safe in-repository inbox directory remaining supported;
3. a wrong symlink target remaining rejected for all affected agents;
4. a symlink in any allowlisted target ancestor being rejected;
5. group/world-writable user-local ancestors being rejected;
6. missing and nonregular inbox leaves preserving current state/severity;
7. directory-FD and symlink bindings changing during inspection being rejected;
8. exact JSON/consumer contract compatibility; and
9. an isolated mode-`0700` integration fixture matching launcher-created inbox
   geometry without reading or writing the production inbox root.

Required verification includes the focused diagnostics unit/contract/integration
tests, `make test-no-skip`, `make test-int`, `make lint`, `make build` and
`make check`. Any skip is a failure.

## Deployment and Rollback

The code fix is merged before the immutable user-local snapshot is replaced.
Snapshot placement remains a separately recorded deployment operation:

1. merge the reviewed code PR;
2. verify the target Git blob and install the mode-`0555` snapshot using the
   existing atomic installer;
3. update the single-active-deployment registry on GitHub main, superseding the
   previous record;
4. verify the registry/source hash contract;
5. deploy repository main to the live source only after all pre-start gates;
6. run the official launcher exactly once; and
7. accept only a trusted diagnostic with all eleven inbox sources present and
   no errors or warnings attributable to this mismatch.

On any snapshot, registry, startup or acceptance failure, use the retained
snapshot/source rollback records and do not automatically restart or retry.
Deployment does not change WebUI, approve permission prompts, or implement P2.

# OpenCode-specific operating rules

These rules are the environment-specific execution layer for OpenCode.
Use them to apply the shared multi-agent-shogun protocol faithfully within this tool and permission model.

## Overview

- `AGENTS.md` is the shared repo contract and is read automatically.
- Use `skill` for reusable workflows instead of duplicating them in the prompt.

## How to interpret the combined prompt

The generated prompt is assembled from a role definition, shared protocol/task-flow sections, and this environment-specific section.

When deciding what to do, interpret instructions in this order:

1. Role-specific responsibilities and prohibitions
2. Explicit permission boundaries for the current agent
3. Shared protocol and task-flow rules
4. General tool guidance in this file

If multiple sections describe the same topic, prefer the narrower and more role-specific instruction over the broader procedural explanation.

Do not treat repeated shared rules as separate obligations that must all be restated.
Treat repeated text as one shared protocol, then apply the responsibility of the current role.

## Conflict handling for repeated shared rules

The generated prompt may repeat descriptions of inbox handling, escalation, redo flow, delivery flow, report flow, or completion flow.

When that happens:

- do not assume repetition means higher priority
- do not spend a turn re-explaining the whole protocol
- do not expand your role merely because a shared flow mentions the same artifact or step

Instead:

- identify your current role's concrete responsibility
- identify the next concrete action that your role can actually perform
- execute that action with tools, or report a specific blocker

## Ownership and permission interpretation

When a shared artifact, workflow step, or operational duty appears in multiple places:

- prefer the role definition that explicitly assigns responsibility
- prefer the permission boundary when it is narrower than prose
- treat write authority as stronger than incidental mentions inside routing or reporting flow
- do not infer ownership merely from being mentioned in a process description

If an artifact is readable by many roles but writable by only one role, treat that writable role as the owner unless another instruction explicitly overrides it.

If prose and permissions seem to disagree, operate within permissions and continue the task without inventing broader authority.

## Tool usage

Available tools may include `bash`, `read`, `edit`, `write`, `grep`, `glob`, `list`, `apply_patch`, `skill`, `todowrite`, `webfetch`, `websearch`, and `question`.

Tool availability still follows the generated agent permissions.

Use tools in a deliberate order.

For routine inspection and evidence gathering, prefer:

- `read`
- `grep`
- `glob`
- `list`

Use `edit` only after reading the relevant file.

Use `write` only when creating a new file is clearly part of the task and allowed for your role.

Use `bash` only when file tools are insufficient, or when command execution is genuinely needed for validation, testing, building, or command-line-only work.

Do not shell out for work that file tools can perform directly.

Before editing, read enough surrounding context to understand:

- what the file currently says
- what contract or protocol it enforces
- whether the change belongs to your role

## Use skills and specialized agents correctly

- Use `skill` for reusable workflows instead of duplicating them in your response.
- If a task clearly fits a specialized agent definition, prefer that agent instead of stretching the current role.
- Do not compensate for weak role fit by informally taking over another role's job.

## No-pretend rule

- Files, queues, and processes only change via tools (`read`, `write`, `edit`, `apply_patch`, `bash`, etc.), not by narrative.
- If your answer says you "updated" a file, "changed" a status, or "ran" a script, you must have actually invoked the corresponding tool in this turn and it must have completed without error.
- Do not describe fictitious tool calls or state changes.

Once you have indicated that you have started working on a cmd or task, you must not end the turn with "plan only" and zero tool calls.

For any cmd with `status: in_progress` or task with `status: assigned`, each turn must either:

- execute at least one concrete tool call that moves that cmd/task forward, or
- report a specific blocker and state explicitly that there is no progress in this turn

If your role forbids a given operation, do not claim to have done it.
Delegate according to AGENTS.md and describe only what was actually executed.

## Response discipline

Keep response text concise, but do not omit the decision that explains your next action.

In each meaningful response, prefer this shape:

1. current action or decision
2. key result or blocking fact
3. next concrete step

Do not restate the whole shared protocol unless protocol clarification is the task itself.

Do not copy long prompt text back into the conversation when a short task-local explanation is enough.

Prefer tool-backed progress over verbal protocol summaries.

## Role fidelity

Stay within the current role.

Do not take over another role's planning, reporting, ownership, completion judgment, or execution merely because the broader protocol mentions the same artifact or workflow.

If another role owns the next required action:

- report the relevant result
- hand off clearly
- stop extending your scope

Role fidelity is more important than locally convenient overreach.

## Practical fallback for ambiguity

When unsure how to proceed, use this fallback order:

1. prefer the narrower role-specific instruction
2. prefer the explicit permission boundary
3. prefer a concrete action on the currently assigned task
4. prefer handing off over silently expanding your role
5. prefer reporting a real blocker over pretending progress

Maintain the multi-agent-shogun roleplay style, but let operational decisions be driven by responsibility, permissions, and the current task.

## tmux interaction

### TUI mode

- Use `OPENCODE_TUI_CONFIG=... opencode --model provider/model --agent <agent>`.
- Keep the repository-pinned `config/opencode-tui.json` so tmux automation sees stable keybinds.
- `app_exit` is disabled.
- `session_interrupt` is `escape`.
- `input_clear` is `ctrl+c,ctrl+u`.

### Session control

- Use `/new` to start a fresh session.
- Treat model changes as relaunch-only in tmux automation.
- Use `/sessions` and `/models` only when interactive inspection is needed.
- Do not use context-resetting commands casually during active execution.
- Before any reset, ensure that important state has already been written to the required persistent file.

## Notes

- `opencode stats` shows token usage and cost statistics.
- Keep response text concise and reduce verbosity.

# OpenCode CLI Tools

This section describes OpenCode-specific tools and features.

## Overview

OpenCode starts the TUI by default with `opencode`, and can run headless work with `opencode run`.
Each agent loads a pre-built definition from `.opencode/agents/<name>.md` via `--agent`.

- `AGENTS.md` is the shared repo contract and is read automatically.
- Treat `.opencode/agents/<name>.md` as the OpenCode-specific layer on top of that shared contract.
- Use `skill` for reusable workflows instead of duplicating them in the prompt.

## Tool Usage

OpenCode provides built-in tools including `bash`, `read`, `edit`, `write`, `grep`, `glob`, `list`, `apply_patch`, `skill`, `todowrite`, `webfetch`, `websearch`, and `question`.
Tool availability still follows the generated agent permissions.

Guidelines:

1. **Read before edit**: inspect relevant files before changing them.
2. **Use focused tools**: prefer `read`/`grep`/`glob` over shelling out for routine inspection.
3. **Use `skill` for reusable workflows**: load the matching `SKILL.md` when a task maps to an existing skill.
4. **Prefer dedicated agents**: if a task fits a specialized OpenCode agent definition, select that agent instead of stretching the current prompt.

## Custom Instructions

OpenCode reads project instructions from `AGENTS.md` automatically. Additional instruction files can be layered via the `instructions` field in `opencode.json`, but that field is shared across all agents and is not a per-agent override.

## tmux Interaction

### TUI Mode

- Use `OPENCODE_TUI_CONFIG=<tui-config> opencode --model provider/model --agent <agent_id>`.
- Keep the repository-pinned `config/opencode-tui.json` so tmux automation sees stable keybinds.
- `app_exit` is disabled; `session_interrupt` is `escape`; `input_clear` is `ctrl+c,ctrl+u`.

### Session Control

- Use `/new` to start a fresh session.
- Treat model changes as relaunch-only in tmux automation.
- Use `/sessions` and `/models` only when interactive inspection is needed.

## Notes

- `opencode stats` shows token usage and cost statistics.
- Keep your response text concise and reduce verbosity.

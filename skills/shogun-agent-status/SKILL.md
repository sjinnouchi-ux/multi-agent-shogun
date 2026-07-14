---
name: shogun-agent-status
description: Produce a bounded read-only summary of Shogun agent availability. Use when Shogun or Karo needs routing capacity without opening tmux panes or raw operational files.
---

# Shogun agent status

This is a read-only routing aid for Shogun and Karo. It must not assign work, update the dashboard, or mutate queue state.

1. Run the installed [status helper](scripts/agent_status.sh) with no arguments. It is self-contained and works from any current directory.
2. Accept only its JSON Lines records. Every record has exactly `agent_id`, `role`, and `coarse_availability`; availability is one of `available`, `busy`, `offline`, or `unknown`.
3. The helper may read only bounded tmux metadata: the allowlisted `@agent_id`, the pane dead bit, and whether `@current_task` is empty. It never emits the task value.
4. Never pass a caller-selected pane or session. Never capture pane content or read task, report, queue, log, repository, authentication, or environment-selected helper data.
5. Karo may use the summary to route work. Shogun may use it to assess capacity. Other roles should request routing through Karo.

If tmux metadata is unavailable, the helper returns the canonical records with `unknown` availability instead of guessing from processes or files. Ignore any record that does not use the exact schema.

The output is evidence for a current routing decision only. Treat it as stale after any assignment or session restart.

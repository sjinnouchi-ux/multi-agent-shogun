# Handoff Watchdog

The handoff watchdog extends the existing event-driven inbox watcher. It does
not start another LLM agent and does not poll tmux panes in a separate process.

## State machine

1. `awaiting_receipt`: the watcher sent the initial `inboxN` notification.
2. `retry_sent`: the same unread handoff received one retry after 120 seconds.
3. `handoff_stalled`: it is still unread after 300 seconds. No further retry is
   sent. Ashigaru, Gunshi, and Oometsuke stalls produce one alert for Karo.
4. `execution_retry_sent`: an acknowledged `task_assigned` message still has an
   idle `assigned` task after 300 seconds. One resume notification is sent.
5. `execution_stalled`: the accepted task remains idle after 600 seconds. One
   Karo alert is emitted.

While the agent is busy, the same accepted task is projected as
`execution_in_progress` and does not consume either retry allowance.
Before the idle retry threshold is reached it is projected as
`execution_accepted`.

Karo and Shogun stalls never inject input into the Shogun pane. They are exposed
only through `status/handoff_watchdog/{agent}.yaml`, which intentionally omits
message content and is suitable for the management terminal's read-only health
projection.

## Compatibility and controls

Messages keep the existing required fields. The additive `delivery` object is
also created lazily for older messages. The old escalation path remains
available by setting `HANDOFF_WATCHDOG_ENABLED=0`.

Thresholds can be changed without code edits:

- `HANDOFF_RETRY_AFTER` (default `120` seconds)
- `HANDOFF_STALL_AFTER` (default `300` seconds)
- `HANDOFF_TASK_RETRY_AFTER` (default `300` seconds)
- `HANDOFF_TASK_STALL_AFTER` (default `600` seconds)

The watchdog allows one initial notification and one retry. It never performs
an automatic `/clear` or `/new` as a response to a stalled handoff.

#!/usr/bin/env python3
"""Persist inbox delivery receipts and project a content-free watchdog state."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml


SPECIAL_TYPES = {"clear_command", "model_switch", "cli_restart"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbox", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--status-file", required=True)
    parser.add_argument("--task-file")
    parser.add_argument("--report-file")
    parser.add_argument("--now", type=int, default=int(dt.datetime.now().timestamp()))
    parser.add_argument("--retry-after", type=int, default=120)
    parser.add_argument("--stall-after", type=int, default=300)
    parser.add_argument("--task-retry-after", type=int, default=300)
    parser.add_argument("--task-stall-after", type=int, default=600)
    parser.add_argument("--can-notify", choices=("0", "1"), default="1")
    parser.add_argument(
        "--cli-state-at-notify",
        choices=(
            "ready",
            "busy",
            "permission_prompt",
            "login_prompt",
            "shell_prompt",
            "absent",
            "unknown",
        ),
        default="unknown",
    )
    parser.add_argument(
        "--delivery-blocked-reason",
        choices=(
            "none",
            "busy",
            "permission_prompt",
            "login_prompt",
            "shell_prompt",
            "absent",
            "unknown",
        ),
        default="none",
    )
    parser.add_argument(
        "--record-notification", choices=("0", "1"), default="1"
    )
    return parser.parse_args()


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def atomic_dump(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(value, handle, allow_unicode=True, sort_keys=False)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def iso_now(epoch: int) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).astimezone().replace(
        microsecond=0
    ).isoformat()


def to_epoch(value: Any, fallback: int) -> int:
    if not value:
        return fallback
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return int(parsed.timestamp())
    except (TypeError, ValueError):
        return fallback


def delivery_for(message: dict[str, Any]) -> dict[str, Any]:
    delivery = message.get("delivery")
    if not isinstance(delivery, dict):
        delivery = {}
        message["delivery"] = delivery
    delivery.setdefault("created_at", message.get("timestamp"))
    delivery.setdefault("notification_count", 0)
    delivery.setdefault("first_notified_at", None)
    delivery.setdefault("last_notified_at", None)
    delivery.setdefault("acknowledged_at", None)
    delivery.setdefault("stalled_at", None)
    delivery.setdefault("escalation_sent_at", None)
    delivery.setdefault("cli_state_at_notify", None)
    delivery.setdefault("delivery_blocked_reason", None)
    return delivery


def task_finished(report_file: Path | None, task_id: str | None) -> bool:
    if not report_file or not report_file.exists() or not task_id:
        return False
    report = load_yaml(report_file)
    return report.get("task_id") == task_id and report.get("status") in {
        "done",
        "failed",
        "blocked",
    }


def reconcile(args: argparse.Namespace) -> dict[str, Any]:
    inbox_path = Path(args.inbox)
    inbox = load_yaml(inbox_path)
    original_inbox = copy.deepcopy(inbox)
    messages = inbox.get("messages") or []
    if not isinstance(messages, list):
        messages = []
        inbox["messages"] = messages

    now_iso = iso_now(args.now)
    can_notify = args.can_notify == "1"
    record_notification = args.record_notification == "1"
    cli_state_at_notify = args.cli_state_at_notify
    delivery_blocked_reason = (
        None
        if args.delivery_blocked_reason == "none"
        else args.delivery_blocked_reason
    )
    action = "none"
    escalation = False
    unread: list[dict[str, Any]] = []

    for message in messages:
        if not isinstance(message, dict):
            continue
        delivery = delivery_for(message)
        if message.get("read", False):
            if not delivery.get("acknowledged_at"):
                delivery["acknowledged_at"] = now_iso
            continue
        if message.get("type") not in SPECIAL_TYPES:
            unread.append(message)

    for message in unread:
        delivery = delivery_for(message)
        delivery["cli_state_at_notify"] = cli_state_at_notify
        delivery["delivery_blocked_reason"] = delivery_blocked_reason
        created = to_epoch(delivery.get("created_at"), args.now)
        count = int(delivery.get("notification_count") or 0)
        last_notified = to_epoch(delivery.get("last_notified_at"), created)

        if can_notify and count == 0:
            if action == "none":
                action = "notify"
            if record_notification:
                delivery["notification_count"] = 1
                delivery["first_notified_at"] = now_iso
                delivery["last_notified_at"] = now_iso
        elif can_notify and count == 1 and args.now - last_notified >= args.retry_after:
            action = "retry"
            if record_notification:
                delivery["notification_count"] = 2
                delivery["last_notified_at"] = now_iso

        count = int(delivery.get("notification_count") or 0)
        stall_wait = max(1, args.stall_after - args.retry_after)
        last_notified = to_epoch(delivery.get("last_notified_at"), created)
        if count >= 2 and args.now - last_notified >= stall_wait:
            if not delivery.get("stalled_at"):
                delivery["stalled_at"] = now_iso
            if not delivery.get("escalation_sent_at"):
                delivery["escalation_sent_at"] = now_iso
                escalation = True

    task_data: dict[str, Any] = {}
    task_file = Path(args.task_file) if args.task_file else None
    report_file = Path(args.report_file) if args.report_file else None
    if task_file and task_file.exists():
        raw_task = load_yaml(task_file)
        task_data = raw_task.get("task") or raw_task
        if not isinstance(task_data, dict):
            task_data = {}

    task_status = str(task_data.get("status") or "")
    task_id = task_data.get("task_id")
    task_message = next(
        (
            message
            for message in reversed(messages)
            if isinstance(message, dict)
            and message.get("type") == "task_assigned"
            and message.get("read", False)
        ),
        None,
    )
    execution_state = "none"
    if (
        can_notify
        and not unread
        and task_status == "assigned"
        and task_message
        and not task_finished(report_file, task_id)
    ):
        execution_state = "accepted"
        delivery = delivery_for(task_message)
        acknowledged = to_epoch(delivery.get("acknowledged_at"), args.now)
        acknowledged_age = args.now - acknowledged
        if (
            acknowledged_age >= args.task_retry_after
            and not delivery.get("execution_retry_at")
        ):
            action = "task_retry"
            if record_notification:
                delivery["cli_state_at_notify"] = cli_state_at_notify
                delivery["delivery_blocked_reason"] = delivery_blocked_reason
                delivery["execution_retry_at"] = now_iso
                execution_state = "retry_sent"
        elif delivery.get("execution_retry_at"):
            execution_state = "retry_sent"

        execution_retry = to_epoch(delivery.get("execution_retry_at"), args.now)
        execution_stall_wait = max(
            1, args.task_stall_after - args.task_retry_after
        )
        if (
            delivery.get("execution_retry_at")
            and args.now - execution_retry >= execution_stall_wait
            and not delivery.get("execution_stalled_at")
        ):
            delivery["execution_stalled_at"] = now_iso
            if not delivery.get("execution_escalation_sent_at"):
                delivery["execution_escalation_sent_at"] = now_iso
                escalation = True
            execution_state = "stalled"
        elif delivery.get("execution_stalled_at"):
            execution_state = "stalled"
    elif (
        not unread
        and task_status == "assigned"
        and task_message
        and not task_finished(report_file, task_id)
    ):
        execution_state = "in_progress"
        delivery = delivery_for(task_message)
        acknowledged = to_epoch(delivery.get("acknowledged_at"), args.now)
        acknowledged_age = args.now - acknowledged
        if (
            acknowledged_age >= args.task_retry_after
            and not delivery.get("execution_retry_at")
        ):
            delivery["cli_state_at_notify"] = cli_state_at_notify
            delivery["delivery_blocked_reason"] = delivery_blocked_reason

    inbox["messages"] = messages
    if inbox != original_inbox:
        atomic_dump(inbox_path, inbox)

    oldest = min(
        unread,
        key=lambda item: to_epoch(delivery_for(item).get("created_at"), args.now),
        default=None,
    )
    oldest_delivery = delivery_for(oldest) if oldest else {}
    oldest_age = (
        args.now
        - to_epoch(oldest_delivery.get("created_at"), args.now)
        if oldest
        else 0
    )

    if any(delivery_for(message).get("stalled_at") for message in unread):
        state = "handoff_stalled"
    elif execution_state == "stalled":
        state = "execution_stalled"
    elif execution_state == "retry_sent":
        state = "execution_retry_sent"
    elif execution_state == "in_progress":
        state = "execution_in_progress"
    elif execution_state == "accepted":
        state = "execution_accepted"
    elif any(
        int(delivery_for(message).get("notification_count") or 0) >= 2
        for message in unread
    ):
        state = "retry_sent"
    elif unread:
        state = "awaiting_receipt"
    else:
        state = "healthy"

    projection: dict[str, Any] = {
        "agent_id": args.agent,
        "state": state,
        "updated_at": now_iso,
        "unread_count": len(unread),
        "cli_state_at_notify": cli_state_at_notify,
        "delivery_blocked_reason": delivery_blocked_reason,
    }
    if oldest:
        projection["oldest_unread"] = {
            "message_id": oldest.get("id"),
            "message_type": oldest.get("type"),
            "age_sec": oldest_age,
            "notification_count": int(
                oldest_delivery.get("notification_count") or 0
            ),
        }
    if task_id:
        projection["task"] = {
            "task_id": task_id,
            "status": task_status,
            "handoff_state": execution_state,
        }
    atomic_dump(Path(args.status_file), projection)

    return {
        "action": action,
        "escalate": escalation,
        "state": state,
        "unread_count": len(unread),
        "age_sec": oldest_age,
        "message_type": oldest.get("type") if oldest else "",
        "task_id": task_id or "",
    }


def main() -> int:
    print(json.dumps(reconcile(parse_args()), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

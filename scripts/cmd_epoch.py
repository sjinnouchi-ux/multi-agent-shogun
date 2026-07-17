#!/usr/bin/env python3
"""Generate and compare the optional formal command epoch.

New records use ``cmd`` as an immutable command identifier and pair it with
``task_id`` for task-scoped messages.  Missing ``cmd`` remains a supported
legacy format; once both sides are formal, comparison is fail-closed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import yaml


CMD_TOKEN = re.compile(r"^cmd_[A-Za-z0-9][A-Za-z0-9._:-]*$")
NUMERIC_CMD = re.compile(r"^cmd_(\d+)$")
TASK_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
COMPARE_STATES = {"match", "stale", "legacy", "invalid"}


def load_yaml(path: Path) -> Any:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def unwrap_task(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    task = value.get("task")
    return task if isinstance(task, dict) else value


def valid_cmd(value: Any) -> bool:
    return isinstance(value, str) and CMD_TOKEN.fullmatch(value) is not None


def valid_task_id(value: Any) -> bool:
    return isinstance(value, str) and TASK_TOKEN.fullmatch(value) is not None


def compare_identity(task: dict[str, Any], message: dict[str, Any]) -> str:
    """Compare formal ``cmd`` + ``task_id`` identities.

    Legacy compatibility is selected by the current task, not by the incoming
    message.  Once a task declares a formal epoch, an identity-less message is
    stale and malformed formal data is invalid rather than legacy.
    """

    task_cmd = task.get("cmd")
    message_cmd = message.get("cmd")
    if task_cmd not in (None, "") and not valid_cmd(task_cmd):
        return "invalid"
    if message_cmd not in (None, "") and not valid_cmd(message_cmd):
        return "invalid"
    if task_cmd in (None, ""):
        return "legacy"
    if message_cmd in (None, ""):
        return "stale"

    task_id = task.get("task_id")
    message_task_id = message.get("task_id")
    if not valid_task_id(task_id) or not valid_task_id(message_task_id):
        return "invalid"
    if task_cmd == message_cmd and task_id == message_task_id:
        return "match"
    return "stale"


def iter_command_values(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"id", "cmd"} and isinstance(child, str):
                yield child
            else:
                yield from iter_command_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_command_values(child)


def next_command_id(paths: Iterable[Path]) -> str:
    highest = 0
    for path in paths:
        try:
            document = load_yaml(path)
        except (OSError, yaml.YAMLError):
            print("cmd_epoch: ignored unreadable command source", file=sys.stderr)
            continue
        for value in iter_command_values(document):
            match = NUMERIC_CMD.fullmatch(value)
            if match:
                highest = max(highest, int(match.group(1)))
    return f"cmd_{highest + 1:03d}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)

    next_parser = subparsers.add_parser("next")
    next_parser.add_argument("sources", nargs="+", type=Path)

    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--task-file", required=True, type=Path)
    compare_parser.add_argument("--cmd", default="")
    compare_parser.add_argument("--task-id", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.action == "next":
        print(next_command_id(args.sources))
        return 0

    try:
        task = unwrap_task(load_yaml(args.task_file))
        if not task and args.cmd:
            state = "invalid"
        else:
            state = compare_identity(
                task,
                {"cmd": args.cmd or None, "task_id": args.task_id or None},
            )
    except (OSError, yaml.YAMLError):
        state = "invalid"
        print("cmd_epoch: unreadable task identity", file=sys.stderr)
    assert state in COMPARE_STATES
    print(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

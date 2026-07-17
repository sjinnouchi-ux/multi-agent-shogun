#!/usr/bin/env bash
# Verify that terminal commands have no work left eligible for execution.

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QUEUE_DIR="${SHOGUN_QUEUE_DIR:-${SCRIPT_DIR}/../queue}"
PYTHON_BIN="${SHOGUN_PYTHON_BIN:-${SCRIPT_DIR}/../.venv/bin/python3}"
CLOSING_CMD=""

sanitized_failure() {
    printf '%s\n' "cmd_closure: blocked open=0 invalid=1 legacy=0"
    exit 1
}

if [ "$#" -eq 2 ] && [ "$1" = "--closing-cmd" ]; then
    CLOSING_CMD="$2"
elif [ "$#" -ne 0 ]; then
    sanitized_failure
fi

if [[ "$PYTHON_BIN" == */* ]]; then
    [ -x "$PYTHON_BIN" ] || sanitized_failure
else
    command -v "$PYTHON_BIN" >/dev/null 2>&1 || sanitized_failure
fi

"$PYTHON_BIN" -c 'import yaml' >/dev/null 2>&1 || sanitized_failure

"$PYTHON_BIN" - "$QUEUE_DIR" "$CLOSING_CMD" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml


CMD_TOKEN = re.compile(r"^cmd_[A-Za-z0-9][A-Za-z0-9._:-]*$")
TASK_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
COMMAND_ACTIVE = {"pending", "in_progress"}
COMMAND_TERMINAL = {"done", "cancelled", "paused"}
TASK_ACTIVE = {"assigned", "blocked", "pending_blocked"}
TASK_TERMINAL = {"done", "failed"}


def valid_token(pattern: re.Pattern[str], value: Any) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def load_document(path: Path, *, required: bool) -> tuple[Any, int]:
    if not path.is_file():
        return ({}, 1) if required else ({}, 0)
    try:
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}, 0
    except (OSError, UnicodeError, yaml.YAMLError):
        return {}, 1


def collect_command_records(document: Any) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    invalid = 0
    if isinstance(document, list):
        for value in document:
            if isinstance(value, dict):
                records.append(value)
            else:
                invalid += 1
        return records, invalid
    if not isinstance(document, dict):
        return records, 1
    if not document:
        return records, 0

    found_container = False
    for key in ("commands", "queue", "archive"):
        if key not in document:
            continue
        found_container = True
        values = document[key]
        if not isinstance(values, list):
            invalid += 1
            continue
        for value in values:
            if isinstance(value, dict):
                records.append(value)
            else:
                invalid += 1
    if not found_container:
        invalid += 1
    return records, invalid


def collect_task_records(document: Any) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    invalid = 0

    def visit(value: Any) -> None:
        nonlocal invalid
        if isinstance(value, list):
            for child in value:
                visit(child)
            return
        if not isinstance(value, dict):
            invalid += 1
            return
        if not value:
            return

        if "task" in value:
            nested = value["task"]
            if isinstance(nested, dict):
                visit(nested)
            else:
                invalid += 1
            return

        if "status" in value and any(
            key in value for key in ("task_id", "cmd", "parent_cmd", "worker_id")
        ):
            records.append(value)
            return

        found_container = False
        for key in ("tasks", "pending_tasks", "pending", "queue", "items"):
            if key in value:
                found_container = True
                visit(value[key])
        if not found_container:
            invalid += 1

    visit(document)
    return records, invalid


def main() -> int:
    queue_dir = Path(sys.argv[1])
    closing_cmd = sys.argv[2]
    invalid = 0
    legacy = 0
    checked = 0
    open_count = 0

    active_doc, load_errors = load_document(
        queue_dir / "shogun_to_karo.yaml", required=True
    )
    invalid += load_errors
    archive_doc, load_errors = load_document(
        queue_dir / "shogun_to_karo_archive.yaml", required=False
    )
    invalid += load_errors

    active_commands: set[str] = set()
    terminal_commands: set[str] = set()
    known_commands: set[str] = set()

    active_records, schema_errors = collect_command_records(active_doc)
    invalid += schema_errors
    archive_records, schema_errors = collect_command_records(archive_doc)
    invalid += schema_errors

    timestamped_archive_dir = queue_dir / "archive"
    if timestamped_archive_dir.is_dir():
        for archive_path in sorted(
            timestamped_archive_dir.glob("shogun_to_karo_*.yaml")
        ):
            document, load_errors = load_document(archive_path, required=True)
            invalid += load_errors
            if load_errors:
                continue
            records, schema_errors = collect_command_records(document)
            invalid += schema_errors
            archive_records.extend(records)

    for record in active_records + archive_records:
        raw_cmd = record.get("cmd")
        raw_id = record.get("id")
        if raw_cmd not in (None, ""):
            if not valid_token(CMD_TOKEN, raw_cmd):
                invalid += 1
                continue
            if raw_id not in (None, "") and raw_id != raw_cmd:
                invalid += 1
                continue
            command_id = raw_cmd
        else:
            if not valid_token(CMD_TOKEN, raw_id):
                invalid += 1
                continue
            command_id = raw_id

        status = str(record.get("status", ""))
        known_commands.add(command_id)
        if status in COMMAND_TERMINAL:
            terminal_commands.add(command_id)
        elif status in COMMAND_ACTIVE:
            active_commands.add(command_id)
        else:
            invalid += 1

    if closing_cmd:
        if not valid_token(CMD_TOKEN, closing_cmd) or closing_cmd not in known_commands:
            invalid += 1
        else:
            terminal_commands.add(closing_cmd)
            active_commands.discard(closing_cmd)

    tasks_dir = queue_dir / "tasks"
    task_files = sorted(tasks_dir.glob("*.yaml")) if tasks_dir.is_dir() else []
    for task_file in task_files:
        document, load_errors = load_document(task_file, required=True)
        invalid += load_errors
        if load_errors:
            continue
        records, schema_errors = collect_task_records(document)
        invalid += schema_errors
        for record in records:
            status = str(record.get("status", ""))
            task_id = record.get("task_id")
            raw_cmd = record.get("cmd")
            parent_cmd = record.get("parent_cmd")

            if status == "idle" and task_id in (None, ""):
                continue
            checked += 1
            if status not in TASK_ACTIVE and status not in TASK_TERMINAL:
                invalid += 1
                continue

            if raw_cmd not in (None, ""):
                if not valid_token(CMD_TOKEN, raw_cmd) or not valid_token(
                    TASK_TOKEN, task_id
                ):
                    invalid += 1
                    continue
                if parent_cmd not in (None, "") and parent_cmd != raw_cmd:
                    invalid += 1
                    continue
                command_id = raw_cmd
                if command_id not in known_commands:
                    invalid += 1
                    continue
            else:
                legacy += 1
                if parent_cmd in (None, ""):
                    command_id = ""
                elif valid_token(CMD_TOKEN, parent_cmd):
                    command_id = parent_cmd
                else:
                    invalid += 1
                    continue

            if command_id in terminal_commands and status in TASK_ACTIVE:
                open_count += 1

    if open_count or invalid:
        print(
            f"cmd_closure: blocked open={open_count} "
            f"invalid={invalid} legacy={legacy}"
        )
        return 1
    print(f"cmd_closure: ok checked={checked} legacy={legacy}")
    return 0


try:
    raise SystemExit(main())
except SystemExit:
    raise
except Exception:
    print("cmd_closure: blocked open=0 invalid=1 legacy=0")
    raise SystemExit(1)
PY

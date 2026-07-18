#!/usr/bin/env python3
"""Validate Claude Hook command safety constraints."""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from typing import Any, Iterator


def iter_hooks(settings: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        return
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        for entry_index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            nested = entry.get("hooks", [])
            if not isinstance(nested, list):
                continue
            for hook_index, hook in enumerate(nested):
                if isinstance(hook, dict):
                    yield f"{event}[{entry_index}].hooks[{hook_index}]", hook


def validate(path: Path) -> list[str]:
    try:
        with path.open(encoding="utf-8") as handle:
            settings = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return ["invalid_json"]

    if not isinstance(settings, dict):
        return ["invalid_json"]

    errors: list[str] = []
    for location, hook in iter_hooks(settings):
        if "args" in hook:
            errors.append(f"args_forbidden:{location}")
        command = hook.get("command")
        if isinstance(command, str) and uses_bare_relative_script(command):
            errors.append(f"bare_relative_path:{location}")
    return errors


def uses_bare_relative_script(command: str) -> bool:
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    return any(word.startswith(("scripts/", "./scripts/")) for word in words)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: lint_hook_settings.py SETTINGS_JSON", file=sys.stderr)
        return 2
    errors = validate(Path(argv[1]))
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

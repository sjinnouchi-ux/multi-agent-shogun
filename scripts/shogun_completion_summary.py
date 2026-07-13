#!/usr/bin/env python3
"""Create a sanitized GitHub-boundary completion summary for a Shogun task."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


class SummaryError(RuntimeError):
    """Expected repository or input validation failure."""


def git(repo: Path, *args: str) -> str:
    try:
        process = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise SummaryError(f"git {' '.join(args)} failed: {exc}") from exc
    return process.stdout.strip()


def scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--project", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--repo-url")
    parser.add_argument("--source", default="shogun", choices=("shogun", "codex"))
    parser.add_argument("--verification", action="append", default=[])
    parser.add_argument("--risk", action="append", default=[])
    parser.add_argument("--pr-url", default="none")
    parser.add_argument("--drive-url", default="none")
    parser.add_argument("--report-url", default="none")
    parser.add_argument("--summary", default="")
    parser.add_argument(
        "--review-status",
        default="none",
        choices=("none", "approved", "passed", "completed"),
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def build_summary(args: argparse.Namespace) -> str:
    repo = args.repo.resolve(strict=True)
    git(repo, "rev-parse", "--git-dir")
    dirty = git(repo, "status", "--porcelain")
    if dirty:
        raise SummaryError("repository has uncommitted or untracked changes")

    branch = git(repo, "branch", "--show-current")
    if not branch:
        raise SummaryError("detached HEAD is not allowed")
    head = git(repo, "rev-parse", "HEAD")
    base = git(repo, "rev-parse", "--verify", f"{args.base_commit}^{{commit}}")
    try:
        git(repo, "merge-base", "--is-ancestor", base, head)
    except SummaryError as exc:
        raise SummaryError("base commit is not an ancestor of result commit") from exc

    repo_url = args.repo_url or git(repo, "remote", "get-url", "origin")
    changed = git(repo, "diff", "--name-only", f"{base}..{head}").splitlines()
    verification = args.verification or ["none"]
    risks = args.risk or ["none"]

    lines = [
        "---",
        f"project: {scalar(args.project)}",
        f"source: {scalar(args.source)}",
        f"task_id: {scalar(args.task_id)}",
        f"repository_url: {scalar(repo_url)}",
        f"working_branch: {scalar(branch)}",
        f"base_commit: {scalar(base)}",
        f"result_commit: {scalar(head)}",
        f"pr_url: {scalar(args.pr_url)}",
        f"drive_url: {scalar(args.drive_url)}",
        f"report_url: {scalar(args.report_url)}",
        f"summary: {scalar(args.summary)}",
        f"review_status: {scalar(args.review_status)}",
        "---",
        "",
        "# Shogun Completion Summary",
        "",
        "## Changed Files",
        "",
    ]
    lines.extend(f"- `{path}`" for path in changed)
    if not changed:
        lines.append("- none")
    lines.extend(["", "## Verification", ""])
    lines.extend(f"- {item}" for item in verification)
    lines.extend(["", "## Remaining Risks", ""])
    lines.extend(f"- {item}" for item in risks)
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    try:
        output = build_summary(args)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
        else:
            print(output, end="")
        return 0
    except (SummaryError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

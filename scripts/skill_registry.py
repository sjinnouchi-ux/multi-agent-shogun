#!/usr/bin/env python3
"""Validate, render, and lock the Shogun cross-CLI skill registry."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import tarfile
import unicodedata
from io import BytesIO
import uuid
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote

import yaml


SCHEMA_VERSION = 1
GENERATOR_NAME = "shogun-skill-registry"
GENERATOR_VERSION = 1
SKILL_ID_RE = re.compile(r"^(?=.{1,64}$)[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_STATUSES = {"enabled", "disabled", "quarantined", "revoked"}
ALLOWED_TARGETS = {"claude", "codex"}
ALLOWED_ACTIVATION = {"automatic", "manual"}
ALLOWED_CLASSIFICATION = {"required", "optional"}
ALLOWED_ROLES = {"shogun", "karo", "ashigaru", "gunshi", "oometsuke"}
ALLOWED_DISPOSITIONS = {"codex-only", "adapted", "excluded", "pending"}
PORTABLE_FRONTMATTER = {"name", "description"}
TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".py", ".sh"}
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
MARKDOWN_REFERENCE_DEFINITION_RE = re.compile(
    r"(?m)^[ \t]{0,3}\[[^\]\n]+\]:[ \t]*(?:<([^>\n]+)>|(\S+))"
)
MARKDOWN_HTML_REFERENCE_RE = re.compile(
    r"(?i)\b(?:href|src)\s*=\s*(?:\"([^\"\n]+)\"|'([^'\n]+)')"
)
NON_POSIX_MACHINE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9:])(?:[A-Za-z]:[\\/]|\\\\|~[/\\])"
)
# Shared prose may name an explicit public web URL or a portable, uppercase
# environment-variable root.  Scrub only those narrow forms before looking for
# POSIX paths; relative Markdown targets are handled separately below.
PUBLIC_WEB_URL_RE = re.compile(r"(?i)\bhttps?://[^\s<>()`]+")
PORTABLE_VARIABLE_PATH_RE = re.compile(
    r"\$(?:[A-Z_][A-Z0-9_]*|\{[A-Z_][A-Z0-9_]*\})(?:/[A-Za-z0-9._~+-]+)+"
)
ABSOLUTE_POSIX_PATH_RE = re.compile(
    r'''(?<![A-Za-z0-9_./~<])/+(?=[^\s/\\<>`"'()\[\]{}])'''
)
BARE_REPOSITORY_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:scripts|skills)/[A-Za-z0-9_.\-/]+\.(?:sh|py|ya?ml)\b"
)
MARKER_NAME = ".shogun-skill.json"
MARKER_OWNER = "multi-agent-shogun"
JOURNAL_SCHEMA_VERSION = 2
TRANSACTION_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{12}Z-[0-9a-f]{8}$")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
JOURNAL_STATUSES = {
    "prepared",
    "applying",
    "applied",
    "compensating",
    "compensating_cleanup",
    "compensated",
    "compensation_failed",
    "rollback_preparing",
    "rolling_back",
    "rollback_compensating_cleanup",
    "rollback_cleanup",
    "rolled_back",
    "rollback_failed",
}
OPERATION_STATES = {
    "planned",
    "backup_complete",
    "mutation_started",
    "destination_committed",
    "applied",
    "compensating",
    "compensated",
    "rollback_started",
    "rolled_back",
}
PLACEHOLDER_PATTERNS = (
    (re.compile(r"\$ARGUMENTS\b"), "$ARGUMENTS"),
    (re.compile(r"\$[0-9]\b"), "positional Claude placeholder"),
    (re.compile(r"\$\{CLAUDE_[A-Za-z0-9_]*\}"), "${CLAUDE_*}"),
    (re.compile(r"!`[^`]+`"), "Claude command preprocessing"),
)


class RegistryError(RuntimeError):
    """Expected fail-closed registry validation or drift error."""


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def construct_unique_mapping(
    loader: UniqueKeyLoader, node: yaml.nodes.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_unique_mapping
)


def fail(message: str) -> None:
    raise RegistryError(message)


def parse_semver(value: str) -> tuple[tuple[int, int, int], tuple[tuple[int, Any], ...] | None]:
    """Parse the precedence-bearing portion of SemVer 2.0.0."""

    match = SEMVER_RE.fullmatch(value)
    if match is None:
        fail(f"version is not semantic: {value}")
    core = tuple(int(part) for part in match.group(0).split("+", 1)[0].split("-", 1)[0].split("."))
    without_build = value.split("+", 1)[0]
    if "-" not in without_build:
        return core, None
    identifiers: list[tuple[int, Any]] = []
    for identifier in without_build.split("-", 1)[1].split("."):
        if identifier.isdigit():
            if len(identifier) > 1 and identifier.startswith("0"):
                fail(f"numeric prerelease identifiers must not have leading zeroes: {value}")
            identifiers.append((0, int(identifier)))
        else:
            identifiers.append((1, identifier))
    return core, tuple(identifiers)


def compare_semver(left: str, right: str) -> int:
    left_core, left_pre = parse_semver(left)
    right_core, right_pre = parse_semver(right)
    if left_core != right_core:
        return 1 if left_core > right_core else -1
    if left_pre is None or right_pre is None:
        if left_pre is right_pre:
            return 0
        return 1 if left_pre is None else -1
    for left_part, right_part in zip(left_pre, right_pre):
        if left_part == right_part:
            continue
        if left_part[0] != right_part[0]:
            return -1 if left_part[0] == 0 else 1
        return 1 if left_part[1] > right_part[1] else -1
    if len(left_pre) == len(right_pre):
        return 0
    return 1 if len(left_pre) > len(right_pre) else -1


def require_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{context} must be a mapping")
    return value


def require_list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        fail(f"{context} must be a list")
    return value


def require_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{context} must be a non-empty string")
    return value


def require_keys(
    value: dict[str, Any],
    *,
    allowed: set[str],
    required: set[str],
    context: str,
) -> None:
    unknown = sorted(set(value) - allowed)
    missing = sorted(required - set(value))
    if unknown:
        fail(f"{context} has unknown field(s): {', '.join(unknown)}")
    if missing:
        fail(f"{context} is missing required field(s): {', '.join(missing)}")


def read_yaml_with_raw(path: Path, context: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw_bytes = normalized_bytes(path)
    except FileNotFoundError as exc:
        raise RegistryError(f"{context} not found: {path.name}") from exc
    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RegistryError(f"invalid UTF-8 in {context}: {path.name}") from exc
    try:
        loaded = yaml.load(raw, Loader=UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise RegistryError(f"invalid YAML in {context}: {exc}") from exc
    return require_mapping(loaded, context), raw_bytes


def read_yaml(path: Path, context: str) -> dict[str, Any]:
    data, _raw = read_yaml_with_raw(path, context)
    return data


def normalized_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    if b"\r" in raw and path.suffix.lower() in TEXT_SUFFIXES:
        fail(f"text file must use LF line endings: {path.name}")
    return raw


def safe_source_path(registry_dir: Path, source: str, skill_id: str) -> Path:
    if "\\" in source:
        fail(f"skill {skill_id} source must use POSIX path separators")
    pure = PurePosixPath(source)
    if pure.is_absolute() or source != skill_id or any(part in {"", ".", ".."} for part in pure.parts):
        fail(f"skill {skill_id} source path is invalid: {source}")
    candidate = registry_dir.joinpath(*pure.parts)
    try:
        resolved_parent = candidate.parent.resolve(strict=True)
        registry_resolved = registry_dir.resolve(strict=True)
    except FileNotFoundError as exc:
        raise RegistryError(f"skill {skill_id} source not found: {source}") from exc
    if resolved_parent != registry_resolved:
        fail(f"skill {skill_id} source escapes the skills directory")
    if not candidate.is_dir() or candidate.is_symlink():
        fail(f"skill {skill_id} source must be a real directory")
    return candidate


def parse_frontmatter(skill_file: Path) -> tuple[dict[str, Any], bytes, bytes]:
    raw = normalized_bytes(skill_file)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RegistryError(f"SKILL.md is not valid UTF-8: {skill_file.parent.name}") from exc
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\n") != "---":
        fail(f"SKILL.md frontmatter is missing for {skill_file.parent.name}")
    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.rstrip("\n") == "---":
            end_index = index
            break
    if end_index is None:
        fail(f"SKILL.md frontmatter is not closed for {skill_file.parent.name}")
    frontmatter_text = "".join(lines[1:end_index])
    try:
        frontmatter = yaml.load(frontmatter_text, Loader=UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise RegistryError(
            f"invalid YAML frontmatter in {skill_file.parent.name}/SKILL.md: {exc}"
        ) from exc
    frontmatter = require_mapping(frontmatter, f"{skill_file.parent.name} frontmatter")
    body = "".join(lines[end_index + 1 :]).encode("utf-8")
    return frontmatter, body, raw


def markdown_targets(text: str) -> list[str]:
    targets = [match.group(1) for match in MARKDOWN_LINK_RE.finditer(text)]
    targets.extend(
        match.group(1) or match.group(2)
        for match in MARKDOWN_REFERENCE_DEFINITION_RE.finditer(text)
    )
    targets.extend(
        match.group(1) or match.group(2)
        for match in MARKDOWN_HTML_REFERENCE_RE.finditer(text)
    )
    return targets


def validate_markdown(
    skill_id: str, source_dir: Path, markdown_path: Path, text: str
) -> set[str]:
    relative_markdown = markdown_path.relative_to(source_dir).as_posix()
    local_references: set[str] = set()
    for pattern, label in PLACEHOLDER_PATTERNS:
        if pattern.search(text):
            fail(
                f"skill {skill_id} shared Markdown {relative_markdown} "
                f"contains forbidden placeholder: {label}"
            )
    scrubbed = MARKDOWN_LINK_RE.sub("", text)
    scrubbed = MARKDOWN_REFERENCE_DEFINITION_RE.sub("", scrubbed)
    scrubbed = MARKDOWN_HTML_REFERENCE_RE.sub("", scrubbed)
    if NON_POSIX_MACHINE_PATH_RE.search(scrubbed):
        fail(
            f"skill {skill_id} shared Markdown {relative_markdown} contains a "
            "machine-specific absolute path"
        )
    portable_scrubbed = PUBLIC_WEB_URL_RE.sub("", scrubbed)
    portable_scrubbed = PORTABLE_VARIABLE_PATH_RE.sub("", portable_scrubbed)
    if ABSOLUTE_POSIX_PATH_RE.search(portable_scrubbed):
        fail(
            f"skill {skill_id} shared Markdown {relative_markdown} contains an "
            "absolute POSIX path and is not self-contained"
        )
    if BARE_REPOSITORY_PATH_RE.search(scrubbed):
        fail(
            f"skill {skill_id} shared Markdown {relative_markdown} contains a bare "
            "repository path and is not self-contained"
        )
    for raw_target in markdown_targets(text):
        stripped = raw_target.strip()
        if stripped.startswith("<") and ">" in stripped:
            target_text = stripped[1 : stripped.index(">")]
        else:
            target_text = stripped.split(maxsplit=1)[0]
        target = unquote(target_text)
        target = target.split("#", 1)[0]
        if not target or target.startswith(("http://", "https://", "mailto:", "data:")):
            continue
        pure = PurePosixPath(target)
        if pure.is_absolute() or "\\" in target or ".." in pure.parts:
            fail(
                f"skill {skill_id} Markdown {relative_markdown} has escaping "
                f"relative reference: {target}"
            )
        candidate = markdown_path.parent.joinpath(*pure.parts)
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as exc:
            raise RegistryError(
                f"skill {skill_id} Markdown {relative_markdown} missing relative "
                f"reference: {target}"
            ) from exc
        try:
            relative_target = resolved.relative_to(source_dir.resolve(strict=True))
        except ValueError as exc:
            raise RegistryError(f"skill {skill_id} reference escapes source: {target}") from exc
        local_references.add(relative_target.as_posix())
    return local_references


def filesystem_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def has_git_metadata(path: Path) -> bool:
    current = path.resolve(strict=True)
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return True
    return False


def run_git(arguments: list[str], *, cwd: Path, context: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(cwd), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RegistryError(f"Git failed while {context}") from exc


def git_mode(path: Path, registry_dir: Path) -> tuple[bool, bool]:
    """Return the authoritative executable mode, failing closed inside Git."""

    candidate_root = registry_dir.parent.resolve(strict=True)
    probe = run_git(
        ["rev-parse", "--is-inside-work-tree"],
        cwd=candidate_root,
        context="detecting the repository",
    )
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        if has_git_metadata(candidate_root):
            fail("Git repository metadata could not be read")
        return filesystem_executable(path), False

    top_result = run_git(
        ["rev-parse", "--show-toplevel"],
        cwd=candidate_root,
        context="locating the repository root",
    )
    if top_result.returncode != 0 or not top_result.stdout.strip():
        fail("Git repository root could not be determined")
    try:
        top_path = Path(top_result.stdout.strip()).resolve(strict=True)
        relative = path.resolve(strict=True).relative_to(top_path).as_posix()
    except (FileNotFoundError, ValueError) as exc:
        raise RegistryError("skill asset is outside the detected Git repository") from exc

    result = run_git(
        ["ls-files", "--stage", "--", relative],
        cwd=top_path,
        context=f"reading the Git index for {relative}",
    )
    if result.returncode != 0:
        fail(f"Git index could not be read for {relative}")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if len(lines) > 1:
        fail(f"Git index has unresolved entries for {relative}")
    if lines:
        mode = lines[0].split(maxsplit=1)[0]
        if mode not in {"100644", "100755"}:
            fail(f"Git index has unsupported mode {mode} for {relative}")
        return mode == "100755", True
    if filesystem_executable(path):
        fail(f"untracked executable asset cannot be locked: {relative}")
    return False, False


def uses_reserved_marker_path(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    if not parts:
        return False
    return unicodedata.normalize("NFC", parts[0]).casefold() == unicodedata.normalize(
        "NFC", MARKER_NAME
    ).casefold()


def portable_path_parts(relative: str) -> tuple[str, ...]:
    return tuple(
        unicodedata.normalize("NFC", part).casefold()
        for part in PurePosixPath(relative).parts
    )


def validate_portable_file_inventory(paths: list[str], context: str) -> None:
    nodes: dict[tuple[str, ...], tuple[tuple[str, ...], str, str]] = {}
    for path in paths:
        if path != unicodedata.normalize("NFC", path):
            fail(f"{context} path must use Unicode NFC normalization: {path}")
        raw_parts = PurePosixPath(path).parts
        key_parts = portable_path_parts(path)
        for depth in range(1, len(key_parts) + 1):
            key = key_parts[:depth]
            raw = raw_parts[:depth]
            kind = "file" if depth == len(key_parts) else "directory"
            previous = nodes.get(key)
            if previous is None:
                nodes[key] = (raw, kind, path)
                continue
            previous_raw, previous_kind, previous_path = previous
            if previous_raw != raw:
                fail(
                    f"{context} has a portable path alias collision: "
                    f"{previous_path} and {path}"
                )
            if previous_kind != kind:
                fail(
                    f"{context} has a portable file-directory ancestor collision: "
                    f"{previous_path} and {path}"
                )
            if kind == "file":
                fail(
                    f"{context} has a portable path collision: "
                    f"{previous_path} and {path}"
                )


def scan_source_files(source_dir: Path, registry_dir: Path) -> dict[str, tuple[bytes, bool]]:
    ensure_no_nested_mounts(source_dir, f"skill {source_dir.name}")
    files: dict[str, tuple[bytes, bool]] = {}
    for root, dirnames, filenames in os.walk(source_dir, followlinks=False):
        root_path = Path(root)
        for dirname in list(dirnames):
            path = root_path / dirname
            if path.is_symlink():
                fail(f"symlink is forbidden in skill {source_dir.name}: {path.name}")
            if dirname == "__pycache__":
                dirnames.remove(dirname)
                continue
            relative = path.relative_to(source_dir).as_posix()
            if uses_reserved_marker_path(relative):
                fail(
                    f"skill {source_dir.name} must not contain reserved ownership marker "
                    f"{MARKER_NAME}"
                )
        for filename in filenames:
            path = root_path / filename
            if path.is_symlink():
                fail(f"symlink is forbidden in skill {source_dir.name}: {path.name}")
            if not path.is_file():
                fail(f"special file is forbidden in skill {source_dir.name}: {path.name}")
            relative = path.relative_to(source_dir).as_posix()
            if relative == "agents/openai.yaml":
                fail(f"skill {source_dir.name} must not contain generated agents/openai.yaml")
            if uses_reserved_marker_path(relative):
                fail(
                    f"skill {source_dir.name} must not contain reserved ownership marker "
                    f"{MARKER_NAME}"
                )
            raw = normalized_bytes(path)
            executable, _tracked = git_mode(path, registry_dir)
            files[relative] = (raw, executable)
    validate_portable_file_inventory(
        list(files), f"skill {source_dir.name} source inventory"
    )
    return dict(sorted(files.items()))


def validate_distribution(
    skill_id: str,
    value: Any,
    files: dict[str, tuple[bytes, bool]],
) -> set[str]:
    if value is None:
        return set()
    data = require_mapping(value, f"skill {skill_id} distribution")
    require_keys(
        data,
        allowed={"exclude"},
        required={"exclude"},
        context=f"skill {skill_id} distribution",
    )
    excluded = require_list(data["exclude"], f"skill {skill_id} distribution.exclude")
    seen: set[tuple[str, ...]] = set()
    result: set[str] = set()
    protected_roots = {
        portable_path_parts("SKILL.md"),
        portable_path_parts("LICENSE"),
        portable_path_parts("NOTICE"),
        portable_path_parts("COPYING"),
    }
    for index, item in enumerate(excluded):
        relative = require_string(item, f"skill {skill_id} distribution.exclude[{index}]")
        pure = PurePosixPath(relative)
        if (
            relative != unicodedata.normalize("NFC", relative)
            or pure.is_absolute()
            or "\\" in relative
            or any(character in relative for character in "*?[]")
            or not pure.parts
            or any(part in {"", ".", ".."} for part in pure.parts)
            or pure.as_posix() != relative
        ):
            fail(
                f"skill {skill_id} distribution exclusion must be an exact "
                f"normalized relative POSIX file without glob syntax: {relative}"
            )
        key = portable_path_parts(relative)
        if key in seen:
            fail(f"skill {skill_id} distribution has a duplicate exclusion: {relative}")
        seen.add(key)
        if key in protected_roots:
            fail(f"skill {skill_id} distribution cannot exclude protected file {relative}")
        if relative not in files:
            fail(
                f"skill {skill_id} distribution exclusion is not an exact source file: "
                f"{relative}"
            )
        result.add(relative)
    return result


def validate_claude_metadata(skill_id: str, value: Any, targets: set[str]) -> dict[str, Any]:
    if value is None:
        return {}
    if "claude" not in targets:
        fail(f"skill {skill_id} has claude metadata without a claude target")
    data = require_mapping(value, f"skill {skill_id} claude metadata")
    require_keys(
        data,
        allowed={"argument_hint"},
        required=set(),
        context=f"skill {skill_id} claude metadata",
    )
    if "argument_hint" in data:
        require_string(data["argument_hint"], f"skill {skill_id} claude.argument_hint")
    return data


def validate_codex_metadata(skill_id: str, value: Any, targets: set[str]) -> dict[str, Any]:
    if value is None:
        return {}
    if "codex" not in targets:
        fail(f"skill {skill_id} has codex metadata without a codex target")
    data = require_mapping(value, f"skill {skill_id} codex metadata")
    require_keys(
        data,
        allowed={"interface"},
        required=set(),
        context=f"skill {skill_id} codex metadata",
    )
    if "interface" not in data:
        return data
    interface = require_mapping(data["interface"], f"skill {skill_id} codex.interface")
    allowed = {"display_name", "short_description", "default_prompt"}
    require_keys(interface, allowed=allowed, required=set(), context=f"skill {skill_id} codex.interface")
    for key, item in interface.items():
        require_string(item, f"skill {skill_id} codex.interface.{key}")
    if "short_description" in interface and not 25 <= len(interface["short_description"]) <= 64:
        fail(f"skill {skill_id} codex short_description must be 25-64 characters")
    if "default_prompt" in interface and f"${skill_id}" not in interface["default_prompt"]:
        fail(f"skill {skill_id} codex default_prompt must mention ${skill_id}")
    return data


def contained_registry_file(registry_dir: Path, relative: str, context: str) -> Path:
    if "\\" in relative:
        fail(f"{context} must use POSIX path separators")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        fail(f"{context} is invalid")
    current = registry_dir
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            fail(f"{context} contains a symlink")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(registry_dir.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise RegistryError(f"{context} is missing or escapes the registry") from exc
    if not resolved.is_file():
        fail(f"{context} must be a regular file")
    return resolved


def validate_provenance(skill_id: str, value: Any, registry_dir: Path) -> dict[str, Any]:
    data = require_mapping(value, f"skill {skill_id} provenance")
    kind = data.get("kind")
    if kind == "bundled":
        require_keys(
            data,
            allowed={"kind", "license"},
            required={"kind", "license"},
            context=f"skill {skill_id} provenance",
        )
        require_string(data["license"], f"skill {skill_id} provenance.license")
        return data
    if kind != "adapted":
        fail(f"skill {skill_id} provenance kind must be bundled or adapted")
    required = {
        "kind",
        "license",
        "repository",
        "tag",
        "commit",
        "path",
        "upstream_sha256",
        "adaptation_revision",
        "notice_file",
    }
    require_keys(data, allowed=required, required=required, context=f"skill {skill_id} provenance")
    for key in required - {"adaptation_revision"}:
        require_string(data[key], f"skill {skill_id} provenance.{key}")
    if not COMMIT_RE.fullmatch(data["commit"]):
        fail(f"skill {skill_id} provenance commit must be 40 lowercase hex characters")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", data["upstream_sha256"]):
        fail(f"skill {skill_id} provenance upstream_sha256 is invalid")
    if type(data["adaptation_revision"]) is not int or data["adaptation_revision"] < 1:
        fail(f"skill {skill_id} adaptation_revision must be a positive integer")
    notice_path = contained_registry_file(
        registry_dir, data["notice_file"], f"skill {skill_id} notice_file"
    )
    validated = dict(data)
    validated["_notice_path"] = notice_path
    validated["_notice_raw"] = normalized_bytes(notice_path)
    return validated


def validate_registry(registry_path: Path) -> dict[str, Any]:
    data, registry_raw = read_yaml_with_raw(registry_path, "registry")
    require_keys(
        data,
        allowed={"schema_version", "outputs", "skills", "approvals", "intake_decisions"},
        required={"schema_version", "outputs", "skills", "intake_decisions"},
        context="registry",
    )
    if type(data["schema_version"]) is not int or data["schema_version"] != SCHEMA_VERSION:
        fail(f"registry schema_version must be {SCHEMA_VERSION}")
    outputs = require_mapping(data["outputs"], "registry outputs")
    require_keys(outputs, allowed=ALLOWED_TARGETS, required=ALLOWED_TARGETS, context="registry outputs")
    expected_output_paths = {"claude": "~/.claude/skills", "codex": "~/.agents/skills"}
    for target, expected_path in expected_output_paths.items():
        output = require_mapping(outputs[target], f"output {target}")
        require_keys(output, allowed={"path"}, required={"path"}, context=f"output {target}")
        if output["path"] != expected_path:
            fail(f"output {target} path must be {expected_path}")

    registry_dir = registry_path.parent
    validated_skills: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(require_list(data["skills"], "registry skills")):
        skill = require_mapping(item, f"skills[{index}]")
        allowed = {
            "id",
            "version",
            "source",
            "status",
            "targets",
            "activation",
            "classification",
            "eligible_roles",
            "applicability",
            "distribution",
            "claude",
            "codex",
            "provenance",
        }
        required = allowed - {"claude", "codex", "distribution"}
        require_keys(skill, allowed=allowed, required=required, context=f"skills[{index}]")
        skill_id = require_string(skill["id"], f"skills[{index}].id")
        if not SKILL_ID_RE.fullmatch(skill_id):
            fail(f"skill id is invalid: {skill_id}")
        if skill_id in seen_ids:
            fail(f"duplicate skill id: {skill_id}")
        seen_ids.add(skill_id)
        version = require_string(skill["version"], f"skill {skill_id} version")
        try:
            parse_semver(version)
        except RegistryError as exc:
            raise RegistryError(f"skill {skill_id} {exc}") from exc
        if not isinstance(skill["status"], str) or skill["status"] not in ALLOWED_STATUSES:
            fail(f"skill {skill_id} status is invalid: {skill['status']}")
        targets_list = require_list(skill["targets"], f"skill {skill_id} targets")
        if any(not isinstance(target, str) for target in targets_list):
            fail(f"skill {skill_id} targets must be strings")
        targets = set(targets_list)
        if not targets_list or len(targets) != len(targets_list) or not targets <= ALLOWED_TARGETS:
            fail(f"skill {skill_id} target list is invalid: {targets_list}")
        if not isinstance(skill["activation"], str) or skill["activation"] not in ALLOWED_ACTIVATION:
            fail(f"skill {skill_id} activation is invalid")
        if (
            not isinstance(skill["classification"], str)
            or skill["classification"] not in ALLOWED_CLASSIFICATION
        ):
            fail(f"skill {skill_id} classification is invalid")
        roles_list = require_list(skill["eligible_roles"], f"skill {skill_id} eligible_roles")
        if any(not isinstance(role, str) for role in roles_list):
            fail(f"skill {skill_id} eligible roles must be strings")
        roles = set(roles_list)
        if not roles_list or len(roles) != len(roles_list) or not roles <= ALLOWED_ROLES:
            invalid = sorted(str(role) for role in roles - ALLOWED_ROLES)
            fail(f"skill {skill_id} role list is invalid: {', '.join(invalid) or roles_list}")
        require_string(skill["applicability"], f"skill {skill_id} applicability")
        source = require_string(skill["source"], f"skill {skill_id} source")
        source_dir = safe_source_path(registry_dir, source, skill_id)
        skill_file = source_dir / "SKILL.md"
        if not skill_file.is_file() or skill_file.is_symlink():
            fail(f"skill {skill_id} is missing SKILL.md")
        frontmatter, body, raw_skill = parse_frontmatter(skill_file)
        require_keys(
            frontmatter,
            allowed=PORTABLE_FRONTMATTER,
            required=PORTABLE_FRONTMATTER,
            context=f"skill {skill_id} frontmatter",
        )
        name = require_string(frontmatter["name"], f"skill {skill_id} frontmatter.name")
        description = require_string(
            frontmatter["description"], f"skill {skill_id} frontmatter.description"
        )
        if name != skill_id or source_dir.name != skill_id:
            fail(f"skill id/name/directory mismatch: {skill_id}, {name}, {source_dir.name}")
        markdown_references = {
            "SKILL.md": validate_markdown(
                skill_id, source_dir, skill_file, raw_skill.decode("utf-8")
            )
        }
        files = scan_source_files(source_dir, registry_dir)
        if "SKILL.md" not in files or files["SKILL.md"][0] != raw_skill:
            fail(f"skill {skill_id} SKILL.md changed while its source snapshot was captured")
        for relative, (raw, _executable) in files.items():
            if not relative.lower().endswith(".md") or relative == "SKILL.md":
                continue
            markdown_path = source_dir.joinpath(*PurePosixPath(relative).parts)
            try:
                markdown_text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise RegistryError(
                    f"skill {skill_id} Markdown is not valid UTF-8: {relative}"
                ) from exc
            markdown_references[relative] = validate_markdown(
                skill_id, source_dir, markdown_path, markdown_text
            )
        distribution_exclude = validate_distribution(
            skill_id, skill.get("distribution"), files
        )
        for relative, references in markdown_references.items():
            if relative in distribution_exclude:
                continue
            conflicts = sorted(references & distribution_exclude)
            if conflicts:
                fail(
                    f"skill {skill_id} retained Markdown {relative} references "
                    f"excluded distribution file {conflicts[0]}"
                )
        claude = validate_claude_metadata(skill_id, skill.get("claude"), targets)
        codex = validate_codex_metadata(skill_id, skill.get("codex"), targets)
        provenance = validate_provenance(skill_id, skill["provenance"], registry_dir)
        validated = dict(skill)
        validated.update(
            {
                "_source_dir": source_dir,
                "_frontmatter": {"name": name, "description": description},
                "_body": body,
                "_raw_skill": raw_skill,
                "_files": files,
                "_distribution_exclude": distribution_exclude,
                "_claude": claude,
                "_codex": codex,
                "_provenance": provenance,
            }
        )
        for target in sorted(targets):
            render_target(validated, target)
        validated_skills.append(validated)

    approval_ids: set[str] = set()
    approvals = require_list(data.get("approvals", []), "approvals")
    for index, item in enumerate(approvals):
        approval = require_mapping(item, f"approvals[{index}]")
        require_keys(
            approval,
            allowed={"id", "kind", "recorded_at", "scope"},
            required={"id", "kind", "recorded_at", "scope"},
            context=f"approvals[{index}]",
        )
        approval_id = require_string(approval["id"], f"approvals[{index}].id")
        if not SKILL_ID_RE.fullmatch(approval_id) or approval_id in approval_ids:
            fail(f"approval id is invalid or duplicated: {approval_id}")
        approval_ids.add(approval_id)
        if approval["kind"] != "explicit-user":
            fail(f"approval {approval_id} kind must be explicit-user")
        recorded_at = require_string(
            approval["recorded_at"], f"approval {approval_id} recorded_at"
        )
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", recorded_at):
            fail(f"approval {approval_id} recorded_at must be YYYY-MM-DD")
        require_string(approval["scope"], f"approval {approval_id} scope")

    decisions = require_list(data["intake_decisions"], "intake_decisions")
    seen_decisions: set[str] = set()
    for index, item in enumerate(decisions):
        decision = require_mapping(item, f"intake_decisions[{index}]")
        require_keys(
            decision,
            allowed={"id", "disposition", "reason", "upstream", "approval_ref"},
            required={"id", "disposition", "reason"},
            context=f"intake_decisions[{index}]",
        )
        decision_id = require_string(decision["id"], f"intake_decisions[{index}].id")
        if not SKILL_ID_RE.fullmatch(decision_id):
            fail(f"intake decision id is invalid: {decision_id}")
        if decision_id in seen_ids or decision_id in seen_decisions:
            fail(f"duplicate registry/intake id: {decision_id}")
        seen_decisions.add(decision_id)
        if (
            not isinstance(decision["disposition"], str)
            or decision["disposition"] not in ALLOWED_DISPOSITIONS
        ):
            fail(f"intake decision {decision_id} disposition is invalid")
        require_string(decision["reason"], f"intake decision {decision_id} reason")
        approval_ref = decision.get("approval_ref")
        if decision["disposition"] in {"codex-only", "excluded"}:
            if not isinstance(approval_ref, str) or approval_ref not in approval_ids:
                fail(
                    f"intake decision {decision_id} requires a recorded approval_ref"
                )
        elif approval_ref is not None and approval_ref not in approval_ids:
            fail(f"intake decision {decision_id} approval_ref is unknown")
        if "upstream" in decision:
            upstream = require_mapping(decision["upstream"], f"intake decision {decision_id} upstream")
            require_keys(
                upstream,
                allowed={"repository", "tag", "commit", "path"},
                required={"repository", "commit", "path"},
                context=f"intake decision {decision_id} upstream",
            )
            for key in {"repository", "commit", "path"}:
                require_string(upstream[key], f"intake decision {decision_id} upstream.{key}")
            if not COMMIT_RE.fullmatch(upstream["commit"]):
                fail(f"intake decision {decision_id} upstream commit is invalid")

    return {
        "data": data,
        "registry_path": registry_path,
        "registry_dir": registry_dir,
        "registry_raw": registry_raw,
        "skills": validated_skills,
    }


def yaml_bytes(value: dict[str, Any]) -> bytes:
    text = yaml.safe_dump(
        value,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=1000,
        line_break="\n",
    )
    if not text.endswith("\n"):
        text += "\n"
    return text.encode("utf-8")


def render_claude(skill: dict[str, Any]) -> bytes:
    metadata: dict[str, Any] = dict(skill["_frontmatter"])
    claude = skill["_claude"]
    if "argument_hint" in claude:
        metadata["argument-hint"] = claude["argument_hint"]
    if skill["activation"] == "manual":
        metadata["disable-model-invocation"] = True
    return b"---\n" + yaml_bytes(metadata) + b"---\n" + skill["_body"]


def render_openai_yaml(skill: dict[str, Any]) -> bytes | None:
    interface = skill["_codex"].get("interface", {})
    manual = skill["activation"] == "manual"
    if not interface and not manual:
        return None
    lines: list[str] = []
    if interface:
        lines.append("interface:")
        for key in ("display_name", "short_description", "default_prompt"):
            if key in interface:
                lines.append(f"  {key}: {json.dumps(interface[key], ensure_ascii=False)}")
    if manual:
        lines.extend(["policy:", "  allow_implicit_invocation: false"])
    return ("\n".join(lines) + "\n").encode("utf-8")


def render_target(skill: dict[str, Any], target: str) -> dict[str, tuple[bytes, bool]]:
    openai: bytes | None = None
    reserved = [MARKER_NAME]
    if target == "codex":
        openai = render_openai_yaml(skill)
        if openai is not None:
            reserved.append("agents/openai.yaml")
    if skill["_provenance"]["kind"] == "adapted":
        reserved.append("LICENSE")
    validate_portable_file_inventory(
        [*skill["_files"], *reserved],
        f"skill {skill['id']} {target} target inventory",
    )
    rendered = {
        relative: content
        for relative, content in skill["_files"].items()
        if relative not in skill["_distribution_exclude"]
    }
    if target == "claude":
        rendered["SKILL.md"] = (render_claude(skill), False)
    elif target == "codex":
        rendered["SKILL.md"] = (skill["_raw_skill"], False)
        if openai is not None:
            rendered["agents/openai.yaml"] = (openai, False)
    else:
        fail(f"unknown render target: {target}")
    if skill["_provenance"]["kind"] == "adapted":
        rendered["LICENSE"] = (skill["_provenance"]["_notice_raw"], False)
    validate_portable_file_inventory(
        [*rendered, MARKER_NAME],
        f"skill {skill['id']} {target} rendered inventory",
    )
    return dict(sorted(rendered.items()))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_records(files: dict[str, tuple[bytes, bool]]) -> list[dict[str, Any]]:
    records = []
    for path, (raw, executable) in sorted(files.items()):
        records.append(
            {
                "path": path,
                "bytes": len(raw),
                "executable": bool(executable),
                "sha256": f"sha256:{sha256_hex(raw)}",
            }
        )
    return records


def tree_sha256(records: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        mode = "100755" if record["executable"] else "100644"
        digest.update(record["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(mode.encode("ascii"))
        digest.update(b"\0")
        digest.update(record["sha256"].removeprefix("sha256:").encode("ascii"))
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"


def line_count(raw: bytes) -> int:
    if not raw:
        return 0
    return raw.count(b"\n") + (0 if raw.endswith(b"\n") else 1)


def target_lock(skill: dict[str, Any], target: str, output_path: str) -> dict[str, Any]:
    files = render_target(skill, target)
    records = file_records(files)
    skill_md = files["SKILL.md"][0]
    description = skill["_frontmatter"]["description"]
    listing_chars = len(f"{skill['id']}\n{description}")
    return {
        "destination": f"{output_path}/{skill['id']}",
        "tree_sha256": tree_sha256(records),
        "metrics": {
            "description_chars": len(description),
            "listing_chars": listing_chars,
            "bytes": sum(len(raw) for raw, _executable in files.values()),
            "lines": line_count(skill_md),
        },
        "files": records,
    }


def build_lock(validated: dict[str, Any]) -> dict[str, Any]:
    registry_path = validated["registry_path"]
    data = validated["data"]
    registry_raw = validated["registry_raw"]
    output_listing = {"claude": 0, "codex": 0}
    locked_skills: list[dict[str, Any]] = []
    for skill in sorted(validated["skills"], key=lambda item: item["id"]):
        source_records = file_records(skill["_files"])
        provenance = {
            key: value for key, value in skill["_provenance"].items() if not key.startswith("_")
        }
        notice_path = skill["_provenance"].get("_notice_path")
        if notice_path is not None:
            notice_raw = skill["_provenance"]["_notice_raw"]
            provenance["notice"] = {
                "path": f"skills/{skill['_provenance']['notice_file']}",
                "bytes": len(notice_raw),
                "executable": False,
                "sha256": f"sha256:{sha256_hex(notice_raw)}",
            }
        targets: dict[str, Any] = {}
        for target in sorted(skill["targets"]):
            target_data = target_lock(skill, target, data["outputs"][target]["path"])
            targets[target] = target_data
            if skill["status"] == "enabled":
                output_listing[target] += target_data["metrics"]["listing_chars"]
        locked_skills.append(
            {
                "id": skill["id"],
                "version": skill["version"],
                "status": skill["status"],
                "classification": skill["classification"],
                "activation": skill["activation"],
                "eligible_roles": sorted(skill["eligible_roles"]),
                "applicability": skill["applicability"],
                "source": {
                    "path": f"skills/{skill['source']}",
                    "tree_sha256": tree_sha256(source_records),
                    "files": source_records,
                },
                "targets": targets,
                "provenance": provenance,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": {"name": GENERATOR_NAME, "version": GENERATOR_VERSION},
        "registry_sha256": f"sha256:{sha256_hex(registry_raw)}",
        "outputs": {
            target: {
                "path": data["outputs"][target]["path"],
                "listing_chars": output_listing[target],
            }
            for target in ("claude", "codex")
        },
        "skills": locked_skills,
        "intake_decisions": data["intake_decisions"],
        "approvals": data.get("approvals", []),
    }


def resolve_git_base(registry_path: Path, base_ref: str) -> tuple[Path, str, PurePosixPath]:
    candidate_root = registry_path.parent.resolve(strict=True)
    top_result = run_git(
        ["rev-parse", "--show-toplevel"],
        cwd=candidate_root,
        context="locating the repository for the base comparison",
    )
    if top_result.returncode != 0 or not top_result.stdout.strip():
        fail("--base-ref requires the registry to be inside a Git repository")
    try:
        repo_root = Path(top_result.stdout.strip()).resolve(strict=True)
        registry_relative = PurePosixPath(
            registry_path.resolve(strict=True).relative_to(repo_root).as_posix()
        )
    except (FileNotFoundError, ValueError) as exc:
        raise RegistryError("registry is outside the detected Git repository") from exc
    resolved = run_git(
        ["rev-parse", "--verify", "--end-of-options", f"{base_ref}^{{commit}}"],
        cwd=repo_root,
        context="resolving --base-ref",
    )
    commit = resolved.stdout.strip()
    if resolved.returncode != 0 or not COMMIT_RE.fullmatch(commit):
        fail("--base-ref does not resolve to a Git commit")
    return repo_root, commit, registry_relative


def git_tree_contains(repo_root: Path, commit: str, relative: PurePosixPath) -> bool:
    result = run_git(
        ["ls-tree", "--name-only", commit, "--", relative.as_posix()],
        cwd=repo_root,
        context="checking the base registry",
    )
    if result.returncode != 0:
        fail("Git could not inspect the base registry")
    return relative.as_posix() in result.stdout.splitlines()


def archive_registry_parent(
    repo_root: Path, commit: str, registry_relative: PurePosixPath, destination: Path
) -> Path:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "archive",
                "--format=tar",
                commit,
                "--",
                registry_relative.parent.as_posix(),
            ],
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RegistryError("Git failed while reading the base registry tree") from exc
    if result.returncode != 0:
        fail("Git could not archive the base registry tree")
    try:
        with tarfile.open(fileobj=BytesIO(result.stdout), mode="r:") as archive:
            for member in archive.getmembers():
                pure = PurePosixPath(member.name)
                if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
                    fail("base registry archive contains an unsafe path")
                target = destination.joinpath(*pure.parts)
                try:
                    target.resolve(strict=False).relative_to(destination.resolve(strict=True))
                except ValueError as exc:
                    raise RegistryError("base registry archive escapes its staging directory") from exc
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    fail("base registry archive contains a link or special file")
                source = archive.extractfile(member)
                if source is None:
                    fail("base registry archive contains an unreadable file")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read())
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
    except (tarfile.TarError, OSError) as exc:
        raise RegistryError("base registry archive is invalid") from exc
    return destination.joinpath(*registry_relative.parts)


def skill_version_payload(skill: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in skill.items() if key != "version"}


def enforce_base_versions(validated: dict[str, Any], current_lock: dict[str, Any], base_ref: str) -> None:
    """Require a greater SemVer for source, rendered, provenance, or lifecycle changes."""

    repo_root, commit, registry_relative = resolve_git_base(
        validated["registry_path"], base_ref
    )
    if not git_tree_contains(repo_root, commit, registry_relative):
        return
    with tempfile.TemporaryDirectory(prefix="shogun-skill-base-") as temporary:
        temporary_root = Path(temporary)
        base_registry_path = archive_registry_parent(
            repo_root, commit, registry_relative, temporary_root
        )
        base_data = read_yaml(base_registry_path, "base registry")
        if base_data.get("schema_version") != SCHEMA_VERSION:
            return
        base_validated = validate_registry(base_registry_path.resolve(strict=True))
        base_lock = build_lock(base_validated)

    current_skills = {skill["id"]: skill for skill in current_lock["skills"]}
    base_skills = {skill["id"]: skill for skill in base_lock["skills"]}
    removed = sorted(set(base_skills) - set(current_skills))
    for skill_id in removed:
        if base_skills[skill_id].get("status") != "revoked":
            fail(
                f"base comparison: remove {skill_id} through a versioned revoked lifecycle first"
            )
    added = sorted(set(current_skills) - set(base_skills))
    for skill_id in added:
        if current_skills[skill_id].get("version") != "1.0.0":
            fail(f"base comparison: newly introduced skill {skill_id} must start at 1.0.0")
    for skill_id in sorted(set(current_skills) & set(base_skills)):
        current = current_skills[skill_id]
        base = base_skills[skill_id]
        precedence = compare_semver(current["version"], base["version"])
        if precedence < 0:
            fail(f"base comparison: {skill_id} version must not decrease")
        changed = skill_version_payload(current) != skill_version_payload(base)
        if changed and precedence <= 0:
            fail(
                f"base comparison: {skill_id} changed without a greater semantic version"
            )


def atomic_write(path: Path, raw: bytes, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", dir=path.parent, delete=False
        ) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
        if mode is not None:
            path.chmod(mode)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def collect_paths(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        if isinstance(value.get("path"), str):
            found.add(value["path"])
        for child in value.values():
            found.update(collect_paths(child))
    elif isinstance(value, list):
        for child in value:
            found.update(collect_paths(child))
    return found


def describe_drift(actual: dict[str, Any], expected: dict[str, Any]) -> str:
    actual_paths = collect_paths(actual)
    expected_paths = collect_paths(expected)
    changed_paths = sorted(actual_paths ^ expected_paths)
    if changed_paths:
        return f"lock drift: file inventory changed: {changed_paths[0]}"
    return "lock drift: hash or metadata changed"


def read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RegistryError(f"{context} not found") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistryError(f"invalid JSON in {context}") from exc
    return require_mapping(value, context)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    atomic_write(path, raw, mode=0o600)


def configured_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return Path(os.path.abspath(path))


def ensure_no_symlink_ancestors(path: Path, context: str) -> None:
    absolute = configured_path(path)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if current.is_symlink():
            fail(f"{context} contains a symlink")
        if current.exists() and current != absolute and not current.is_dir():
            fail(f"{context} has a non-directory ancestor")


def secure_directory(path: Path) -> None:
    ensure_no_symlink_ancestors(path, "transaction state directory")
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        fail("transaction state directory must be a real directory")
    path.chmod(0o700)


def deepest_existing_ancestor(path: Path) -> Path:
    current = configured_path(path)
    while not current.exists() and not current.is_symlink():
        parent = current.parent
        if parent == current:
            break
        current = parent
    return current


def path_volume_is_case_insensitive(path: Path) -> bool:
    """Probe existing ancestors without writes; do not assume all POSIX is alike."""

    if os.name == "nt":
        return True
    current = deepest_existing_ancestor(path)
    for candidate in (current, *current.parents):
        name = candidate.name
        variant = None
        for index, character in enumerate(name):
            if character.isalpha():
                swapped = character.swapcase()
                if swapped != character:
                    variant = name[:index] + swapped + name[index + 1 :]
                    break
        if variant is None:
            continue
        alternate = candidate.with_name(variant)
        try:
            if alternate.exists() and os.path.samefile(candidate, alternate):
                return True
        except OSError:
            continue
    return False


def lexical_paths_overlap(left: Path, right: Path) -> bool:
    try:
        left.relative_to(right)
        return True
    except ValueError:
        pass
    try:
        right.relative_to(left)
        return True
    except ValueError:
        return False


def path_component_sequences_overlap(
    left: tuple[str, ...], right: tuple[str, ...]
) -> bool:
    return (
        left[: len(right)] == right
        or right[: len(left)] == left
    )


def existing_path_ancestors(path: Path) -> tuple[Path, ...]:
    deepest = deepest_existing_ancestor(path)
    return (deepest, *deepest.parents)


def volume_component_key(component: str, *, case_insensitive: bool) -> str:
    normalized = unicodedata.normalize("NFC", component)
    return normalized.casefold() if case_insensitive else normalized


def paths_overlap(left: Path, right: Path) -> bool:
    left = configured_path(left)
    right = configured_path(right)
    if lexical_paths_overlap(left, right):
        return True
    if left.exists() and right.exists():
        try:
            if os.path.samefile(left, right):
                return True
        except OSError:
            pass
    left_ancestors = existing_path_ancestors(left)
    right_ancestors = existing_path_ancestors(right)
    for left_ancestor in left_ancestors:
        for right_ancestor in right_ancestors:
            try:
                if not os.path.samefile(left_ancestor, right_ancestor):
                    continue
            except OSError:
                continue
            left_tail = left.relative_to(left_ancestor).parts
            right_tail = right.relative_to(right_ancestor).parts
            case_insensitive = (
                path_volume_is_case_insensitive(left_ancestor)
                or path_volume_is_case_insensitive(right_ancestor)
            )
            left_tail = tuple(
                volume_component_key(part, case_insensitive=case_insensitive)
                for part in left_tail
            )
            right_tail = tuple(
                volume_component_key(part, case_insensitive=case_insensitive)
                for part in right_tail
            )
            if path_component_sequences_overlap(left_tail, right_tail):
                return True
    left_existing = left_ancestors[0]
    right_existing = right_ancestors[0]
    try:
        same_volume = left_existing.stat().st_dev == right_existing.stat().st_dev
    except OSError:
        same_volume = False
    if not same_volume:
        return False
    normalized_left = Path(
        *(volume_component_key(part, case_insensitive=False) for part in left.parts)
    )
    normalized_right = Path(
        *(volume_component_key(part, case_insensitive=False) for part in right.parts)
    )
    if lexical_paths_overlap(normalized_left, normalized_right):
        return True
    case_insensitive = (
        path_volume_is_case_insensitive(left_existing)
        or path_volume_is_case_insensitive(right_existing)
    )
    if not case_insensitive:
        return False
    folded_left = Path(
        *(volume_component_key(part, case_insensitive=True) for part in left.parts)
    )
    folded_right = Path(
        *(volume_component_key(part, case_insensitive=True) for part in right.parts)
    )
    return lexical_paths_overlap(folded_left, folded_right)


def state_directory() -> Path:
    override = os.environ.get("SHOGUN_SKILL_REGISTRY_STATE_DIR")
    if override:
        return configured_path(override)
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local/state"
    return configured_path(base / "multi-agent-shogun/skill-registry")


def target_directories() -> dict[str, Path]:
    return {
        "claude": configured_path(Path(
            os.environ.get(
                "SHOGUN_SKILL_REGISTRY_CLAUDE_DIR", str(Path.home() / ".claude/skills")
            )
        )),
        "codex": configured_path(Path(
            os.environ.get(
                "SHOGUN_SKILL_REGISTRY_CODEX_DIR", str(Path.home() / ".agents/skills")
            )
        )),
    }


def validate_runtime_roots(
    state_dir: Path,
    registry_path: Path,
    targets: set[str] | None = None,
) -> dict[str, Path]:
    selected = ALLOWED_TARGETS if targets is None else targets
    if not selected or not selected <= ALLOWED_TARGETS:
        fail("runtime target selection is invalid")
    all_roots = {target: configured_path(path) for target, path in target_directories().items()}
    roots = {target: all_roots[target] for target in sorted(selected)}
    state = configured_path(state_dir)
    projects = validate_state_runtime_root(state, registry_path)
    for target, root in roots.items():
        ensure_no_symlink_ancestors(root, f"{target} skill root")
        if root.exists() and not root.is_dir():
            fail(f"{target} skill root must be a real directory")
        if paths_overlap(state, root):
            fail(f"transaction state root must not overlap the {target} skill root")
        if any(paths_overlap(root, project) for project in projects):
            fail(f"{target} skill root must not overlap the canonical project or registry sources")
    if len(roots) > 1 and paths_overlap(roots["claude"], roots["codex"]):
        fail("Claude and Codex skill roots must be distinct and non-nested")
    return roots


def validate_state_runtime_root(state_dir: Path, registry_path: Path) -> set[Path]:
    state = configured_path(state_dir)
    projects = {
        configured_path(registry_path).parent.parent,
        Path(__file__).resolve().parent.parent,
    }
    ensure_no_symlink_ancestors(state, "transaction state root")
    if state.exists() and (state.is_symlink() or not state.is_dir()):
        fail("transaction state root must be a real directory")
    if any(paths_overlap(state, project) for project in projects):
        fail("transaction state root must not overlap the canonical project or registry sources")
    for name in ("transactions", "backups", "rollback-backups"):
        subtree = state / name
        ensure_no_symlink_ancestors(subtree, f"transaction state {name} root")
        if subtree.exists() and (subtree.is_symlink() or not subtree.is_dir()):
            fail(f"transaction state {name} root must be a real directory")
    return projects


@contextmanager
def mutation_lock(state_dir: Path, roots: dict[str, Path]):
    secure_directory(state_dir)
    try:
        import fcntl
    except ImportError as exc:  # pragma: no cover - Shogun runtime is POSIX
        raise RegistryError("mutating registry commands require POSIX file locking") from exc
    lock_paths = {state_dir / "registry.lock"}
    for root in roots.values():
        parent = root.parent
        ensure_no_symlink_ancestors(parent, "skill root parent")
        parent.mkdir(parents=True, exist_ok=True)
        lock_paths.add(parent / ".shogun-skill-registry.lock")
    handles = []
    try:
        for lock_path in sorted(lock_paths, key=lambda item: str(item)):
            if lock_path.is_symlink():
                fail("skill registry lock path must not be a symlink")
            flags = os.O_RDWR | os.O_CREAT
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(lock_path, flags, 0o600)
            except OSError as exc:
                raise RegistryError("skill registry lock could not be opened safely") from exc
            os.fchmod(descriptor, 0o600)
            handle = os.fdopen(descriptor, "a+b")
            handles.append(handle)
        deadline = time.monotonic() + 10.0
        for handle in handles:
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        fail("skill registry mutation lock timed out after 10 seconds")
                    time.sleep(0.1)
        yield
    finally:
        for handle in reversed(handles):
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()


MOUNTINFO_ESCAPE_RE = re.compile(r"\\([0-7]{3})")


def decode_mountinfo_path(value: str) -> Path:
    decoded = MOUNTINFO_ESCAPE_RE.sub(
        lambda match: chr(int(match.group(1), 8)), value
    )
    path = Path(decoded)
    if not path.is_absolute():
        fail("Linux mountinfo contains a non-absolute mount point")
    return configured_path(path)


def linux_mount_points() -> frozenset[Path]:
    if not sys.platform.startswith("linux"):
        return frozenset()
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise RegistryError("cannot verify Linux mount boundaries") from exc
    mount_points: set[Path] = set()
    for line in lines:
        fields = line.split()
        if len(fields) < 6:
            fail("Linux mountinfo record is malformed")
        mount_points.add(decode_mountinfo_path(fields[4]))
    return frozenset(mount_points)


def ensure_no_nested_mounts(path: Path, context: str) -> None:
    root = configured_path(path)
    try:
        root_stat = os.stat(root, follow_symlinks=False)
    except OSError as exc:
        raise RegistryError(f"{context} is unavailable") from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        fail(f"{context} must be a real directory")
    if os.path.ismount(root):
        fail(f"{context} must not be a filesystem mount point")
    for mount_point in linux_mount_points():
        try:
            mount_point.relative_to(root)
        except ValueError:
            continue
        fail(f"{context} contains a filesystem mount boundary")
    for walk_root, dirnames, filenames in os.walk(root, followlinks=False):
        root_path = Path(walk_root)
        for name in (*dirnames, *filenames):
            child = root_path / name
            try:
                child_stat = os.stat(child, follow_symlinks=False)
            except OSError as exc:
                raise RegistryError(f"{context} changed during mount validation") from exc
            if child_stat.st_dev != root_stat.st_dev or os.path.ismount(child):
                fail(f"{context} contains a nested filesystem boundary: {name}")


def ensure_real_directory_tree(path: Path, context: str) -> None:
    ensure_no_nested_mounts(path, context)
    if path.is_symlink() or not path.is_dir():
        fail(f"{context} must be a real directory")
    for root, dirnames, filenames in os.walk(path, followlinks=False):
        root_path = Path(root)
        for name in dirnames:
            child = root_path / name
            if child.is_symlink():
                fail(f"{context} contains a symlink: {name}")
        for name in filenames:
            child = root_path / name
            if child.is_symlink() or not child.is_file():
                fail(f"{context} contains a symlink or special file: {name}")


def directory_fd_chain_no_follow(path: Path, context: str) -> list[int]:
    path = configured_path(path)
    required_flags = ["O_DIRECTORY", "O_NOFOLLOW"]
    if any(not hasattr(os, name) for name in required_flags):
        fail(f"{context} requires no-follow directory descriptors")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptors: list[int] = []
    try:
        current = os.open(path.anchor, flags)
        descriptors.append(current)
        for part in path.parts[1:]:
            current = os.open(part, flags, dir_fd=current)
            descriptors.append(current)
    except OSError as exc:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        raise RegistryError(
            f"{context} contains an unsafe or missing ancestor"
        ) from exc
    return descriptors


def secure_remove_tree(
    root: Path,
    relative: str | Path,
    context: str,
    *,
    missing_ok: bool = True,
    expected_identity: tuple[int, int] | None = None,
) -> None:
    """Atomically tombstone then resumably remove one contained real tree."""

    root = configured_path(root)
    relative_text = Path(relative).as_posix()
    pure = PurePosixPath(relative_text)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        fail(f"{context} removal path is invalid")
    ensure_no_symlink_ancestors(root, f"{context} root")
    if not root.exists():
        if missing_ok:
            return
        fail(f"{context} root is missing")
    if root.is_symlink() or not root.is_dir():
        fail(f"{context} root must be a real directory")
    if not getattr(shutil.rmtree, "avoids_symlink_attacks", False):
        fail(f"{context} requires symlink-safe directory removal")
    descriptors = directory_fd_chain_no_follow(root, f"{context} root")
    try:
        current = descriptors[-1]
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        for part in pure.parts[:-1]:
            try:
                current = os.open(part, flags, dir_fd=current)
            except FileNotFoundError:
                if missing_ok:
                    return
                raise
            except OSError as exc:
                raise RegistryError(f"{context} contains an unsafe ancestor") from exc
            descriptors.append(current)
        leaf = pure.parts[-1]
        parent = root.joinpath(*pure.parts[:-1])
        tombstone_pattern = re.compile(
            rf"^\.shogun-discard-{re.escape(leaf)}-d([0-9a-f]+)-i([0-9a-f]+)$"
        )
        tombstones = []
        for name in os.listdir(current):
            match = tombstone_pattern.fullmatch(name)
            if match is None:
                continue
            tombstone_stat = os.stat(name, dir_fd=current, follow_symlinks=False)
            expected_device = int(match.group(1), 16)
            expected_inode = int(match.group(2), 16)
            if (
                not stat.S_ISDIR(tombstone_stat.st_mode)
                or tombstone_stat.st_dev != expected_device
                or tombstone_stat.st_ino != expected_inode
            ):
                fail(f"{context} tombstone identity mismatch")
            if expected_identity is not None and (
                tombstone_stat.st_dev,
                tombstone_stat.st_ino,
            ) != expected_identity:
                fail(f"{context} tombstone is not the expected directory")
            tombstones.append(name)
        if len(tombstones) > 1:
            fail(f"{context} has multiple removal tombstones")
        if tombstones:
            ensure_no_nested_mounts(
                parent / tombstones[0], f"{context} removal tombstone"
            )
            shutil.rmtree(tombstones[0], dir_fd=current)
            # A leaf recreated after the original atomic detach is not part of
            # this deletion.  Preserve it and fail closed instead of silently
            # accepting a cleanup postcondition that is no longer true.
            try:
                os.stat(leaf, dir_fd=current, follow_symlinks=False)
            except FileNotFoundError:
                return
            fail(f"{context} leaf reappeared during resumable removal")
        try:
            leaf_stat = os.stat(leaf, dir_fd=current, follow_symlinks=False)
        except FileNotFoundError:
            if missing_ok:
                return
            raise RegistryError(f"{context} is missing")
        if not stat.S_ISDIR(leaf_stat.st_mode):
            fail(f"{context} must be a real directory")
        if expected_identity is not None and (
            leaf_stat.st_dev,
            leaf_stat.st_ino,
        ) != expected_identity:
            fail(f"{context} is not the expected directory")
        tombstone = (
            f".shogun-discard-{leaf}-d{leaf_stat.st_dev:x}-i{leaf_stat.st_ino:x}"
        )
        ensure_no_nested_mounts(parent / leaf, context)
        rename_name_no_replace_at(current, leaf, tombstone)
        renamed_stat = os.stat(tombstone, dir_fd=current, follow_symlinks=False)
        if (
            not stat.S_ISDIR(renamed_stat.st_mode)
            or renamed_stat.st_dev != leaf_stat.st_dev
            or renamed_stat.st_ino != leaf_stat.st_ino
        ):
            fail(f"{context} tombstone identity changed during removal")
        ensure_no_nested_mounts(parent / tombstone, f"{context} removal tombstone")
        control_value = os.environ.get(
            "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_DURING_TRANSACTION_RMTREE"
        )
        if control_value:
            tombstone_path = parent / tombstone
            ensure_real_directory_tree(tombstone_path, f"{context} test tombstone")
            for candidate in sorted(
                (item for item in tombstone_path.rglob("*") if item.is_file()),
                key=lambda item: item.as_posix(),
            ):
                candidate.unlink()
                break
            pause_at_control_for_test(
                "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_DURING_TRANSACTION_RMTREE",
                parent / leaf,
            )
        shutil.rmtree(tombstone, dir_fd=current)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def disk_tree_records(path: Path, *, include_marker: bool = False) -> list[dict[str, Any]]:
    ensure_real_directory_tree(path, f"installed skill {path.name}")
    files: dict[str, tuple[bytes, bool]] = {}
    for candidate in sorted(path.rglob("*"), key=lambda item: item.as_posix()):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(path).as_posix()
        if relative == MARKER_NAME and not include_marker:
            continue
        executable = bool(
            candidate.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        )
        files[relative] = (candidate.read_bytes(), executable)
    return file_records(files)


def disk_tree_sha256(path: Path) -> str:
    return tree_sha256(disk_tree_records(path))


def backup_tree_sha256(path: Path) -> str:
    return tree_sha256(disk_tree_records(path, include_marker=True))


def load_marker(path: Path) -> dict[str, Any] | None:
    marker_path = path / MARKER_NAME
    if not marker_path.exists():
        return None
    if marker_path.is_symlink() or not marker_path.is_file():
        fail(f"invalid ownership marker for {path.name}")
    marker = read_json(marker_path, f"ownership marker for {path.name}")
    required = {
        "schema_version",
        "owner",
        "skill_id",
        "target",
        "version",
        "registry_sha256",
        "tree_sha256",
        "transaction_id",
    }
    if set(marker) != required or marker.get("schema_version") != 1:
        fail(f"invalid ownership marker schema for {path.name}")
    if marker.get("owner") != MARKER_OWNER:
        fail(f"invalid ownership marker owner for {path.name}")
    if not isinstance(marker.get("skill_id"), str) or not SKILL_ID_RE.fullmatch(
        marker["skill_id"]
    ):
        fail(f"invalid ownership marker skill id for {path.name}")
    if marker.get("target") not in ALLOWED_TARGETS:
        fail(f"invalid ownership marker target for {path.name}")
    version = marker.get("version")
    if not isinstance(version, str):
        fail(f"invalid ownership marker version for {path.name}")
    parse_semver(version)
    if not isinstance(marker.get("registry_sha256"), str) or not HASH_RE.fullmatch(
        marker["registry_sha256"]
    ):
        fail(f"invalid ownership marker registry hash for {path.name}")
    if not isinstance(marker.get("tree_sha256"), str) or not HASH_RE.fullmatch(
        marker["tree_sha256"]
    ):
        fail(f"invalid ownership marker tree hash for {path.name}")
    if not isinstance(marker.get("transaction_id"), str) or not TRANSACTION_ID_RE.fullmatch(
        marker["transaction_id"]
    ):
        fail(f"invalid ownership marker transaction id for {path.name}")
    return marker


def validate_managed_tree(path: Path, marker: dict[str, Any]) -> None:
    if marker.get("owner") != MARKER_OWNER:
        fail(f"ownership marker for {path.name} is not managed by {MARKER_OWNER}")
    actual = disk_tree_sha256(path)
    if actual != marker.get("tree_sha256"):
        fail(f"managed skill tree drift detected: {path.name}")


def validate_marker_identity(
    path: Path, marker: dict[str, Any], *, target: str, skill_id: str
) -> None:
    if marker.get("skill_id") != skill_id or marker.get("target") != target:
        fail(f"managed marker identity mismatch: {path.name}")
    if path.name != skill_id:
        fail(f"managed destination path mismatch: {path.name}")
    validate_managed_tree(path, marker)


def lock_skill_map(expected_lock: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["id"]: entry for entry in expected_lock["skills"]}


def selected_targets(selection: str) -> list[str]:
    return ["claude", "codex"] if selection == "all" else [selection]


def plan_apply(
    validated: dict[str, Any],
    expected_lock: dict[str, Any],
    selection: str,
    roots: dict[str, Path],
) -> list[dict[str, Any]]:
    locked = lock_skill_map(expected_lock)
    operations: list[dict[str, Any]] = []
    for target in selected_targets(selection):
        root = roots[target]
        if root.exists() and (root.is_symlink() or not root.is_dir()):
            fail(f"{target} skill root must be a real directory")
        desired = {
            skill["id"]: skill
            for skill in validated["skills"]
            if skill["status"] == "enabled" and target in skill["targets"]
        }
        for skill_id, skill in sorted(desired.items()):
            destination = root / skill_id
            rendered = render_target(skill, target)
            expected_tree = locked[skill_id]["targets"][target]["tree_sha256"]
            action = "install"
            original_tree_sha256 = None
            if destination.exists() or destination.is_symlink():
                if destination.is_symlink() or not destination.is_dir():
                    fail(f"destination for {skill_id} is a symlink or special file")
                ensure_real_directory_tree(destination, f"destination for {skill_id}")
                marker = load_marker(destination)
                if marker is not None:
                    validate_marker_identity(
                        destination, marker, target=target, skill_id=skill_id
                    )
                    if (
                        marker.get("version") == skill["version"]
                        and marker.get("registry_sha256") == expected_lock["registry_sha256"]
                        and marker.get("tree_sha256") == expected_tree
                    ):
                        continue
                action = "replace"
                original_tree_sha256 = backup_tree_sha256(destination)
            operations.append(
                {
                    "target": target,
                    "skill_id": skill_id,
                    "version": skill["version"],
                    "action": action,
                    "destination": destination,
                    "rendered": rendered,
                    "tree_sha256": expected_tree,
                    "original_tree_sha256": original_tree_sha256,
                }
            )
        if not root.exists():
            continue
        desired_ids = set(desired)
        for child in sorted(root.iterdir(), key=lambda item: item.name):
            if child.name in desired_ids or child.name.startswith("."):
                continue
            if child.is_symlink() or not child.is_dir():
                continue
            marker = load_marker(child)
            if marker is None or marker.get("owner") != MARKER_OWNER:
                continue
            validate_marker_identity(child, marker, target=target, skill_id=child.name)
            operations.append(
                {
                    "target": target,
                    "skill_id": child.name,
                    "version": marker.get("version"),
                    "action": "prune",
                    "destination": child,
                    "rendered": None,
                    "tree_sha256": marker.get("tree_sha256"),
                    "original_tree_sha256": backup_tree_sha256(child),
                }
            )
    return operations


def transaction_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def transaction_journal(
    transaction: str,
    expected_lock: dict[str, Any],
    selection: str,
    operations: list[dict[str, Any]],
    state_dir: Path,
) -> dict[str, Any]:
    entries = []
    for operation in operations:
        backup_relative = None
        backup_tree_sha256 = None
        if operation["action"] != "install":
            backup_relative = (
                Path("backups") / transaction / operation["target"] / operation["skill_id"]
            ).as_posix()
            backup_tree_sha256 = operation["original_tree_sha256"]
        entries.append(
            {
                "target": operation["target"],
                "skill_id": operation["skill_id"],
                "version": operation["version"],
                "action": operation["action"],
                "destination": str(operation["destination"]),
                "tree_sha256": operation["tree_sha256"],
                "backup": backup_relative,
                "backup_tree_sha256": backup_tree_sha256,
                "rollback_tree_sha256": None,
                "state": "planned",
            }
        )
    return {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "transaction_id": transaction,
        "status": "prepared",
        "registry_sha256": expected_lock["registry_sha256"],
        "selection": selection,
        "state_root": str(state_dir),
        "operations": entries,
    }


def journal_path(state_dir: Path, transaction: str) -> Path:
    if not TRANSACTION_ID_RE.fullmatch(transaction):
        fail("transaction id is invalid")
    return state_dir / "transactions" / f"{transaction}.json"


def validate_journal_data(
    journal: dict[str, Any], state_dir: Path, *, filename_transaction: str
) -> dict[str, Any]:
    required = {
        "schema_version",
        "transaction_id",
        "status",
        "registry_sha256",
        "selection",
        "state_root",
        "operations",
    }
    if set(journal) != required or journal.get("schema_version") != JOURNAL_SCHEMA_VERSION:
        fail("transaction journal schema is invalid")
    transaction = journal.get("transaction_id")
    if (
        not isinstance(transaction, str)
        or not TRANSACTION_ID_RE.fullmatch(transaction)
        or transaction != filename_transaction
    ):
        fail("transaction journal id does not match its filename")
    if journal.get("status") not in JOURNAL_STATUSES:
        fail("transaction journal status is invalid")
    if not isinstance(journal.get("registry_sha256"), str) or not HASH_RE.fullmatch(
        journal["registry_sha256"]
    ):
        fail("transaction journal registry hash is invalid")
    selection = journal.get("selection")
    if selection not in {"all", "claude", "codex"}:
        fail("transaction journal target selection is invalid")
    if journal.get("state_root") != str(configured_path(state_dir)):
        fail("transaction journal state root does not match the configured state root")
    operations = require_list(journal.get("operations"), "transaction operations")
    if not operations:
        fail("transaction journal must contain operations")
    roots = target_directories()
    seen: set[tuple[str, str]] = set()
    entry_fields = {
        "target",
        "skill_id",
        "version",
        "action",
        "destination",
        "tree_sha256",
        "backup",
        "backup_tree_sha256",
        "rollback_tree_sha256",
        "state",
    }
    operation_states: list[str] = []
    for index, raw_entry in enumerate(operations):
        entry = require_mapping(raw_entry, f"transaction operations[{index}]")
        if set(entry) != entry_fields:
            fail("transaction operation schema is invalid")
        target = entry.get("target")
        if target not in ALLOWED_TARGETS:
            fail("transaction journal target is invalid")
        if selection != "all" and target != selection:
            fail("transaction operation target does not match the single-target selection")
        skill_id = entry.get("skill_id")
        if not isinstance(skill_id, str) or not SKILL_ID_RE.fullmatch(skill_id):
            fail("transaction journal skill id is invalid")
        identity = (target, skill_id)
        if identity in seen:
            fail("transaction journal contains a duplicate operation")
        seen.add(identity)
        version = entry.get("version")
        if not isinstance(version, str):
            fail("transaction journal version is invalid")
        parse_semver(version)
        action = entry.get("action")
        if action not in {"install", "replace", "prune"}:
            fail("transaction journal action is invalid")
        expected_destination = configured_path(roots[target] / skill_id)
        destination_value = entry.get("destination")
        if not isinstance(destination_value, str) or configured_path(
            destination_value
        ) != expected_destination:
            fail("transaction destination does not match the configured target root")
        if not isinstance(entry.get("tree_sha256"), str) or not HASH_RE.fullmatch(
            entry["tree_sha256"]
        ):
            fail("transaction operation tree hash is invalid")
        expected_backup = None
        if action != "install":
            expected_backup = (
                Path("backups") / transaction / target / skill_id
            ).as_posix()
        if entry.get("backup") != expected_backup:
            fail("transaction backup path does not match the operation identity")
        backup_hash = entry.get("backup_tree_sha256")
        if backup_hash is not None and (
            not isinstance(backup_hash, str) or not HASH_RE.fullmatch(backup_hash)
        ):
            fail("transaction backup tree hash is invalid")
        if action == "install" and backup_hash is not None:
            fail("install transaction must not declare a backup hash")
        rollback_hash = entry.get("rollback_tree_sha256")
        if rollback_hash is not None and (
            not isinstance(rollback_hash, str) or not HASH_RE.fullmatch(rollback_hash)
        ):
            fail("transaction rollback tree hash is invalid")
        if action == "prune" and rollback_hash is not None:
            fail("prune transaction must not declare a rollback tree hash")
        if entry.get("state") not in OPERATION_STATES:
            fail("transaction operation state is invalid")
        operation_states.append(entry["state"])
    apply_states = {
        "planned",
        "backup_complete",
        "mutation_started",
        "destination_committed",
        "applied",
    }
    status_states = {
        "prepared": {"planned"},
        "applying": apply_states,
        "applied": {"applied"},
        "compensating": apply_states | {"compensating", "compensated"},
        "compensating_cleanup": {"compensated"},
        "compensation_failed": apply_states | {"compensating", "compensated"},
        "compensated": {"compensated"},
        "rollback_preparing": {"applied"},
        "rolling_back": {"applied", "rollback_started", "rolled_back"},
        "rollback_compensating_cleanup": {"applied"},
        "rollback_cleanup": {"rolled_back"},
        "rollback_failed": {"applied", "rollback_started", "rolled_back"},
        "rolled_back": {"rolled_back"},
    }
    allowed_states = status_states[journal["status"]]
    if any(state not in allowed_states for state in operation_states):
        fail("transaction journal status and operation state are inconsistent")
    nonprune_rollback_hashes = [
        entry["rollback_tree_sha256"]
        for entry in operations
        if entry["action"] != "prune"
    ]
    rollback_hash_statuses = {
        "rolling_back",
        "rollback_compensating_cleanup",
        "rollback_cleanup",
        "rollback_failed",
        "rolled_back",
    }
    if journal["status"] in rollback_hash_statuses:
        if any(value is None for value in nonprune_rollback_hashes):
            fail("transaction rollback snapshot hashes are incomplete")
    elif journal["status"] == "rollback_preparing":
        populated = [value is not None for value in nonprune_rollback_hashes]
        if any(populated) and not all(populated):
            fail("rollback preparation snapshot hashes are incomplete")
    elif any(value is not None for value in nonprune_rollback_hashes):
        fail("quiescent transaction must not retain rollback snapshot hashes")
    return journal


def read_journal(path: Path, state_dir: Path) -> dict[str, Any]:
    if path.suffix != ".json" or not TRANSACTION_ID_RE.fullmatch(path.stem):
        fail("transaction journal filename is invalid")
    journal = read_json(path, f"transaction journal {path.name}")
    return validate_journal_data(journal, state_dir, filename_transaction=path.stem)


def save_journal(state_dir: Path, journal: dict[str, Any]) -> None:
    transaction = journal.get("transaction_id")
    if not isinstance(transaction, str):
        fail("transaction journal id is invalid")
    validate_journal_data(journal, state_dir, filename_transaction=transaction)
    directory = state_dir / "transactions"
    secure_directory(directory)
    atomic_json(journal_path(state_dir, transaction), journal)


def reject_incomplete_transactions(state_dir: Path) -> None:
    directory = state_dir / "transactions"
    if not directory.exists():
        return
    for path in sorted(directory.glob("*.json")):
        journal = read_journal(path, state_dir)
        if journal.get("status") not in {"applied", "compensated", "rolled_back"}:
            fail(f"incomplete transaction requires recovery: {journal.get('transaction_id', path.stem)}")


def copy_directory(
    source: Path,
    destination: Path,
    context: str,
    *,
    pause_variable: str | None = None,
    pause_subject: Path | None = None,
) -> None:
    ensure_real_directory_tree(source, context)
    if destination.exists():
        fail(f"transaction path already exists: {destination.name}")
    paused = False

    def copy_file(source_file: str, destination_file: str) -> str:
        nonlocal paused
        copied = shutil.copy2(source_file, destination_file)
        if pause_variable is not None and not paused:
            paused = True
            pause_at_control_for_test(
                pause_variable,
                pause_subject if pause_subject is not None else destination,
            )
        return copied

    shutil.copytree(source, destination, copy_function=copy_file)


def write_rendered_stage(
    operation: dict[str, Any], transaction: str, expected_lock: dict[str, Any]
) -> tuple[Path, tuple[int, int]]:
    destination: Path = operation["destination"]
    root = destination.parent
    root.mkdir(parents=True, exist_ok=True)
    stage = root / f".stage-{transaction}-{operation['target']}-{operation['skill_id']}"
    if stage.exists():
        fail(f"staging path already exists for {operation['skill_id']}")
    stage.mkdir()
    stage_identity = real_directory_identity(stage, "render staging tree")
    try:
        pause_at_control_for_test(
            "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_RENDER_STAGE_CREATE",
            stage,
        )
        if not directory_has_identity(stage, stage_identity):
            fail(f"render staging identity changed for {operation['skill_id']}")
        for relative, (raw, executable) in operation["rendered"].items():
            path = stage.joinpath(*PurePosixPath(relative).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            path.chmod(0o755 if executable else 0o644)
        actual_tree = disk_tree_sha256(stage)
        if actual_tree != operation["tree_sha256"]:
            fail(f"rendered tree hash mismatch for {operation['skill_id']} ({operation['target']})")
        marker = {
            "schema_version": 1,
            "owner": MARKER_OWNER,
            "skill_id": operation["skill_id"],
            "target": operation["target"],
            "version": operation["version"],
            "registry_sha256": expected_lock["registry_sha256"],
            "tree_sha256": operation["tree_sha256"],
            "transaction_id": transaction,
        }
        atomic_json(stage / MARKER_NAME, marker)
        if not directory_has_identity(stage, stage_identity):
            fail(f"render staging identity changed for {operation['skill_id']}")
        return stage, stage_identity
    except Exception:
        if (
            stage.exists()
            and not stage.is_symlink()
            and stage.is_dir()
            and not directory_has_identity(stage, stage_identity)
        ):
            preserve_unexpected_directory(
                stage,
                destination,
                transaction,
                "stage-preserved",
                "concurrent render staging tree",
            )
        secure_remove_tree(
            stage.parent,
            stage.name,
            "render staging tree",
            expected_identity=stage_identity,
        )
        raise


def local_previous_path(destination: Path, transaction: str) -> Path:
    return destination.parent / f".backup-{transaction}-{destination.name}"


def rename_name_no_replace_at(
    directory_fd: int, source_name: str, destination_name: str
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        renameatx_np = getattr(libc, "renameatx_np", None)
        if renameatx_np is None:
            fail("safe directory mutation requires renameatx_np with RENAME_EXCL")
        renameatx_np.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameatx_np.restype = ctypes.c_int
        result = renameatx_np(
            directory_fd,
            os.fsencode(source_name),
            directory_fd,
            os.fsencode(destination_name),
            0x00000004,
        )
        if result == 0:
            return
        error_number = ctypes.get_errno()
        if error_number in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
            fail("safe directory mutation requires renameatx_np with RENAME_EXCL")
        raise OSError(error_number, os.strerror(error_number), destination_name)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        fail("safe directory mutation requires renameat2 with RENAME_NOREPLACE")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        directory_fd,
        os.fsencode(source_name),
        directory_fd,
        os.fsencode(destination_name),
        1,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
        fail("safe directory mutation requires renameat2 with RENAME_NOREPLACE")
    raise OSError(error_number, os.strerror(error_number), destination_name)


@contextmanager
def open_directory_no_follow(path: Path, context: str):
    descriptors = directory_fd_chain_no_follow(path, context)
    try:
        yield descriptors[-1]
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def rename_directory_no_replace(source: Path, destination: Path) -> None:
    """Atomically rename same-parent directories through a held no-follow dirfd."""

    source = configured_path(source)
    destination = configured_path(destination)
    if source.parent != destination.parent:
        fail("safe directory mutation requires a shared parent")
    with open_directory_no_follow(source.parent, "directory rename parent") as parent_fd:
        rename_name_no_replace_at(parent_fd, source.name, destination.name)


def pause_at_control_for_test(variable: str, subject: Path) -> None:
    """Deterministic test interposition; never enabled without an explicit test variable."""

    control_value = os.environ.pop(variable, None)
    if not control_value:
        return
    control = configured_path(control_value)
    control.mkdir(parents=True, exist_ok=True)
    atomic_write(control / "ready", (str(subject) + "\n").encode("utf-8"), mode=0o600)
    deadline = time.monotonic() + 10.0
    while not (control / "continue").exists():
        if time.monotonic() >= deadline:
            fail("test detach interposition timed out")
        time.sleep(0.01)


def pause_before_detach_for_test(destination: Path) -> None:
    pause_at_control_for_test(
        "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_BEFORE_DETACH", destination
    )


def restore_detached_without_overwrite(detached: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        fail(f"concurrent destination appeared while restoring {destination.name}")
    rename_directory_no_replace(detached, destination)


def real_directory_identity(path: Path, context: str) -> tuple[int, int]:
    try:
        path_stat = os.lstat(path)
    except OSError as exc:
        raise RegistryError(f"{context} is unavailable") from exc
    if not stat.S_ISDIR(path_stat.st_mode):
        fail(f"{context} must be a real directory")
    return path_stat.st_dev, path_stat.st_ino


def directory_has_identity(path: Path, expected: tuple[int, int]) -> bool:
    try:
        path_stat = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(path_stat.st_mode) and (
        path_stat.st_dev,
        path_stat.st_ino,
    ) == expected


def atomic_replace_directory(
    destination: Path,
    replacement: Path,
    transaction: str,
    expected_existing_hash: str | None,
) -> Path | None:
    previous = destination.parent / f".backup-{transaction}-{destination.name}"
    if previous.exists() or previous.is_symlink():
        fail(f"temporary backup already exists for {destination.name}")
    pause_before_detach_for_test(destination)
    if destination.exists() or destination.is_symlink():
        if expected_existing_hash is None:
            fail(f"destination appeared concurrently for {destination.name}")
        rename_directory_no_replace(destination, previous)
        if (
            previous.is_symlink()
            or not previous.is_dir()
            or backup_tree_sha256(previous) != expected_existing_hash
        ):
            restore_detached_without_overwrite(previous, destination)
            fail(f"destination changed concurrently for {destination.name}")
        pause_at_control_for_test(
            "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_APPLY_ORIGINAL_DETACH",
            destination,
        )
        pause_at_control_for_test(
            "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_BEFORE_RENDER_COMMIT",
            replacement,
        )
        try:
            rename_directory_no_replace(replacement, destination)
        except Exception:
            if not destination.exists() and not destination.is_symlink():
                restore_detached_without_overwrite(previous, destination)
            raise
        pause_at_control_for_test(
            "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_RENDER_RENAME",
            replacement,
        )
        return previous
    if expected_existing_hash is not None:
        fail(f"destination disappeared concurrently for {destination.name}")
    pause_at_control_for_test(
        "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_BEFORE_RENDER_COMMIT",
        replacement,
    )
    rename_directory_no_replace(replacement, destination)
    pause_at_control_for_test(
        "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_RENDER_RENAME",
        replacement,
    )
    return None


def atomic_remove_directory(
    destination: Path, transaction: str, expected_existing_hash: str
) -> Path:
    previous = destination.parent / f".backup-{transaction}-{destination.name}"
    if previous.exists() or previous.is_symlink():
        fail(f"temporary backup already exists for {destination.name}")
    pause_before_detach_for_test(destination)
    if not destination.exists() and not destination.is_symlink():
        fail(f"destination disappeared concurrently for {destination.name}")
    rename_directory_no_replace(destination, previous)
    if (
        previous.is_symlink()
        or not previous.is_dir()
        or backup_tree_sha256(previous) != expected_existing_hash
    ):
        restore_detached_without_overwrite(previous, destination)
        fail(f"destination changed concurrently for {destination.name}")
    pause_at_control_for_test(
        "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_APPLY_ORIGINAL_DETACH",
        destination,
    )
    return previous


def apply_operation(
    operation: dict[str, Any],
    index: int,
    transaction: str,
    journal: dict[str, Any],
    state_dir: Path,
    expected_lock: dict[str, Any],
) -> None:
    entry = journal["operations"][index]
    destination: Path = operation["destination"]
    if entry["backup"] is not None:
        backup = state_dir.joinpath(*PurePosixPath(entry["backup"]).parts)
        secure_directory(backup.parent)
        copy_directory(destination, backup, f"destination backup for {operation['skill_id']}")
        captured_backup_hash = backup_tree_sha256(backup)
        if (
            captured_backup_hash != entry["backup_tree_sha256"]
            or captured_backup_hash != operation["original_tree_sha256"]
        ):
            fail(f"destination changed while backing up {operation['skill_id']}")
        entry["state"] = "backup_complete"
        save_journal(state_dir, journal)
    stage = None
    rendered_stage_identity: tuple[int, int] | None = None
    if operation["action"] != "prune":
        stage, rendered_stage_identity = write_rendered_stage(
            operation, transaction, expected_lock
        )
        pause_at_control_for_test(
            "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_RENDER_STAGE_RETURN",
            stage,
        )
    entry["state"] = "mutation_started"
    save_journal(state_dir, journal)
    previous = None
    if operation["action"] == "prune":
        previous = atomic_remove_directory(
            destination, transaction, entry["backup_tree_sha256"]
        )
    else:
        assert stage is not None
        assert rendered_stage_identity is not None
        committed_identity = rendered_stage_identity
        try:
            try:
                previous = atomic_replace_directory(
                    destination,
                    stage,
                    transaction,
                    entry["backup_tree_sha256"],
                )
            except Exception:
                if (
                    stage.exists()
                    and not stage.is_symlink()
                    and stage.is_dir()
                    and not directory_has_identity(stage, committed_identity)
                ):
                    concurrent_identity = real_directory_identity(
                        stage, "concurrent render staging tree"
                    )
                    preserved_stage = transaction_detached_path(
                        destination, transaction, "stage-preserved"
                    )
                    if preserved_stage.exists() or preserved_stage.is_symlink():
                        fail(
                            f"stage preservation path already exists for "
                            f"{operation['skill_id']}"
                        )
                    rename_directory_no_replace(stage, preserved_stage)
                    if not directory_has_identity(
                        preserved_stage, concurrent_identity
                    ):
                        if not stage.exists() and not stage.is_symlink():
                            restore_detached_without_overwrite(
                                preserved_stage, stage
                            )
                        fail(
                            f"concurrent stage changed while preserving "
                            f"{operation['skill_id']}"
                        )
                raise
        finally:
            if (
                stage.exists()
                and not stage.is_symlink()
                and stage.is_dir()
                and not directory_has_identity(stage, committed_identity)
            ):
                preserve_unexpected_directory(
                    stage,
                    destination,
                    transaction,
                    "stage-preserved",
                    "recreated render staging tree",
                )
                fail(
                    f"recreated render staging tree preserved for "
                    f"{operation['skill_id']}"
                )
            secure_remove_tree(
                stage.parent,
                stage.name,
                "render staging tree",
                expected_identity=committed_identity,
            )
        pause_at_control_for_test(
            "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_RENDER_COMMIT",
            destination,
        )
        try:
            if not directory_has_identity(destination, committed_identity):
                fail(
                    f"committed destination identity changed for "
                    f"{operation['skill_id']}"
                )
            validate_expected_transaction_tree(
                journal,
                entry,
                destination,
                require_destination_name=True,
            )
        except Exception:
            failed_commit = transaction_detached_path(
                destination, transaction, "failed-commit"
            )
            if directory_has_identity(destination, committed_identity):
                rename_directory_no_replace(destination, failed_commit)
                if not directory_has_identity(failed_commit, committed_identity):
                    if not destination.exists() and not destination.is_symlink():
                        restore_detached_without_overwrite(failed_commit, destination)
                    fail(
                        f"committed destination changed concurrently for "
                        f"{operation['skill_id']}"
                    )
                if previous is not None:
                    restore_detached_without_overwrite(previous, destination)
                    previous = None
                secure_remove_tree(
                    failed_commit.parent,
                    failed_commit.name,
                    "failed committed render tree",
                    expected_identity=committed_identity,
                )
            elif (
                destination.exists()
                and not destination.is_symlink()
                and destination.is_dir()
            ):
                concurrent_identity = real_directory_identity(
                    destination, "concurrent committed destination"
                )
                preserved = transaction_detached_path(
                    destination, transaction, "concurrent-preserved"
                )
                if preserved.exists() or preserved.is_symlink():
                    fail(
                        f"concurrent preservation path already exists for "
                        f"{operation['skill_id']}"
                    )
                rename_directory_no_replace(destination, preserved)
                if not directory_has_identity(preserved, concurrent_identity):
                    if not destination.exists() and not destination.is_symlink():
                        restore_detached_without_overwrite(preserved, destination)
                    fail(
                        f"concurrent destination changed while preserving "
                        f"{operation['skill_id']}"
                    )
                if previous is not None:
                    restore_detached_without_overwrite(previous, destination)
                    previous = None
                fail(
                    f"concurrent replacement preserved for manual recovery: "
                    f"{operation['skill_id']}"
                )
            raise
    entry["state"] = "destination_committed"
    save_journal(state_dir, journal)
    if previous is not None:
        if (
            previous.is_symlink()
            or not previous.is_dir()
            or backup_tree_sha256(previous) != entry["backup_tree_sha256"]
        ):
            fail(f"temporary backup drift detected for {operation['skill_id']}")
        secure_remove_tree(previous.parent, previous.name, "temporary destination backup")
    entry["state"] = "applied"
    save_journal(state_dir, journal)


DETACHED_ROLES = {
    "apply-compensation": "apply-detached",
    "concurrent-preserved": "concurrent-preserved",
    "failed-commit": "failed-commit",
    "rollback-applied": "rollback-applied",
    "rollback-original": "rollback-restored-original",
    "restore-stage-preserved": "restore-stage-preserved",
    "stage-preserved": "stage-preserved",
}


def transaction_detached_path(
    destination: Path, transaction: str, role: str
) -> Path:
    label = DETACHED_ROLES.get(role)
    if label is None:
        fail("transaction detached-tree role is invalid")
    return destination.parent / f".shogun-{label}-{transaction}-{destination.name}"


def preserve_unexpected_directory(
    source: Path,
    destination: Path,
    transaction: str,
    role: str,
    context: str,
) -> Path:
    source_identity = real_directory_identity(source, context)
    preserved = transaction_detached_path(destination, transaction, role)
    if preserved.exists() or preserved.is_symlink():
        fail(f"{context} preservation path already exists")
    rename_directory_no_replace(source, preserved)
    if not directory_has_identity(preserved, source_identity):
        if not source.exists() and not source.is_symlink():
            restore_detached_without_overwrite(preserved, source)
        fail(f"{context} changed while preserving it")
    return preserved


def remove_destination_for_restore(
    destination: Path,
    transaction: str,
    expected_current_hash: str | None,
    role: str,
) -> Path | None:
    if expected_current_hash is None:
        if destination.exists() or destination.is_symlink():
            fail(f"destination appeared concurrently for {destination.name}")
        return None
    if not destination.exists() and not destination.is_symlink():
        fail(f"destination disappeared concurrently for {destination.name}")
    temporary = transaction_detached_path(destination, transaction, role)
    if temporary.exists() or temporary.is_symlink():
        fail(f"restore temporary path already exists for {destination.name}")
    pause_before_detach_for_test(destination)
    rename_directory_no_replace(destination, temporary)
    if (
        temporary.is_symlink()
        or not temporary.is_dir()
        or backup_tree_sha256(temporary) != expected_current_hash
    ):
        restore_detached_without_overwrite(temporary, destination)
        fail(f"destination changed concurrently for {destination.name}")
    return temporary
def restore_backup(
    destination: Path, backup: Path, transaction: str, expected_backup_hash: str
) -> None:
    stage = restore_stage_path(destination, transaction)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage_identity: tuple[int, int] | None = None
    try:
        if stage.exists() or stage.is_symlink():
            if stage.is_symlink() or not stage.is_dir():
                fail(f"restore staging path is unsafe for {destination.name}")
            stage_identity = real_directory_identity(stage, "restore staging tree")
            if backup_tree_sha256(stage) != expected_backup_hash:
                secure_remove_tree(
                    stage.parent,
                    stage.name,
                    "partial restore staging tree",
                    expected_identity=stage_identity,
                )
                stage_identity = None
        if not stage.exists():
            copy_directory(
                backup,
                stage,
                f"transaction backup for {destination.name}",
                pause_variable="SHOGUN_SKILL_REGISTRY_TEST_PAUSE_DURING_RESTORE_COPY",
                pause_subject=destination,
            )
            stage_identity = real_directory_identity(stage, "restore staging tree")
        if backup_tree_sha256(stage) != expected_backup_hash:
            fail(f"restore staging hash mismatch for {destination.name}")
        rename_directory_no_replace(stage, destination)
        pause_at_control_for_test(
            "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_RESTORE_COMMIT",
            stage,
        )
        if stage_identity is None or not directory_has_identity(
            destination, stage_identity
        ):
            fail(f"restored destination identity changed for {destination.name}")
        if backup_tree_sha256(destination) != expected_backup_hash:
            fail(f"restored backup hash mismatch for {destination.name}")
    finally:
        if stage_identity is not None:
            if (
                stage.exists()
                and not stage.is_symlink()
                and stage.is_dir()
                and not directory_has_identity(stage, stage_identity)
            ):
                preserve_unexpected_directory(
                    stage,
                    destination,
                    transaction,
                    "restore-stage-preserved",
                    "recreated restore staging tree",
                )
                fail(f"recreated restore staging tree preserved for {destination.name}")
            secure_remove_tree(
                stage.parent,
                stage.name,
                "restore staging tree",
                expected_identity=stage_identity,
            )


def restore_stage_path(destination: Path, transaction: str) -> Path:
    return destination.parent / f".stage-{transaction}-restore-{destination.name}"


def transaction_artifact_paths(
    entry: dict[str, Any], destination: Path, transaction: str
) -> list[Path]:
    return [
        destination.parent
        / f".stage-{transaction}-{entry['target']}-{entry['skill_id']}",
        restore_stage_path(destination, transaction),
        local_previous_path(destination, transaction),
        transaction_detached_path(destination, transaction, "apply-compensation"),
        transaction_detached_path(destination, transaction, "concurrent-preserved"),
        transaction_detached_path(destination, transaction, "failed-commit"),
        transaction_detached_path(destination, transaction, "rollback-applied"),
        transaction_detached_path(destination, transaction, "rollback-original"),
        transaction_detached_path(
            destination, transaction, "restore-stage-preserved"
        ),
        transaction_detached_path(destination, transaction, "stage-preserved"),
        rollback_original_path(destination, transaction, entry["skill_id"]),
    ]


def artifact_or_tombstone_exists(path: Path) -> bool:
    if path.exists() or path.is_symlink():
        return True
    if not path.parent.is_dir() or path.parent.is_symlink():
        return False
    prefix = f".shogun-discard-{path.name}-d"
    return any(child.name.startswith(prefix) for child in path.parent.iterdir())


def validate_no_target_transaction_artifacts(journal: dict[str, Any]) -> None:
    transaction = journal["transaction_id"]
    for entry in journal["operations"]:
        destination = configured_path(entry["destination"])
        for artifact in transaction_artifact_paths(entry, destination, transaction):
            if artifact_or_tombstone_exists(artifact):
                fail(f"transaction target artifact remains: {entry['skill_id']}")


def validate_destination_intent(journal: dict[str, Any], intent: str) -> None:
    if intent not in {"preapply", "applied", "rolled_back"}:
        fail("terminal destination validation intent is invalid")
    pause_at_control_for_test(
        "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_BEFORE_TERMINAL_VALIDATION",
        configured_path(journal["operations"][0]["destination"]),
    )
    for entry in journal["operations"]:
        destination = configured_path(entry["destination"])
        action = entry["action"]
        if intent == "applied":
            if action == "prune":
                if destination.exists() or destination.is_symlink():
                    fail(f"recovered prune destination remains: {entry['skill_id']}")
                continue
            if destination.is_symlink() or not destination.is_dir():
                fail(f"recovered applied destination is missing: {entry['skill_id']}")
            validate_expected_transaction_tree(
                journal,
                entry,
                destination,
                require_destination_name=True,
            )
            continue
        should_be_absent = action == "install"
        if should_be_absent:
            if destination.exists() or destination.is_symlink():
                fail(f"recovered install destination remains: {entry['skill_id']}")
            continue
        expected_hash = entry.get("backup_tree_sha256")
        if not isinstance(expected_hash, str):
            fail(f"recovered destination backup hash is missing: {entry['skill_id']}")
        if (
            destination.is_symlink()
            or not destination.is_dir()
            or backup_tree_sha256(destination) != expected_hash
        ):
            fail(f"recovered original destination drift detected: {entry['skill_id']}")


def validate_terminal_destinations(journal: dict[str, Any], intent: str) -> None:
    validate_destination_intent(journal, intent)
    validate_no_target_transaction_artifacts(journal)


def validated_backup(entry: dict[str, Any], state_dir: Path) -> Path:
    backup_value = entry.get("backup")
    expected_hash = entry.get("backup_tree_sha256")
    if not isinstance(backup_value, str) or not isinstance(expected_hash, str):
        fail(f"transaction backup metadata is incomplete: {entry['skill_id']}")
    backup = state_dir.joinpath(*PurePosixPath(backup_value).parts)
    if not backup.is_dir() or backup.is_symlink():
        fail(f"transaction backup is missing: {entry['skill_id']}")
    if backup_tree_sha256(backup) != expected_hash:
        fail(f"transaction backup drift detected: {entry['skill_id']}")
    return backup


def validated_detached_apply_tree(
    journal: dict[str, Any], entry: dict[str, Any], destination: Path
) -> Path | None:
    """Return a verified tree detached by interrupted apply compensation."""

    transaction = journal["transaction_id"]
    detached = transaction_detached_path(
        destination, transaction, "apply-compensation"
    )
    if not detached.exists() and not detached.is_symlink():
        return None
    if detached.is_symlink() or not detached.is_dir():
        fail(f"detached apply tree is unsafe: {entry['skill_id']}")
    if entry["action"] not in {"install", "replace"}:
        fail(f"unexpected detached apply tree: {entry['skill_id']}")
    marker = load_marker(detached)
    if marker is None:
        fail(f"detached apply tree has no ownership marker: {entry['skill_id']}")
    validate_expected_transaction_tree(journal, entry, detached, marker)
    return detached


def validate_expected_transaction_tree(
    journal: dict[str, Any],
    entry: dict[str, Any],
    path: Path,
    marker: dict[str, Any] | None = None,
    *,
    require_destination_name: bool = False,
) -> None:
    if marker is None:
        marker = load_marker(path)
    if marker is None:
        fail(f"managed transaction tree has no ownership marker: {entry['skill_id']}")
    expected_marker = {
        "transaction_id": journal["transaction_id"],
        "target": entry["target"],
        "skill_id": entry["skill_id"],
        "version": entry["version"],
        "registry_sha256": journal["registry_sha256"],
        "tree_sha256": entry["tree_sha256"],
    }
    if any(marker.get(key) != value for key, value in expected_marker.items()):
        fail(f"managed transaction tree ownership mismatch: {entry['skill_id']}")
    validate_managed_tree(path, marker)
    if require_destination_name and path.name != entry["skill_id"]:
        fail(f"managed destination path mismatch: {path.name}")


def reconcile_detached_apply_compensation(
    journal: dict[str, Any],
    entry: dict[str, Any],
    destination: Path,
    previous: Path,
    state_dir: Path,
) -> None:
    """Finish a compensation step interrupted after its destination detach."""

    detached = validated_detached_apply_tree(journal, entry, destination)
    if detached is None:
        return
    if entry["action"] == "install":
        if destination.exists() or destination.is_symlink():
            fail(f"cannot reconcile a later install destination: {entry['skill_id']}")
        secure_remove_tree(detached.parent, detached.name, "detached installed tree")
        return

    backup = validated_backup(entry, state_dir)
    expected_hash = entry["backup_tree_sha256"]
    if previous.exists() or previous.is_symlink():
        if (
            previous.is_symlink()
            or not previous.is_dir()
            or backup_tree_sha256(previous) != expected_hash
        ):
            fail(f"local transaction backup drift detected: {entry['skill_id']}")
    if destination.exists() or destination.is_symlink():
        if (
            destination.is_symlink()
            or not destination.is_dir()
            or backup_tree_sha256(destination) != expected_hash
        ):
            fail(f"cannot reconcile changed destination: {entry['skill_id']}")
    else:
        restore_backup(destination, backup, journal["transaction_id"], expected_hash)
    # Remove the duplicate original before the detached applied tree.  A crash
    # between these operations is therefore safely recognizable on the retry.
    if previous.exists():
        secure_remove_tree(previous.parent, previous.name, "local transaction backup")
    secure_remove_tree(detached.parent, detached.name, "detached managed tree")


def compensate_apply(journal: dict[str, Any], state_dir: Path) -> None:
    transaction = journal["transaction_id"]
    if journal.get("status") == "compensating_cleanup":
        validate_terminal_destinations(journal, "preapply")
        secure_remove_tree(
            state_dir,
            Path("backups") / transaction,
            "transaction backup tree",
        )
        pause_at_control_for_test(
            "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_APPLY_COMPENSATION_ARTIFACT_CLEANUP",
            state_dir / "backups" / transaction,
        )
        validate_terminal_destinations(journal, "preapply")
        journal["status"] = "compensated"
        save_journal(state_dir, journal)
        return
    journal["status"] = "compensating"
    save_journal(state_dir, journal)
    for entry in reversed(journal["operations"]):
        destination = configured_path(entry["destination"])
        stage = destination.parent / (
            f".stage-{transaction}-{entry['target']}-{entry['skill_id']}"
        )
        if entry.get("state") in {"planned", "backup_complete", "compensated"}:
            if stage.exists() or stage.is_symlink():
                if stage.is_symlink() or not stage.is_dir():
                    fail(f"invalid transaction staging path: {entry['skill_id']}")
            secure_remove_tree(stage.parent, stage.name, "render staging tree")
            restore_stage = restore_stage_path(destination, transaction)
            secure_remove_tree(
                restore_stage.parent, restore_stage.name, "restore staging tree"
            )
            failed_commit = transaction_detached_path(
                destination, transaction, "failed-commit"
            )
            secure_remove_tree(
                failed_commit.parent, failed_commit.name, "failed committed render tree"
            )
            if entry.get("state") != "compensated":
                entry["state"] = "compensated"
                save_journal(state_dir, journal)
            continue
        entry["state"] = "compensating"
        save_journal(state_dir, journal)
        previous = local_previous_path(destination, transaction)
        if previous.exists() or previous.is_symlink():
            if previous.is_symlink() or not previous.is_dir():
                fail(f"invalid local transaction backup: {entry['skill_id']}")
        reconcile_detached_apply_compensation(
            journal, entry, destination, previous, state_dir
        )
        if entry["action"] == "install":
            if previous.exists():
                fail(f"unexpected local backup for install: {entry['skill_id']}")
            detached = None
            if destination.exists():
                marker = load_marker(destination)
                validate_expected_transaction_tree(
                    journal,
                    entry,
                    destination,
                    marker,
                    require_destination_name=True,
                )
                current_hash = backup_tree_sha256(destination)
                detached = remove_destination_for_restore(
                    destination,
                    transaction,
                    current_hash,
                    "apply-compensation",
                )
            if detached is not None:
                pause_at_control_for_test(
                    "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_COMPENSATION_DETACH",
                    destination,
                )
            detached_path = transaction_detached_path(
                destination, transaction, "apply-compensation"
            )
            secure_remove_tree(
                detached_path.parent, detached_path.name, "detached installed tree"
            )
        else:
            detached = None
            backup = validated_backup(entry, state_dir)
            expected_hash = entry["backup_tree_sha256"]
            already_original = False
            if destination.exists():
                destination_hash = backup_tree_sha256(destination)
                if destination_hash == expected_hash and previous.exists():
                    if backup_tree_sha256(previous) != expected_hash:
                        fail(f"local transaction backup drift detected: {entry['skill_id']}")
                    secure_remove_tree(
                        previous.parent,
                        previous.name,
                        "duplicate local transaction backup",
                    )
                already_original = destination_hash == expected_hash
                if not already_original:
                    if entry["action"] == "prune":
                        fail(f"cannot compensate a later pruned destination: {entry['skill_id']}")
                    marker = load_marker(destination)
                    validate_expected_transaction_tree(
                        journal,
                        entry,
                        destination,
                        marker,
                        require_destination_name=True,
                    )
                    if previous.exists() and backup_tree_sha256(previous) != expected_hash:
                        fail(f"local transaction backup drift detected: {entry['skill_id']}")
            if not already_original:
                current_hash = (
                    backup_tree_sha256(destination)
                    if destination.exists() and not destination.is_symlink()
                    else None
                )
                detached = remove_destination_for_restore(
                    destination,
                    transaction,
                    current_hash,
                    "apply-compensation",
                )
                if detached is not None:
                    pause_at_control_for_test(
                        "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_COMPENSATION_DETACH",
                        destination,
                    )
                try:
                    restore_backup(destination, backup, transaction, expected_hash)
                    pause_at_control_for_test(
                        "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_APPLY_COMPENSATION_RESTORE",
                        destination,
                    )
                except Exception:
                    if detached is not None and not destination.exists() and not destination.is_symlink():
                        restore_detached_without_overwrite(detached, destination)
                    raise
            if previous.exists():
                if backup_tree_sha256(previous) != expected_hash:
                    fail(f"local transaction backup drift detected: {entry['skill_id']}")
            secure_remove_tree(previous.parent, previous.name, "local transaction backup")
            detached_path = transaction_detached_path(
                destination, transaction, "apply-compensation"
            )
            secure_remove_tree(
                detached_path.parent, detached_path.name, "detached managed tree"
            )
        if stage.exists() or stage.is_symlink():
            if stage.is_symlink() or not stage.is_dir():
                fail(f"invalid transaction staging path: {entry['skill_id']}")
        secure_remove_tree(stage.parent, stage.name, "render staging tree")
        restore_stage = restore_stage_path(destination, transaction)
        secure_remove_tree(
            restore_stage.parent, restore_stage.name, "restore staging tree"
        )
        failed_commit = transaction_detached_path(
            destination, transaction, "failed-commit"
        )
        secure_remove_tree(
            failed_commit.parent, failed_commit.name, "failed committed render tree"
        )
        entry["state"] = "compensated"
        save_journal(state_dir, journal)
    validate_terminal_destinations(journal, "preapply")
    journal["status"] = "compensating_cleanup"
    save_journal(state_dir, journal)
    secure_remove_tree(
        state_dir,
        Path("backups") / transaction,
        "transaction backup tree",
    )
    pause_at_control_for_test(
        "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_APPLY_COMPENSATION_ARTIFACT_CLEANUP",
        state_dir / "backups" / transaction,
    )
    validate_terminal_destinations(journal, "preapply")
    journal["status"] = "compensated"
    save_journal(state_dir, journal)


def execute_apply(
    validated: dict[str, Any], expected_lock: dict[str, Any], selection: str
) -> None:
    state_dir = state_directory()
    roots = validate_runtime_roots(
        state_dir,
        validated["registry_path"],
        set(selected_targets(selection)),
    )
    with mutation_lock(state_dir, roots):
        reject_incomplete_transactions(state_dir)
        fresh_validated = validate_registry(validated["registry_path"])
        fresh_expected = build_lock(fresh_validated)
        if yaml_bytes(fresh_expected) != yaml_bytes(expected_lock):
            fail("registry changed while waiting for the mutation lock")
        operations = plan_apply(fresh_validated, fresh_expected, selection, roots)
        if not operations:
            print("OK: registry targets already synchronized; start a new session only after changes")
            return
        transaction = transaction_id()
        journal = transaction_journal(transaction, fresh_expected, selection, operations, state_dir)
        save_journal(state_dir, journal)
        pause_at_control_for_test(
            "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_PREPARED_JOURNAL",
            journal_path(state_dir, transaction),
        )
        journal["status"] = "applying"
        save_journal(state_dir, journal)
        try:
            current_target = None
            for index, operation in enumerate(operations):
                if current_target is not None and operation["target"] != current_target:
                    if os.environ.get("SHOGUN_SKILL_REGISTRY_TEST_FAIL_AFTER_TARGET") == current_target:
                        raise RegistryError(f"injected failure after target {current_target}")
                current_target = operation["target"]
                apply_operation(
                    operation, index, transaction, journal, state_dir, fresh_expected
                )
            if (
                current_target is not None
                and os.environ.get("SHOGUN_SKILL_REGISTRY_TEST_FAIL_AFTER_TARGET") == current_target
            ):
                raise RegistryError(f"injected failure after target {current_target}")
        except Exception as exc:
            try:
                compensate_apply(journal, state_dir)
            except Exception as compensation_error:
                if journal.get("status") != "compensating_cleanup":
                    journal["status"] = "compensation_failed"
                    save_journal(state_dir, journal)
                raise OSError(
                    f"transaction {transaction} failed and compensation failed: {compensation_error}"
                ) from exc
            raise RegistryError(
                f"{exc}; transaction {transaction} compensated"
            ) from exc
        validate_terminal_destinations(journal, "applied")
        journal["status"] = "applied"
        save_journal(state_dir, journal)
        print(f"OK: skills applied; transaction={transaction}; start a new CLI session")


def latest_applied_journal(state_dir: Path, requested: str | None) -> tuple[Path, dict[str, Any]]:
    transactions = state_dir / "transactions"
    if requested:
        if not TRANSACTION_ID_RE.fullmatch(requested):
            fail("transaction id is invalid")
        path = transactions / f"{requested}.json"
        journal = read_journal(path, state_dir)
        if journal.get("status") != "applied":
            fail(f"transaction is not applied: {requested}")
        return path, journal
    candidates = []
    if transactions.exists():
        for path in sorted(transactions.glob("*.json"), reverse=True):
            journal = read_journal(path, state_dir)
            if journal.get("status") == "applied":
                candidates.append((path, journal))
    if not candidates:
        fail("no applied skill registry transaction is available to roll back")
    return candidates[0]


def validate_rollback_destination(
    entry: dict[str, Any],
    transaction: str,
    state_dir: Path,
    roots: dict[str, Path],
    registry_sha256: str,
) -> tuple[Path, Path | None, str | None]:
    target = entry.get("target")
    skill_id = entry["skill_id"]
    destination = configured_path(entry["destination"])
    expected_destination = configured_path(roots[target] / skill_id)
    if destination != expected_destination:
        fail("transaction destination does not match configured target root")
    backup = None
    preflight_hash = None
    if entry.get("backup"):
        backup = validated_backup(entry, state_dir)
    if entry.get("action") == "prune":
        if destination.exists() or destination.is_symlink():
            fail(f"pruned destination was replaced later: {skill_id}")
    else:
        if not destination.is_dir() or destination.is_symlink():
            fail(f"managed destination is missing or replaced: {skill_id}")
        marker = load_marker(destination)
        if marker is None or (
            marker.get("transaction_id") != transaction
            or marker.get("version") != entry["version"]
            or marker.get("tree_sha256") != entry["tree_sha256"]
            or marker.get("registry_sha256") != registry_sha256
        ):
            fail(f"managed destination ownership changed: {skill_id}")
        validate_marker_identity(
            destination, marker, target=target, skill_id=skill_id
        )
        preflight_hash = backup_tree_sha256(destination)
    return destination, backup, preflight_hash


def rollback_snapshot_path(
    state_dir: Path, transaction: str, entry: dict[str, Any]
) -> Path:
    return state_dir / "rollback-backups" / transaction / entry["target"] / entry["skill_id"]


def prepare_rollback_snapshots(
    journal: dict[str, Any],
    state_dir: Path,
    prepared: list[tuple[dict[str, Any], Path, Path | None, str | None]],
) -> None:
    transaction = journal["transaction_id"]
    snapshot_root = state_dir / "rollback-backups" / transaction
    if snapshot_root.exists() or snapshot_root.is_symlink():
        if snapshot_root.is_symlink() or not snapshot_root.is_dir():
            fail(f"rollback snapshot path is invalid: {transaction}")
        hashes_present = [
            entry.get("rollback_tree_sha256") is not None
            for entry, _destination, _backup, _preflight_hash in prepared
            if entry["action"] != "prune"
        ]
        if hashes_present and all(hashes_present):
            for entry, _destination, _backup, preflight_hash in prepared:
                if entry["action"] == "prune":
                    continue
                snapshot = rollback_snapshot_path(state_dir, transaction, entry)
                if (
                    not snapshot.is_dir()
                    or snapshot.is_symlink()
                    or backup_tree_sha256(snapshot) != entry["rollback_tree_sha256"]
                    or entry["rollback_tree_sha256"] != preflight_hash
                ):
                    fail(f"rollback snapshot drift detected: {entry['skill_id']}")
            return
        if any(hashes_present):
            fail(f"rollback snapshot metadata is incomplete: {transaction}")
        secure_remove_tree(
            state_dir,
            Path("rollback-backups") / transaction,
            "rollback snapshot tree",
        )
    hashes: list[tuple[dict[str, Any], str | None]] = []
    try:
        for entry, destination, _backup, preflight_hash in prepared:
            if entry["action"] == "prune":
                hashes.append((entry, None))
                continue
            snapshot = rollback_snapshot_path(state_dir, transaction, entry)
            secure_directory(snapshot.parent)
            pause_at_control_for_test(
                "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_BEFORE_ROLLBACK_SNAPSHOT",
                destination,
            )
            copy_directory(
                destination,
                snapshot,
                f"rollback snapshot for {entry['skill_id']}",
                pause_variable="SHOGUN_SKILL_REGISTRY_TEST_PAUSE_DURING_ROLLBACK_SNAPSHOT_COPY",
                pause_subject=destination,
            )
            snapshot_hash = backup_tree_sha256(snapshot)
            if snapshot_hash != preflight_hash:
                fail(f"rollback destination changed before snapshot: {entry['skill_id']}")
            hashes.append((entry, snapshot_hash))
    except Exception:
        secure_remove_tree(
            state_dir,
            Path("rollback-backups") / transaction,
            "rollback snapshot tree",
        )
        raise
    for entry, snapshot_hash in hashes:
        entry["rollback_tree_sha256"] = snapshot_hash
    save_journal(state_dir, journal)
    pause_at_control_for_test(
        "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_SNAPSHOT_JOURNAL",
        state_dir / "rollback-backups" / transaction,
    )


def optional_tree_hash(path: Path, context: str) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_dir():
        fail(f"{context} must be a real directory")
    return backup_tree_sha256(path)


def rollback_original_path(destination: Path, transaction: str, skill_id: str) -> Path:
    return destination.parent / f".shogun-rollback-original-{transaction}-{skill_id}"


def compensate_prune_rollback(
    entry: dict[str, Any], destination: Path, transaction: str, state_dir: Path
) -> None:
    validated_backup(entry, state_dir)
    expected_hash = entry["backup_tree_sha256"]
    detached = transaction_detached_path(destination, transaction, "rollback-original")
    destination_hash = optional_tree_hash(
        destination, f"prune rollback destination for {entry['skill_id']}"
    )
    detached_hash = optional_tree_hash(
        detached, f"detached prune rollback tree for {entry['skill_id']}"
    )
    if detached_hash is not None:
        if detached_hash != expected_hash:
            fail(f"detached prune rollback tree drift detected: {entry['skill_id']}")
        if destination_hash is not None:
            fail(f"unexpected coexisting prune rollback trees: {entry['skill_id']}")
    elif destination_hash is not None:
        if destination_hash != expected_hash:
            fail(f"cannot compensate changed rollback destination: {entry['skill_id']}")
        detached = remove_destination_for_restore(
            destination, transaction, expected_hash, "rollback-original"
        )
        if detached is None:
            fail(f"prune rollback destination disappeared: {entry['skill_id']}")
        pause_at_control_for_test(
            "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_COMPENSATION_DETACH",
            destination,
        )
    secure_remove_tree(detached.parent, detached.name, "detached prune rollback tree")
    restore_stage = restore_stage_path(destination, transaction)
    secure_remove_tree(restore_stage.parent, restore_stage.name, "restore staging tree")


def compensate_nonprune_rollback(
    journal: dict[str, Any],
    entry: dict[str, Any],
    destination: Path,
    state_dir: Path,
) -> None:
    transaction = journal["transaction_id"]
    snapshot_hash = entry.get("rollback_tree_sha256")
    if not isinstance(snapshot_hash, str):
        fail(f"rollback snapshot metadata is missing: {entry['skill_id']}")
    snapshot = rollback_snapshot_path(state_dir, transaction, entry)
    if (
        not snapshot.is_dir()
        or snapshot.is_symlink()
        or backup_tree_sha256(snapshot) != snapshot_hash
    ):
        fail(f"rollback snapshot drift detected: {entry['skill_id']}")

    original_hash = None
    if entry["action"] == "replace":
        validated_backup(entry, state_dir)
        original_hash = entry["backup_tree_sha256"]
    detached_applied = transaction_detached_path(
        destination, transaction, "rollback-applied"
    )
    detached_original = transaction_detached_path(
        destination, transaction, "rollback-original"
    )
    rolled_back_copy = rollback_original_path(
        destination, transaction, entry["skill_id"]
    )
    destination_hash = optional_tree_hash(
        destination, f"rollback destination for {entry['skill_id']}"
    )
    detached_applied_hash = optional_tree_hash(
        detached_applied, f"detached applied rollback tree for {entry['skill_id']}"
    )
    detached_original_hash = optional_tree_hash(
        detached_original, f"detached original rollback tree for {entry['skill_id']}"
    )
    rolled_back_hash = optional_tree_hash(
        rolled_back_copy, f"rollback original tree for {entry['skill_id']}"
    )
    allowed_destination_hashes = {snapshot_hash}
    if original_hash is not None:
        allowed_destination_hashes.add(original_hash)
    if (
        destination_hash is not None
        and destination_hash not in allowed_destination_hashes
    ):
        fail(f"cannot compensate changed rollback destination: {entry['skill_id']}")
    if detached_applied_hash is not None and detached_applied_hash != snapshot_hash:
        fail(f"detached applied rollback tree drift detected: {entry['skill_id']}")
    if (
        detached_original_hash is not None
        and detached_original_hash != original_hash
    ):
        fail(f"detached original rollback tree drift detected: {entry['skill_id']}")
    if rolled_back_hash is not None and rolled_back_hash != original_hash:
        fail(f"rollback original tree drift detected: {entry['skill_id']}")
    if detached_applied_hash is not None and detached_original_hash is not None:
        fail(f"multiple detached rollback roles coexist: {entry['skill_id']}")
    if rolled_back_hash is not None and detached_original_hash is not None:
        fail(f"multiple original rollback roles coexist: {entry['skill_id']}")

    # A prior recovery already moved the original aside.  Only the two adjacent
    # states of that no-overwrite swap are valid.
    if rolled_back_hash is not None:
        if destination_hash is None and detached_applied_hash == snapshot_hash:
            rename_directory_no_replace(detached_applied, destination)
            if backup_tree_sha256(destination) != snapshot_hash:
                fail(f"restored rollback snapshot drift detected: {entry['skill_id']}")
            pause_at_control_for_test(
                "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_APPLIED_RESTORE",
                destination,
            )
            destination_hash = snapshot_hash
            detached_applied_hash = None
        elif destination_hash == snapshot_hash and detached_applied_hash is None:
            pass
        else:
            fail(f"inconsistent rollback recovery trees: {entry['skill_id']}")

    if detached_applied_hash == snapshot_hash:
        if destination_hash is None:
            rename_directory_no_replace(detached_applied, destination)
            if backup_tree_sha256(destination) != snapshot_hash:
                fail(f"restored rollback snapshot drift detected: {entry['skill_id']}")
            pause_at_control_for_test(
                "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_APPLIED_RESTORE",
                destination,
            )
            destination_hash = snapshot_hash
            detached_applied_hash = None
        elif destination_hash == original_hash and original_hash is not None:
            rename_directory_no_replace(destination, rolled_back_copy)
            if backup_tree_sha256(rolled_back_copy) != original_hash:
                restore_detached_without_overwrite(rolled_back_copy, destination)
                fail(f"rollback destination changed concurrently: {entry['skill_id']}")
            pause_at_control_for_test(
                "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_ORIGINAL_DETACH",
                destination,
            )
            rename_directory_no_replace(detached_applied, destination)
            if backup_tree_sha256(destination) != snapshot_hash:
                fail(f"restored rollback snapshot drift detected: {entry['skill_id']}")
            pause_at_control_for_test(
                "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_APPLIED_RESTORE",
                destination,
            )
            destination_hash = snapshot_hash
            detached_applied_hash = None
        else:
            fail(f"unexpected coexisting rollback trees: {entry['skill_id']}")
    elif detached_original_hash is not None:
        if destination_hash is None:
            restore_backup(destination, snapshot, transaction, snapshot_hash)
            destination_hash = snapshot_hash
        elif destination_hash != snapshot_hash:
            fail(f"unexpected coexisting rollback trees: {entry['skill_id']}")

    if destination_hash != snapshot_hash:
        if destination_hash == original_hash and original_hash is not None:
            detached_original = remove_destination_for_restore(
                destination,
                transaction,
                original_hash,
                "rollback-original",
            )
            if detached_original is None:
                fail(f"rollback destination disappeared: {entry['skill_id']}")
            pause_at_control_for_test(
                "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_COMPENSATION_DETACH",
                destination,
            )
            try:
                restore_backup(destination, snapshot, transaction, snapshot_hash)
            except Exception:
                if not destination.exists() and not destination.is_symlink():
                    restore_detached_without_overwrite(detached_original, destination)
                raise
            pause_at_control_for_test(
                "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_APPLIED_RESTORE",
                destination,
            )
            destination_hash = snapshot_hash
        elif destination_hash is None:
            restore_backup(destination, snapshot, transaction, snapshot_hash)
            destination_hash = snapshot_hash
        else:
            fail(f"cannot compensate changed rollback destination: {entry['skill_id']}")

    marker = load_marker(destination)
    if marker is None or marker.get("transaction_id") != transaction:
        fail(f"rollback snapshot ownership mismatch: {entry['skill_id']}")
    validate_marker_identity(
        destination,
        marker,
        target=entry["target"],
        skill_id=entry["skill_id"],
    )
    secure_remove_tree(
        detached_applied.parent,
        detached_applied.name,
        "detached applied rollback tree",
    )
    secure_remove_tree(
        detached_original.parent,
        detached_original.name,
        "detached original rollback tree",
    )
    secure_remove_tree(
        rolled_back_copy.parent,
        rolled_back_copy.name,
        "rolled-back original tree",
    )
    restore_stage = restore_stage_path(destination, transaction)
    secure_remove_tree(restore_stage.parent, restore_stage.name, "restore staging tree")


def compensate_rollback(journal: dict[str, Any], state_dir: Path) -> None:
    transaction = journal["transaction_id"]
    if journal.get("status") == "rollback_compensating_cleanup":
        validate_terminal_destinations(journal, "applied")
        secure_remove_tree(
            state_dir,
            Path("rollback-backups") / transaction,
            "rollback snapshot tree",
        )
        pause_at_control_for_test(
            "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_COMPENSATION_ARTIFACT_CLEANUP",
            state_dir / "rollback-backups" / transaction,
        )
        for entry in journal["operations"]:
            entry["rollback_tree_sha256"] = None
        validate_terminal_destinations(journal, "applied")
        journal["status"] = "applied"
        save_journal(state_dir, journal)
        return
    for entry in journal["operations"]:
        destination = configured_path(entry["destination"])
        if entry["action"] == "prune":
            compensate_prune_rollback(entry, destination, transaction, state_dir)
        else:
            compensate_nonprune_rollback(journal, entry, destination, state_dir)
        entry["state"] = "applied"
        save_journal(state_dir, journal)
    validate_terminal_destinations(journal, "applied")
    journal["status"] = "rollback_compensating_cleanup"
    save_journal(state_dir, journal)
    secure_remove_tree(
        state_dir,
        Path("rollback-backups") / transaction,
        "rollback snapshot tree",
    )
    pause_at_control_for_test(
        "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_COMPENSATION_ARTIFACT_CLEANUP",
        state_dir / "rollback-backups" / transaction,
    )
    for entry in journal["operations"]:
        entry["rollback_tree_sha256"] = None
    validate_terminal_destinations(journal, "applied")
    journal["status"] = "applied"
    save_journal(state_dir, journal)


def complete_rollback_cleanup(journal: dict[str, Any], state_dir: Path) -> None:
    transaction = journal["transaction_id"]
    validate_terminal_destinations(journal, "rolled_back")
    secure_remove_tree(
        state_dir,
        Path("backups") / transaction,
        "transaction backup tree",
    )
    secure_remove_tree(
        state_dir,
        Path("rollback-backups") / transaction,
        "rollback snapshot tree",
    )
    pause_at_control_for_test(
        "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_ARTIFACT_CLEANUP",
        state_dir / "backups" / transaction,
    )
    validate_terminal_destinations(journal, "rolled_back")
    journal["status"] = "rolled_back"
    save_journal(state_dir, journal)


def cancel_rollback_preparation(journal: dict[str, Any], state_dir: Path) -> None:
    transaction = journal["transaction_id"]
    validate_terminal_destinations(journal, "applied")
    secure_remove_tree(
        state_dir,
        Path("rollback-backups") / transaction,
        "rollback preparation snapshot tree",
    )
    pause_at_control_for_test(
        "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_PREPARATION_ARTIFACT_CLEANUP",
        state_dir / "rollback-backups" / transaction,
    )
    for entry in journal["operations"]:
        entry["rollback_tree_sha256"] = None
    validate_terminal_destinations(journal, "applied")
    journal["status"] = "applied"
    save_journal(state_dir, journal)


def journal_target_set(journal: dict[str, Any]) -> set[str]:
    targets = {entry["target"] for entry in journal["operations"]}
    if not targets or not targets <= ALLOWED_TARGETS:
        fail("transaction journal target set is invalid")
    return targets


def execute_recover(requested: str, registry_path: Path) -> None:
    if not TRANSACTION_ID_RE.fullmatch(requested):
        fail("transaction id is invalid")
    state_dir = state_directory()
    if not state_dir.exists():
        fail("skill registry transaction state does not exist")
    validate_state_runtime_root(state_dir, registry_path)
    path = journal_path(state_dir, requested)
    peek_journal = read_journal(path, state_dir)
    selected = journal_target_set(peek_journal)
    roots = validate_runtime_roots(state_dir, registry_path, selected)
    with mutation_lock(state_dir, roots):
        journal = read_journal(path, state_dir)
        if journal_target_set(journal) != selected:
            fail("transaction targets changed while waiting for the mutation lock")
        transactions = state_dir / "transactions"
        for other_path in sorted(transactions.glob("*.json")):
            if other_path == path:
                continue
            other = read_journal(other_path, state_dir)
            if other["status"] not in {"applied", "compensated", "rolled_back"}:
                fail(f"another incomplete transaction requires recovery: {other['transaction_id']}")
        status = journal["status"]
        if status in {
            "prepared",
            "applying",
            "compensating",
            "compensating_cleanup",
            "compensation_failed",
        }:
            compensate_apply(journal, state_dir)
            print(
                f"OK: transaction {requested} recovered to its pre-apply state; retry apply explicitly"
            )
            return
        if status == "rollback_preparing":
            cancel_rollback_preparation(journal, state_dir)
            print(
                f"OK: rollback {requested} preparation discarded; retry rollback explicitly"
            )
            return
        if status in {
            "rolling_back",
            "rollback_compensating_cleanup",
            "rollback_failed",
        }:
            compensate_rollback(journal, state_dir)
            print(
                f"OK: rollback {requested} recovered to the applied state; retry rollback explicitly"
            )
            return
        if status == "rollback_cleanup":
            complete_rollback_cleanup(journal, state_dir)
            print(
                f"OK: rollback {requested} cleanup recovered; transaction remains rolled back"
            )
            return
        fail(f"transaction does not require recovery: {requested} ({status})")


def execute_rollback(requested: str | None, registry_path: Path) -> None:
    state_dir = state_directory()
    if not state_dir.exists():
        fail("skill registry transaction state does not exist")
    validate_state_runtime_root(state_dir, registry_path)
    peek_path, peek_journal = latest_applied_journal(state_dir, requested)
    peek_transaction = peek_journal["transaction_id"]
    selected = journal_target_set(peek_journal)
    roots = validate_runtime_roots(state_dir, registry_path, selected)
    with mutation_lock(state_dir, roots):
        reject_incomplete_transactions(state_dir)
        _path, journal = latest_applied_journal(state_dir, requested)
        if (
            journal["transaction_id"] != peek_transaction
            or journal_target_set(journal) != selected
            or _path != peek_path
        ):
            fail("rollback transaction changed while waiting for the mutation lock")
        transaction = require_string(journal.get("transaction_id"), "transaction id")
        prepared: list[tuple[dict[str, Any], Path, Path | None, str | None]] = []
        for entry in journal.get("operations", []):
            if entry.get("state") != "applied":
                fail(f"transaction operation is not applied: {entry.get('skill_id', 'unknown')}")
            destination, backup, preflight_hash = validate_rollback_destination(
                entry,
                transaction,
                state_dir,
                roots,
                journal["registry_sha256"],
            )
            prepared.append((entry, destination, backup, preflight_hash))
        journal["status"] = "rollback_preparing"
        save_journal(state_dir, journal)
        prepare_rollback_snapshots(journal, state_dir, prepared)
        journal["status"] = "rolling_back"
        save_journal(state_dir, journal)
        try:
            previous_target = None
            for entry, destination, backup, preflight_hash in reversed(prepared):
                if (
                    previous_target is not None
                    and entry["target"] != previous_target
                    and os.environ.get(
                        "SHOGUN_SKILL_REGISTRY_TEST_FAIL_ROLLBACK_AFTER_TARGET"
                    )
                    == previous_target
                ):
                    raise RegistryError(
                        f"injected rollback failure after target {previous_target}"
                    )
                previous_target = entry["target"]
                entry["state"] = "rollback_started"
                save_journal(state_dir, journal)
                detached = remove_destination_for_restore(
                    destination,
                    transaction,
                    preflight_hash,
                    "rollback-applied",
                )
                try:
                    if backup is not None:
                        restore_backup(
                            destination,
                            backup,
                            transaction,
                            entry["backup_tree_sha256"],
                        )
                        pause_at_control_for_test(
                            "SHOGUN_SKILL_REGISTRY_TEST_PAUSE_AFTER_ROLLBACK_RESTORE",
                            destination,
                        )
                except Exception:
                    if detached is not None and not destination.exists() and not destination.is_symlink():
                        restore_detached_without_overwrite(detached, destination)
                    raise
                if detached is not None:
                    secure_remove_tree(detached.parent, detached.name, "detached applied tree")
                entry["state"] = "rolled_back"
                save_journal(state_dir, journal)
            if (
                previous_target is not None
                and os.environ.get("SHOGUN_SKILL_REGISTRY_TEST_FAIL_ROLLBACK_AFTER_TARGET")
                == previous_target
            ):
                raise RegistryError(f"injected rollback failure after target {previous_target}")
            validate_terminal_destinations(journal, "rolled_back")
        except Exception as exc:
            try:
                compensate_rollback(journal, state_dir)
            except Exception as compensation_error:
                if journal.get("status") != "rollback_compensating_cleanup":
                    journal["status"] = "rollback_failed"
                    save_journal(state_dir, journal)
                raise OSError(
                    f"rollback {transaction} failed and compensation failed: {compensation_error}"
                ) from exc
            raise RegistryError(
                f"{exc}; rollback {transaction} compensated to the applied state"
            ) from exc
        journal["status"] = "rollback_cleanup"
        save_journal(state_dir, journal)
        complete_rollback_cleanup(journal, state_dir)
        print(f"OK: transaction {transaction} rolled back; start a new CLI session")


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=project_root / "skills/registry.yaml")
    parser.add_argument("--lock", dest="lock_path", type=Path, default=project_root / "skills/registry.lock.yaml")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    subparsers.add_parser("lock")
    check = subparsers.add_parser("check")
    check.add_argument("--base-ref")
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--targets", choices=("all", "claude", "codex"), default="all")
    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--transaction")
    recover = subparsers.add_parser("recover")
    recover.add_argument("--transaction", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "recover":
            execute_recover(args.transaction, args.registry)
            return 0
        if args.command == "rollback":
            execute_rollback(args.transaction, args.registry)
            return 0
        try:
            registry_path = args.registry.resolve(strict=True)
        except FileNotFoundError as exc:
            raise RegistryError(f"registry not found: {args.registry.name}") from exc
        validated = validate_registry(registry_path)
        if args.command == "validate":
            print(f"OK: registry valid ({len(validated['skills'])} skills)")
            return 0
        expected = build_lock(validated)
        if args.command == "lock":
            atomic_write(args.lock_path, yaml_bytes(expected))
            print(f"OK: lock updated ({len(validated['skills'])} skills)")
            return 0
        if args.command in {"check", "apply"}:
            try:
                actual_raw = args.lock_path.read_bytes()
            except FileNotFoundError as exc:
                raise RegistryError("registry lock not found") from exc
            actual = read_yaml(args.lock_path, "registry lock")
            if actual_raw != yaml_bytes(expected):
                fail(describe_drift(actual, expected))
        if args.command == "check":
            if args.base_ref:
                enforce_base_versions(validated, expected, args.base_ref)
            print(f"OK: registry lock verified ({len(validated['skills'])} skills)")
            return 0
        if args.command == "apply":
            execute_apply(validated, expected, args.targets)
            return 0
        fail(f"{args.command} is not implemented yet")
    except RegistryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"ERROR: registry operation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

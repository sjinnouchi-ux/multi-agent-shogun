#!/usr/bin/env python3
"""Publish reviewed Shogun artifacts to a dedicated Google Shared Drive."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import yaml

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
FOLDER_MIME = "application/vnd.google-apps.folder"
DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
PROJECT_FOLDERS = (
    "01_要件・依頼",
    "02_参考資料",
    "03_レビュー待ち",
    "04_承認済み成果物",
    "99_アーカイブ",
)
STAGE_FOLDERS = {
    "review": "03_レビュー待ち",
    "approved": "04_承認済み成果物",
}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
BLOCKED_NAMES = {
    ".env",
    "application_default_credentials.json",
    "credentials.json",
    "service-account.json",
}
BLOCKED_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
BLOCKED_FRAGMENTS = ("credential", "secret", "token")


class PublisherError(RuntimeError):
    """Expected validation, authentication, or Drive API failure."""


@contextmanager
def publisher_lock(path: Path):
    """Fail closed when another publisher process owns the single-writer lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise PublisherError(
            f"another Drive publisher is running (lock exists: {path})"
        ) from exc
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(f"{os.getpid()}\n")
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PublisherError(f"cannot read YAML {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PublisherError(f"YAML root must be a mapping: {path}")
    return value


def require_text(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PublisherError(f"missing or invalid required field: {key}")
    return value.strip()


def validate_identifier(value: str, label: str) -> None:
    if not SAFE_ID.fullmatch(value):
        raise PublisherError(
            f"{label} must use 1-128 ASCII letters, digits, dot, underscore, or hyphen"
        )


def is_blocked_name(relative_path: Path) -> bool:
    for part in relative_path.parts:
        lowered = part.lower()
        if lowered in BLOCKED_NAMES or Path(lowered).suffix in BLOCKED_SUFFIXES:
            return True
        if any(fragment in lowered for fragment in BLOCKED_FRAGMENTS):
            return True
    return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_artifacts(
    manifest: dict[str, Any], artifact_dir: Path, max_file_bytes: int
) -> list[dict[str, Any]]:
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise PublisherError("files must be a non-empty list")

    root = artifact_dir.resolve(strict=True)
    resolved: list[dict[str, Any]] = []
    seen: set[str] = {"manifest.yaml"}
    for raw in raw_files:
        if not isinstance(raw, str) or not raw.strip():
            raise PublisherError("each files entry must be a non-empty relative path")
        relative = Path(raw.strip())
        if relative.is_absolute() or ".." in relative.parts or relative == Path("."):
            raise PublisherError(f"unsafe artifact path: {raw}")
        if is_blocked_name(relative):
            raise PublisherError(f"blocked secret-like artifact name: {raw}")
        destination = relative.as_posix()
        if destination in seen:
            raise PublisherError(f"duplicate artifact destination: {destination}")
        seen.add(destination)

        source = (root / relative).resolve(strict=True)
        try:
            source.relative_to(root)
        except ValueError as exc:
            raise PublisherError(f"artifact escapes artifact directory: {raw}") from exc
        if not source.is_file():
            raise PublisherError(f"artifact is not a regular file: {raw}")
        size = source.stat().st_size
        if size > max_file_bytes:
            raise PublisherError(
                f"artifact exceeds max_file_bytes ({max_file_bytes}): {raw} ({size})"
            )
        resolved.append(
            {
                "source": source,
                "relative_path": destination,
                "size": size,
                "sha256": sha256_file(source),
                "mime_type": mimetypes.guess_type(source.name)[0]
                or "application/octet-stream",
            }
        )
    return resolved


def validate_inputs(
    config: dict[str, Any],
    manifest: dict[str, Any],
    artifact_dir: Path,
    stage: str,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    normalized = {
        "project_id": require_text(config, "project_id"),
        "service_account": require_text(config, "service_account"),
        "drive_id": require_text(config, "drive_id"),
        "projects_folder": require_text(config, "projects_folder"),
        "project": require_text(manifest, "project"),
        "artifact_id": require_text(manifest, "artifact_id"),
        "source_tool": require_text(manifest, "source_tool"),
        "manifest_status": require_text(manifest, "status"),
        "created_at": require_text(manifest, "created_at"),
    }
    validate_identifier(normalized["project"], "project")
    validate_identifier(normalized["artifact_id"], "artifact_id")
    if normalized["source_tool"] not in {"shogun", "codex", "claude"}:
        raise PublisherError("source_tool must be shogun, codex, or claude")
    if stage not in STAGE_FOLDERS:
        raise PublisherError(f"unsupported stage: {stage}")
    if normalized["manifest_status"] != stage:
        raise PublisherError(
            f"manifest status {normalized['manifest_status']!r} does not match stage {stage!r}"
        )
    if stage == "approved":
        review = manifest.get("review")
        if not isinstance(review, dict):
            raise PublisherError("approved publication requires a review mapping")
        if review.get("result") != "approved":
            raise PublisherError("approved publication requires review.result=approved")
        require_text(review, "reviewer")
        require_text(review, "approved_at")
    max_file_bytes = config.get("max_file_bytes", 52_428_800)
    if not isinstance(max_file_bytes, int) or max_file_bytes < 1:
        raise PublisherError("max_file_bytes must be a positive integer")
    gcloud_config_dir = config.get("gcloud_config_dir", "")
    if not isinstance(gcloud_config_dir, str):
        raise PublisherError("gcloud_config_dir must be a string when provided")
    normalized["gcloud_config_dir"] = gcloud_config_dir.strip()
    gcloud_bin = config.get("gcloud_bin", "")
    if not isinstance(gcloud_bin, str):
        raise PublisherError("gcloud_bin must be a string when provided")
    normalized["gcloud_bin"] = gcloud_bin.strip()
    return normalized, resolve_artifacts(manifest, artifact_dir, max_file_bytes)


def resolve_gcloud_bin(cli_value: str | None, config_value: str) -> str:
    """Resolve gcloud without requiring callers to repeat a WSL-specific path."""
    return cli_value or os.environ.get("GCLOUD_BIN") or config_value or "gcloud"


def json_request(
    method: str,
    url: str,
    token: str,
    *,
    payload: dict[str, Any] | None = None,
    data: bytes | None = None,
    content_type: str = "application/json; charset=utf-8",
    attempts: int = 3,
) -> dict[str, Any]:
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = content_type
    for attempt in range(1, attempts + 1):
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=60) as response:
                body = response.read()
                return json.loads(body.decode("utf-8")) if body else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code in {429, 500, 502, 503, 504} and attempt < attempts:
                time.sleep(2 ** (attempt - 1))
                continue
            raise PublisherError(f"Google API HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            if attempt < attempts:
                time.sleep(2 ** (attempt - 1))
                continue
            raise PublisherError(f"Google API network error: {exc}") from exc
    raise PublisherError("Google API request exhausted retries")


def get_drive_token(
    project_id: str,
    service_account: str,
    gcloud_bin: str,
    gcloud_config_dir: str | None = None,
) -> str:
    environment = {**os.environ, "CLOUDSDK_CORE_PROJECT": project_id}
    if gcloud_config_dir:
        environment["CLOUDSDK_CONFIG"] = gcloud_config_dir
    try:
        process = subprocess.run(
            [gcloud_bin, "auth", "print-access-token"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            detail = f": {exc.stderr.strip()}"
        raise PublisherError(f"cannot obtain gcloud access token: {exc}{detail}") from exc
    bootstrap_token = process.stdout.strip()
    if not bootstrap_token:
        raise PublisherError("gcloud returned an empty access token")
    endpoint = (
        "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
        f"{quote(service_account, safe='')}:generateAccessToken"
    )
    response = json_request(
        "POST",
        endpoint,
        bootstrap_token,
        payload={"scope": [DRIVE_SCOPE], "lifetime": "900s"},
    )
    token = response.get("accessToken")
    if not isinstance(token, str) or not token:
        raise PublisherError("IAM Credentials API returned no accessToken")
    return token


def escape_drive_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class DriveClient:
    def __init__(self, token: str, drive_id: str) -> None:
        self.token = token
        self.drive_id = drive_id

    def list_named_child(
        self, parent_id: str, name: str, mime_type: str | None = None
    ) -> list[dict[str, Any]]:
        clauses = [
            f"'{escape_drive_query(parent_id)}' in parents",
            f"name = '{escape_drive_query(name)}'",
            "trashed = false",
        ]
        if mime_type:
            clauses.append(f"mimeType = '{escape_drive_query(mime_type)}'")
        params = {
            "q": " and ".join(clauses),
            "corpora": "drive",
            "driveId": self.drive_id,
            "includeItemsFromAllDrives": "true",
            "supportsAllDrives": "true",
            "fields": "files(id,name,mimeType,webViewLink,size,md5Checksum)",
            "pageSize": "10",
        }
        response = json_request(
            "GET", f"{DRIVE_API}/files?{urlencode(params)}", self.token
        )
        files = response.get("files", [])
        return files if isinstance(files, list) else []

    def create_folder(self, parent_id: str, name: str) -> dict[str, Any]:
        params = {"supportsAllDrives": "true", "fields": "id,name,webViewLink"}
        return json_request(
            "POST",
            f"{DRIVE_API}/files?{urlencode(params)}",
            self.token,
            payload={"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]},
        )

    def ensure_folder(self, parent_id: str, name: str) -> dict[str, Any]:
        matches = self.list_named_child(parent_id, name, FOLDER_MIME)
        if len(matches) > 1:
            raise PublisherError(f"duplicate Drive folders named {name!r} under {parent_id}")
        return matches[0] if matches else self.create_folder(parent_id, name)

    def upsert_bytes(
        self,
        parent_id: str,
        name: str,
        content: bytes,
        mime_type: str,
        app_properties: dict[str, str],
    ) -> dict[str, Any]:
        matches = self.list_named_child(parent_id, name)
        if len(matches) > 1:
            raise PublisherError(f"duplicate Drive files named {name!r} under {parent_id}")
        existing = matches[0] if matches else None
        metadata: dict[str, Any] = {
            "name": name,
            "appProperties": app_properties,
        }
        if not existing:
            metadata["parents"] = [parent_id]
        boundary = f"shogun_{uuid.uuid4().hex}"
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
        ).encode("utf-8")
        body += json.dumps(metadata, ensure_ascii=False).encode("utf-8")
        body += (
            f"\r\n--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")
        body += content + f"\r\n--{boundary}--\r\n".encode("utf-8")
        params = {
            "uploadType": "multipart",
            "supportsAllDrives": "true",
            "fields": "id,name,webViewLink,mimeType,size,md5Checksum",
        }
        if existing:
            url = f"{DRIVE_UPLOAD_API}/files/{existing['id']}?{urlencode(params)}"
            method = "PATCH"
        else:
            url = f"{DRIVE_UPLOAD_API}/files?{urlencode(params)}"
            method = "POST"
        return json_request(
            method,
            url,
            self.token,
            data=body,
            content_type=f"multipart/related; boundary={boundary}",
        )


def publish(
    client: DriveClient,
    normalized: dict[str, str],
    manifest_path: Path,
    artifacts: list[dict[str, Any]],
    stage: str,
) -> dict[str, Any]:
    root = normalized["drive_id"]
    projects = client.ensure_folder(root, normalized["projects_folder"])
    project = client.ensure_folder(projects["id"], normalized["project"])
    stage_ids: dict[str, str] = {}
    for folder_name in PROJECT_FOLDERS:
        folder = client.ensure_folder(project["id"], folder_name)
        stage_ids[folder_name] = folder["id"]
    stage_folder_name = STAGE_FOLDERS[stage]
    artifact_folder = client.ensure_folder(
        stage_ids[stage_folder_name], normalized["artifact_id"]
    )
    base_properties = {
        "artifact_id": normalized["artifact_id"],
        "project": normalized["project"],
        "stage": stage,
        "source_tool": normalized["source_tool"],
    }
    uploaded = [
        client.upsert_bytes(
            artifact_folder["id"],
            "manifest.yaml",
            manifest_path.read_bytes(),
            "application/yaml",
            base_properties,
        )
    ]
    folder_cache: dict[tuple[str, str], str] = {}
    for artifact in artifacts:
        relative = Path(artifact["relative_path"])
        parent_id = artifact_folder["id"]
        for part in relative.parts[:-1]:
            cache_key = (parent_id, part)
            if cache_key not in folder_cache:
                nested = client.ensure_folder(parent_id, part)
                folder_cache[cache_key] = nested["id"]
            parent_id = folder_cache[cache_key]
        properties = {**base_properties, "sha256": artifact["sha256"]}
        uploaded.append(
            client.upsert_bytes(
                parent_id,
                relative.name,
                artifact["source"].read_bytes(),
                artifact["mime_type"],
                properties,
            )
        )
    return {
        "status": "published",
        "project": normalized["project"],
        "artifact_id": normalized["artifact_id"],
        "stage": stage,
        "folder_id": artifact_folder["id"],
        "folder_url": f"https://drive.google.com/drive/folders/{artifact_folder['id']}",
        "files": uploaded,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--stage", choices=sorted(STAGE_FOLDERS), required=True)
    parser.add_argument("--gcloud-bin")
    parser.add_argument(
        "--lock-file",
        type=Path,
        help="single-writer lock path (default: <repo>/logs/drive_publisher.lock)",
    )
    parser.add_argument("--result", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = load_yaml(args.config)
        manifest = load_yaml(args.manifest)
        normalized, artifacts = validate_inputs(
            config, manifest, args.artifact_dir, args.stage
        )
        normalized["drive_id"] = require_text(config, "drive_id")
        if args.dry_run:
            result: dict[str, Any] = {
                "status": "dry-run",
                "destination": (
                    f"{normalized['projects_folder']}/{normalized['project']}/"
                    f"{STAGE_FOLDERS[args.stage]}/{normalized['artifact_id']}"
                ),
                "files": [
                    {
                        "relative_path": item["relative_path"],
                        "size": item["size"],
                        "sha256": item["sha256"],
                    }
                    for item in artifacts
                ],
            }
        else:
            lock_file = args.lock_file or (
                Path(__file__).resolve().parent.parent / "logs/drive_publisher.lock"
            )
            with publisher_lock(lock_file):
                token = get_drive_token(
                    normalized["project_id"],
                    normalized["service_account"],
                    resolve_gcloud_bin(args.gcloud_bin, normalized["gcloud_bin"]),
                    normalized["gcloud_config_dir"] or None,
                )
                result = publish(
                    DriveClient(token, normalized["drive_id"]),
                    normalized,
                    args.manifest,
                    artifacts,
                    args.stage,
                )
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.result:
            args.result.parent.mkdir(parents=True, exist_ok=True)
            args.result.write_text(output + "\n", encoding="utf-8")
        print(output)
        return 0
    except (PublisherError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

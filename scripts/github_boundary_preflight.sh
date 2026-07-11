#!/usr/bin/env bash
# Validate the lightweight GitHub boundary before a Shogun task starts.
set -euo pipefail

REPO_PATH="$(pwd)"
SOURCE="shogun"
BRANCH_PREFIX="shogun/"
PRIMARY_BRANCH="main"
CANONICAL_URL=""

usage() {
    cat <<'EOF'
Usage: github_boundary_preflight.sh [options]

Options:
  --repo PATH              Target Git repository (default: current directory)
  --canonical-url URL      Required Git remote URL, checked without authentication
  --branch-prefix PREFIX   Required working branch prefix (default: shogun/)
  --primary-branch NAME    Protected primary branch (default: main)
  --source NAME            Record source label (default: shogun)
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo) REPO_PATH="$2"; shift 2 ;;
        --canonical-url) CANONICAL_URL="$2"; shift 2 ;;
        --branch-prefix) BRANCH_PREFIX="$2"; shift 2 ;;
        --primary-branch) PRIMARY_BRANCH="$2"; shift 2 ;;
        --source) SOURCE="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

abort() {
    echo "[ABORT] $1" >&2
    exit 2
}

normalize_remote() {
    local value="$1"
    value="${value%.git}"
    if [[ "$value" =~ ^git@github\.com:(.+)$ ]]; then
        value="https://github.com/${BASH_REMATCH[1]}"
    fi
    printf '%s\n' "$value"
}

git -C "$REPO_PATH" rev-parse --git-dir >/dev/null 2>&1 \
    || abort "not a Git repository: $REPO_PATH"

CURRENT_BRANCH="$(git -C "$REPO_PATH" branch --show-current)"
[[ -n "$CURRENT_BRANCH" ]] || abort "detached HEAD is not allowed"
[[ "$CURRENT_BRANCH" != "$PRIMARY_BRANCH" ]] \
    || abort "direct work on primary branch is not allowed: $PRIMARY_BRANCH"
[[ -z "$BRANCH_PREFIX" || "$CURRENT_BRANCH" == "$BRANCH_PREFIX"* ]] \
    || abort "branch must start with $BRANCH_PREFIX (current: $CURRENT_BRANCH)"

EFFECTIVE_CODEX_HOME="${CODEX_HOME:-${HOME:?HOME is required}/.codex}"
RESOLVED_CODEX_HOME="$(realpath -m "$EFFECTIVE_CODEX_HOME")"
[[ "$RESOLVED_CODEX_HOME" != /mnt/* ]] \
    || abort "CODEX_HOME must stay inside WSL2 Linux: $RESOLVED_CODEX_HOME"

MATCHED_REMOTE=""
if [[ -n "$CANONICAL_URL" ]]; then
    EXPECTED="$(normalize_remote "$CANONICAL_URL")"
    while IFS= read -r remote; do
        url="$(git -C "$REPO_PATH" remote get-url "$remote")"
        if [[ "$(normalize_remote "$url")" == "$EXPECTED" ]]; then
            MATCHED_REMOTE="$remote"
            break
        fi
    done < <(git -C "$REPO_PATH" remote)
    [[ -n "$MATCHED_REMOTE" ]] \
        || abort "canonical Git remote is not configured: $CANONICAL_URL"
fi

BASE_COMMIT="$(git -C "$REPO_PATH" rev-parse HEAD)"
REPO_URL="${CANONICAL_URL:-$(git -C "$REPO_PATH" remote get-url origin)}"
if [[ "$REPO_URL" =~ ^https?://[^/]+@ ]]; then
    abort "credential-bearing remote URL cannot be recorded; pass --canonical-url"
fi

printf 'source=%s\n' "$SOURCE"
printf 'repository_url=%s\n' "$REPO_URL"
printf 'branch=%s\n' "$CURRENT_BRANCH"
printf 'base_commit=%s\n' "$BASE_COMMIT"
printf 'codex_home=%s\n' "$RESOLVED_CODEX_HOME"
if [[ -n "$MATCHED_REMOTE" ]]; then
    printf 'canonical_remote=%s\n' "$MATCHED_REMOTE"
fi

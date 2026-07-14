#!/usr/bin/env bash
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${SHOGUN_PYTHON_BIN:-${PROJECT_ROOT}/.venv/bin/python3}"

if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(command -v python3 || true)"
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "ERROR: python3 is required for the Shogun Skill Registry" >&2
    exit 2
fi

exec "$PYTHON_BIN" "${SCRIPT_DIR}/skill_registry.py" "$@"

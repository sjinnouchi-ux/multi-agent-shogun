#!/usr/bin/env bash
# Select one explicitly named local image. This helper never scans directories.
set -euo pipefail

usage() {
    echo "usage: capture_local.sh --input FILE" >&2
}

if (( $# != 2 )) || [[ "$1" != "--input" ]] || [[ -z "$2" ]]; then
    usage
    exit 64
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
exec python3 "$script_dir/safe_image_io.py" --select "$2"

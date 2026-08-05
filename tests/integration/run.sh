#!/usr/bin/env bash
set -euo pipefail

readonly root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root_dir"

command -v docker >/dev/null 2>&1 || {
    printf '[r13-integration] fatal: docker is required\n' >&2
    exit 1
}
docker compose version >/dev/null 2>&1 || {
    printf '[r13-integration] fatal: Docker Compose v2 is required\n' >&2
    exit 1
}
command -v python3 >/dev/null 2>&1 || {
    printf '[r13-integration] fatal: python3 is required\n' >&2
    exit 1
}

exec python3 tests/integration/r13_integration.py

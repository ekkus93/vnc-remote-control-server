#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly root_dir
cd "$root_dir"

command -v docker >/dev/null 2>&1 || {
    printf '[mcp-e2e] fatal: docker is required\n' >&2
    exit 1
}
docker compose version >/dev/null 2>&1 || {
    printf '[mcp-e2e] fatal: Docker Compose v2 is required\n' >&2
    exit 1
}
command -v python3 >/dev/null 2>&1 || {
    printf '[mcp-e2e] fatal: python3 is required\n' >&2
    exit 1
}
python3 - <<'PY' >/dev/null 2>&1 || {
import importlib.metadata
import mcp
import vnc_remote_control

if importlib.metadata.version("mcp") != "2.1.1":
    raise SystemExit("wrong MCP SDK version")
PY
    printf '[mcp-e2e] fatal: exact mcp==2.1.1 extra and Python client are required\n' >&2
    exit 1
}

if [[ -n "${MCP_E2E_FAILURE_ARTIFACT_DIR:-}" ]]; then
    mkdir -p -- "$MCP_E2E_FAILURE_ARTIFACT_DIR"
    printf 'mcp_e2e_started=1\n' > "$MCP_E2E_FAILURE_ARTIFACT_DIR/run-started.txt"
fi

export PYTHONPATH="$root_dir:$root_dir/tests/integration${PYTHONPATH:+:$PYTHONPATH}"
exec python3 tests/mcp_e2e.py

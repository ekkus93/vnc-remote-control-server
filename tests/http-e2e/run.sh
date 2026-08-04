#!/usr/bin/env bash
set -euo pipefail

readonly image_name="vnc-remote-control-desktop:native-test"
readonly container_name="vnc-remote-control-http-e2e-${GITHUB_RUN_ID:-local}-$$"
readonly vnc_password='http-e2e-vnc-password'
readonly api_token='http-e2e-api-token'
temporary_directory=""
controller_pid=""
controller_log=""

log() {
    printf '[http-e2e] %s\n' "$*" >&2
}

fail() {
    log "fatal: $*"
    exit 1
}

cleanup() {
    if [[ -n "$controller_pid" ]] && kill -0 "$controller_pid" >/dev/null 2>&1; then
        kill -TERM "$controller_pid" >/dev/null 2>&1 || true
        wait "$controller_pid" >/dev/null 2>&1 || true
    fi
    docker rm --force "$container_name" >/dev/null 2>&1 || true
    if [[ -n "$temporary_directory" ]]; then
        rm -rf -- "$temporary_directory"
    fi
}

on_exit() {
    local exit_status=$?
    trap - EXIT
    if (( exit_status != 0 )); then
        [[ -z "$controller_log" || ! -f "$controller_log" ]] || cat "$controller_log" >&2
        docker logs "$container_name" >&2 2>/dev/null || true
    fi
    cleanup
    exit "$exit_status"
}
trap on_exit EXIT

wait_for_desktop() {
    local deadline=$((SECONDS + 90))
    local status
    while (( SECONDS < deadline )); do
        status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container_name")"
        case "$status" in
            healthy)
                return 0
                ;;
            unhealthy)
                fail "desktop container became unhealthy"
                ;;
        esac
        sleep 1
    done
    fail "desktop health deadline exceeded"
}

wait_for_controller() {
    local deadline=$((SECONDS + 90))
    local status
    while (( SECONDS < deadline )); do
        if ! kill -0 "$controller_pid" >/dev/null 2>&1; then
            wait "$controller_pid" || true
            fail "controller exited before readiness"
        fi
        status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
            "http://127.0.0.1:${api_port}/health/ready" || true)"
        if [[ "$status" == "200" ]]; then
            return 0
        fi
        sleep 1
    done
    fail "controller readiness deadline exceeded"
}

temporary_directory="$(mktemp -d)"
printf '%s\n' "$vnc_password" > "$temporary_directory/vnc_password"
printf '%s\n' "$api_token" > "$temporary_directory/api_token"
chmod 0444 "$temporary_directory/vnc_password" "$temporary_directory/api_token"
controller_log="$temporary_directory/controller.log"

if ! docker image inspect "$image_name" >/dev/null 2>&1; then
    log "building project-owned desktop image"
    docker build --tag "$image_name" desktop
fi

docker run --detach \
    --name "$container_name" \
    --mount "type=bind,source=$temporary_directory/vnc_password,target=/run/secrets/vnc_password,readonly" \
    --publish 127.0.0.1::5901 \
    "$image_name" >/dev/null
wait_for_desktop

port_mapping="$(docker port "$container_name" 5901/tcp)"
vnc_port="${port_mapping##*:}"
[[ "$vnc_port" =~ ^[0-9]+$ ]] || fail "could not resolve dynamically published VNC port"
api_port="$(python3 - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    print(sock.getsockname()[1])
PY
)"

log "building and starting the production controller binary"
cargo build --locked --quiet -p controller-api --bin controller-api
env \
    VRC_LISTEN_ADDR="127.0.0.1:${api_port}" \
    VRC_API_TOKEN_FILE="$temporary_directory/api_token" \
    VRC_VNC_HOST=127.0.0.1 \
    VRC_VNC_PORT="$vnc_port" \
    VRC_VNC_PASSWORD_FILE="$temporary_directory/vnc_password" \
    VRC_HTTP_HEADER_TIMEOUT_MS=1000 \
    VRC_HTTP_BODY_TIMEOUT_MS=1000 \
    VRC_SHUTDOWN_GRACE_MS=3000 \
    target/debug/controller-api >"$controller_log" 2>&1 &
controller_pid=$!
wait_for_controller

log "verifying bearer authentication fails closed"
status="$(curl --silent --output "$temporary_directory/unauthorized.json" --write-out '%{http_code}' \
    "http://127.0.0.1:${api_port}/v1/status")"
[[ "$status" == "401" ]] || fail "unauthenticated status request returned HTTP $status"

grep -Fq '"code":"unauthorized"' "$temporary_directory/unauthorized.json" || \
    fail "unauthenticated response did not use the stable error envelope"


log "verifying WebSocket upgrades require bearer authentication"
python3 - "$api_port" "$api_token" <<'PY'
import base64
import hashlib
import os
import socket
import sys

host = "127.0.0.1"
port = int(sys.argv[1])
api_token = sys.argv[2]
websocket_guid = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

def check_upgrade(path: str, authorization: str | None, expected_status: int) -> None:
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    lines = [
        f"GET {path} HTTP/1.1",
        f"Host: {host}:{port}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Key: {key}",
        "Sec-WebSocket-Version: 13",
    ]
    if authorization is not None:
        lines.append(f"Authorization: Bearer {authorization}")
    request = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")

    with socket.create_connection((host, port), timeout=5) as sock:
        sock.settimeout(5)
        sock.sendall(request)
        response = bytearray()
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response.extend(chunk)
            if len(response) > 65536:
                raise AssertionError("WebSocket handshake response exceeded limit")

        header_block = bytes(response).split(b"\r\n\r\n", 1)[0].decode("iso-8859-1")
        header_lines = header_block.split("\r\n")
        status = int(header_lines[0].split()[1])
        if status != expected_status:
            raise AssertionError(
                f"{path} returned {status}, expected {expected_status}: {header_block}"
            )
        headers = {}
        for line in header_lines[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()

        if expected_status == 101:
            expected_accept = base64.b64encode(
                hashlib.sha1((key + websocket_guid).encode("ascii")).digest()
            ).decode("ascii")
            if headers.get("sec-websocket-accept") != expected_accept:
                raise AssertionError("authenticated upgrade returned invalid accept key")
            if headers.get("upgrade", "").lower() != "websocket":
                raise AssertionError("authenticated upgrade omitted Upgrade: websocket")
            if "upgrade" not in headers.get("connection", "").lower():
                raise AssertionError("authenticated upgrade omitted Connection: upgrade")
            sock.sendall(b"\x88\x80" + os.urandom(4))
        elif "sec-websocket-accept" in headers:
            raise AssertionError("unauthorized upgrade returned a WebSocket accept key")

check_upgrade("/v1/events", None, 401)
check_upgrade(f"/v1/events?token={api_token}", None, 401)
check_upgrade("/v1/events", "wrong-token", 401)
check_upgrade("/v1/events", api_token, 101)
PY

log "sending an authenticated pointer command through HTTP and the production worker"
status="$(curl --silent --show-error --output "$temporary_directory/pointer.json" --write-out '%{http_code}' \
    --request POST \
    --header "Authorization: Bearer ${api_token}" \
    --header 'Content-Type: application/json' \
    --data '{"x":417,"y":263}' \
    "http://127.0.0.1:${api_port}/v1/pointer/move")"
[[ "$status" == "202" ]] || fail "authenticated pointer request returned HTTP $status"
grep -Fq '"status":"accepted"' "$temporary_directory/pointer.json" || \
    fail "pointer response did not publish the accepted marker"

log "verifying TigerVNC delivered the HTTP command to the deterministic desktop"
docker exec -i "$container_name" python3 - <<'PY'
import json
import time
from pathlib import Path

path = Path('/tmp/vnc-test-app-state.json')
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    state = json.loads(path.read_text(encoding='utf-8'))
    if state.get('pointer') == {'x': 417, 'y': 263}:
        break
    time.sleep(0.1)
else:
    raise AssertionError('HTTP pointer command was not observed: ' + json.dumps(state, sort_keys=True))
PY

log "requesting signal-driven graceful shutdown"
kill -TERM "$controller_pid"
shutdown_deadline=$((SECONDS + 10))
while kill -0 "$controller_pid" >/dev/null 2>&1; do
    (( SECONDS < shutdown_deadline )) || fail "controller did not exit after SIGTERM"
    sleep 0.1
done
set +e
wait "$controller_pid"
controller_status=$?
set -e
controller_pid=""
[[ "$controller_status" -eq 0 ]] || fail "controller exited with status $controller_status"

if grep -Fq "$vnc_password" "$controller_log"; then
    fail "controller log exposed the VNC password"
fi
if grep -Fq "$api_token" "$controller_log"; then
    fail "controller log exposed the API token"
fi
grep -Fq 'authorization=[REDACTED]' "$controller_log" || \
    fail "controller access log did not emit the authorization redaction marker"
grep -Fq 'path=/v1/events status=101' "$controller_log" || \
    fail "controller access log did not record the authenticated WebSocket upgrade"

printf 'http_runtime_e2e_complete=1\n'
log "authenticated HTTP to TigerVNC E2E test passed"

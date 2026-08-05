\
#!/usr/bin/env bash
set -euo pipefail

readonly image_name="vnc-remote-control-desktop:native-test"
readonly container_name="vnc-remote-control-http-e2e-${GITHUB_RUN_ID:-local}-$$"
readonly vnc_password='http-e2e-vnc-password'
readonly api_token='http-e2e-api-token'
readonly typed_secret='R11-TYPED-PAYLOAD-MUST-NOT-LOG'
readonly clipboard_secret='R11-CLIPBOARD-PAYLOAD-MUST-NOT-LOG'
readonly documented_text='R15-DOCUMENTED-CURL-TEXT'
readonly documented_clipboard='R15-DOCUMENTED-CURL-CLIPBOARD'
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
    VRC_WEBSOCKET_EVENT_CAPACITY=4 \
    VRC_WEBSOCKET_MAX_CLIENTS=1 \
    VRC_WEBSOCKET_PING_INTERVAL_MS=500 \
    VRC_WEBSOCKET_IDLE_TIMEOUT_MS=5000 \
    target/debug/controller-api >"$controller_log" 2>&1 &
controller_pid=$!
wait_for_controller

# R15_DOCUMENTED_CURL_EXAMPLES
log "verifying R15 documented curl examples against the real controller"
base_url="http://127.0.0.1:${api_port}"
authorization_header="Authorization: Bearer ${api_token}"

curl --fail-with-body --silent --show-error \
    --output "$temporary_directory/documented-live.json" \
    "$base_url/health/live"
curl --fail-with-body --silent --show-error \
    --header "$authorization_header" \
    --output "$temporary_directory/documented-status.json" \
    "$base_url/v1/status"
curl --fail-with-body --silent --show-error \
    --header "$authorization_header" \
    --output "$temporary_directory/documented-display.json" \
    "$base_url/v1/display"
curl --fail-with-body --silent --show-error \
    --header "$authorization_header" \
    --dump-header "$temporary_directory/documented-screenshot.headers" \
    --output "$temporary_directory/documented-screenshot.png" \
    "$base_url/v1/screenshot.png"
curl --fail-with-body --silent --show-error \
    --request POST \
    --header "$authorization_header" \
    --header 'Content-Type: application/json' \
    --data '{"x":401,"y":251}' \
    --output "$temporary_directory/documented-pointer.json" \
    "$base_url/v1/pointer/move"
curl --fail-with-body --silent --show-error \
    --request POST \
    --header "$authorization_header" \
    --header 'Content-Type: application/json' \
    --data "{\"text\":\"${documented_text}\"}" \
    --output "$temporary_directory/documented-text.json" \
    "$base_url/v1/keyboard/text"
curl --fail-with-body --silent --show-error \
    --request PUT \
    --header "$authorization_header" \
    --header 'Content-Type: application/json' \
    --data "{\"text\":\"${documented_clipboard}\"}" \
    --output "$temporary_directory/documented-clipboard.json" \
    "$base_url/v1/clipboard"
python3 - "$temporary_directory" <<'PYDOC'
import json
import struct
import sys
from pathlib import Path

root = Path(sys.argv[1])
if json.loads((root / "documented-live.json").read_text())["status"] != "alive":
    raise SystemExit("documented liveness example returned unexpected content")
if json.loads((root / "documented-status.json").read_text())["state"] != "connected":
    raise SystemExit("documented status example was not connected")
display = json.loads((root / "documented-display.json").read_text())
if (display["width"], display["height"], display["complete"]) != (1280, 800, True):
    raise SystemExit("documented display example returned unexpected metadata")
png = (root / "documented-screenshot.png").read_bytes()
if not png.startswith(b"\x89PNG\r\n\x1a\n"):
    raise SystemExit("documented screenshot example did not return PNG")
width, height = struct.unpack(">II", png[16:24])
if (width, height) != (1280, 800):
    raise SystemExit("documented screenshot dimensions are wrong")
for name in ("documented-pointer.json", "documented-text.json", "documented-clipboard.json"):
    payload = json.loads((root / name).read_text())
    if payload.get("status") != "accepted" or not isinstance(payload.get("command_id"), int):
        raise SystemExit(f"{name} did not return accepted command semantics")
PYDOC

log "verifying bearer authentication fails closed"
status="$(curl --silent --output "$temporary_directory/unauthorized.json" --write-out '%{http_code}' \
    "http://127.0.0.1:${api_port}/v1/status")"
[[ "$status" == "401" ]] || fail "unauthenticated status request returned HTTP $status"
grep -Fq '"code":"unauthorized"' "$temporary_directory/unauthorized.json" || \
    fail "unauthenticated response did not use the stable error envelope"

log "verifying authenticated WebSocket snapshots, event delivery, heartbeats, and client limits"
python3 - "$api_port" "$api_token" <<'PY'
import base64
import hashlib
import http.client
import json
import os
import socket
import struct
import sys
import time

HOST = "127.0.0.1"
PORT = int(sys.argv[1])
API_TOKEN = sys.argv[2]
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def handshake(path: str, authorization: str | None):
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    lines = [
        f"GET {path} HTTP/1.1",
        f"Host: {HOST}:{PORT}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Key: {key}",
        "Sec-WebSocket-Version: 13",
    ]
    if authorization is not None:
        lines.append(f"Authorization: Bearer {authorization}")
    request = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")
    sock = socket.create_connection((HOST, PORT), timeout=5)
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
    headers_raw, _, leftover = bytes(response).partition(b"\r\n\r\n")
    header_lines = headers_raw.decode("iso-8859-1").split("\r\n")
    status = int(header_lines[0].split()[1])
    headers = {}
    for line in header_lines[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()
    if status == 101:
        expected = base64.b64encode(
            hashlib.sha1((key + GUID).encode("ascii")).digest()
        ).decode("ascii")
        if headers.get("sec-websocket-accept") != expected:
            raise AssertionError("invalid WebSocket accept key")
    return sock, status, headers, bytearray(leftover)


def expect_status(path: str, authorization: str | None, expected: int):
    sock, status, headers, _ = handshake(path, authorization)
    try:
        if status != expected:
            raise AssertionError(f"{path} returned {status}, expected {expected}")
        if expected != 101 and "sec-websocket-accept" in headers:
            raise AssertionError("rejected upgrade returned an accept key")
    finally:
        sock.close()


def recv_exact(sock: socket.socket, buffer: bytearray, length: int) -> bytes:
    while len(buffer) < length:
        chunk = sock.recv(4096)
        if not chunk:
            raise AssertionError("WebSocket closed while reading a frame")
        buffer.extend(chunk)
    data = bytes(buffer[:length])
    del buffer[:length]
    return data


def read_frame(sock: socket.socket, buffer: bytearray):
    first, second = recv_exact(sock, buffer, 2)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", recv_exact(sock, buffer, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", recv_exact(sock, buffer, 8))[0]
    mask = recv_exact(sock, buffer, 4) if masked else b""
    payload = bytearray(recv_exact(sock, buffer, length))
    if masked:
        for index in range(len(payload)):
            payload[index] ^= mask[index % 4]
    return opcode, bytes(payload)


def send_frame(sock: socket.socket, opcode: int, payload: bytes = b""):
    mask = os.urandom(4)
    length = len(payload)
    header = bytearray([0x80 | opcode])
    if length < 126:
        header.append(0x80 | length)
    elif length <= 0xFFFF:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    header.extend(mask)
    masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    sock.sendall(bytes(header) + masked)


def next_json(sock: socket.socket, buffer: bytearray, deadline: float):
    while time.monotonic() < deadline:
        opcode, payload = read_frame(sock, buffer)
        if opcode == 0x1:
            return json.loads(payload.decode("utf-8"))
        if opcode == 0x9:
            send_frame(sock, 0xA, payload)
            continue
        if opcode == 0x8:
            raise AssertionError("WebSocket closed before expected event")
    raise AssertionError("WebSocket event deadline exceeded")


expect_status("/v1/events", None, 401)
expect_status(f"/v1/events?token={API_TOKEN}", None, 401)
expect_status("/v1/events", "wrong-token", 401)

sock, status, _, buffer = handshake("/v1/events", API_TOKEN)
if status != 101:
    raise AssertionError(f"authenticated upgrade returned {status}")
try:
    snapshot = next_json(sock, buffer, time.monotonic() + 5)
    if snapshot.get("type") != "snapshot":
        raise AssertionError("first WebSocket message was not a snapshot: " + repr(snapshot))
    if snapshot.get("state") != "connected":
        raise AssertionError("snapshot did not report connected state: " + repr(snapshot))
    if not isinstance(snapshot.get("sequence"), int):
        raise AssertionError("snapshot sequence is missing")
    if not isinstance(snapshot.get("timestamp_unix_ms"), int):
        raise AssertionError("snapshot timestamp is missing")

    second, second_status, _, _ = handshake("/v1/events", API_TOKEN)
    try:
        if second_status != 503:
            raise AssertionError(f"excess WebSocket client returned {second_status}, expected 503")
    finally:
        second.close()

    connection = http.client.HTTPConnection(HOST, PORT, timeout=5)
    connection.request(
        "POST",
        "/v1/connection/reconnect",
        body=b"",
        headers={"Authorization": f"Bearer {API_TOKEN}", "Content-Length": "0"},
    )
    response = connection.getresponse()
    response.read()
    connection.close()
    if response.status != 202:
        raise AssertionError(f"reconnect returned HTTP {response.status}")

    observed = []
    sequences = [snapshot["sequence"]]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        event = next_json(sock, buffer, deadline)
        serialized = json.dumps(event, sort_keys=True)
        for forbidden in [API_TOKEN, "password", "clipboard_text", "typed_text", "pixels"]:
            if forbidden in serialized:
                raise AssertionError("event exposed prohibited data")
        sequence = event.get("sequence")
        if not isinstance(sequence, int) or sequence <= sequences[-1]:
            raise AssertionError("event sequences are not strictly increasing")
        sequences.append(sequence)
        observed.append(event.get("type"))
        if "connection_state" in observed and "framebuffer_invalidated" in observed:
            break
    else:
        raise AssertionError("reconnect events were not observed: " + repr(observed))
finally:
    try:
        send_frame(sock, 0x8, struct.pack("!H", 1000))
    finally:
        sock.close()
PY

log "waiting for controller readiness after reconnect"
wait_for_controller

log "sending authenticated input and payload-redaction probes"
status="$(curl --silent --show-error --output "$temporary_directory/pointer.json" --write-out '%{http_code}' \
    --request POST \
    --header "Authorization: Bearer ${api_token}" \
    --header 'Content-Type: application/json' \
    --data '{"x":417,"y":263}' \
    "http://127.0.0.1:${api_port}/v1/pointer/move")"
[[ "$status" == "202" ]] || fail "authenticated pointer request returned HTTP $status"
grep -Fq '"status":"accepted"' "$temporary_directory/pointer.json" || \
    fail "pointer response did not publish the accepted marker"

status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --request POST \
    --header "Authorization: Bearer ${api_token}" \
    --header 'Content-Type: application/json' \
    --data "{\"text\":\"${typed_secret}\"}" \
    "http://127.0.0.1:${api_port}/v1/keyboard/text")"
[[ "$status" == "202" ]] || fail "authenticated text request returned HTTP $status"

status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --request PUT \
    --header "Authorization: Bearer ${api_token}" \
    --header 'Content-Type: application/json' \
    --data "{\"text\":\"${clipboard_secret}\"}" \
    "http://127.0.0.1:${api_port}/v1/clipboard")"
[[ "$status" == "202" ]] || fail "authenticated clipboard request returned HTTP $status"

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

log "verifying authenticated bounded-label metrics"
status="$(curl --silent --show-error --output "$temporary_directory/metrics.txt" --write-out '%{http_code}' \
    --header "Authorization: Bearer ${api_token}" \
    "http://127.0.0.1:${api_port}/v1/metrics")"
[[ "$status" == "200" ]] || fail "metrics request returned HTTP $status"
for metric in \
    vrc_connection_state \
    vrc_worker_command_queue_capacity \
    vrc_commands_total \
    vrc_websocket_rejected_total \
    vrc_events_total \
    vrc_protocol_errors_total; do
    grep -Fq "$metric" "$temporary_directory/metrics.txt" || fail "metrics omitted $metric"
done
for secret in "$api_token" "$vnc_password" "$typed_secret" "$clipboard_secret" "$documented_text" "$documented_clipboard"; do
    if grep -Fq "$secret" "$temporary_directory/metrics.txt"; then
        fail "metrics exposed prohibited payload or secret data"
    fi
done

log "verifying the documented curl reconnect example"
# The WebSocket lifecycle probe above performs a manual reconnect.
# Wait past the documented 2-second admission interval before
# validating the standalone curl example.
sleep 2.1
curl --fail-with-body --silent --show-error \
    --request POST \
    --header "$authorization_header" \
    --output "$temporary_directory/documented-reconnect.json" \
    "$base_url/v1/connection/reconnect"
grep -Fq '"status":"accepted"' "$temporary_directory/documented-reconnect.json" || \
    fail "documented reconnect example did not return accepted semantics"
wait_for_controller

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

for secret in "$vnc_password" "$api_token" "$typed_secret" "$clipboard_secret" "$documented_text" "$documented_clipboard"; do
    if grep -Fq "$secret" "$controller_log"; then
        fail "controller log exposed prohibited payload or secret data"
    fi
done
grep -Fq '[REDACTED]' "$controller_log" || \
    fail "controller access log did not emit the authorization redaction marker"
grep -Fq 'http_access' "$controller_log" || \
    fail "controller did not emit structured HTTP access events"
grep -Fq '/v1/events' "$controller_log" || \
    fail "controller access log did not record the WebSocket endpoint"
grep -Fq 'worker_state_transition' "$controller_log" || \
    fail "controller did not emit structured worker state transitions"

printf 'http_runtime_e2e_complete=1\n'
log "authenticated HTTP/WebSocket observability E2E test passed"

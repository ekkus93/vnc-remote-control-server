#!/usr/bin/env bash
set -euo pipefail

readonly image_name="vnc-remote-control-desktop:native-test"
readonly container_name="vnc-remote-control-worker-text-clipboard-${GITHUB_RUN_ID:-local}-$$"
readonly password='worker-text-clipboard-vnc-password'
readonly supported_text='worker text 123'
readonly unsupported_text='blocked☃'
readonly outbound_clipboard='worker outbound clipboard'
readonly inbound_clipboard='desktop inbound clipboard'
temporary_directory=""
driver_pid=""
driver_log=""

log() {
    printf '[worker-text-clipboard-e2e] %s\n' "$*" >&2
}

fail() {
    log "fatal: $*"
    exit 1
}

cleanup() {
    if [[ -n "$driver_pid" ]] && kill -0 "$driver_pid" 2>/dev/null; then
        kill -TERM "$driver_pid" 2>/dev/null || true
        wait "$driver_pid" 2>/dev/null || true
    fi
    docker rm --force "$container_name" >/dev/null 2>&1 || true
    if [[ -n "$temporary_directory" ]]; then
        rm -rf -- "$temporary_directory"
    fi
}
trap cleanup EXIT

wait_for_health() {
    local deadline=$((SECONDS + 90))
    local status
    while (( SECONDS < deadline )); do
        status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container_name")"
        case "$status" in
            healthy)
                return 0
                ;;
            unhealthy)
                docker logs "$container_name" >&2 || true
                fail "desktop container became unhealthy"
                ;;
        esac
        sleep 1
    done
    docker logs "$container_name" >&2 || true
    fail "desktop health deadline exceeded"
}

wait_for_driver_marker() {
    local marker="$1"
    local deadline=$((SECONDS + 30))
    while (( SECONDS < deadline )); do
        if grep -Fq "$marker" "$driver_log"; then
            return 0
        fi
        if ! kill -0 "$driver_pid" 2>/dev/null; then
            set +e
            wait "$driver_pid"
            local status=$?
            set -e
            driver_pid=""
            cat "$driver_log" >&2
            fail "worker text/clipboard driver exited before marker with status $status"
        fi
        sleep 0.1
    done
    cat "$driver_log" >&2
    fail "worker text/clipboard driver did not publish marker: $marker"
}

temporary_directory="$(mktemp -d)"
printf '%s\n' "$password" > "$temporary_directory/vnc_password"
chmod 0444 "$temporary_directory/vnc_password"

if ! docker image inspect "$image_name" >/dev/null 2>&1; then
    log "building project-owned desktop image"
    docker build --tag "$image_name" desktop
fi

docker run --detach \
    --name "$container_name" \
    --mount "type=bind,source=$temporary_directory/vnc_password,target=/run/secrets/vnc_password,readonly" \
    --publish 127.0.0.1::5901 \
    "$image_name" >/dev/null

wait_for_health

port_mapping="$(docker port "$container_name" 5901/tcp)"
host_port="${port_mapping##*:}"
[[ "$host_port" =~ ^[0-9]+$ ]] || fail "could not resolve dynamically published VNC port"

log "starting production WorkerClient text and clipboard driver"
driver_log="$temporary_directory/worker-text-clipboard-e2e.log"
timeout --kill-after=5s 70s env \
    VRC_VNC_HOST=127.0.0.1 \
    VRC_VNC_PORT="$host_port" \
    VRC_VNC_PASSWORD_FILE="$temporary_directory/vnc_password" \
    cargo run --locked --quiet -p controller-api --bin worker-text-clipboard-e2e \
    >"$driver_log" 2>&1 &
driver_pid=$!

wait_for_driver_marker 'worker_text_clipboard_outbound_ready=1'

log "verifying supported text and unsupported-text atomicity"
docker exec -i "$container_name" python3 - "$supported_text" <<'PY'
import json
import sys
import time
from pathlib import Path

expected = sys.argv[1]
state_path = Path('/tmp/vnc-test-app-state.json')
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    state = json.loads(state_path.read_text(encoding='utf-8'))
    if state['text'] == expected and state['keys_down'] == []:
        break
    time.sleep(0.1)
else:
    raise AssertionError(
        'deterministic app text differs after supported and rejected unsupported input: '
        + json.dumps(state, sort_keys=True)
    )
PY

log "verifying outbound worker clipboard on the desktop"
docker exec -i --env DISPLAY=:1 "$container_name" python3 - "$outbound_clipboard" <<'PY'
import sys
import time
import tkinter as tk

expected = sys.argv[1]
root = tk.Tk()
root.withdraw()
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    root.update()
    try:
        value = root.clipboard_get()
    except tk.TclError:
        value = None
    if value == expected:
        break
    time.sleep(0.1)
else:
    root.destroy()
    raise AssertionError('desktop did not observe outbound WorkerClient clipboard')
root.destroy()
PY

log "publishing desktop clipboard for inbound worker observation"
docker exec -i --env DISPLAY=:1 "$container_name" python3 - "$inbound_clipboard" <<'PY'
import sys
import time
import tkinter as tk

value = sys.argv[1]
root = tk.Tk()
root.withdraw()
root.clipboard_clear()
root.clipboard_append(value)
root.update_idletasks()
deadline = time.monotonic() + 8
while time.monotonic() < deadline:
    root.update()
    time.sleep(0.05)
root.destroy()
PY

set +e
wait "$driver_pid"
driver_status=$?
set -e
driver_pid=""
[[ "$driver_status" -eq 0 ]] || {
    cat "$driver_log" >&2
    docker logs "$container_name" >&2 || true
    fail "worker text/clipboard driver exited with status $driver_status"
}

grep -Fq 'worker_text_clipboard_e2e_complete=1' "$driver_log" || {
    cat "$driver_log" >&2
    fail "worker text/clipboard driver did not publish completion marker"
}
grep -Eq 'clipboard_revision=[1-9][0-9]*' "$driver_log" || {
    cat "$driver_log" >&2
    fail "worker text/clipboard driver did not publish a positive clipboard revision"
}

for forbidden in \
    "$password" \
    "$supported_text" \
    "$unsupported_text" \
    "$outbound_clipboard" \
    "$inbound_clipboard"; do
    if grep -Fq "$forbidden" "$driver_log"; then
        cat "$driver_log" >&2
        fail "worker log exposed a secret or text/clipboard payload"
    fi
    if docker logs "$container_name" 2>&1 | grep -Fq "$forbidden"; then
        fail "desktop log exposed a secret or text/clipboard payload"
    fi
done

cat "$driver_log"
log "WorkerHandle TigerVNC text and clipboard E2E test passed"

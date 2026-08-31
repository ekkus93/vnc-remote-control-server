#!/usr/bin/env bash
set -euo pipefail

readonly image_name="vnc-remote-control-desktop:native-test"
readonly container_name="vnc-remote-control-native-test-${GITHUB_RUN_ID:-local}-$$"
readonly password='vnc-test'
temporary_directory=""
native_pid=""
native_spike=""

log() {
    printf '[native-smoke] %s\n' "$*" >&2
}

fail() {
    log "fatal: $*"
    exit 1
}

cleanup() {
    if [[ -n "$native_pid" ]] && kill -0 "$native_pid" 2>/dev/null; then
        kill -TERM "$native_pid" 2>/dev/null || true
        wait "$native_pid" 2>/dev/null || true
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

run_expected_connection_failure() {
    local label="$1"
    local port="$2"
    local password_file="$3"
    local forbidden_secret="$4"
    local failure_log="$temporary_directory/${label}.log"
    local status

    log "verifying bounded native failure: $label"
    set +e
    timeout --kill-after=2s 10s env \
        VRC_VNC_HOST=127.0.0.1 \
        VRC_VNC_PORT="$port" \
        VRC_VNC_PASSWORD_FILE="$password_file" \
        VRC_PROOF_HOLD_SECONDS=0 \
        "$native_spike" \
        >"$failure_log" 2>&1
    status=$?
    set -e

    [[ "$status" -eq 1 ]] || {
        cat "$failure_log" >&2
        fail "$label exited with status $status instead of a clean application failure"
    }
    grep -Fq 'native spike failed:' "$failure_log" || {
        cat "$failure_log" >&2
        fail "$label did not produce the bounded native error envelope"
    }
    if grep -Fq 'proof_ready=1' "$failure_log"; then
        cat "$failure_log" >&2
        fail "$label unexpectedly reached an authenticated proof state"
    fi
    if grep -Fq "$forbidden_secret" "$failure_log"; then
        cat "$failure_log" >&2
        fail "$label exposed its VNC password in output"
    fi
}

temporary_directory="$(mktemp -d)"
printf '%s\n' "$password" > "$temporary_directory/vnc_password"
chmod 0444 "$temporary_directory/vnc_password"

log "running native clipboard callback failure unit test"
read -r -a vnc_cflags <<< "$(pkg-config --cflags libvncclient)"
read -r -a vnc_libs <<< "$(pkg-config --libs libvncclient)"
"${CC:-cc}" -std=c11 -Wall -Wextra -Werror -pedantic \
    "${vnc_cflags[@]}" \
    tests/native/vnc_shim_clipboard_callback_test.c \
    -o "$temporary_directory/vnc-shim-clipboard-callback-test" \
    "${vnc_libs[@]}"
"$temporary_directory/vnc-shim-clipboard-callback-test"

log "building native adapter proof binary"
cargo build --locked --quiet -p libvnc-adapter --bin native-spike
native_spike="${CARGO_TARGET_DIR:-target}/debug/native-spike"
[[ -x "$native_spike" ]] || fail "native adapter proof binary was not produced"

log "building project-owned desktop image"
docker build --tag "$image_name" desktop

docker run --detach \
    --name "$container_name" \
    --mount "type=bind,source=$temporary_directory/vnc_password,target=/run/secrets/vnc_password,readonly" \
    --publish 127.0.0.1:5901:5901 \
    "$image_name" >/dev/null

wait_for_health

log "connecting through the Rust LibVNCClient adapter"
spike_log="$temporary_directory/native-spike.log"
timeout --kill-after=2s 35s env \
    VRC_VNC_HOST=127.0.0.1 \
    VRC_VNC_PORT=5901 \
    VRC_VNC_PASSWORD_FILE="$temporary_directory/vnc_password" \
    VRC_PROOF_HOLD_SECONDS=15 \
    "$native_spike" \
    >"$spike_log" 2>&1 &
native_pid=$!

proof_deadline=$((SECONDS + 25))
proof_ready=0
while (( SECONDS < proof_deadline )); do
    if grep -Fq 'proof_ready=1' "$spike_log"; then
        proof_ready=1
        break
    fi
    if ! kill -0 "$native_pid" 2>/dev/null; then
        set +e
        wait "$native_pid"
        native_status=$?
        set -e
        native_pid=""
        cat "$spike_log" >&2
        fail "native adapter exited before proof verification with status $native_status"
    fi
    sleep 0.1
done
[[ "$proof_ready" -eq 1 ]] || {
    cat "$spike_log" >&2
    fail "native adapter did not reach the proof-ready state"
}

log "verifying pointer and key observations"
docker exec -i "$container_name" python3 - <<'PY'
import json
import time
from pathlib import Path

state_path = Path('/tmp/vnc-test-app-state.json')
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    state = json.loads(state_path.read_text(encoding='utf-8'))
    events = state['events']
    pointer_ok = state['pointer'] == {'x': 100, 'y': 100}
    key_down = any(event['type'] == 'key_down' and event.get('key') == 'F5' for event in events)
    key_up = any(event['type'] == 'key_up' and event.get('key') == 'F5' for event in events)
    if pointer_ok and key_down and key_up:
        break
    time.sleep(0.1)
else:
    raise AssertionError('deterministic test app did not observe native pointer and F5 input')
PY

log "verifying outbound clipboard observation while connected"
docker exec -i --env DISPLAY=:1 "$container_name" python3 - <<'PY'
import time
import tkinter as tk

root = tk.Tk()
root.withdraw()
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    root.update()
    try:
        value = root.clipboard_get()
    except tk.TclError:
        value = None
    if value == 'native-clipboard-proof':
        break
    time.sleep(0.1)
else:
    root.destroy()
    raise AssertionError('desktop did not observe the native clipboard value while connected')
root.destroy()
PY

set +e
wait "$native_pid"
native_status=$?
set -e
native_pid=""
[[ "$native_status" -eq 0 ]] || {
    cat "$spike_log" >&2
    fail "native adapter exited with status $native_status after proof verification"
}
cat "$spike_log"

wrong_password='definitely-wrong-native-password'
printf '%s\n' "$wrong_password" > "$temporary_directory/wrong_vnc_password"
chmod 0444 "$temporary_directory/wrong_vnc_password"
run_expected_connection_failure \
    wrong-password \
    5901 \
    "$temporary_directory/wrong_vnc_password" \
    "$wrong_password"
run_expected_connection_failure \
    unreachable-port \
    1 \
    "$temporary_directory/vnc_password" \
    "$password"

if docker logs "$container_name" 2>&1 | grep -Fq "$password"; then
    fail "runtime password appeared in desktop logs"
fi

log "native adapter smoke test passed"

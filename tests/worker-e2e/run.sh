#!/usr/bin/env bash
set -euo pipefail

readonly image_name="vnc-remote-control-desktop:native-test"
readonly container_name="vnc-remote-control-worker-e2e-${GITHUB_RUN_ID:-local}-$$"
readonly password='worker-e2e-vnc-password'
readonly failure_artifact_directory="${WORKER_E2E_FAILURE_ARTIFACT_DIR:-}"
readonly force_failure_after_input="${WORKER_E2E_FORCE_FAILURE_AFTER_INPUT:-0}"
readonly redaction_self_test="${WORKER_E2E_REDACTION_SELF_TEST:-0}"
temporary_directory=""
worker_log=""

log() {
    printf '[worker-e2e] %s\n' "$*" >&2
}

fail() {
    log "fatal: $*"
    exit 1
}

sanitize_file() {
    local path="$1"
    [[ -f "$path" ]] || return 0

    WORKER_E2E_SECRET="$password" python3 - "$path" <<'PY'
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
secret = os.environ["WORKER_E2E_SECRET"]
data = path.read_text(encoding="utf-8", errors="replace")
path.write_text(data.replace(secret, "[REDACTED]"), encoding="utf-8")
PY
}

capture_failure_artifacts() {
    local exit_status="$1"
    local artifact

    [[ -n "$failure_artifact_directory" ]] || return 0
    mkdir -p "$failure_artifact_directory"

    if [[ -n "$worker_log" && -f "$worker_log" ]]; then
        cp -- "$worker_log" "$failure_artifact_directory/worker-input-e2e.log"
    else
        printf 'worker log was not created\n' > "$failure_artifact_directory/worker-input-e2e.log"
    fi

    if docker inspect "$container_name" >/dev/null 2>&1; then
        docker logs "$container_name" > "$failure_artifact_directory/desktop.log" 2>&1 || true
        docker inspect --format '{{json .State}}' "$container_name" \
            > "$failure_artifact_directory/container-state.json" 2>&1 || true
        docker exec "$container_name" cat /tmp/vnc-test-app-state.json \
            > "$failure_artifact_directory/desktop-state.json" 2> "$failure_artifact_directory/desktop-state-error.log" || true
    else
        printf 'desktop container was not created\n' > "$failure_artifact_directory/desktop.log"
        printf '{}\n' > "$failure_artifact_directory/container-state.json"
        printf '{}\n' > "$failure_artifact_directory/desktop-state.json"
        printf 'desktop container unavailable\n' > "$failure_artifact_directory/desktop-state-error.log"
    fi

    python3 - "$failure_artifact_directory/failure-manifest.json" "$exit_status" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
manifest = {
    "schema_version": 1,
    "test": "WorkerHandle TigerVNC input E2E",
    "exit_status": int(sys.argv[2]),
    "github_run_id": os.environ.get("GITHUB_RUN_ID"),
    "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
    "github_sha": os.environ.get("GITHUB_SHA"),
}
path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

    if [[ "$redaction_self_test" == "1" ]]; then
        printf '%s\n' "$password" > "$failure_artifact_directory/redaction-self-test.log"
    fi
    [[ "$redaction_self_test" == "0" || "$redaction_self_test" == "1" ]] || {
        printf 'invalid WORKER_E2E_REDACTION_SELF_TEST value\n' \
            > "$failure_artifact_directory/redaction-self-test-error.log"
    }

    for artifact in "$failure_artifact_directory"/*; do
        sanitize_file "$artifact"
    done

    log "captured sanitized failure artifacts in $failure_artifact_directory"
}

cleanup() {
    docker rm --force "$container_name" >/dev/null 2>&1 || true
    if [[ -n "$temporary_directory" ]]; then
        rm -rf -- "$temporary_directory"
    fi
}

on_exit() {
    local exit_status=$?
    trap - EXIT
    if (( exit_status != 0 )); then
        capture_failure_artifacts "$exit_status"
    fi
    cleanup
    exit "$exit_status"
}
trap on_exit EXIT

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

log "sending input through the production WorkerClient"
worker_log="$temporary_directory/worker-input-e2e.log"
set +e
timeout --kill-after=5s 60s env \
    VRC_VNC_HOST=127.0.0.1 \
    VRC_VNC_PORT="$host_port" \
    VRC_VNC_PASSWORD_FILE="$temporary_directory/vnc_password" \
    cargo run --locked --quiet -p controller-api --bin worker-input-e2e \
    >"$worker_log" 2>&1
worker_status=$?
set -e
[[ "$worker_status" -eq 0 ]] || {
    cat "$worker_log" >&2
    docker logs "$container_name" >&2 || true
    fail "worker input E2E driver exited with status $worker_status"
}
grep -Fq 'worker_input_e2e_complete=1' "$worker_log" || {
    cat "$worker_log" >&2
    fail "worker input E2E driver did not publish its completion marker"
}
if grep -Fq "$password" "$worker_log"; then
    cat "$worker_log" >&2
    fail "worker input E2E driver exposed the VNC password"
fi

log "verifying deterministic desktop observations"
docker exec -i "$container_name" python3 - <<'PY'
import json
import time
from pathlib import Path

state_path = Path('/tmp/vnc-test-app-state.json')
deadline = time.monotonic() + 10


def contains_ordered(events, expected):
    index = 0
    for event in events:
        if index >= len(expected):
            break
        if all(event.get(key) == value for key, value in expected[index].items()):
            index += 1
    return index == len(expected)


def count_events(events, **expected):
    return sum(
        1
        for event in events
        if all(event.get(key) == value for key, value in expected.items())
    )


mouse_sequence = [
    {'type': 'button_down', 'button': 'left', 'x': 320, 'y': 240},
    {'type': 'button_up', 'button': 'left', 'x': 320, 'y': 240},
    {'type': 'button_down', 'button': 'left', 'x': 320, 'y': 240},
    {'type': 'button_up', 'button': 'left', 'x': 320, 'y': 240},
    {'type': 'button_down', 'button': 'middle', 'x': 340, 'y': 260},
    {'type': 'button_up', 'button': 'middle', 'x': 340, 'y': 260},
    {'type': 'button_down', 'button': 'right', 'x': 360, 'y': 280},
    {'type': 'button_up', 'button': 'right', 'x': 360, 'y': 280},
    {'type': 'button_down', 'button': 'left', 'x': 380, 'y': 300},
    {'type': 'button_up', 'button': 'left', 'x': 380, 'y': 300},
    {'type': 'button_down', 'button': 'left', 'x': 380, 'y': 300},
    {'type': 'button_up', 'button': 'left', 'x': 380, 'y': 300},
]

key_sequence = [
    {'type': 'key_down', 'key': 'F5'},
    {'type': 'key_up', 'key': 'F5'},
    {'type': 'key_down', 'key': 'Control_L'},
    {'type': 'key_down', 'key': 'Shift_L'},
    {'type': 'key_down', 'key': 'F6'},
    {'type': 'key_up', 'key': 'F6'},
    {'type': 'key_up', 'key': 'Shift_L'},
    {'type': 'key_up', 'key': 'Control_L'},
]

while time.monotonic() < deadline:
    state = json.loads(state_path.read_text(encoding='utf-8'))
    events = state['events']

    positive_vertical_steps = count_events(
        events,
        type='scroll',
        delta_x=0,
        delta_y=1,
    )
    negative_vertical_steps = count_events(
        events,
        type='scroll',
        delta_x=0,
        delta_y=-1,
    )

    if (
        state['pointer'] == {'x': 320, 'y': 240}
        and state['buttons'] == {'left': False, 'middle': False, 'right': False}
        and state['scroll'] == {'x': 0, 'y': 1}
        and state['keys_down'] == []
        and contains_ordered(events, mouse_sequence)
        and contains_ordered(events, key_sequence)
        and positive_vertical_steps == 2
        and negative_vertical_steps == 1
    ):
        break
    time.sleep(0.1)
else:
    raise AssertionError(
        'deterministic test app did not observe the complete WorkerClient input sequence: '
        + json.dumps(state, sort_keys=True)
    )
PY

if docker logs "$container_name" 2>&1 | grep -Fq "$password"; then
    fail "runtime password appeared in desktop logs"
fi

if [[ "$force_failure_after_input" == "1" ]]; then
    fail "injected post-verification failure for diagnostics self-test"
fi
[[ "$force_failure_after_input" == "0" ]] || fail "WORKER_E2E_FORCE_FAILURE_AFTER_INPUT must be 0 or 1"

cat "$worker_log"
log "WorkerHandle TigerVNC input E2E test passed"

#!/usr/bin/env bash
set -euo pipefail

readonly image_name="vnc-remote-control-desktop:native-test"
readonly container_name="vnc-remote-control-worker-e2e-${GITHUB_RUN_ID:-local}-$$"
readonly password='worker-e2e-vnc-password'
temporary_directory=""

log() {
    printf '[worker-e2e] %s\n' "$*" >&2
}

fail() {
    log "fatal: $*"
    exit 1
}

cleanup() {
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
        event_type, key = expected[index]
        if event.get('type') == event_type and event.get('key') == key:
            index += 1
    return index == len(expected)


while time.monotonic() < deadline:
    state = json.loads(state_path.read_text(encoding='utf-8'))
    events = state['events']

    click_down = any(
        event.get('type') == 'button_down'
        and event.get('button') == 'left'
        and event.get('x') == 320
        and event.get('y') == 240
        for event in events
    )
    click_up = any(
        event.get('type') == 'button_up'
        and event.get('button') == 'left'
        and event.get('x') == 320
        and event.get('y') == 240
        for event in events
    )
    vertical_steps = sum(
        1
        for event in events
        if event.get('type') == 'scroll'
        and event.get('delta_x') == 0
        and event.get('delta_y') == 1
    )
    standalone_key = contains_ordered(
        events,
        [('key_down', 'F5'), ('key_up', 'F5')],
    )
    chord = contains_ordered(
        events,
        [
            ('key_down', 'Control_L'),
            ('key_down', 'Shift_L'),
            ('key_down', 'F6'),
            ('key_up', 'F6'),
            ('key_up', 'Shift_L'),
            ('key_up', 'Control_L'),
        ],
    )

    if (
        state['pointer'] == {'x': 320, 'y': 240}
        and state['buttons'] == {'left': False, 'middle': False, 'right': False}
        and state['scroll'] == {'x': 0, 'y': 2}
        and state['keys_down'] == []
        and click_down
        and click_up
        and vertical_steps == 2
        and standalone_key
        and chord
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

cat "$worker_log"
log "WorkerHandle TigerVNC input E2E test passed"

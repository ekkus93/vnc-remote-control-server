#!/usr/bin/env bash
set -euo pipefail

readonly image_name="vnc-remote-control-desktop:native-test"
readonly container_name="vnc-remote-control-native-test-${GITHUB_RUN_ID:-local}-$$"
readonly password='vnc-test'
temporary_directory=""

log() {
    printf '[native-smoke] %s\n' "$*" >&2
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

log "building project-owned desktop image"
docker build --tag "$image_name" desktop

docker run --detach \
    --name "$container_name" \
    --mount "type=bind,source=$temporary_directory/vnc_password,target=/run/secrets/vnc_password,readonly" \
    --publish 127.0.0.1:5901:5901 \
    "$image_name" >/dev/null

wait_for_health

log "connecting through the Rust LibVNCClient adapter"
VRC_VNC_HOST=127.0.0.1 \
VRC_VNC_PORT=5901 \
VRC_VNC_PASSWORD_FILE="$temporary_directory/vnc_password" \
    cargo run --locked --quiet -p libvnc-adapter --bin native-spike

if docker logs "$container_name" 2>&1 | grep -Fq "$password"; then
    fail "runtime password appeared in desktop logs"
fi

log "native adapter smoke test passed"

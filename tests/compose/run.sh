#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly root_dir
cd "$root_dir"

log() {
    printf '[compose-smoke] %s\n' "$*" >&2
}

fail() {
    log "fatal: $*"
    exit 1
}

command -v docker >/dev/null 2>&1 || fail "docker is required"
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required"
command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v python3 >/dev/null 2>&1 || fail "python3 is required"

temp_dir="$(mktemp -d)"
project_suffix="${GITHUB_RUN_ID:-$$}-${GITHUB_RUN_ATTEMPT:-1}"
project_name="$(printf 'vrc-r12-%s' "$project_suffix" | tr '[:upper:]_' '[:lower:]-' | tr -cd 'a-z0-9-')"
api_token="r12-api-token-${project_suffix}"
vnc_password="r12-vnc-password-${project_suffix}"

free_port() {
    python3 - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}

api_port="$(free_port)"
debug_vnc_port="$(free_port)"
api_secret="${temp_dir}/api_token"
vnc_secret="${temp_dir}/vnc_password"
printf '%s' "$api_token" > "$api_secret"
printf '%s' "$vnc_password" > "$vnc_secret"
# Local Compose implements file-backed secrets as read-only bind mounts and
# preserves the host file owner. Keep the containing directory private while
# making each mounted file readable by the non-root service UID.
chmod 0700 "$temp_dir"
chmod 0444 "$api_secret" "$vnc_secret"

export VRC_API_BIND_ADDRESS=127.0.0.1
export VRC_API_HOST_PORT="$api_port"
export VRC_DEBUG_VNC_PORT="$debug_vnc_port"
export VRC_API_TOKEN_SOURCE="$api_secret"
export VRC_VNC_PASSWORD_SOURCE="$vnc_secret"
export VRC_DESKTOP_HOME_VOLUME="${project_name}-desktop-home"

base=(docker compose --project-name "$project_name" -f deploy/compose.yaml)
debug=(docker compose --project-name "$project_name" -f deploy/compose.yaml -f deploy/compose.debug-vnc.yaml)
persistent=(docker compose --project-name "$project_name" -f deploy/compose.yaml -f deploy/compose.persistence.yaml)

cleanup() {
    "${debug[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
    "${persistent[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
    "${base[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
    docker volume rm "$VRC_DESKTOP_HOME_VOLUME" >/dev/null 2>&1 || true
    rm -rf -- "$temp_dir"
}
trap cleanup EXIT

wait_healthy() {
    local compose_name="$1"
    local service="$2"
    local deadline=$((SECONDS + 120))
    local container_id=""
    while (( SECONDS < deadline )); do
        case "$compose_name" in
            base) container_id="$("${base[@]}" ps -q "$service")" ;;
            debug) container_id="$("${debug[@]}" ps -q "$service")" ;;
            persistent) container_id="$("${persistent[@]}" ps -q "$service")" ;;
            *) fail "unknown compose selector: $compose_name" ;;
        esac
        if [[ -n "$container_id" ]]; then
            status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"
            if [[ "$status" == "healthy" ]]; then
                return 0
            fi
            if [[ "$status" == "unhealthy" || "$status" == "exited" || "$status" == "dead" ]]; then
                docker logs "$container_id" >&2 || true
                fail "${service} became ${status}"
            fi
        fi
        sleep 1
    done
    [[ -z "$container_id" ]] || docker logs "$container_id" >&2 || true
    fail "timed out waiting for ${service} health"
}

assert_compose_contract() {
    "${base[@]}" config --format json > "${temp_dir}/production.json"
    "${debug[@]}" config --format json > "${temp_dir}/debug.json"
    python3 - "${temp_dir}/production.json" "${temp_dir}/debug.json" <<'PY'
import json
import sys
from pathlib import Path

production = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
debug = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

desktop = production["services"]["desktop"]
controller = production["services"]["controller"]

if desktop.get("ports"):
    raise SystemExit("production desktop unexpectedly publishes a host port")
if not any(str(value).split("/", 1)[0] == "5901" for value in desktop.get("expose", [])):
    raise SystemExit("production desktop does not expose 5901 internally")
desktop_networks = set(desktop.get("networks", {}))
controller_networks = set(controller.get("networks", {}))
if desktop_networks != {"desktop_control"}:
    raise SystemExit(f"desktop has unexpected networks: {desktop_networks!r}")
if controller_networks != {"desktop_control", "api_ingress"}:
    raise SystemExit(f"controller has unexpected networks: {controller_networks!r}")
if not production["networks"]["desktop_control"].get("internal"):
    raise SystemExit("desktop_control network is not internal")
if production["networks"]["api_ingress"].get("internal"):
    raise SystemExit("api_ingress network is unexpectedly internal")
if not controller.get("read_only"):
    raise SystemExit("controller root filesystem is not read-only")
if any("docker.sock" in json.dumps(value) for value in production.get("services", {}).values()):
    raise SystemExit("production Compose mounts the Docker socket")

debug_ports = debug["services"]["desktop"].get("ports", [])
if len(debug_ports) != 1:
    raise SystemExit(f"debug VNC expected one published port, found {debug_ports!r}")
port = debug_ports[0]
if str(port.get("target")) != "5901" or port.get("host_ip") != "127.0.0.1":
    raise SystemExit(f"debug VNC is not loopback-only: {port!r}")
PY
}

assert_controller_image_contract() {
    local image_id
    image_id="$("${base[@]}" images -q controller)"
    [[ -n "$image_id" ]] || fail "controller image id is missing"

    [[ "$(docker image inspect --format '{{.Config.User}}' "$image_id")" == "controller:controller" ]] \
        || fail "controller image does not run as the dedicated user"

    docker run --rm --entrypoint /bin/sh "$image_id" -ec '
        test "$(id -u)" = 10002
        ! command -v cargo
        ! command -v rustc
        ! command -v cc
        ! test -d /usr/local/cargo
        ldd /usr/local/bin/controller-api | grep -F libvncclient
        test -x /usr/local/bin/controller-healthcheck
    ' >/dev/null

    if docker history --no-trunc "$image_id" | grep -Fq "$api_token"; then
        fail "API token appeared in controller image history"
    fi
    if docker history --no-trunc "$image_id" | grep -Fq "$vnc_password"; then
        fail "VNC password appeared in controller image history"
    fi
}

assert_running_security_contract() {
    local controller_id desktop_id
    controller_id="$("${base[@]}" ps -q controller)"
    desktop_id="$("${base[@]}" ps -q desktop)"
    [[ -n "$controller_id" && -n "$desktop_id" ]] || fail "stack containers are missing"

    [[ "$(docker inspect --format '{{.HostConfig.ReadonlyRootfs}}' "$controller_id")" == "true" ]] \
        || fail "running controller root filesystem is writable"
    docker inspect --format '{{json .HostConfig.SecurityOpt}}' "$controller_id" \
        | grep -Fq 'no-new-privileges:true' \
        || fail "controller no-new-privileges is absent"
    docker inspect --format '{{json .HostConfig.Binds}} {{json .Mounts}}' "$controller_id" \
        | grep -Fqv 'docker.sock' \
        || fail "controller mounts the Docker socket"

    if "${base[@]}" port desktop 5901 2>/dev/null | grep -q .; then
        fail "production desktop has a published VNC port"
    fi
}

assert_api() {
    local base_url="http://127.0.0.1:${api_port}"
    curl --fail --silent --show-error "${base_url}/health/live" >/dev/null
    curl --fail --silent --show-error "${base_url}/health/ready" >/dev/null
    curl --fail --silent --show-error \
        -H "Authorization: Bearer ${api_token}" \
        "${base_url}/v1/status" > "${temp_dir}/status.json"
    curl --fail --silent --show-error \
        -H "Authorization: Bearer ${api_token}" \
        "${base_url}/v1/display" > "${temp_dir}/display.json"
    curl --fail --silent --show-error \
        -H "Authorization: Bearer ${api_token}" \
        "${base_url}/v1/screenshot.png" > "${temp_dir}/screenshot.png"

    python3 - "${temp_dir}/status.json" "${temp_dir}/display.json" "${temp_dir}/screenshot.png" <<'PY'
import json
import sys
from pathlib import Path

status = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
display = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
png = Path(sys.argv[3]).read_bytes()

if status.get("state") != "connected":
    raise SystemExit(f"unexpected controller state: {status!r}")
if display.get("width") != 1280 or display.get("height") != 800:
    raise SystemExit(f"unexpected display metadata: {display!r}")
if not png.startswith(b"\x89PNG\r\n\x1a\n"):
    raise SystemExit("screenshot is not a PNG")
PY
}

assert_secret_absent_from_home() {
    printf '%s' "$vnc_password" \
        | "${persistent[@]}" exec -T desktop sh -ec '
            secret="$(cat)"
            if find /home/desktop -type f -name passwd -print -quit | grep -q .; then
                exit 1
            fi
            if grep -R -F -q -- "$secret" /home/desktop 2>/dev/null; then
                exit 1
            fi
        ' || fail "secret material was found in the persistent desktop home"
}

log "validating rendered Compose topology"
assert_compose_contract

log "building production images"
"${base[@]}" build

log "starting disposable production stack"
if ! "${base[@]}" up --detach; then
    "${base[@]}" ps --all >&2 || true
    "${base[@]}" logs --no-color >&2 || true
    fail "production stack failed before health checks"
fi
wait_healthy base desktop
wait_healthy base controller
assert_controller_image_contract
assert_running_security_contract
assert_api

log "verifying disposable desktop recreation"
"${base[@]}" exec -T desktop sh -ec 'printf disposable > /home/desktop/r12-disposable-marker'
"${base[@]}" down --remove-orphans
"${base[@]}" up --detach
wait_healthy base desktop
wait_healthy base controller
"${base[@]}" exec -T desktop test ! -e /home/desktop/r12-disposable-marker \
    || fail "disposable desktop state survived recreation"
"${base[@]}" down --remove-orphans

log "verifying loopback-only development VNC override"
"${debug[@]}" up --detach desktop
wait_healthy debug desktop
debug_binding="$("${debug[@]}" port desktop 5901)"
[[ "$debug_binding" == "127.0.0.1:${debug_vnc_port}" ]] \
    || fail "unexpected debug VNC binding: ${debug_binding}"
python3 - "$debug_vnc_port" <<'PY'
import socket
import sys
with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=5):
    pass
PY
"${debug[@]}" down --remove-orphans

log "verifying persistent desktop-home recreation"
"${persistent[@]}" up --detach
wait_healthy persistent desktop
wait_healthy persistent controller
"${persistent[@]}" exec -T desktop sh -ec 'printf persistent > /home/desktop/r12-persistent-marker'
assert_secret_absent_from_home
"${persistent[@]}" down --remove-orphans
"${persistent[@]}" up --detach
wait_healthy persistent desktop
wait_healthy persistent controller
"${persistent[@]}" exec -T desktop grep -Fxq persistent /home/desktop/r12-persistent-marker \
    || fail "persistent desktop state did not survive recreation"
assert_secret_absent_from_home
assert_api

log "R12 Compose, image, security, API, debug VNC, and persistence smoke passed"

#!/usr/bin/env bash
set -euo pipefail

readonly image_name="vnc-remote-control-desktop:test"
readonly container_name="vnc-remote-control-desktop-test-${GITHUB_RUN_ID:-local}-$$"
readonly password='vnc-test'
readonly base_reference='debian:13.6-slim@sha256:020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd'
temporary_directory=""

log() {
    printf '[desktop-smoke] %s\n' "$*" >&2
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

viewer_log_has_auth_failure() {
    local log_path="$1"
    grep -Eiq 'authentication failure|authentication failed|password.*failed|security.*failed' "$log_path"
}

viewer_log_has_connection_evidence() {
    local log_path="$1"
    grep -Eq 'Connected to host 127\.0\.0\.1 port 5901' "$log_path" \
        && grep -Eq 'Using RFB protocol version' "$log_path" \
        && grep -Eq 'Choosing security type VncAuth' "$log_path"
}

viewer_log_has_authenticated_session_evidence() {
    local log_path="$1"
    grep -Eq 'Using pixel format depth' "$log_path" \
        && grep -Eq 'Enabling continuous updates' "$log_path"
}

run_viewer_probe() {
    local password_value="$1"
    local expected="$2"
    local password_path="$temporary_directory/viewer-${expected}.passwd"
    local log_path="$temporary_directory/viewer-${expected}.log"
    printf '%s\n' "$password_value" | tigervncpasswd -f > "$password_path"
    chmod 0600 "$password_path"

    set +e
    timeout --kill-after=2s 8s xvfb-run -a vncviewer \
        -PasswordFile "$password_path" \
        -SecurityTypes VncAuth \
        -Shared \
        -ViewOnly \
        127.0.0.1::5901 >"$log_path" 2>&1
    local status=$?
    set -e

    viewer_log_has_connection_evidence "$log_path" || {
        cat "$log_path" >&2
        fail "viewer probe did not reach the expected VNC protocol negotiation"
    }

    if [[ "$expected" == "success" ]]; then
        [[ "$status" -eq 124 ]] || {
            cat "$log_path" >&2
            fail "correct VNC password did not keep an authenticated viewer session open"
        }
        if viewer_log_has_auth_failure "$log_path"; then
            cat "$log_path" >&2
            fail "correct VNC password produced authentication-failure evidence"
        fi
        viewer_log_has_authenticated_session_evidence "$log_path" || {
            cat "$log_path" >&2
            fail "correct VNC password produced no post-authentication session evidence"
        }
    else
        viewer_log_has_auth_failure "$log_path" || {
            cat "$log_path" >&2
            fail "wrong-password viewer failure was not diagnosable"
        }
        if viewer_log_has_authenticated_session_evidence "$log_path"; then
            cat "$log_path" >&2
            fail "wrong VNC password reached an authenticated viewer session"
        fi
    fi
}

temporary_directory="$(mktemp -d)"
printf '%s\n' "$password" > "$temporary_directory/vnc_password"
chmod 0444 "$temporary_directory/vnc_password"

log "pulling the pinned immutable desktop base"
docker pull "$base_reference" >/dev/null
docker image inspect "$base_reference" >/dev/null
printf 'DESKTOP_BASE_DIGEST=%s\n' "${base_reference#*@}"

log "building desktop image"
docker build --pull --tag "$image_name" desktop

if docker history --no-trunc "$image_name" | grep -Fq "$password"; then
    fail "runtime password appeared in image history"
fi

docker run --detach \
    --name "$container_name" \
    --mount "type=bind,source=$temporary_directory/vnc_password,target=/run/secrets/vnc_password,readonly" \
    --publish 127.0.0.1:5901:5901 \
    "$image_name" >/dev/null

wait_for_health

[[ "$(docker exec "$container_name" id -u)" == "10001" ]] || fail "desktop container is not running as UID 10001"
[[ "$(docker exec "$container_name" stat -c '%a' /home/desktop/.vnc/passwd)" == "600" ]] || fail "encoded VNC password permissions are not 0600"
docker exec "$container_name" pgrep -u 10001 -x Xtigervnc >/dev/null || fail "Xtigervnc is not running as desktop user"
docker exec "$container_name" sh -eu -c "nc -z 127.0.0.1 5901"
dimensions="$(docker exec "$container_name" sh -eu -c "xdpyinfo -display :1 | awk '/dimensions:/{print \$2; exit}'")"
[[ "$dimensions" == "1280x800" ]] || fail "unexpected desktop dimensions: $dimensions"
docker exec "$container_name" python3 - <<'PY'
import json
from pathlib import Path

state = json.loads(Path('/tmp/vnc-test-app-state.json').read_text(encoding='utf-8'))
assert state['schema_version'] == 1
assert state['ready'] is True
assert state['counter'] == 0
assert state['events'] == []
PY

if docker logs "$container_name" 2>&1 | grep -Fq "$password"; then
    fail "runtime password appeared in container logs"
fi

run_viewer_probe 'definitely-wrong' failure
run_viewer_probe "$password" success

log "verifying fail-closed startup without a secret"
missing_secret_name="${container_name}-missing-secret"
set +e
docker run --name "$missing_secret_name" "$image_name" >/dev/null 2>&1
missing_secret_status=$?
set -e
[[ "$missing_secret_status" -ne 0 ]] || fail "desktop started without a VNC secret"
docker rm "$missing_secret_name" >/dev/null

log "stopping authenticated desktop"
docker stop --time 15 "$container_name" >/dev/null
exit_code="$(docker inspect --format '{{.State.ExitCode}}' "$container_name")"
[[ "$exit_code" -ne 0 ]] || fail "signal-driven shutdown was reported as a successful application exit"

log "desktop smoke test passed"

#!/usr/bin/env bash
set -euo pipefail

readonly display_number=1
readonly display=":${display_number}"
readonly vnc_port="$((5900 + display_number))"
readonly password_file="${VNC_PASSWORD_FILE:-/run/secrets/vnc_password}"
readonly geometry="${VNC_GEOMETRY:-1280x800}"
readonly depth="${VNC_DEPTH:-24}"
readonly vnc_runtime_dir=/tmp/vnc-runtime
readonly encoded_password_file="${vnc_runtime_dir}/passwd"
readonly readiness_file=/tmp/vnc-desktop-ready
readonly supervisor_pid_file=/tmp/vnc-desktop-supervisor.pid
readonly startup_timeout_seconds="${VNC_STARTUP_TIMEOUT_SECONDS:-30}"

vnc_pid=""
desktop_pid=""

log() {
    printf '[desktop-entrypoint] %s\n' "$*" >&2
}

fail() {
    log "fatal: $*"
    exit 1
}

is_positive_integer() {
    [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

validate_configuration() {
    [[ "$geometry" =~ ^[1-9][0-9]*x[1-9][0-9]*$ ]] || fail "VNC_GEOMETRY must be WIDTHxHEIGHT"
    is_positive_integer "$depth" || fail "VNC_DEPTH must be a positive integer"
    is_positive_integer "$startup_timeout_seconds" || fail "VNC_STARTUP_TIMEOUT_SECONDS must be a positive integer"
    [[ -r "$password_file" ]] || fail "VNC password secret file is missing or unreadable"
    [[ -s "$password_file" ]] || fail "VNC password secret file is empty"
}

remove_stale_display_files() {
    local lock_file="/tmp/.X${display_number}-lock"
    local socket_file="/tmp/.X11-unix/X${display_number}"
    if [[ -e "$lock_file" ]]; then
        local owner_pid
        owner_pid="$(tr -cd '0-9' < "$lock_file")"
        if [[ -n "$owner_pid" ]] && kill -0 "$owner_pid" 2>/dev/null; then
            fail "display ${display} is owned by live process ${owner_pid}"
        fi
        rm -f -- "$lock_file"
    fi
    if [[ -S "$socket_file" ]] && ! pgrep -u "$(id -u)" -x Xtigervnc >/dev/null 2>&1; then
        rm -f -- "$socket_file"
    fi
}

create_password_file() {
    rm -rf -- "$vnc_runtime_dir"
    install -d -m 0700 "$vnc_runtime_dir"
    umask 077
    local password
    password="$(cat -- "$password_file")"
    [[ -n "$password" ]] || fail "VNC password secret is empty"
    printf '%s\n' "$password" | tigervncpasswd -f > "$encoded_password_file"
    unset password
    chmod 0600 "$encoded_password_file"
}

stop_children() {
    local signal="${1:-TERM}"
    if [[ -n "$desktop_pid" ]] && kill -0 "$desktop_pid" 2>/dev/null; then
        kill -s "$signal" "$desktop_pid" 2>/dev/null || true
    fi
    if [[ -n "$vnc_pid" ]] && kill -0 "$vnc_pid" 2>/dev/null; then
        kill -s "$signal" "$vnc_pid" 2>/dev/null || true
    fi
}

cleanup() {
    rm -f -- "$readiness_file" "$supervisor_pid_file"
    stop_children TERM
    local deadline=$((SECONDS + 10))
    while (( SECONDS < deadline )); do
        if { [[ -z "$desktop_pid" ]] || ! kill -0 "$desktop_pid" 2>/dev/null; } \
            && { [[ -z "$vnc_pid" ]] || ! kill -0 "$vnc_pid" 2>/dev/null; }; then
            break
        fi
        sleep 0.1
    done
    stop_children KILL
    wait "$desktop_pid" 2>/dev/null || true
    wait "$vnc_pid" 2>/dev/null || true
    rm -rf -- "$vnc_runtime_dir"
}

trap 'cleanup; exit 143' TERM
trap 'cleanup; exit 130' INT
trap cleanup EXIT

validate_configuration
remove_stale_display_files
create_password_file
printf '%s\n' "$$" > "$supervisor_pid_file"

log "starting authenticated TigerVNC server on ${display}"
Xtigervnc "$display" \
    -geometry "$geometry" \
    -depth "$depth" \
    -rfbauth "$encoded_password_file" \
    -SecurityTypes VncAuth \
    -localhost no \
    -AlwaysShared \
    -DisconnectClients=0 \
    -desktop "VNC Remote Control Test Desktop" \
    -pn &
vnc_pid="$!"

readonly startup_deadline=$((SECONDS + startup_timeout_seconds))
until nc -z 127.0.0.1 "$vnc_port" && xdpyinfo -display "$display" >/dev/null 2>&1; do
    kill -0 "$vnc_pid" 2>/dev/null || fail "Xtigervnc exited during startup"
    (( SECONDS < startup_deadline )) || fail "VNC startup deadline exceeded"
    sleep 0.2
done

log "starting XFCE and deterministic test application"
DISPLAY="$display" /usr/local/bin/xstartup &
desktop_pid="$!"

readonly desktop_deadline=$((SECONDS + startup_timeout_seconds))
until [[ -s "${TEST_APP_STATE_FILE:-/tmp/vnc-test-app-state.json}" ]]; do
    kill -0 "$vnc_pid" 2>/dev/null || fail "Xtigervnc exited while desktop was starting"
    kill -0 "$desktop_pid" 2>/dev/null || fail "desktop session exited during startup"
    (( SECONDS < desktop_deadline )) || fail "desktop startup deadline exceeded"
    sleep 0.2
done

touch "$readiness_file"
log "desktop is ready"

set +e
wait -n "$vnc_pid" "$desktop_pid"
status="$?"
set -e
rm -f -- "$readiness_file"
if (( status == 0 )); then
    fail "a required desktop process exited unexpectedly with status 0"
fi
fail "a required desktop process exited with status ${status}"

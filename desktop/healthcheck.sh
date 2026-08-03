#!/usr/bin/env bash
set -euo pipefail

mode="${1:-ready}"
readonly supervisor_pid_file=/tmp/vnc-desktop-supervisor.pid
readonly readiness_file=/tmp/vnc-desktop-ready

[[ -s "$supervisor_pid_file" ]] || exit 1
supervisor_pid="$(cat -- "$supervisor_pid_file")"
[[ "$supervisor_pid" =~ ^[1-9][0-9]*$ ]] || exit 1
kill -0 "$supervisor_pid" 2>/dev/null || exit 1

if [[ "$mode" == "live" ]]; then
    exit 0
fi

[[ "$mode" == "ready" ]] || exit 2
[[ -f "$readiness_file" ]] || exit 1
nc -z 127.0.0.1 5901
xdpyinfo -display :1 >/dev/null 2>&1

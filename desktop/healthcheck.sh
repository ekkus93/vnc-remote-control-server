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

for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    if [[ -f "$readiness_file" ]] \
        && nc -z -w 1 127.0.0.1 5901 \
        && timeout 1s xdpyinfo -display :1 >/dev/null 2>&1; then
        exit 0
    fi
    sleep 0.1
done

exit 1

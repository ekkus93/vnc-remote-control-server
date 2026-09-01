#!/usr/bin/env bash
set -euo pipefail

: "${XFCE_PID:?XFCE_PID is required}"
readonly attempts="${XFCE_SAVE_ON_EXIT_ATTEMPTS:-100}"
readonly retry_delay="${XFCE_SAVE_ON_EXIT_RETRY_DELAY_SECONDS:-0.1}"

if ! [[ "$attempts" =~ ^[1-9][0-9]*$ ]]; then
    printf 'invalid XFCE_SAVE_ON_EXIT_ATTEMPTS\n' >&2
    exit 1
fi

for ((attempt = 1; attempt <= attempts; attempt++)); do
    if ! kill -0 "$XFCE_PID" 2>/dev/null; then
        printf 'XFCE session exited before SaveOnExit verification\n' >&2
        exit 1
    fi

    set_ok=0
    if xfconf-query -c xfce4-session -p /general/SaveOnExit -s false >/dev/null 2>&1; then
        set_ok=1
    elif xfconf-query -c xfce4-session -p /general/SaveOnExit -n -t bool -s false >/dev/null 2>&1; then
        set_ok=1
    fi

    if (( set_ok == 1 )); then
        if value="$(xfconf-query -c xfce4-session -p /general/SaveOnExit 2>/dev/null)"; then
            if [[ "$value" == "false" ]]; then
                if ! kill -0 "$XFCE_PID" 2>/dev/null; then
                    printf 'XFCE session exited during SaveOnExit verification\n' >&2
                    exit 1
                fi
                exit 0
            fi
        fi
    fi

    if (( attempt < attempts )); then
        sleep "$retry_delay"
    fi
done

printf 'failed to set and verify XFCE SaveOnExit=false within retry bound\n' >&2
exit 1

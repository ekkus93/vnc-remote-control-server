#!/bin/sh
set -eu

mode="${1:-live}"
case "$mode" in
    live|ready)
        ;;
    *)
        printf 'usage: controller-healthcheck [live|ready]\n' >&2
        exit 64
        ;;
esac

port="${VRC_HEALTHCHECK_PORT:-8080}"
case "$port" in
    ''|*[!0-9]*)
        printf 'VRC_HEALTHCHECK_PORT must be numeric\n' >&2
        exit 64
        ;;
esac

exec curl \
    --fail \
    --silent \
    --show-error \
    --max-time 2 \
    "http://127.0.0.1:${port}/health/${mode}" \
    >/dev/null

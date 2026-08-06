# VNC Remote Control Server Operator Guide

This guide covers the supported v0.1 deployment: one controller container managing one project-owned Debian XFCE desktop container through TigerVNC on a private Docker network.

## 1. Product and trust boundary

The controller is a remote-desktop primitive, not a general-purpose automation platform. It provides current framebuffer observation and explicit pointer, keyboard, text, clipboard, and reconnect operations. It does not provide OCR, DOM or accessibility-tree access, Playwright, AI planning, arbitrary external VNC targets, multiple concurrent desktops, or end-user authorization.

Treat every API client as fully trusted to observe and control the desktop. The v0.1 bearer token is process-wide; it does not provide per-user roles or per-operation authorization.

## 2. Architecture

```mermaid
flowchart TB
    APIClient[Trusted client] -->|TLS required outside localhost| ReverseProxy[Trusted reverse proxy]
    ReverseProxy -->|HTTP and WebSocket| Controller[controller-api, UID 10002]
    Controller -->|RFB on desktop_control| Desktop[XtigerVNC + XFCE, UID 10001]
    Controller -->|read only| ApiSecret[/run/secrets/api_token]
    Controller -->|read only| VncSecret[/run/secrets/vnc_password]
    Desktop -->|read only| VncSecret
    Desktop -. opt-in .-> HomeVolume[(desktop-home volume)]
```

The `desktop_control` network is `internal: true`. The desktop service does not publish port `5901` in production. The controller joins both `desktop_control` and `api_ingress`, and the host API binding defaults to `127.0.0.1:8080`.

## 3. Prerequisites

### Runtime host

- Linux host supported by Docker Engine;
- Docker Engine with Docker Compose v2;
- enough memory for two Debian-based containers and a 1280×800 RGBA framebuffer;
- a free loopback TCP port, default `8080`;
- `openssl` for secret generation;
- `curl` for the examples below;
- optional `websocat` for interactive WebSocket inspection.

### Development host

In addition to the runtime requirements:

- Rust 1.97.1 through `rustup`;
- GNU Make;
- C compiler and `pkg-config`;
- Debian/Ubuntu package `libvncserver-dev` for LibVNCClient headers and libraries;
- Python 3.12 for first-party contract and integration tests.

## 4. Generate and protect secrets

Create the default Compose secret sources:

```bash
install -d -m 0700 deploy/secrets
umask 077
openssl rand -hex 32 > deploy/secrets/api_token.txt
openssl rand -hex 4 > deploy/secrets/vnc_password.txt
chmod 0444 deploy/secrets/api_token.txt deploy/secrets/vnc_password.txt
```

Why the permissions differ:

- `deploy/secrets` is `0700`, so other host users cannot traverse it;
- source files are `0444` because local Docker Compose bind-mounts file-backed secrets read-only while preserving host ownership, and both services run as non-root UIDs;
- the files remain protected by the private parent directory.

Do not put either secret value in an environment variable. The supported environment variables select secret file paths:

- `VRC_API_TOKEN_SOURCE` for the Compose source file;
- `VRC_VNC_PASSWORD_SOURCE` for the Compose source file;
- `VRC_API_TOKEN_FILE` and `VRC_VNC_PASSWORD_FILE` inside the controller process.

The desktop converts the plaintext VNC source secret into `/tmp/vnc-runtime/passwd` at startup. That generated file is mode `0600`, is deleted at shutdown, and is never stored in the persistent home volume.

## 5. Build and start

### Disposable production mode

```bash
docker compose -f deploy/compose.yaml up --build --detach --wait
```

The desktop home is part of the container writable layer. Recreating or removing the desktop container discards user-created desktop files and settings.

Check service state:

```bash
docker compose -f deploy/compose.yaml ps
docker compose -f deploy/compose.yaml logs --no-color controller desktop
```

Stop and remove the stack:

```bash
docker compose -f deploy/compose.yaml down --volumes --remove-orphans
```

### Persistent desktop-home mode

```bash
docker compose \
  -f deploy/compose.yaml \
  -f deploy/compose.persistence.yaml \
  up --build --detach --wait
```

The named volume preserves `/home/desktop`. It does not preserve:

- `/tmp`;
- the generated TigerVNC password file;
- controller process state;
- API or VNC source secret files;
- framebuffer, clipboard, command queue, or WebSocket state.

Stop without deleting the home volume:

```bash
docker compose \
  -f deploy/compose.yaml \
  -f deploy/compose.persistence.yaml \
  down --remove-orphans
```

Delete the persistent home deliberately:

```bash
docker compose \
  -f deploy/compose.yaml \
  -f deploy/compose.persistence.yaml \
  down --volumes --remove-orphans
```

### Development-only raw VNC

```bash
docker compose \
  -f deploy/compose.yaml \
  -f deploy/compose.debug-vnc.yaml \
  up --build --detach --wait
```

The override binds `127.0.0.1:5901`. It also gives the desktop temporary access to the non-internal ingress network because Docker cannot publish a port from a service attached only to an internal network.

Never use this override on a production host. Never change the binding to `0.0.0.0` or a public interface.

## 6. API binding and TLS

The default host binding is:

```text
127.0.0.1:8080
```

Change only the host port with:

```bash
VRC_API_HOST_PORT=18080 docker compose -f deploy/compose.yaml up --detach --wait
```

`VRC_API_BIND_ADDRESS` controls the host interface. Keep it at `127.0.0.1` unless a documented network boundary requires otherwise.

The controller does not terminate TLS. Before exposing the API beyond localhost, place it behind a trusted reverse proxy that:

- terminates TLS with a valid certificate;
- supports WebSocket upgrade for `/v1/events`;
- preserves the `Authorization` header without logging its value;
- forwards `X-Request-ID` or permits the controller to generate one;
- enforces request and idle timeouts compatible with controller limits;
- does not expose the raw desktop VNC port;
- restricts network access to trusted clients.

Do not place bearer tokens in query strings. URLs are commonly logged by proxies and clients.

## 7. Health and readiness

Public endpoints:

```bash
BASE_URL=http://127.0.0.1:8080
curl --fail-with-body "$BASE_URL/health/live"
curl --fail-with-body "$BASE_URL/health/ready"
```

- `/health/live` returns `200` when the HTTP process is alive.
- `/health/ready` returns `200` only when the worker is connected and a complete current framebuffer exists.
- readiness returns `503 not_ready` during startup, reconnect, framebuffer invalidation, fatal worker failure, or shutdown.

Do not route control traffic solely because liveness passes. Use readiness.

## 8. Authentication setup for examples

```bash
BASE_URL=http://127.0.0.1:8080
API_TOKEN="$(cat deploy/secrets/api_token.txt)"
AUTH_HEADER="Authorization: Bearer $API_TOKEN"
```

Every `/v1/*` HTTP route and the WebSocket handshake require the bearer token. Missing and incorrect tokens intentionally receive the same `401 unauthorized` response.

Every routed response includes `X-Request-ID`. Clients may provide an ID containing only ASCII letters, digits, `.`, `_`, and `-`, up to 64 bytes. Invalid IDs are replaced. Requests rejected by the lower-level HTTP runtime before routing can return an empty `400`, `408`, or `413` response without the JSON envelope or request ID.

## 9. Authenticated HTTP examples

### Status and display

```bash
curl --fail-with-body --header "$AUTH_HEADER" "$BASE_URL/v1/status"
curl --fail-with-body --header "$AUTH_HEADER" "$BASE_URL/v1/display"
```

`/v1/display` is unavailable until a current complete frame exists.

### Screenshot and conditional request

```bash
curl --fail-with-body \
  --header "$AUTH_HEADER" \
  --dump-header /tmp/vrc-screenshot.headers \
  --output /tmp/vrc-screenshot.png \
  "$BASE_URL/v1/screenshot.png"

ETAG="$(awk 'tolower($1)=="etag:" {gsub("\\r", "", $2); print $2}' /tmp/vrc-screenshot.headers)"

curl --silent --show-error \
  --header "$AUTH_HEADER" \
  --header "If-None-Match: $ETAG" \
  --output /dev/null \
  --write-out '%{http_code}\n' \
  "$BASE_URL/v1/screenshot.png"
```

The second request should return `304`. ETags include a process-instance component and framebuffer revision. A reconnect invalidates the old frame, and a new complete frame receives a new ETag.

### Pointer movement and click

```bash
curl --fail-with-body \
  --request POST \
  --header "$AUTH_HEADER" \
  --header 'Content-Type: application/json' \
  --data '{"x":640,"y":400}' \
  "$BASE_URL/v1/pointer/move"

curl --fail-with-body \
  --request POST \
  --header "$AUTH_HEADER" \
  --header 'Content-Type: application/json' \
  --data '{"x":640,"y":400,"button":"left"}' \
  "$BASE_URL/v1/pointer/click"
```

Coordinates are zero-based and must be inside the current display. They are never silently clamped.

### Keyboard key, chord, and text

```bash
curl --fail-with-body \
  --request POST \
  --header "$AUTH_HEADER" \
  --header 'Content-Type: application/json' \
  --data '{"key":"ENTER","action":"down"}' \
  "$BASE_URL/v1/keyboard/key"

curl --fail-with-body \
  --request POST \
  --header "$AUTH_HEADER" \
  --header 'Content-Type: application/json' \
  --data '{"key":"ENTER","action":"up"}' \
  "$BASE_URL/v1/keyboard/key"

curl --fail-with-body \
  --request POST \
  --header "$AUTH_HEADER" \
  --header 'Content-Type: application/json' \
  --data '{"keys":["CTRL_LEFT","a"]}' \
  "$BASE_URL/v1/keyboard/chord"

curl --fail-with-body \
  --request POST \
  --header "$AUTH_HEADER" \
  --header 'Content-Type: application/json' \
  --data '{"text":"documented ASCII text"}' \
  "$BASE_URL/v1/keyboard/text"
```

Text input supports horizontal tab, carriage return, line feed, and printable ASCII `U+0020` through `U+007E`. Other Unicode is rejected before any partial input is sent. Chord keys use documented symbolic names or one printable ASCII character. Raw numeric keysyms are not accepted.

### Clipboard

```bash
curl --fail-with-body \
  --request PUT \
  --header "$AUTH_HEADER" \
  --header 'Content-Type: application/json' \
  --data '{"text":"documented clipboard value"}' \
  "$BASE_URL/v1/clipboard"

curl --fail-with-body --header "$AUTH_HEADER" "$BASE_URL/v1/clipboard"
```

The API accepts UTF-8 clipboard strings up to 1 MiB and rejects embedded NUL bytes. RFB clipboard transport is a byte-oriented legacy channel; inbound bytes must form valid UTF-8 or the adapter rejects the update. Applications and desktop toolkits may normalize line endings or provide clipboard updates only after an explicit copy operation.

### Manual reconnect

```bash
curl --fail-with-body \
  --request POST \
  --header "$AUTH_HEADER" \
  "$BASE_URL/v1/connection/reconnect"
```

Manual reconnect is rate-limited. Automatic reconnect remains active for transport loss.

### Metrics

```bash
curl --fail-with-body --header "$AUTH_HEADER" "$BASE_URL/v1/metrics"
```

Metrics use bounded labels and exclude request payloads and secret values. Every exported series includes Prometheus `# HELP` and `# TYPE` metadata.

`vrc_worker_command_submissions_in_flight` is a gauge of command submissions that have acquired an accounting permit but have not yet released it. Permit acquisition occurs before bounded-queue admission, so this value can transiently exceed `VRC_COMMAND_CAPACITY`; it is not queue depth. The earlier `vrc_worker_command_queue_depth` name was removed without an alias in v0.1 because no repository-local dashboard, alert, API response, or R13 contract consumed it.

## 10. Asynchronous command semantics

Input, clipboard-set, and reconnect endpoints return `202 Accepted` only after the command has been admitted to the bounded worker queue and its bounded worker acknowledgement succeeds. The response contains a process-local `command_id` and `status: "accepted"`.

`202` does not promise that a target desktop application interpreted the input semantically. It proves that the controller validated and executed the RFB operation without a reported worker failure.

Queue saturation, shutdown, timeouts, and transport failures remain visible as non-2xx responses. Commands are not silently dropped.

## 11. WebSocket events

With `websocat` installed:

```bash
websocat \
  -H="Authorization: Bearer $API_TOKEN" \
  "ws://127.0.0.1:8080/v1/events"
```

The first text frame is a `snapshot`. Later payload-free events report connection-state transitions, framebuffer revisions or invalidation, clipboard revisions, overload, and protocol errors. The server sends WebSocket ping frames; clients must remain responsive. Slow or idle clients are disconnected within configured bounds.

See [`WEBSOCKET_EVENTS.md`](WEBSOCKET_EVENTS.md) for the exact event envelope and close behavior.

## 12. Shutdown behavior

Compose services use a 15-second stop grace period. `VRC_SHUTDOWN_GRACE_MS` bounds HTTP server draining, while `VRC_SHUTDOWN_TIMEOUT_MS` is one total process-cleanup budget shared by the worker and event bridge. The controller establishes one deadline, spends the remaining budget on worker shutdown, then passes only the remainder to bridge cleanup. Server error precedence remains server, worker, then bridge.

The controller handles SIGTERM by:

1. making readiness fail closed;
2. rejecting new commands;
3. stopping HTTP acceptance;
4. releasing tracked keys and buttons where possible;
5. closing the VNC connection;
6. joining the native worker and event bridge within the one total cleanup budget;
7. observing an already-completed bridge exit even when no budget remains, or deliberately detaching a still-active bridge with a payload-free diagnostic;
8. exiting before the Compose stop grace period expires under the documented defaults.

The default process-cleanup budget is 5000 ms. Configuration below `max(500 ms, 8 × 50 ms)` is rejected; with the current event-bridge poll interval, the derived minimum is 500 ms. Direct bridge wake-up is deliberately deferred: the current dependency-free stop flag and bounded poll remain authoritative.

Use:

```bash
docker compose -f deploy/compose.yaml down --remove-orphans
```

Do not use `docker kill --signal KILL` during ordinary operation; it bypasses graceful release and cleanup.

## 13. Recovery behavior

For a transport interruption or desktop restart:

- readiness becomes false;
- the prior framebuffer becomes unavailable rather than being served as current;
- tracked key and button state is cleared;
- reconnect uses bounded exponential backoff with jitter;
- a full framebuffer is requested after reconnect;
- readiness returns only after a complete new frame arrives.

Authentication failure is visible as `authentication_failed` and does not retry rapidly. Correct the VNC source secret, recreate the affected services, and verify readiness.

A manual reconnect request is available, but it is rate-limited and should not be used as a polling loop.

## 14. Resource limits and tuning

Compose applies:

- controller PID limit: `256`;
- desktop PID limit: `512`;
- controller read-only root filesystem;
- controller `/tmp` tmpfs: `64 MiB`, `nosuid`, `nodev`, `noexec`;
- all Linux capabilities dropped;
- `no-new-privileges` on both services.

Important controller defaults:

| Setting | Environment variable | Default | Bound or rule |
|---|---|---:|---|
| JSON request body | `VRC_MAX_JSON_BYTES` | 1 MiB | maximum 2 MiB |
| HTTP header read | `VRC_HTTP_HEADER_TIMEOUT_MS` | 5000 ms | maximum 300000 ms |
| HTTP body read | `VRC_HTTP_BODY_TIMEOUT_MS` | 5000 ms | maximum 300000 ms |
| HTTP shutdown drain | `VRC_SHUTDOWN_GRACE_MS` | 10000 ms | maximum 300000 ms |
| Complete worker startup | `VRC_STARTUP_TIMEOUT_MS` | 10000 ms | one total acknowledgement-and-cleanup budget |
| Process cleanup | `VRC_SHUTDOWN_TIMEOUT_MS` | 5000 ms | minimum `max(500 ms, 8 × event-bridge poll interval)` |
| Worker command queue | `VRC_COMMAND_CAPACITY` | 64 | bounded, nonzero |
| Worker event queue | `VRC_EVENT_CAPACITY` | 256 | bounded, nonzero |
| Command acknowledgement | `VRC_COMMAND_ACK_TIMEOUT_MS` | 5000 ms | nonzero |
| Concurrent PNG encodes | `VRC_SCREENSHOT_MAX_CONCURRENT` | 2 | maximum 64 |
| PNG encode timeout | `VRC_SCREENSHOT_TIMEOUT_MS` | 5000 ms | nonzero |
| WebSocket event buffer | `VRC_WEBSOCKET_EVENT_CAPACITY` | 256 | per client, bounded |
| WebSocket clients | `VRC_WEBSOCKET_MAX_CLIENTS` | 16 | bounded |
| WebSocket ping | `VRC_WEBSOCKET_PING_INTERVAL_MS` | 15000 ms | nonzero |
| WebSocket idle timeout | `VRC_WEBSOCKET_IDLE_TIMEOUT_MS` | 45000 ms | greater than ping interval |
| Maximum framebuffer | `VRC_MAX_FRAMEBUFFER_BYTES` | 64 MiB | cannot exceed 64 MiB |
| Reconnect minimum | `VRC_RECONNECT_MIN_MS` | 250 ms | no greater than maximum |
| Reconnect maximum | `VRC_RECONNECT_MAX_MS` | 30000 ms | bounded duration |
| Manual reconnect interval | `VRC_MANUAL_RECONNECT_INTERVAL_MS` | 2000 ms | nonzero |
| Stall probe | `VRC_STALL_PROBE_AFTER_MS` | 30000 ms | nonzero |
| Stall confirmation | `VRC_STALL_CONFIRM_AFTER_MS` | 10000 ms | nonzero |

Tune one limit at a time and rerun the real integration suite. Increasing queue or WebSocket capacities increases worst-case memory use. Increasing timeouts can increase shutdown and client-visible latency. Invalid settings fail startup closed. `VRC_STARTUP_TIMEOUT_MS` bounds the complete startup operation: acknowledgement wait, shutdown-flag publication, the permit-counted compatibility nudge, exit observation, and cleanup all consume the same deadline rather than separate full timeout windows.

## 15. Troubleshooting

### Desktop does not start

Inspect:

```bash
docker compose -f deploy/compose.yaml ps
docker compose -f deploy/compose.yaml logs --no-color desktop
```

Check:

- `deploy/secrets/vnc_password.txt` exists, is nonempty, and is reachable through the `0700` parent directory;
- the source file is readable by the Compose mount setup;
- no stale container from another Compose project owns required resources;
- the image build completed;
- the deterministic desktop state file was created before the health deadline.

The desktop entrypoint fails closed if Xtigervnc, XFCE, or the deterministic test application exits.

### VNC authentication fails

Symptoms include controller state `authentication_failed` and readiness `503`.

Check that both services mount the same VNC secret source:

```bash
docker compose -f deploy/compose.yaml config
```

Do not print the secret value. Correct `VRC_VNC_PASSWORD_SOURCE` or the default file, then recreate both services:

```bash
docker compose -f deploy/compose.yaml up --detach --force-recreate desktop controller
```

Authentication failures are intentionally backoff-safe and do not become a rapid retry loop.

### Controller cannot connect

Inspect controller logs and rendered Compose topology:

```bash
docker compose -f deploy/compose.yaml logs --no-color controller
docker compose -f deploy/compose.yaml config
```

Check:

- desktop is healthy;
- controller and desktop both join `desktop_control`;
- `VRC_VNC_HOST` remains `desktop` and `VRC_VNC_PORT` remains `5901` in the standard topology;
- API and VNC secret mounts are readable;
- custom timeout values are valid and nonzero.

Do not publish raw VNC as a workaround. Repair the private-network or secret configuration.

### Liveness passes but readiness does not

Query status with authentication:

```bash
curl --fail-with-body --header "$AUTH_HEADER" "$BASE_URL/v1/status"
```

Interpret the state:

- `starting` or `connecting`: initial connection is still active;
- `authentication_failed`: VNC credentials do not match;
- `degraded`, `disconnected`, or `reconnecting`: transport recovery is active;
- `connected` with no framebuffer revision: a complete frame has not arrived;
- `fatal_exit: true`: the worker exited unexpectedly and the service must be recreated.

Readiness remains false until a complete current framebuffer exists. Do not weaken the readiness probe to liveness.

### Screenshot is unavailable or busy

- `framebuffer_unavailable`: wait for readiness or investigate reconnect state;
- `screenshot_busy`: concurrent encode capacity is exhausted; reduce client concurrency or deliberately raise the bounded limit;
- `screenshot_timeout`: encoding exceeded its configured deadline.

Do not serve a cached pre-disconnect screenshot as current.

### Commands return `503` or `504`

- `command_queue_full`: clients are producing commands faster than the single worker can execute them;
- `worker_unavailable`: shutdown or worker failure is active;
- `command_timeout`: the bounded acknowledgement deadline elapsed;
- `desktop_operation_failed`: the native VNC operation failed.

Back off at the client. Do not retry tight loops, and do not hide these failures as successful input.

## 16. Validation commands

Repository quality:

```bash
make fmt
make lint
make test
make build
```

Real Compose integration:

```bash
make integration-test
```

Documentation contracts:

```bash
python3 -m unittest tests.test_documentation_contract -v
```

The complete authoritative CI workflow runs the full quality, native, desktop, API, Compose, and integration surface.

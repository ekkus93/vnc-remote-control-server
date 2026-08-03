# VNC Remote Control Server v0.1 Specification

**Status:** Initial implementation specification  
**Target repository:** `ekkus93/vnc-remote-control-server`  
**Target release:** v0.1  
**Last updated:** 2026-08-03

## 1. Purpose

VNC Remote Control Server is a containerized service that exposes a controlled HTTP and WebSocket API for observing and operating a Linux graphical desktop.

The system runs a Debian desktop behind a private TigerVNC server. A Rust controller connects to that server with LibVNCClient, keeps a local copy of the framebuffer, and translates authenticated API requests into VNC pointer, keyboard, scrolling, and clipboard operations.

The v0.1 product boundary is deliberately narrow:

> Observe pixels, send input, report connection state, and recover safely from failures.

The project is not yet an autonomous desktop agent. OCR, computer vision, accessibility-tree inspection, Playwright, semantic element selection, and AI task planning are separate future layers that can consume this API.

## 2. Goals

v0.1 must provide:

1. A reproducible Debian graphical desktop running in Docker.
2. A TigerVNC `Xvnc` server reachable only on a private Docker network.
3. A Rust API server using Axum and Tokio.
4. A narrowly scoped safe Rust adapter around LibVNCClient.
5. A persistent VNC connection owned by a dedicated worker thread.
6. Coherent PNG screenshots of the latest decoded framebuffer.
7. Pointer movement, mouse buttons, clicks, double-clicks, and scrolling.
8. Key down/up, key chords, and bounded text entry.
9. Clipboard send and last-known clipboard receive support.
10. Connection health, reconnection, bounded queues, explicit errors, and structured logs.
11. Bearer-token authentication for every control or observation endpoint except liveness.
12. Unit, integration, and real-container end-to-end tests.

## 3. Non-goals for v0.1

The following are explicitly out of scope:

- Multiple simultaneous desktop sessions.
- Multi-user accounts, OAuth, RBAC, or tenant isolation.
- Public exposure of the raw VNC port.
- Browser-based VNC viewing.
- Video streaming or RFB proxying through the API.
- OCR, template matching, image recognition, or multimodal models.
- AT-SPI accessibility-tree automation.
- Playwright or browser-specific automation.
- AI planning or natural-language task execution.
- Dynamic screen resizing.
- Container creation and deletion through the public API.
- Cross-platform desktop targets other than the provided Debian environment.
- General connection to untrusted third-party VNC servers.

## 4. Locked v0.1 decisions

| Area | Decision |
|---|---|
| Session model | Exactly one configured desktop session |
| Container model | Separate `desktop` and `controller` containers |
| Desktop OS | Current supported Debian stable image, pinned by digest for releases |
| Desktop environment | XFCE |
| VNC server | TigerVNC `Xvnc` |
| Default display | `:1` / TCP `5901` |
| Default resolution | `1280x800`, 24-bit color |
| API language | Rust |
| API framework | Axum on Tokio |
| VNC client | LibVNCClient behind an internal Rust adapter |
| FFI ownership | One dedicated native worker thread owns the `rfbClient*` |
| API transport | HTTP/JSON plus WebSocket event notifications |
| Screenshot format | PNG |
| Authentication | Static bearer token supplied as a secret |
| VNC authentication | Password supplied as a separate secret |
| Production VNC exposure | Private Docker network only |
| Persistence | Disposable by default; optional persistent home volume |
| Live display | Screenshot polling driven by WebSocket revision events |

Exact dependency versions are selected during implementation and pinned in lockfiles and container manifests. The implementation must not rely on an abandoned Rust wrapper without first validating its required client-side coverage. A small project-owned wrapper around low-level bindings is the preferred production design.

## 5. System architecture

```text
API client or automation layer
        |
        | HTTP/JSON and WebSocket
        v
Rust controller container
  Axum + Tokio
  authentication middleware
  validation and rate limits
  screenshot encoder
  VNC command facade
        |
        | bounded command channel
        v
Dedicated VNC worker thread
  owns LibVNCClient state
  reads RFB server messages
  sends pointer/key/clipboard events
  updates local framebuffer
        |
        | RFB/VNC over private TCP
        v
Debian desktop container
  TigerVNC Xvnc display :1
  XFCE session
  terminal and deterministic test application
  optional Chromium installation
```

A conventional VNC viewer may be enabled only through a local-development Compose profile that binds the server to `127.0.0.1`. It is not part of the production data path.

## 6. Repository layout

The intended top-level layout is:

```text
.
├── Cargo.toml
├── Cargo.lock
├── crates/
│   ├── controller-api/
│   │   └── src/
│   ├── remote-desktop-core/
│   │   └── src/
│   └── libvnc-adapter/
│       ├── build.rs
│       ├── src/
│       └── wrapper.h
├── desktop/
│   ├── Dockerfile
│   ├── entrypoint.sh
│   ├── xstartup
│   └── test-app/
├── deploy/
│   ├── compose.yaml
│   ├── compose.debug-vnc.yaml
│   └── example.env
├── docs/
│   ├── VNC_REMOTE_CONTROL_SERVER_V01_SPEC.md
│   └── VNC_REMOTE_CONTROL_SERVER_V01_TODO.md
├── tests/
│   └── e2e/
└── .github/workflows/
    └── ci.yml
```

A single crate is acceptable during the earliest spike, but the final v0.1 structure must keep raw FFI code isolated from HTTP and business logic.

## 7. Desktop container specification

### 7.1 Required packages

The desktop image must contain, at minimum:

- TigerVNC standalone server and common utilities.
- XFCE and a minimal session configuration.
- D-Bus support required by the desktop session.
- A terminal emulator.
- Basic fonts and X11 keyboard data.
- A deterministic graphical test application.
- Utilities needed for health checks and clean shutdown.

Chromium may be included for realistic manual testing, but browser automation is outside v0.1 acceptance criteria.

### 7.2 User and permissions

- Desktop applications must run as a dedicated non-root user.
- The VNC password file must be created at startup from a mounted secret or secret-file path.
- The password must never be embedded in an image layer, Compose file, log, or process argument visible to unrelated users.
- The container must use an explicit writable home directory.
- Persistent mode mounts that home directory as a named volume.
- Disposable mode uses the container filesystem and loses state when recreated.

### 7.3 Startup contract

The desktop entrypoint must:

1. Validate required configuration and secret files.
2. Create the VNC password file with restrictive permissions.
3. Remove stale VNC PID, lock, and Unix socket files only after validating that no live server owns them.
4. Start `Xvnc` on display `:1` with the configured geometry and depth.
5. Start the XFCE session through the VNC startup script.
6. Report readiness only after the VNC TCP listener is accepting connections and the desktop session has started.
7. Forward termination signals and stop child processes cleanly.

The entrypoint must fail closed. It must not start an unauthenticated VNC server because a password was missing or malformed.

### 7.4 Networking

Production Compose must use an internal Docker network:

```text
controller -> desktop:5901
```

Production must not publish `5901` to a host interface.

A development-only override may publish:

```text
127.0.0.1:5901 -> desktop:5901
```

Binding raw VNC to `0.0.0.0` is prohibited by the deployment contract.

## 8. Rust controller architecture

### 8.1 Crate responsibilities

#### `remote-desktop-core`

Contains dependency-light domain types and validation:

- Coordinates and display dimensions.
- Mouse buttons and pointer masks.
- Keyboard keys and key chords.
- Clipboard values and revisions.
- Connection states and errors.
- Framebuffer metadata and snapshots.
- Worker commands and events.

It must not depend on Axum or raw LibVNCClient bindings.

#### `libvnc-adapter`

Contains all unsafe and C interop code:

- Binding generation or reviewed low-level bindings.
- `rfbClient*` allocation, initialization, and cleanup.
- Authentication callbacks.
- Framebuffer allocation and pixel-format setup.
- Framebuffer update callbacks.
- Server clipboard callbacks.
- Pointer, keyboard, and clipboard sends.
- Message waiting and handling.
- Connection teardown and reconnect support.

No raw pointer may escape this crate's private implementation boundary.

#### `controller-api`

Contains:

- Configuration loading and validation.
- Axum routes and middleware.
- Authentication.
- Request validation and error mapping.
- VNC worker lifecycle management.
- Screenshot encoding.
- WebSocket event broadcasting.
- Health, readiness, logging, and metrics.

### 8.2 Safe abstraction

The API layer must interact with a safe facade resembling:

```rust
pub trait RemoteDesktop: Send + Sync {
    fn status(&self) -> DesktopStatus;
    fn display_info(&self) -> Result<DisplayInfo, DesktopError>;
    fn framebuffer_snapshot(&self) -> Result<FramebufferSnapshot, DesktopError>;
    fn move_pointer(&self, x: u32, y: u32) -> Result<(), DesktopError>;
    fn set_button(&self, button: MouseButton, pressed: bool) -> Result<(), DesktopError>;
    fn set_key(&self, key: KeyboardKey, pressed: bool) -> Result<(), DesktopError>;
    fn type_text(&self, text: &str) -> Result<TextInputResult, DesktopError>;
    fn set_clipboard(&self, text: &str) -> Result<(), DesktopError>;
    fn reconnect(&self) -> Result<(), DesktopError>;
}
```

Operations may internally return acknowledgements asynchronously, but public handlers must have bounded completion deadlines.

## 9. VNC worker model

### 9.1 Ownership

One dedicated native thread exclusively owns the LibVNCClient connection and raw client pointer. Tokio tasks and Axum handlers must never invoke LibVNCClient concurrently.

### 9.2 Commands

The bounded worker command channel must support at least:

```rust
enum VncCommand {
    MovePointer { x: u32, y: u32 },
    SetButton { button: MouseButton, pressed: bool },
    Click { x: u32, y: u32, button: MouseButton },
    DoubleClick { x: u32, y: u32, button: MouseButton, interval_ms: u64 },
    Scroll { x: u32, y: u32, delta_x: i32, delta_y: i32 },
    SetKey { key: KeyboardKey, pressed: bool },
    Chord { keys: Vec<KeyboardKey> },
    TypeText { text: String },
    SetClipboard { text: String },
    RequestFullRefresh,
    Reconnect,
    Shutdown,
}
```

The channel must be bounded. Queue saturation must return an explicit overload error rather than blocking indefinitely or dropping commands silently.

### 9.3 Worker loop

The loop must repeatedly:

1. Process queued commands within a bounded budget.
2. Wait for VNC socket activity with a bounded timeout.
3. Call the appropriate LibVNCClient message handler.
4. Apply framebuffer updates under a consistency mechanism.
5. Publish state and revision events.
6. Detect transport closure, protocol errors, and stalls.
7. Transition to reconnecting or terminal failure according to policy.

### 9.4 Connection state machine

```text
STARTING
   |
   v
CONNECTING ---> AUTH_FAILED
   |                 |
   v                 v
CONNECTED       WAITING_FOR_RETRY
   |                 ^
   v                 |
DEGRADED ------------+
   |
   v
DISCONNECTED -> RECONNECTING -> CONNECTED
   |
   v
SHUTTING_DOWN -> STOPPED
```

Required externally visible states:

- `starting`
- `connecting`
- `connected`
- `degraded`
- `reconnecting`
- `disconnected`
- `authentication_failed`
- `stopped`

Authentication failure must not retry in a tight loop. Configuration errors must remain distinguishable from transient network failures.

### 9.5 Reconnect policy

- Exponential backoff with jitter.
- Configurable minimum and maximum delay.
- A stable successful connection resets the backoff.
- Manual reconnect bypasses the current wait once but remains rate-limited.
- After reconnect, request a full non-incremental framebuffer update.
- Clear local pressed-key and pressed-button bookkeeping.
- Mark the previous framebuffer stale until a complete refresh has been received.
- Publish state changes through WebSocket events.

## 10. Framebuffer model

### 10.1 Canonical format

The controller must expose a canonical in-memory RGBA8 framebuffer independent of the server's native pixel layout.

```rust
pub struct FramebufferState {
    pub width: u32,
    pub height: u32,
    pub rgba: Vec<u8>,
    pub revision: u64,
    pub complete: bool,
    pub updated_at: SystemTime,
}
```

The implementation must use checked arithmetic when calculating stride, pixel count, rectangle offsets, or allocation sizes.

### 10.2 Update consistency

- Dirty rectangles must be bounds checked before copying.
- Malformed or out-of-range updates must terminate or reset the connection; they must never write outside the allocation.
- A screenshot must represent one coherent framebuffer revision.
- PNG encoding must operate on an immutable snapshot, not a buffer being changed by callbacks.
- Snapshot creation may copy the RGBA buffer in v0.1. Optimization is deferred until measured.
- The first screenshot after startup or reconnect is unavailable until a complete framebuffer has been received.

### 10.3 Revision events

Every committed framebuffer update increments a monotonically increasing process-local revision. WebSocket clients receive revision notifications and may fetch a new PNG.

Revisions are not durable across controller restarts.

## 11. Input semantics

### 11.1 Coordinates

- `(0, 0)` is the upper-left framebuffer pixel.
- Valid coordinates satisfy `x < width` and `y < height`.
- Out-of-range coordinates return `400 invalid_coordinate`.
- Coordinates are never silently clamped.
- Pointer actions are rejected while the framebuffer dimensions are unknown.

### 11.2 Mouse buttons

Supported buttons:

- `left`
- `middle`
- `right`

The adapter must keep a local button mask so simultaneous button state is represented correctly.

A click is an atomic worker command that sends button-down and button-up at the same coordinate. If the down event succeeds and the up event cannot be sent because the connection fails, the failure must be recorded and button state cleared during reconnect.

### 11.3 Double-click

- Implemented as two complete clicks.
- Default interval is configurable and bounded.
- Caller-provided intervals outside configured limits are rejected.
- The worker owns timing so interleaving commands cannot split the double-click sequence.

### 11.4 Scrolling

RFB wheel events are represented with conventional VNC pointer button masks. The API accepts signed deltas and converts them into bounded wheel steps.

- Positive `delta_y`: scroll up.
- Negative `delta_y`: scroll down.
- Positive `delta_x`: scroll right.
- Negative `delta_x`: scroll left.
- Per-request step counts are capped.

The exact horizontal wheel mapping must be verified against the selected TigerVNC version during the FFI spike and covered by integration tests.

### 11.5 Keyboard events

The API supports:

- Explicit key down.
- Explicit key up.
- Chords.
- Text entry.

Chords must press keys in request order and release them in reverse order. A failure must trigger best-effort release of all keys pressed by that command.

The service must maintain local pressed-key bookkeeping. Disconnect and shutdown clear that bookkeeping.

### 11.6 Key representation

The public API uses stable symbolic names for control and navigation keys, for example:

- `CTRL_LEFT`
- `ALT_LEFT`
- `SHIFT_LEFT`
- `META_LEFT`
- `ENTER`
- `TAB`
- `ESCAPE`
- `BACKSPACE`
- `DELETE`
- `HOME`
- `END`
- `PAGE_UP`
- `PAGE_DOWN`
- `ARROW_UP`, `ARROW_DOWN`, `ARROW_LEFT`, `ARROW_RIGHT`
- `F1` through `F12`

Printable text should use `/keyboard/text`, not hard-coded keysyms supplied by clients. Raw numeric keysyms are not part of the public v0.1 API.

### 11.7 Text input and Unicode

VNC keyboard interoperability varies for non-ASCII text. v0.1 must not silently corrupt or omit characters.

Required behavior:

1. UTF-8 input is validated.
2. ASCII characters required by the initial mapping are supported.
3. Additional Unicode characters may be supported only when verified against TigerVNC and represented through a documented Unicode keysym strategy.
4. Unsupported characters cause the entire request to fail before any character is sent unless the caller explicitly selects a future partial-input mode.
5. The response reports the number of Unicode scalar values accepted and sent.
6. Clipboard-based paste may be added as an explicit strategy, but must not be an undocumented fallback.

## 12. Clipboard semantics

### 12.1 Outbound clipboard

`PUT /v1/clipboard` sends bounded text to the VNC server using the supported clipboard mechanism.

- Input must be valid UTF-8 at the HTTP boundary.
- The maximum payload is configurable; default 1 MiB.
- Embedded NUL handling must be explicitly tested and either supported or rejected.
- Success means LibVNCClient accepted the send operation, not that an application pasted the value.

### 12.2 Inbound clipboard

The adapter records the most recent server clipboard callback:

```rust
pub struct ClipboardSnapshot {
    pub text: String,
    pub revision: u64,
    pub received_at: SystemTime,
}
```

`GET /v1/clipboard` returns the last-known server-provided value and timestamp. If no clipboard event has been received, it returns `404 clipboard_unavailable`, not an empty string pretending to be current state.

Legacy RFB clipboard encoding limitations must be documented after implementation testing. Unsupported or invalid incoming text must generate an observable protocol/decoding error; it must not be silently replaced.

## 13. HTTP API

All v1 responses use JSON except PNG screenshots and the WebSocket endpoint.

### 13.1 Liveness and readiness

#### `GET /health/live`

- No authentication required.
- Returns `200` when the API process event loop is alive.
- Does not imply VNC connectivity.

#### `GET /health/ready`

- Authentication may be omitted only when restricted to an internal health-check network.
- Returns `200` only when configuration is valid, the worker is running, the VNC connection is established, and a complete framebuffer has been received.
- Otherwise returns `503` with a machine-readable state.

### 13.2 Status

#### `GET /v1/status`

Returns:

```json
{
  "state": "connected",
  "connected_since": "2026-08-03T22:00:00Z",
  "last_server_message_at": "2026-08-03T22:00:02Z",
  "reconnect_attempt": 0,
  "framebuffer_complete": true,
  "framebuffer_revision": 42,
  "clipboard_revision": 3
}
```

Secrets, passwords, bearer tokens, and full connection URLs must never appear.

### 13.3 Display information

#### `GET /v1/display`

```json
{
  "width": 1280,
  "height": 800,
  "pixel_format": "rgba8",
  "revision": 42,
  "complete": true,
  "updated_at": "2026-08-03T22:00:02Z"
}
```

### 13.4 Screenshot

#### `GET /v1/screenshot.png`

- Returns `image/png`.
- Includes `ETag` derived from the process instance and framebuffer revision.
- Supports `If-None-Match` and may return `304`.
- Returns `503 framebuffer_unavailable` in JSON if no complete framebuffer exists.
- PNG encoding has a bounded execution deadline and concurrency limit.

### 13.5 Pointer endpoints

#### `POST /v1/pointer/move`

```json
{ "x": 640, "y": 400 }
```

#### `POST /v1/pointer/button`

```json
{
  "x": 640,
  "y": 400,
  "button": "left",
  "state": "down"
}
```

`state` is `down` or `up`.

#### `POST /v1/pointer/click`

```json
{ "x": 640, "y": 400, "button": "left" }
```

#### `POST /v1/pointer/double-click`

```json
{
  "x": 640,
  "y": 400,
  "button": "left",
  "interval_ms": 120
}
```

#### `POST /v1/pointer/scroll`

```json
{
  "x": 640,
  "y": 400,
  "delta_x": 0,
  "delta_y": -3
}
```

### 13.6 Keyboard endpoints

#### `POST /v1/keyboard/key`

```json
{ "key": "ENTER", "state": "down" }
```

#### `POST /v1/keyboard/chord`

```json
{ "keys": ["CTRL_LEFT", "ALT_LEFT", "T"] }
```

The initial implementation may limit chord length to eight keys.

#### `POST /v1/keyboard/text`

```json
{ "text": "hello world" }
```

Response:

```json
{
  "accepted_characters": 11,
  "strategy": "keysyms"
}
```

### 13.7 Clipboard endpoints

#### `GET /v1/clipboard`

Returns the last-known inbound clipboard snapshot.

#### `PUT /v1/clipboard`

```json
{ "text": "text to place on the desktop clipboard" }
```

### 13.8 Connection endpoint

#### `POST /v1/connection/reconnect`

Requests one rate-limited immediate reconnect attempt. It returns `202` when queued. It does not block until connection completion.

### 13.9 WebSocket events

#### `GET /v1/events`

Authenticated WebSocket endpoint. Event envelope:

```json
{
  "type": "framebuffer.updated",
  "sequence": 108,
  "occurred_at": "2026-08-03T22:00:02Z",
  "data": {
    "revision": 42,
    "width": 1280,
    "height": 800
  }
}
```

Required event types:

- `connection.state_changed`
- `framebuffer.updated`
- `framebuffer.invalidated`
- `clipboard.updated`
- `worker.overloaded`
- `worker.protocol_error`

WebSocket clients that cannot keep up must be disconnected with an explicit close reason. The server must not accumulate an unbounded per-client backlog.

## 14. API success and error model

Command endpoints return one of:

- `202 Accepted` when a command is validated and queued but not synchronously acknowledged.
- `200 OK` when the operation returns immediate data.
- `204 No Content` only where no response body is useful.

Error envelope:

```json
{
  "error": {
    "code": "invalid_coordinate",
    "message": "x must be less than the current display width",
    "request_id": "01J4...",
    "details": {
      "x": 1280,
      "width": 1280
    }
  }
}
```

Required error codes include:

- `unauthorized`
- `invalid_request`
- `invalid_coordinate`
- `unsupported_key`
- `unsupported_character`
- `payload_too_large`
- `not_connected`
- `framebuffer_unavailable`
- `clipboard_unavailable`
- `command_queue_full`
- `operation_timeout`
- `reconnect_rate_limited`
- `internal_error`

Internal C errors and secrets must not be exposed verbatim to API clients. Detailed causes belong in structured logs with redaction.

## 15. Authentication and security

### 15.1 API bearer token

- Loaded from a secret file by default; an environment variable may be supported for local development.
- Compared in constant-time where practical.
- Required for all `/v1/*` routes and WebSocket upgrades.
- Never accepted through query parameters.
- Never logged.
- Missing or invalid tokens return the same generic `401` response.

### 15.2 VNC credential

- Supplied independently from the API token.
- Read from a mounted secret file.
- Passed to LibVNCClient through its credential callback or another mechanism that avoids logging and unnecessary copies.
- Cleared from temporary mutable buffers where feasible.

### 15.3 Container hardening

Controller container:

- Runs as non-root.
- Uses a read-only root filesystem where practical.
- Drops all Linux capabilities.
- Uses `no-new-privileges`.
- Has explicit CPU, memory, PID, and file-descriptor limits.
- Mounts only required secret files and temporary storage.

Desktop container:

- Runs desktop processes as non-root.
- Drops unnecessary capabilities.
- Uses bounded CPU, memory, PID, and disk resources.
- Does not mount the Docker socket.
- Has no access to unrelated host paths.

### 15.4 Trust boundary

v0.1 is designed to connect only to the project-managed TigerVNC desktop container on a private network. LibVNCClient processes complex binary input and must be treated as a native attack surface.

- Pin a reviewed LibVNCServer/LibVNCClient release or commit.
- Record the selected version and security rationale.
- Run dependency and container vulnerability scanning in CI.
- Do not permit user-supplied VNC hosts in v0.1.
- Abort the connection on malformed framebuffer rectangles or unsafe size calculations.

### 15.5 Request limits

Configurable defaults:

| Limit | Default |
|---|---:|
| JSON body | 64 KiB |
| Clipboard text | 1 MiB |
| Keyboard text | 16 KiB |
| Chord keys | 8 |
| Scroll steps per axis | 100 |
| Pending worker commands | 256 |
| Concurrent PNG encodes | 2 |
| WebSocket clients | 16 |

These values may be tuned, but every queue and payload must remain bounded.

## 16. Configuration

Configuration should use environment variables for non-secret values and mounted files for secrets.

Suggested variables:

```text
VNC_HOST=desktop
VNC_PORT=5901
VNC_PASSWORD_FILE=/run/secrets/vnc_password
API_TOKEN_FILE=/run/secrets/api_token
API_BIND=0.0.0.0:8080
RUST_LOG=info
COMMAND_QUEUE_CAPACITY=256
COMMAND_TIMEOUT_MS=5000
VNC_STALL_TIMEOUT_MS=15000
RECONNECT_MIN_MS=500
RECONNECT_MAX_MS=30000
SCREENSHOT_MAX_CONCURRENCY=2
CLIPBOARD_MAX_BYTES=1048576
TEXT_MAX_BYTES=16384
```

Startup must reject:

- Missing required values.
- Empty secrets.
- Invalid ports or socket addresses.
- Zero or nonsensical capacities and timeouts.
- Secret files with unexpectedly broad permissions when that can be checked reliably.

Configuration validation must complete before the API reports readiness.

## 17. Observability

### 17.1 Logging

Use structured logs with fields such as:

- `request_id`
- `connection_state`
- `framebuffer_revision`
- `command_type`
- `queue_depth`
- `reconnect_attempt`
- `duration_ms`
- `error_kind`

Never log:

- API tokens.
- VNC passwords.
- Clipboard contents.
- Typed text.
- Full screenshots.

Payload content logging must be disabled by default, including in debug mode.

### 17.2 Metrics

A Prometheus-compatible `/metrics` endpoint may be enabled on an internal listener. At minimum track:

- Connection state.
- Reconnect attempts and outcomes.
- Commands accepted, rejected, timed out, and failed by type.
- Current and maximum command queue depth.
- Framebuffer updates and bytes copied.
- Screenshot requests, encode duration, and failures.
- WebSocket clients and dropped clients.
- Protocol errors.

Metrics must not contain secrets or unbounded labels.

## 18. Failure behavior

The system must fail visibly and predictably.

- API requests during disconnection return `503 not_connected`, except reconnect and status operations.
- Queue-full conditions return `503 command_queue_full`.
- No command may be silently discarded.
- No input request may wait indefinitely.
- Worker panic or unexpected exit makes readiness fail and causes the process supervisor to terminate or restart the controller according to deployment policy.
- A stale framebuffer is never served as though current after reconnect; its `complete` flag is cleared.
- Invalid framebuffer updates fail closed.
- Authentication failures are distinct from transport failures.
- Shutdown stops accepting new commands, drains or rejects pending commands deterministically, closes the VNC connection, and joins the worker thread.

## 19. Testing strategy

### 19.1 Unit tests

Must cover:

- Coordinate validation and boundary values.
- Checked framebuffer size arithmetic.
- Dirty-rectangle bounds checking.
- Pixel-format conversion with known fixtures.
- Mouse button mask transitions.
- Click and double-click event ordering.
- Scroll delta conversion and limits.
- Key name to keysym mapping.
- Chord press and reverse-release ordering.
- Unsupported text rejection before partial sends.
- Clipboard size and encoding validation.
- Connection and reconnect state transitions.
- Backoff reset, cap, and jitter bounds.
- Queue-full and timeout behavior.
- API authentication and error mapping.
- Secret redaction from logs and errors.

### 19.2 Adapter tests

Where possible, isolate C callback behavior with controlled fixtures. Unsafe wrapper tests must verify:

- Client allocation and cleanup on every failure path.
- No double free on initialization failure.
- Framebuffer reallocation on dimension changes is safe even though dynamic resizing is not publicly supported.
- Callback context lifetime outlives the C client.
- Panics do not cross the FFI boundary.
- Malformed rectangles are rejected before memory access.

Run sanitizer-enabled native tests in CI where practical.

### 19.3 Integration tests

Start the real desktop container and verify:

1. Controller connects and authenticates.
2. A complete `1280x800` framebuffer is received.
3. Screenshot endpoint returns a valid PNG of the expected dimensions.
4. Pointer movement reaches the desktop.
5. Left, middle, and right clicks are observed by the deterministic test app.
6. Vertical and horizontal scroll behavior is verified.
7. Key down/up and chords are observed in order.
8. Supported text is entered exactly.
9. Outbound and inbound clipboard behavior is verified.
10. Restarting the desktop causes visible disconnect and reconnect transitions.
11. Reconnect invalidates the old framebuffer and obtains a full new frame.
12. Wrong VNC credentials produce `authentication_failed` without rapid retries.

### 19.4 End-to-end test application

Provide a deterministic graphical application that displays and records:

- Current pointer coordinates.
- Mouse button presses and releases.
- Scroll events.
- Key press and release events.
- Text field contents.
- Clipboard copy and paste results.
- A visible color or counter change after each accepted action.

The application should expose a machine-readable local result file or loopback test endpoint so tests validate semantic outcomes rather than relying only on screenshot pixel comparison.

### 19.5 API end-to-end tests

Tests must use only the public API to:

1. Wait for readiness.
2. Fetch and validate the initial screenshot.
3. Click a known control.
4. Type known text.
5. Send a key chord.
6. Scroll a known target.
7. Set and retrieve clipboard state.
8. Confirm the test application's recorded event sequence.
9. Restart the desktop and verify recovery.

## 20. CI requirements

CI must include:

- `cargo fmt --check`
- `cargo clippy --all-targets --all-features -- -D warnings`
- `cargo test --all-targets --all-features`
- Documentation build with warnings denied where practical.
- Dependency license and advisory checks.
- Container build for both images.
- Container image vulnerability scan with an explicit severity policy.
- Docker Compose integration tests.
- End-to-end desktop tests on a Linux runner.
- Shell script linting.
- Dockerfile linting.

Release builds must pin base image digests and preserve a software bill of materials or equivalent dependency inventory.

## 21. Deployment model

The default Compose deployment contains:

```text
desktop
  private network only
  expose 5901
  optional persistent home volume
  VNC password secret

controller
  private connection to desktop:5901
  publish API port 8080
  API token secret
  health checks and resource limits
```

TLS should normally terminate at a trusted reverse proxy outside the controller container. The deployment guide must state that bearer tokens over plaintext networks are unacceptable.

## 22. Acceptance criteria

v0.1 is complete only when all of the following are true:

1. A clean checkout can build and start both containers with documented commands.
2. The desktop runs as a non-root user with TigerVNC authentication enabled.
3. The raw VNC port is not publicly published by the production Compose file.
4. The controller runs as a non-root user and connects through the private network.
5. All raw LibVNCClient operations are confined to the adapter and worker thread.
6. `/health/ready` becomes healthy only after a complete framebuffer arrives.
7. `/v1/screenshot.png` returns a coherent `1280x800` PNG.
8. Every documented pointer, mouse, scroll, keyboard, text, clipboard, status, display, reconnect, and event endpoint behaves as specified.
9. Invalid coordinates, unsupported keys or characters, excessive payloads, disconnects, queue saturation, and timeouts produce explicit machine-readable errors.
10. Restarting the desktop demonstrates bounded disconnect detection and successful automatic reconnection.
11. Old framebuffer content is invalidated during reconnect.
12. Unit, integration, and end-to-end tests pass in CI.
13. No API token, VNC password, typed text, clipboard content, or screenshot data appears in logs.
14. Security and dependency scans meet the documented release policy.
15. The README explains scope, architecture, local startup, API use, debugging, security boundaries, and known limitations.

## 23. Deferred roadmap

Potential post-v0.1 work, in approximate order:

1. Efficient dirty-rectangle or image-frame streaming.
2. Human/automation control leases.
3. Multiple isolated desktop sessions.
4. Session lifecycle and container orchestration APIs.
5. Accessibility-tree integration through AT-SPI.
6. OCR and computer-vision helpers.
7. Playwright integration for browser-specialized workflows.
8. AI-agent action planning above the primitive API.
9. Fine-grained authentication and tenant isolation.
10. Additional Linux desktops or non-Linux targets.

Every deferred capability must remain layered above or beside the stable primitive-control contract rather than leaking semantic automation concerns into the LibVNC adapter.

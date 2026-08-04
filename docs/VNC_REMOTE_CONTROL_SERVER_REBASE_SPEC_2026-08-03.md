# VNC Remote Control Server — Rebased Implementation Spec

Date: 2026-08-03
Repository: `ekkus93/vnc-remote-control-server`
Basis: code review of `master` at `da1d6d636c8ded87471ad7bc0ac493f1ef39e98a`, current TODO `docs/VNC_REMOTE_CONTROL_SERVER_V01_TODO.md`, and latest CI status issue #1.

---

## 1. Purpose

This document rebases the v0.1 implementation plan on the actual repository state after the first implementation pass and code review.

The original v0.1 plan remains useful as the broad target, but the repository is not starting from zero anymore. It now has:

- a Rust workspace baseline;
- a warning-denied core domain crate;
- a Debian XFCE/TigerVNC desktop container;
- a deterministic Tk test app;
- a desktop smoke test harness;
- CI quality checks;
- a ChatGPT-readable CI status bridge through GitHub issue #1.

It also has a red current CI run and major unimplemented areas:

- the desktop smoke test currently misclassifies wrong-password viewer behavior;
- `libvnc-adapter` is still an explicit FFI spike placeholder;
- `controller-api` is still an explicit API placeholder;
- Compose deployment is not present;
- real framebuffer, input, clipboard, WebSocket, metrics, integration, sanitizer, and release evidence are not present.

The objective of this rebased spec is to define the corrected route from the current state to a credible v0.1 release without papering over gaps.

---

## 2. Current repository baseline

### 2.1 Commit and CI state

The reviewed commit is:

```text
da1d6d636c8ded87471ad7bc0ac493f1ef39e98a
```

The latest authoritative CI status was read from GitHub issue #1. At review time, the latest CI run for `master` was:

```text
Workflow: CI
Run: 30862582334
Attempt: 1
Conclusion: failure
Problem job: Secured Debian desktop image
Problem step: Run desktop image smoke test
```

The repository must not treat any milestone as completed if the exact candidate SHA has a red required CI workflow.

### 2.2 Implemented baseline

The repository currently has the following useful pieces:

- workspace `Cargo.toml` with resolver 3, edition 2024, pinned workspace rust-version `1.97.1`, and deny-level Rust/Clippy warning policy;
- `rust-toolchain.toml` pinned to Rust `1.97.1` with `clippy` and `rustfmt`;
- committed `Cargo.lock`;
- `remote-desktop-core` with `#![forbid(unsafe_code)]`;
- core display, coordinate, rectangle, framebuffer snapshot, clipboard snapshot, key, mouse, worker command, connection state, event, and validation types;
- core tests and property tests for boundary validation and overflow behavior;
- desktop image based on digest-pinned `debian:13.6-slim`;
- non-root desktop user;
- runtime VNC secret file loading;
- TigerVNC `Xtigervnc` launch with `VncAuth`;
- deterministic Tk test app that writes atomic JSON state;
- desktop healthcheck;
- desktop smoke test harness;
- basic CI workflow;
- CI status publisher workflow;
- repository policy docs.

### 2.3 Explicitly unimplemented baseline

The following are not implemented and must not be marked complete by inference:

- native LibVNCClient bindings;
- LibVNCClient connection spike;
- Rust FFI safety wrapper;
- adapter worker thread;
- reconnect/backoff/stall detection;
- framebuffer update ingestion;
- PNG screenshot route;
- pointer, button, scroll, keyboard, chord, text, and clipboard control through VNC;
- authenticated HTTP API;
- authenticated WebSocket events;
- structured logging and metrics;
- production Compose topology;
- integration and E2E tests;
- sanitizer/Miri/native safety jobs;
- dependency/image security gates;
- OpenAPI documentation;
- final v0.1 acceptance evidence.

---

## 3. Product boundary

v0.1 is one authenticated API server controlling and observing exactly one project-owned Debian graphical desktop container through VNC.

v0.1 provides:

- connection status;
- display metadata;
- PNG screenshots;
- pointer movement;
- mouse button, click, double-click, and scroll commands;
- symbolic keyboard key and chord commands;
- bounded supported-text input;
- outbound clipboard set;
- inbound clipboard snapshot;
- authenticated WebSocket state/revision events;
- health/readiness endpoints;
- deterministic reconnect, shutdown, and overload behavior;
- production Compose that exposes only the controller API.

v0.1 does not provide:

- multiple desktop sessions;
- user/session management;
- public raw VNC access;
- noVNC browser viewer;
- Playwright integration;
- OCR;
- computer-vision targeting;
- accessibility-tree automation;
- AI task planning;
- arbitrary external VNC server support;
- dynamic desktop resizing;
- JPEG/WebP/live streaming.

Those features may be implemented later only after a deliberate spec revision.

---

## 4. Architecture

### 4.1 Runtime topology

Production topology:

```text
client
  -> HTTPS reverse proxy / local trusted network boundary
     -> controller container
        -> Rust HTTP/WebSocket API
        -> one worker thread
        -> private LibVNCClient adapter
        -> internal Docker network
           -> desktop container
              -> TigerVNC Xvnc on 5901
              -> XFCE/Openbox-compatible desktop
              -> deterministic test application for validation
```

Production Compose must publish only the controller API port. The desktop VNC port must be available only on the private Docker network through `expose`, not host `ports`.

A debug profile may bind raw VNC to `127.0.0.1:5901`, but it must be opt-in, clearly documented as development-only, and impossible to inherit accidentally from production Compose.

### 4.2 Crate boundaries

`remote-desktop-core`:

- safe Rust only;
- no `unsafe`;
- no native dependencies;
- no Axum/Tokio dependency unless there is a clear reason;
- public domain types, validation, typed errors, redaction-safe display formatting, and pure logic tests.

`libvnc-adapter`:

- only crate allowed to touch raw LibVNCClient pointers;
- may contain `unsafe`, but only behind a documented FFI safety contract;
- no raw native pointer may cross the crate boundary;
- exposes safe Rust adapter and worker-facing operations;
- owns native cleanup ordering and panic containment.

`controller-api`:

- owns HTTP/WebSocket routing, config loading, authentication, request IDs, error envelopes, screenshot encoding, graceful shutdown, and API integration tests;
- must not directly touch LibVNCClient state;
- communicates with the adapter only through the worker abstraction.

---

## 5. Corrected M1 desktop smoke behavior

The current red CI is caused by the desktop smoke test's wrong-password viewer probe. The test logs showed that TigerVNC Viewer reported authentication failure, but the harness still treated the timeout status as proof that a wrong-password session was established.

The corrected smoke contract is:

### 5.1 Negative auth probe

For a wrong password:

- invoke the viewer with a bounded timeout;
- capture stdout/stderr;
- require output matching a known authentication-failure pattern, such as `Authentication failure` or `Authentication failed`;
- reject any output that shows a successful authenticated framebuffer/session;
- do not interpret `timeout` exit status alone as success or failure;
- print the captured viewer log on failure.

### 5.2 Positive auth probe

For the correct password:

- invoke the viewer with a bounded timeout;
- require output proving authentication reached a persistent session state;
- reject any authentication failure text;
- tolerate timeout only after positive connection/authentication evidence has appeared;
- print the captured viewer log on failure.

### 5.3 Desktop smoke evidence

The smoke test must continue proving:

- image builds from the pinned base digest;
- the runtime password does not appear in image history;
- the container runs as UID `10001`;
- `Xtigervnc` runs as UID `10001`;
- encoded VNC password file is `0600`;
- VNC listens inside the container;
- display dimensions are exactly `1280x800`;
- test app state file is present and valid;
- runtime password does not appear in container logs;
- wrong VNC password is rejected;
- correct VNC password connects;
- missing secret fails closed;
- shutdown is deterministic and diagnosable.

---

## 6. Native LibVNCClient adapter

### 6.1 Binding strategy

The implementation must choose one binding strategy and document it before writing production adapter code:

Option A: generated bindings

- build image installs native development packages;
- `wrapper.h` includes only required public LibVNCClient headers;
- `build.rs` runs bindgen;
- allowlists restrict exposed functions, types, and constants;
- rerun directives cover `wrapper.h`, build script changes, and relevant environment variables.

Option B: reviewed checked-in minimal bindings

- bindings are handwritten or generated once then reviewed;
- binding source is committed;
- native library discovery is explicit;
- dependency versions are recorded;
- any regenerated binding diff is reviewed.

The selected strategy must make missing native dependencies fail with an actionable build error and must ensure release builds do not accidentally depend on undeclared host libraries.

### 6.2 FFI safety invariants

`libvnc-adapter` must document these invariants at module level:

- every raw native allocation has exactly one owner;
- raw pointers do not cross crate boundaries;
- callback context lives in stable memory for the full C-client lifetime;
- Rust panics are caught before crossing C callback boundaries;
- callback dimensions and rectangle coordinates are validated before memory access;
- buffer arithmetic is checked;
- cleanup ordering is defined for each partial initialization stage;
- cleanup is idempotent or guarded;
- secrets and payload contents are not formatted into errors or logs.

### 6.3 Minimal spike

Before production worker code, add a spike or harness that:

- allocates an `rfbClient` safely;
- configures credentials from the mounted VNC password;
- connects to the real desktop container;
- authenticates;
- receives initial server metadata;
- allocates framebuffer through the supported callback path;
- processes server messages until one complete frame is observed;
- sends one pointer move;
- sends one key press/release;
- sends one clipboard value;
- disconnects and frees all resources;
- records native and Rust dependency versions.

Throwaway spike code must either be removed or promoted into production modules with tests.

---

## 7. Worker lifecycle and state machine

The adapter must be owned by exactly one dedicated native worker thread.

Axum handlers and Tokio tasks must not call LibVNCClient directly.

### 7.1 Worker command flow

HTTP handlers validate and preflight requests, then enqueue bounded commands to the worker.

The worker must provide either:

- enqueue acknowledgement semantics for asynchronous `202` commands; or
- command-completion semantics for synchronous operations.

The selected semantic must be documented route-by-route.

### 7.2 Required worker behavior

The worker must:

- spawn exactly one native thread for the configured session;
- own all native adapter state;
- use a bounded command channel;
- publish events through a bounded broadcast mechanism;
- provide startup acknowledgement;
- provide graceful shutdown and thread join;
- reject commands during shutdown;
- treat unexpected worker exit as a fatal readiness failure;
- never silently drop commands.

### 7.3 Connection state machine

External connection states:

- `starting`;
- `connecting`;
- `connected`;
- `degraded`;
- `reconnecting`;
- `disconnected`;
- `authentication_failed`;
- `stopped`.

The implementation must validate allowed transitions and publish transition events.

Authentication failures must not retry rapidly. Configuration failures must not masquerade as transient transport disconnects.

### 7.4 Reconnection

The worker must implement:

- exponential backoff;
- bounded jitter;
- configurable min/max delays;
- reset after stable connection;
- rate-limited manual reconnect;
- framebuffer invalidation on disconnect;
- clearing pressed-key and button state on disconnect;
- full framebuffer update request after reconnect;
- readiness only after a fresh complete frame.

### 7.5 Stall detection

The worker must track last successful server message time and distinguish idle desktop from stalled connection.

Stall detection may use protocol-safe probes or explicit framebuffer refresh requests. Confirmed stalls must visibly transition to degraded/reconnecting, and API requests must remain time-bounded.

---

## 8. Framebuffer and screenshots

### 8.1 Canonical framebuffer

The controller stores canonical RGBA8 frames.

Requirements:

- safe stride and allocation calculations;
- selected LibVNCClient pixel format conversion;
- zero dimensions rejected;
- overflow rejected;
- dimensions above configured memory limit rejected;
- complete/incomplete state;
- monotonically increasing process-local revision;
- update timestamps;
- invalidation on disconnect/reconnect.

### 8.2 Dirty rectangles

Every rectangle update must validate:

- nonzero width and height;
- `x + width` overflow;
- `y + height` overflow;
- rectangle inside current framebuffer;
- copy source and destination lengths;
- coherent commit boundary.

Revision semantics must be explicitly selected and tested. Prefer one revision per coherent framebuffer commit/message, not per arbitrary byte copy.

### 8.3 Snapshots and PNG encoding

Screenshot route requirements:

- immutable framebuffer snapshots;
- snapshot creation cannot observe partial rectangle copy;
- locks are not held during PNG encoding;
- unavailable before complete frame;
- unavailable/stale after disconnect until full refresh;
- maintained PNG encoder;
- bounded concurrent encode permits;
- encode timeout;
- ETags derived from process instance and framebuffer revision;
- `If-None-Match` support with `304`;
- correct `Content-Type` and cache-control headers.

---

## 9. Input semantics

### 9.1 Pointer movement

Pointer movement must:

- reject unknown dimensions;
- strictly validate coordinates;
- not clamp;
- send movement with current button mask;
- test all edges and out-of-range values.

### 9.2 Mouse buttons/clicks

The worker must maintain the full current button mask.

Required operations:

- button down;
- button up;
- atomic click;
- atomic double-click;
- bounded double-click interval;
- best-effort release on partial failure;
- clear button state on disconnect/shutdown.

### 9.3 Scrolling

Scrolling must:

- verify TigerVNC vertical wheel mask behavior;
- verify horizontal wheel behavior or remove horizontal scroll from v0.1;
- convert signed deltas into bounded wheel steps;
- reject excessive step counts;
- keep each scroll command atomic in the worker.

### 9.4 Keyboard

The public API must expose stable symbolic key names, not raw numeric keysyms.

Required keys:

- modifiers;
- navigation keys;
- editing keys;
- arrows;
- F1-F12;
- printable ASCII needed for chords.

Before the HTTP API lands, `KeyboardKey` serialization/deserialization must be made explicit so the public JSON shape is stable and does not leak Serde's default enum representation.

### 9.5 Chords and text

Chords must:

- press keys in order;
- release in reverse order;
- enforce maximum length;
- avoid duplicate modifier bookkeeping corruption;
- best-effort release after partial failure;
- clear key state on disconnect/shutdown.

Text input v0.1 supports only explicitly documented characters. Unsupported characters must fail preflight before any character is sent. Text contents must never appear in logs, events, metrics, or error formatting.

---

## 10. Clipboard

### 10.1 Outbound clipboard

`PUT /v1/clipboard` must:

- validate UTF-8 through HTTP body parsing;
- enforce byte limit;
- reject or explicitly define embedded NUL behavior;
- send clipboard content through LibVNCClient;
- return success only after accepted send/enqueue semantics;
- never log clipboard contents.

### 10.2 Inbound clipboard

`GET /v1/clipboard` must return the last observed server clipboard snapshot.

Before the first inbound callback, it must return `clipboard_unavailable`.

Inbound callback handling must:

- decode according to verified TigerVNC/RFB behavior;
- reject or visibly report invalid encoding;
- store text, revision, and timestamp;
- publish clipboard revision events without clipboard text.

---

## 11. Authenticated HTTP API

### 11.1 Configuration

Configuration must be typed and validated.

Requirements:

- non-secret values from environment variables;
- API and VNC secrets from files by default;
- environment secrets only in explicitly documented dev mode, if allowed at all;
- reject empty secrets;
- validate socket addresses, ports, capacities, timeouts, and limits;
- warn or fail on overly broad secret-file permissions according to documented policy;
- redact secrets from debug output.

### 11.2 Authentication

All `/v1/*` routes require:

```text
Authorization: Bearer <token>
```

Rules:

- no query-string tokens;
- authenticated WebSocket upgrades;
- timing-resistant token comparison where practical;
- same generic response for missing and invalid tokens;
- authorization header redaction in logs;
- tests for missing, malformed, wrong, and correct credentials.

### 11.3 Request IDs and errors

The API must:

- accept a valid incoming request ID or generate one;
- return request ID in headers and JSON error body;
- use the specification's JSON error envelope;
- map every domain error to stable code and HTTP status;
- prevent native errors, secrets, typed text, clipboard text, and pixels from reaching clients accidentally.

### 11.4 Required routes

Health/status:

- `GET /health/live`;
- `GET /health/ready`;
- `GET /v1/status`;
- `GET /v1/display`.

Screenshots:

- `GET /v1/screenshot.png`.

Pointer:

- `POST /v1/pointer/move`;
- `POST /v1/pointer/button`;
- `POST /v1/pointer/click`;
- `POST /v1/pointer/double-click`;
- `POST /v1/pointer/scroll`.

Keyboard:

- `POST /v1/keyboard/key`;
- `POST /v1/keyboard/chord`;
- `POST /v1/keyboard/text`.

Clipboard and connection:

- `GET /v1/clipboard`;
- `PUT /v1/clipboard`;
- `POST /v1/connection/reconnect`.

The v0.1 API must reject oversized requests and time out slow body/header/ack paths.

---

## 12. WebSocket, logging, metrics, and overload

### 12.1 Events

`GET /v1/events` WebSocket must be authenticated and provide:

- process-local sequence numbers;
- timestamps;
- initial connection-state snapshot;
- connection state changes;
- framebuffer revisions;
- framebuffer invalidation;
- clipboard revisions;
- overload notifications;
- protocol error notifications.

Events must never include clipboard text, typed text, screenshot pixels, bearer tokens, or VNC passwords.

### 12.2 WebSocket overload

The implementation must:

- bound per-client buffering;
- bound total clients;
- disconnect slow clients with a clear close code/reason;
- add ping/pong or idle detection;
- clean up client resources on disconnect.

### 12.3 Logs

Structured tracing must include:

- request spans and request IDs;
- connection and worker spans;
- state transitions;
- queue saturation;
- timeouts;
- reconnect attempts and outcomes.

Redaction tests must verify that API tokens, VNC passwords, typed text, clipboard content, and framebuffer data are absent.

### 12.4 Metrics

Metrics must use bounded labels only.

Track:

- connection state;
- reconnect attempts and outcomes;
- command totals by bounded command type;
- queue depth/capacity;
- framebuffer revision and update failures;
- screenshot encode counts/durations/failures;
- WebSocket clients and slow disconnects;
- protocol/authentication errors.

Do not use unbounded labels such as request IDs, URLs, arbitrary key names, clipboard text, typed text, native error strings, or user-provided values.

---

## 13. Docker Compose and persistence

### 13.1 Production Compose

Add `deploy/compose.yaml` with:

- separate desktop and controller services;
- internal network for controller-to-desktop traffic;
- desktop uses `expose: 5901`, not host `ports`;
- controller API is the only published service;
- secrets mounted through Docker secrets or secret-file mounts;
- healthcheck dependencies that do not rely only on startup order;
- CPU, memory, PID, and file descriptor limits;
- dropped unnecessary capabilities;
- `no-new-privileges`;
- read-only controller root filesystem where practical;
- bounded temp filesystems;
- no Docker socket mount.

### 13.2 Debug VNC profile

Add a development-only override/profile that binds raw VNC only to:

```text
127.0.0.1:5901:5901
```

Production Compose must not inherit that binding.

### 13.3 Persistence modes

Default desktop state is disposable.

Optional persistence profile may mount a named volume for the desktop home directory.

Documentation and tests must define:

- what persists;
- what does not persist;
- how disposable recreation clears state;
- how persistent recreation preserves expected state;
- why secrets must not be copied into persistent home volumes.

---

## 14. CI, integration, and release evidence

### 14.1 Required quality gates

CI must include:

- `cargo fmt --check`;
- Clippy all targets/features with warnings denied;
- Rust tests;
- rustdoc with warnings denied;
- Python compile/checks;
- shell syntax;
- ShellCheck;
- Actionlint;
- Dockerfile lint or documented equivalent;
- Compose validation;
- `cargo deny check`;
- dependency and license policy checks;
- controller and desktop image scans;
- bounded workflow timeout;
- sanitized failure artifacts.

### 14.2 Native safety gates

Add where practical:

- AddressSanitizer coverage for adapter tests;
- UndefinedBehaviorSanitizer coverage;
- ThreadSanitizer for Rust-only shared-state tests if useful;
- Miri for compatible pure-Rust core code;
- explicit limitations for sanitizer coverage around C FFI.

Sanitizer findings are release blockers.

### 14.3 Integration/E2E tests

Real-container tests must cover:

- clean Compose startup;
- API authentication;
- readiness after complete framebuffer;
- status/display/screenshot;
- wrong VNC password failure;
- missing VNC secret failure;
- desktop restart and automatic reconnect;
- old framebuffer unavailable during reconnect;
- pointer/button/click/double-click/scroll/key/chord/text behavior through public API;
- unsupported text preflight without partial mutation;
- outbound and inbound clipboard;
- WebSocket revision events;
- queue saturation;
- oversized JSON/body limits;
- reconnect rate limiting;
- slow WebSocket client disconnect;
- graceful SIGTERM with queued commands;
- no leaked containers, volumes, or networks.

### 14.4 Final evidence record

The final v0.1 release candidate must update a final evidence record with:

```text
Release candidate commit:

Toolchain versions:
- Rust:
- Debian base digest:
- TigerVNC:
- LibVNCClient:
- Docker:

Validation commands:

Results:
- Unit tests:
- Desktop smoke:
- Adapter safety tests:
- Integration tests:
- End-to-end tests:
- Sanitizers:
- Security scans:
- Container smoke test:

Known v0.1 limitations:

Release decision:
```

No release claim is valid without exact commit SHA and exact validation evidence.

---

## 15. Documentation requirements

Update README and operator docs as implementation lands.

Required docs:

- product boundary;
- architecture diagram;
- prerequisites;
- secret generation;
- local build/startup;
- authenticated API examples without real secrets;
- screenshot usage;
- WebSocket usage;
- reverse-proxy/TLS expectations;
- disposable/persistent modes;
- loopback-only debug VNC;
- shutdown/recovery behavior;
- known text and clipboard encoding limitations;
- resource limits/tuning;
- troubleshooting for desktop startup, VNC auth, controller connection, and framebuffer readiness.

Required API docs:

- OpenAPI document for HTTP routes;
- bearer authentication;
- every request/response schema;
- error codes/statuses;
- asynchronous `202` semantics;
- WebSocket event envelope if OpenAPI tooling is insufficient;
- tested curl examples.

---

## 16. Release acceptance criteria

v0.1 is complete only when all of the following are true on the exact candidate SHA:

- current CI is green;
- desktop and controller are separate containers;
- production Compose exposes only authenticated controller API;
- debug raw VNC is loopback-only and opt-in;
- controller and desktop run non-root;
- raw LibVNCClient state is confined to the adapter and one worker thread;
- complete framebuffer is received;
- display metadata is correct;
- PNG screenshots are coherent;
- screenshot ETags/conditional GET work;
- framebuffer invalidates on reconnect;
- authenticated WebSocket revision events work;
- pointer, mouse, scroll, keyboard, chord, text, and clipboard behavior work through public API;
- unsupported text fails before partial input;
- automatic reconnect works after desktop restart;
- authentication failure is visible and backoff-safe;
- queue saturation is visible;
- requests and shutdown are time-bounded;
- slow WebSocket clients cannot consume unbounded memory;
- worker failure causes readiness failure;
- no command is silently dropped;
- bearer auth is required on all `/v1/*` routes;
- VNC authentication is mandatory;
- tokens/passwords come from secrets, not image layers;
- tokens, passwords, typed text, clipboard content, and framebuffer pixels do not appear in logs;
- dependency/image/security policy gates pass;
- README and API docs match actual behavior;
- final evidence record is complete.

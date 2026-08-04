# LibVNCClient Binding Decision

Date: 2026-08-03
Status: Accepted for v0.1

## Decision

Use a project-owned, narrow C shim over the system LibVNCClient API instead of exposing generated `rfbClient` bindings directly to Rust.

The shim is compiled as part of `libvnc-adapter` and exports only opaque handles plus the exact operations required by this project. Rust never reproduces or depends on the layout of `rfbClient`.

## Rationale

LibVNCClient is a C API whose public client structure contains mutable buffers, callback function pointers, connection state, protocol metadata, and version-dependent fields. Broad generated bindings would make that complete layout reachable from Rust and would create a larger unsafe review surface than this single-session service needs.

A narrow shim provides these properties:

- one opaque native handle;
- one allocation and cleanup path;
- callback context owned for the full native-client lifetime;
- checked framebuffer allocation before assigning `client->frameBuffer`;
- no callback from C into Rust;
- no Rust panic can cross a C callback boundary;
- explicit error codes without passwords, clipboard values, typed text, or pixels;
- a stable Rust-facing ABI independent of unrelated `rfbClient` fields.

## Native source

The supported development and CI environment installs the distribution `libvncserver-dev` package and resolves LibVNCClient through `pkg-config` module `libvncclient`.

The build script records the detected `pkg-config` version as `VRC_LIBVNCCLIENT_VERSION` and fails with an actionable error when the compiler, archiver, `pkg-config`, headers, or library are missing.

The release controller image must install the matching runtime library explicitly. It must not rely on an undeclared host library.

## API surface used

The shim is limited to:

- `rfbGetClient`;
- `ConnectToRFBServer`;
- `InitialiseRFBConnection`;
- the configured `MallocFrameBuffer` callback;
- `SetFormatAndEncodings`;
- `WaitForMessage` followed by `HandleRFBServerMessage`;
- `rfbClientSetClientData` and `rfbClientGetClientData`;
- password, framebuffer-allocation, completed-framebuffer-update, and clipboard callbacks;
- `SendFramebufferUpdateRequest`;
- `SendPointerEvent`;
- `SendKeyEvent`;
- `SendClientCutText` and, when available through the installed API, UTF-8 clipboard support;
- `rfbClientCleanup`.

The shim deliberately does not call `rfbInitClient`. LibVNCClient's implementation calls `rfbClientCleanup` internally when connection or protocol initialization fails, which would make an external RAII owner retain a dangling pointer unless it relied on undocumented recovery behavior. Its argv endpoint parser also has semantics that differ from TigerVNC viewer's `host::port` notation. The shim instead passes the configured hostname and raw TCP port directly to `ConnectToRFBServer`, performs the documented initialization sequence, and retains one cleanup owner for every success and failure path.

LibVNCClient documents that `rfbClientCleanup` does not free `client->frameBuffer`; therefore the shim owns and frees that buffer before native cleanup.

## Safety invariants

1. Every native allocation has exactly one owning `NativeClient`.
2. The raw pointer is private to `libvnc-adapter`.
3. The C context and password copy outlive every LibVNCClient callback.
4. The password callback returns a fresh allocation because LibVNCClient frees the returned pointer.
5. Framebuffer dimensions must be positive, arithmetically valid, and at most 64 MiB in canonical 32-bit storage.
6. No rectangle or snapshot copy is exposed until its bounds and length are validated.
7. C callbacks contain no Rust code and cannot unwind into C.
8. Cleanup frees project-owned buffers before calling `rfbClientCleanup` and is guarded against repeated execution.
9. Partial connection and protocol initialization failures remain owned by the shim and are destroyed only through the RAII cleanup path.
10. Native errors expose bounded categories only; secret and payload values are never formatted.
11. The native client is intended only for the project-owned desktop container, not arbitrary untrusted VNC servers.

## Version and security policy

The exact installed LibVNCClient version is captured in CI evidence. Dependency updates require:

- reviewing upstream security notices;
- rebuilding with all C warnings promoted to errors;
- passing the real TigerVNC connection spike;
- passing framebuffer, input, clipboard, cleanup, and sanitizer tests;
- recording the updated native version in release evidence.

## Rejected alternatives

### Broad bindgen output

Rejected because it exposes the full mutable C structure and callback surface, expands the unsafe boundary, and couples Rust code to header layout.

### Hand-maintained Rust representation of `rfbClient`

Rejected because struct layout drift would be memory-unsafe.

### `rfbInitClient` convenience initialization

Rejected because it takes ownership of cleanup on failure and parses connection endpoints through command-line syntax. Both behaviors conflict with this project's explicit single-owner RAII contract.

### High-level third-party Rust wrapper

Deferred because v0.1 requires a small, reviewable client-only surface with explicit ownership and callback behavior. A future replacement must demonstrate equivalent feature coverage, maintenance, safety, and real-container interoperability.

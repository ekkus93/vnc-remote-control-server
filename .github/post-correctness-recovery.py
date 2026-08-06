from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{relative}: expected one recovery anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def insert_before_once(relative: str, anchor: str, addition: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(anchor)
    if count != 1:
        raise SystemExit(f"{relative}: expected one insertion anchor, found {count}")
    path.write_text(text.replace(anchor, addition + anchor, 1), encoding="utf-8")


replace_once(
    "crates/controller-api/src/config.rs",
    '''/// Process-wide API bearer token. The value is intentionally not `Debug` or
/// `Display`; cloning this handle clones an `Arc`, not the token bytes.
#[derive(Clone, PartialEq, Eq)]
pub struct ApiToken {
    inner: Arc<SecretString>,
}

impl ApiToken {
    /// Wraps a parsed file-backed secret as a long-lived bearer token.
    pub fn new(secret: SecretString) -> Self {
        Self {
            inner: Arc::new(secret),
        }
    }

    /// Exposes bytes only to the constant-time bearer comparison boundary.
    pub fn as_bytes(&self) -> &[u8] {
        self.inner.expose_secret().as_bytes()
    }

    /// Returns whether this token would be unusable for authentication.
    pub fn is_empty(&self) -> bool {
        self.inner.expose_secret().is_empty()
    }

    /// Exposes the secret for tests and narrow configuration assertions.
    pub fn expose_secret(&self) -> &str {
        self.inner.expose_secret()
    }
}

impl From<SecretString> for ApiToken {
    fn from(value: SecretString) -> Self {
        Self::new(value)
    }
}

impl From<Arc<str>> for ApiToken {
    fn from(value: Arc<str>) -> Self {
        Self::new(SecretString::from(value.as_ref()))
    }
}

impl From<&str> for ApiToken {
    fn from(value: &str) -> Self {
        Self::new(SecretString::from(value))
    }
}

impl AsRef<str> for ApiToken {
    fn as_ref(&self) -> &str {
        self.expose_secret()
    }
}
''',
    '''/// Process-wide API bearer token. The value is intentionally not `Debug` or
/// `Display`; cloning this handle clones an `Arc`, not the token bytes.
#[derive(Clone, PartialEq, Eq)]
pub struct ApiToken {
    inner: Arc<SecretString>,
}

impl ApiToken {
    /// Transfers one parsed file-backed secret into long-lived token ownership.
    pub(crate) fn from_secret(secret: SecretString) -> Self {
        Self {
            inner: Arc::new(secret),
        }
    }

    /// Exposes bytes only to the constant-time bearer comparison boundary.
    pub(crate) fn as_bytes(&self) -> &[u8] {
        self.inner.expose_secret().as_bytes()
    }

    /// Returns whether this token would be unusable for authentication.
    pub(crate) fn is_empty(&self) -> bool {
        self.inner.expose_secret().is_empty()
    }

    #[cfg(test)]
    fn expose_secret_for_test(&self) -> &str {
        self.inner.expose_secret()
    }
}
''',
)
replace_once(
    "crates/controller-api/src/config.rs",
    "let api_token = ApiToken::new(secrets.read_secret(&api_token_path)?);",
    "let api_token = ApiToken::from_secret(secrets.read_secret(&api_token_path)?);",
)
replace_once(
    "crates/controller-api/src/config.rs",
    '''fn parse_secret_bytes_with_rejection_observer<F>(
    path: &Path,
    bytes: Vec<u8>,
    observe_rejection: F,
) -> Result<SecretString, ConfigError>
where
    F: FnOnce(&[u8]),
{
    let mut value = match String::from_utf8(bytes) {
        Ok(value) => value,
        Err(error) => {
            return scrub_and_reject_secret_bytes(
                path,
                error.into_bytes(),
                "contents are not UTF-8",
                observe_rejection,
            );
        }
    };
    while value.ends_with('\n') || value.ends_with('\r') {
        value.pop();
    }
    if value.is_empty() || value.contains('\0') {
        return scrub_and_reject_secret_bytes(
            path,
            value.into_bytes(),
            "contents are empty or contain NUL",
            observe_rejection,
        );
    }
    Ok(SecretString::from(value))
}

fn scrub_and_reject_secret_bytes<F>(
    path: &Path,
    mut bytes: Vec<u8>,
    reason: &'static str,
    observe_rejection: F,
) -> Result<SecretString, ConfigError>
where
    F: FnOnce(&[u8]),
{
    secure_scrub_bytes(&mut bytes);
    observe_rejection(&bytes);
    Err(ConfigError::SecretFile {
        path: path.to_path_buf(),
        reason,
    })
}

fn secure_scrub_bytes(bytes: &mut [u8]) {
    bytes.fill(0);
    compiler_fence(Ordering::SeqCst);
}
''',
    '''fn parse_secret_bytes_with_rejection_observer<F>(
    path: &Path,
    mut bytes: Vec<u8>,
    observe_rejection: F,
) -> Result<SecretString, ConfigError>
where
    F: FnOnce(&[u8]),
{
    if std::str::from_utf8(&bytes).is_err() {
        return scrub_and_reject_secret_bytes(
            path,
            bytes,
            "contents are not UTF-8",
            observe_rejection,
        );
    }

    let mut trimmed_length = bytes.len();
    while trimmed_length > 0
        && matches!(bytes[trimmed_length - 1], b'\n' | b'\r')
    {
        trimmed_length -= 1;
    }
    if trimmed_length == 0 || bytes[..trimmed_length].contains(&0) {
        return scrub_and_reject_secret_bytes(
            path,
            bytes,
            "contents are empty or contain NUL",
            observe_rejection,
        );
    }

    secure_scrub_bytes(&mut bytes[trimmed_length..]);
    bytes.truncate(trimmed_length);
    match String::from_utf8(bytes) {
        Ok(value) => Ok(SecretString::from(value)),
        Err(error) => scrub_and_reject_secret_bytes(
            path,
            error.into_bytes(),
            "contents are not UTF-8",
            observe_rejection,
        ),
    }
}

fn scrub_and_reject_secret_bytes<F>(
    path: &Path,
    mut bytes: Vec<u8>,
    reason: &'static str,
    observe_rejection: F,
) -> Result<SecretString, ConfigError>
where
    F: FnOnce(&[u8]),
{
    secure_scrub_bytes(&mut bytes);
    observe_rejection(&bytes);
    Err(ConfigError::SecretFile {
        path: path.to_path_buf(),
        reason,
    })
}

fn secure_scrub_bytes(bytes: &mut [u8]) {
    for byte in bytes {
        // SAFETY: every pointer comes from the live, exclusively borrowed slice.
        unsafe { std::ptr::write_volatile(byte, 0) };
    }
    compiler_fence(Ordering::SeqCst);
}
''',
)
replace_once(
    "crates/controller-api/src/config.rs",
    'assert_eq!(config.api_token.as_ref(), "api-token");',
    'assert_eq!(config.api_token.expose_secret_for_test(), "api-token");',
)

replace_once(
    "crates/controller-api/src/http/state.rs",
    '''    pub fn new<T>(
        backend: Arc<dyn HttpBackend>,
        api_token: T,
        process_instance: Arc<str>,
        maximum_json_bytes: usize,
        command_ack_timeout: Duration,
    ) -> Result<Self, HttpBuildError>
    where
        T: Into<ApiToken>,
    {
''',
    '''    pub fn new(
        backend: Arc<dyn HttpBackend>,
        api_token: ApiToken,
        process_instance: Arc<str>,
        maximum_json_bytes: usize,
        command_ack_timeout: Duration,
    ) -> Result<Self, HttpBuildError> {
''',
)
replace_once(
    "crates/controller-api/src/http/state.rs",
    '''    fn new_with_observability<T>(
        backend: Arc<dyn HttpBackend>,
        api_token: T,
        process_instance: Arc<str>,
        maximum_json_bytes: usize,
        command_ack_timeout: Duration,
        events: EventHub,
        metrics: Metrics,
    ) -> Result<Self, HttpBuildError>
    where
        T: Into<ApiToken>,
    {
        let api_token = api_token.into();
''',
    '''    fn new_with_observability(
        backend: Arc<dyn HttpBackend>,
        api_token: ApiToken,
        process_instance: Arc<str>,
        maximum_json_bytes: usize,
        command_ack_timeout: Duration,
        events: EventHub,
        metrics: Metrics,
    ) -> Result<Self, HttpBuildError> {
''',
)

replace_once(
    "crates/controller-api/src/http/tests/mod.rs",
    '''use super::support::bearer_matches;
use crate::framebuffer::FramebufferMetadata;
''',
    '''use super::support::bearer_matches;
use crate::config::ApiToken;
use crate::framebuffer::FramebufferMetadata;
''',
)
replace_once(
    "crates/controller-api/src/http/tests/mod.rs",
    '''use axum::http::{HeaderValue, Request as HttpRequest, StatusCode};
use remote_desktop_core::{ClipboardSnapshot, ConnectionState, DesktopError, WorkerCommand};
''',
    '''use axum::http::{HeaderValue, Request as HttpRequest, StatusCode};
use libvnc_adapter::SecretString;
use remote_desktop_core::{ClipboardSnapshot, ConnectionState, DesktopError, WorkerCommand};
''',
)
replace_once(
    "crates/controller-api/src/http/tests/mod.rs",
    '''        backend.clone(),
        Arc::from("test-token"),
        Arc::from("test-process"),
''',
    '''        backend.clone(),
        ApiToken::from_secret(SecretString::from("test-token")),
        Arc::from("test-process"),
''',
)

replace_once(
    "crates/controller-api/src/events.rs",
    '''            Err(_) => {
                self.sequence_exhausted.store(true, Ordering::Release);
                tracing::error!("worker_event_sequence_exhausted");
                return Err(EventSequenceError::Exhausted);
            }
''',
    '''            Err(_) => {
                if !self.sequence_exhausted.swap(true, Ordering::AcqRel) {
                    tracing::error!("event_hub_sequence_exhausted");
                }
                return Err(EventSequenceError::Exhausted);
            }
''',
)
replace_once(
    "crates/controller-api/src/events.rs",
    '''        let (result, logs) = crate::test_support::capture_logs(|| {
            hub.publish_test(EventPayload::ProtocolError)
        });
        assert_eq!(result, Err(EventSequenceError::Exhausted));
        assert!(hub.sequence_exhausted.load(Ordering::Acquire));
        assert!(logs.contains("worker_event_sequence_exhausted"));
''',
    '''        let ((first, second), logs) = crate::test_support::capture_logs(|| {
            (
                hub.publish_test(EventPayload::ProtocolError),
                hub.publish_test(EventPayload::ProtocolError),
            )
        });
        assert_eq!(first, Err(EventSequenceError::Exhausted));
        assert_eq!(second, Err(EventSequenceError::Exhausted));
        assert!(hub.sequence_exhausted.load(Ordering::Acquire));
        assert_eq!(logs.matches("event_hub_sequence_exhausted").count(), 1);
''',
)

replace_once(
    "crates/controller-api/src/http/tests/health.rs",
    '''    let state = test_state(true, MockScreenshot::Png);
    state.events.force_sequence_for_test(u64::MAX);
    let app = router(state);
''',
    '''    let state = test_state(true, MockScreenshot::Png);
    state.events.force_sequence_for_test(u64::MAX);
    let app = router(state.clone());
''',
)
replace_once(
    "crates/controller-api/src/http/tests/health.rs",
    '''    let body = json_body(response).await;
    assert_eq!(body["error"]["code"], "event_sequence_exhausted");
}
''',
    '''    let body = json_body(response).await;
    assert_eq!(body["error"]["code"], "event_sequence_exhausted");
    let metrics = state.metrics.render(
        &state.backend.snapshot(),
        state.backend.command_submissions_in_flight(),
        state.backend.command_queue_capacity(),
    );
    assert!(metrics.contains("vrc_websocket_clients 0"));
}
''',
)

replace_once(
    "crates/libvnc-adapter/native/vnc_shim.c",
    '''static char *vrc_duplicate(const char *value) {
''',
    '''static void vrc_release_clipboard(char **clipboard, size_t *length) {
    if (clipboard == NULL || length == NULL) {
        return;
    }
    if (*clipboard != NULL) {
        vrc_secure_scrub(*clipboard, *length + 1U);
        free(*clipboard);
    }
    *clipboard = NULL;
    *length = 0U;
}

static char *vrc_duplicate(const char *value) {
''',
)
replace_once(
    "crates/libvnc-adapter/native/vnc_shim.c",
    '''    if (length > 0U && text == NULL) {
        vrc_set_error(client, "invalid clipboard update");
        return;
    }

    copy = malloc(length + 1U);
''',
    '''    if (length > 0U && text == NULL) {
        vrc_set_error(client, "invalid clipboard update");
        return;
    }
    if (client->clipboard_revision == UINT64_MAX) {
        vrc_set_error(client, "clipboard revision overflow");
        return;
    }

    copy = malloc(length + 1U);
''',
)
replace_once(
    "crates/libvnc-adapter/native/vnc_shim.c",
    '''    free(client->clipboard);
    client->clipboard = copy;
    client->clipboard_length = length;
    if (client->clipboard_revision == UINT64_MAX) {
        vrc_set_error(client, "clipboard revision overflow");
        return;
    }
    client->clipboard_revision += 1U;
''',
    '''    vrc_release_clipboard(&client->clipboard, &client->clipboard_length);
    client->clipboard = copy;
    client->clipboard_length = length;
    client->clipboard_revision += 1U;
''',
)
replace_once(
    "crates/libvnc-adapter/native/vnc_shim.c",
    '''    sent = SendClientCutText(client->native, copy, (int)text_length);
    free(copy);
    if (!sent) {
''',
    '''    sent = SendClientCutText(client->native, copy, (int)text_length);
    vrc_secure_scrub(copy, text_length + 1U);
    free(copy);
    if (!sent) {
''',
)
replace_once(
    "crates/libvnc-adapter/native/vnc_shim.c",
    '''    free(client->clipboard);
    if (client->password != NULL) {
''',
    '''    vrc_release_clipboard(&client->clipboard, &client->clipboard_length);
    if (client->password != NULL) {
''',
)

insert_before_once(
    "tests/test_native_contract.py",
    '''    def test_native_smoke_is_bounded_and_uses_file_mounted_password(self):
''',
    '''    def test_project_owned_native_clipboard_buffers_are_scrubbed_before_free(self):
        source = SHIM_SOURCE.read_text(encoding="utf-8")

        helper_start = source.index("static void vrc_release_clipboard")
        helper_end = source.index("static char *vrc_duplicate", helper_start)
        helper = source[helper_start:helper_end]
        self.assertIn("vrc_secure_scrub(*clipboard, *length + 1U);", helper)
        self.assertLess(helper.index("vrc_secure_scrub"), helper.index("free(*clipboard)"))

        store_start = source.index("static void vrc_store_clipboard")
        store_end = source.index("static void vrc_got_clipboard", store_start)
        store = source[store_start:store_end]
        self.assertLess(store.index("clipboard revision overflow"), store.index("copy = malloc"))
        self.assertIn(
            "vrc_release_clipboard(&client->clipboard, &client->clipboard_length);",
            store,
        )

        send_start = source.index("vrc_status vrc_client_send_clipboard")
        send_end = source.index("vrc_status vrc_client_dimensions", send_start)
        send = source[send_start:send_end]
        self.assertIn("vrc_secure_scrub(copy, text_length + 1U);", send)
        self.assertLess(send.index("vrc_secure_scrub"), send.index("free(copy)"))

        destroy_start = source.index("void vrc_client_destroy")
        destroy = source[destroy_start:]
        self.assertIn(
            "vrc_release_clipboard(&client->clipboard, &client->clipboard_length);",
            destroy,
        )

''',
)

replace_once(
    "tests/test_documentation_contract.py",
    '''    "websocket_capacity",
    "screenshot_busy",
''',
    '''    "websocket_capacity",
    "event_sequence_exhausted",
    "screenshot_busy",
''',
)
replace_once(
    "tests/test_documentation_contract.py",
    '''        self.assertIn("code: 1013", source)
        self.assertIn("code: 1001", source)
        self.assertIn("`1013`", document)
        self.assertIn("`1001`", document)
        self.assertIn("client event buffer exhausted", document)
        self.assertIn("client heartbeat timeout", document)
''',
    '''        self.assertIn("code: 1013", source)
        self.assertIn("code: 1011", source)
        self.assertIn("code: 1001", source)
        self.assertIn("`1013`", document)
        self.assertIn("`1011`", document)
        self.assertIn("`1001`", document)
        self.assertIn("client event buffer exhausted", document)
        self.assertIn("event sequence exhausted", document)
        self.assertIn("client heartbeat timeout", document)
''',
)

replace_once(
    "docs/openapi.json",
    '''            "description": "Configured WebSocket client capacity is exhausted.",
''',
    '''            "description": "Configured WebSocket client capacity or the process-local event sequence is exhausted.",
''',
)
replace_once(
    "docs/openapi.json",
    '''              "websocket_capacity",
              "screenshot_busy",
''',
    '''              "websocket_capacity",
              "event_sequence_exhausted",
              "screenshot_busy",
''',
)

replace_once(
    "docs/WEBSOCKET_EVENTS.md",
    '''| `1001` | `event source stopped` | Worker event source stopped during controller shutdown or failure. |
| `1013` | `client event buffer exhausted` | Client was too slow and lagged beyond its bounded event buffer. |

A client-capacity rejection occurs before upgrade and returns HTTP `503` with error code `websocket_capacity`.
''',
    '''| `1001` | `event source stopped` | Worker event source stopped during controller shutdown or failure. |
| `1011` | `event sequence exhausted` | The process-local sequence cannot allocate another unique event ID. |
| `1013` | `client event buffer exhausted` | Client was too slow and lagged beyond its bounded event buffer. |

A client-capacity rejection occurs before upgrade and returns HTTP `503` with error code `websocket_capacity`. If the initial snapshot cannot allocate a unique sequence, the controller releases the client permit and returns HTTP `503` with error code `event_sequence_exhausted` before upgrade. Existing clients close with `1011` no later than the next bounded heartbeat wake-up. The sequence never wraps, resets, saturates, or reuses an earlier value.
''',
)

replace_once(
    "SECURITY.md",
    '''API bearer-token storage and constant-time comparison are unchanged in this pass. Moving the API token to the shared zeroizing abstraction is a deferred follow-up so that this correctness repair does not mix authentication behavior changes into the shutdown and worker-state work.
''',
    '''## API bearer-token lifecycle

The process-wide API token is held by an explicit `ApiToken` handle backed by `Arc<SecretString>`. Cloning controller or router state clones only the shared owner; it does not clone token bytes into an ordinary `String` or `Arc<str>`. The token type implements neither `Debug` nor `Display`, and the HTTP authentication boundary exposes only borrowed bytes for constant-time comparison. When the final owner is dropped, `SecretString` overwrites its live string bytes with volatile writes before releasing the allocation.

This is a project-owned live-buffer guarantee, not a claim that process crashes, core dumps, kernel memory, allocator metadata, reverse proxies, clients, or request-header storage contain no residual token bytes. Operators must still disable core dumps where appropriate, protect process memory, terminate TLS at a trusted boundary, and prevent authorization-header logging outside the controller.

## Secret-file rejection lifecycle

The filesystem reader checks metadata, regular-file status, size, and Unix permissions before reading. After reading, UTF-8 validation and CR/LF trimming operate on one owned byte vector. Invalid UTF-8, empty-after-trim, embedded NUL, and future parser rejection paths overwrite the complete live vector with volatile writes before returning a redaction-safe error. Successful parsing transfers the same allocation into `SecretString`; trailing CR/LF bytes are scrubbed before truncation.

## Clipboard buffer lifecycle

Project-owned native C clipboard allocations are scrubbed before replacement and destruction using the same volatile-byte primitive as the VNC password. The temporary outbound C copy passed to `SendClientCutText` is scrubbed before free on both success and failure. The stored payload length is retained so scrubbing covers the allocation through its terminating NUL.

This guarantee does not cover Rust clipboard request/response values, Axum response bodies, LibVNCClient-owned copies, the VNC server, the desktop test application, toolkit or OS clipboard managers, client applications, allocator residuals, swap, or crash dumps. Clipboard contents remain sensitive product data and must never be logged.
''',
)

replace_once(
    "docs/OPERATOR_GUIDE.md",
    '''The API accepts UTF-8 clipboard strings up to 1 MiB and rejects embedded NUL bytes. RFB clipboard transport is a byte-oriented legacy channel; inbound bytes must form valid UTF-8 or the adapter rejects the update. Applications and desktop toolkits may normalize line endings or provide clipboard updates only after an explicit copy operation.
''',
    '''The API accepts UTF-8 clipboard strings up to 1 MiB and rejects embedded NUL bytes. RFB clipboard transport is a byte-oriented legacy channel; inbound bytes must form valid UTF-8 or the adapter rejects the update. Applications and desktop toolkits may normalize line endings or provide clipboard updates only after an explicit copy operation.

The native shim scrubs its project-owned stored clipboard allocation before replacement or destruction and scrubs its temporary outbound send copy before free. This does not prove that Rust request or response values, LibVNCClient, the VNC server, desktop applications, toolkit or OS clipboard managers, clients, allocators, swap, or crash dumps have no residual copies.
''',
)
replace_once(
    "docs/OPERATOR_GUIDE.md",
    '''The first text frame is a `snapshot`. Later payload-free events report connection-state transitions, framebuffer revisions or invalidation, clipboard revisions, overload, and protocol errors. The server sends WebSocket ping frames; clients must remain responsive. Slow or idle clients are disconnected within configured bounds.
''',
    '''The first text frame is a `snapshot`. Later payload-free events report connection-state transitions, framebuffer revisions or invalidation, clipboard revisions, overload, and protocol errors. The server sends WebSocket ping frames; clients must remain responsive. Slow or idle clients are disconnected within configured bounds.

Event sequences never wrap, reset, saturate silently, or reuse an earlier value. If sequence allocation is exhausted before the initial snapshot, the controller releases the client slot and returns `503 event_sequence_exhausted` before upgrade. Existing clients close with WebSocket code `1011` and reason `event sequence exhausted` no later than the next heartbeat wake-up.
''',
)

notes = ROOT / "docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_RECOVERY_IMPLEMENTATION_NOTES_2026-08-06.md"
notes.write_text(
    '''# VNC Remote Control Server Post-Correctness Hardening Recovery Implementation Notes

Date: 2026-08-06

Starting partial SHA: `100e4454634a577bf5ffd7b0dbc8913cf5a60cea`

This recovery audited the eight partial Rust commits rather than accepting them as completion evidence.

Implemented repairs:

- removed broad ordinary-string conversion and exposure helpers from `ApiToken`;
- made router construction accept the explicit token type directly;
- changed secret parsing to validate borrowed bytes, preserve the full rejection buffer, scrub with volatile writes, and transfer the successful allocation without an extra plaintext copy;
- made EventHub exhaustion logging one-shot and kept allocation fail-closed;
- proved the failed initial WebSocket snapshot releases its client permit;
- retained the CR12 mismatched-frame negative proof and matching-frame positive control;
- retained required `HttpBackend` command metric methods;
- scrubbed project-owned native clipboard storage before replacement/destruction and outbound send copies before free;
- moved clipboard revision-overflow rejection before allocation and replacement;
- documented and tested the exact project-owned clipboard and secret boundaries;
- added `event_sequence_exhausted` to OpenAPI and WebSocket documentation.

The clipboard guarantee is deliberately narrow. It does not cover Rust HTTP values, LibVNCClient, VNC servers, desktop applications, toolkits, OS clipboard managers, clients, allocators, swap, or crash dumps.

Exact permanent workflow run IDs are recorded only after the final repository tip completes CI and Release Gates.
''',
    encoding="utf-8",
)

for temporary in (
    ROOT / ".github/post-correctness-recovery.py",
    ROOT / ".github/workflows/post-correctness-recovery.yml",
):
    temporary.unlink()

use super::backend::HttpBackend;
use super::ids::RequestId;
use super::middleware::{AccessLogContext, REQUEST_ID_HEADER, format_access_log};
use super::router::router;
use super::state::HttpState;
use super::support::bearer_matches;
use crate::config::ApiToken;
use crate::framebuffer::FramebufferMetadata;
use crate::framebuffer::FramebufferStatus;
use crate::screenshot::{ScreenshotError, ScreenshotOutcome};
use crate::worker::WorkerSnapshot;
use axum::body::{Body, to_bytes};
use axum::http::header::{AUTHORIZATION, CONTENT_TYPE, ETAG, IF_NONE_MATCH};
use axum::http::{HeaderValue, Request as HttpRequest, StatusCode};
use libvnc_adapter::SecretString;
use remote_desktop_core::{ClipboardSnapshot, ConnectionState, DesktopError, WorkerCommand};
use serde_json::Value;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, UNIX_EPOCH};
use tower::ServiceExt;

mod access_log_and_validation;
mod commands;
mod display_and_screenshot;
mod health;
mod privacy;

#[derive(Debug, Clone, Copy)]
pub(super) enum MockScreenshot {
    Png,
    NotModified,
    Unavailable,
}

pub(super) struct MockBackend {
    snapshot: WorkerSnapshot,
    framebuffer: FramebufferMetadata,
    screenshot: Mutex<MockScreenshot>,
    pub(super) commands: Mutex<Vec<WorkerCommand>>,
    pub(super) execute_error: Mutex<Option<DesktopError>>,
    pub(super) clipboard: Mutex<Option<ClipboardSnapshot>>,
    next_command_id: AtomicU64,
    command_submissions_in_flight: usize,
    command_queue_capacity: usize,
}

impl HttpBackend for MockBackend {
    fn snapshot(&self) -> WorkerSnapshot {
        self.snapshot.clone()
    }

    fn framebuffer_metadata(&self) -> FramebufferMetadata {
        self.framebuffer
    }

    fn capture_screenshot(
        &self,
        _if_none_match: Option<&str>,
    ) -> Result<ScreenshotOutcome, ScreenshotError> {
        let screenshot = *self
            .screenshot
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        let headers = crate::screenshot::ScreenshotHeaders {
            etag: "\"test-7\"".to_owned(),
            content_type: "image/png",
            cache_control: "private, no-cache, max-age=0",
        };
        match screenshot {
            MockScreenshot::Png => Ok(ScreenshotOutcome::Png {
                headers,
                width: 2,
                height: 2,
                revision: 7,
                bytes: vec![137, 80, 78, 71],
            }),
            MockScreenshot::NotModified => Ok(ScreenshotOutcome::NotModified { headers }),
            MockScreenshot::Unavailable => Err(ScreenshotError::Framebuffer(
                crate::framebuffer::FramebufferError::Unavailable,
            )),
        }
    }

    fn execute_command(
        &self,
        command: WorkerCommand,
        _timeout: Duration,
    ) -> Result<u64, DesktopError> {
        if let Some(error) = self
            .execute_error
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .clone()
        {
            return Err(error);
        }
        self.commands
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .push(command);
        Ok(self.next_command_id.fetch_add(1, Ordering::Relaxed))
    }

    fn clipboard_snapshot(&self) -> Result<ClipboardSnapshot, DesktopError> {
        self.clipboard
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .clone()
            .ok_or(DesktopError::ClipboardUnavailable)
    }

    fn command_submissions_in_flight(&self) -> usize {
        self.command_submissions_in_flight
    }

    fn command_queue_capacity(&self) -> usize {
        self.command_queue_capacity
    }
}

pub(super) fn test_state_with_backend(
    ready: bool,
    screenshot: MockScreenshot,
) -> (HttpState, Arc<MockBackend>) {
    let now = UNIX_EPOCH + Duration::from_secs(100);
    let backend = Arc::new(MockBackend {
        snapshot: WorkerSnapshot {
            state: if ready {
                ConnectionState::Connected
            } else {
                ConnectionState::Connecting
            },
            started_at: now,
            connected_at: ready.then_some(now),
            last_message_at: ready.then_some(now),
            reconnect_attempts: 0,
            last_failure: None,
            framebuffer_revision: ready.then_some(7),
            rejected_commands: 0,
            dropped_events: 0,
            fatal_exit: false,
        },
        framebuffer: FramebufferMetadata {
            status: if ready {
                FramebufferStatus::Current
            } else {
                FramebufferStatus::Unavailable
            },
            width: ready.then_some(2),
            height: ready.then_some(2),
            revision: if ready { 7 } else { 0 },
            updated_at: ready.then_some(now),
        },
        screenshot: Mutex::new(screenshot),
        commands: Mutex::new(Vec::new()),
        execute_error: Mutex::new(None),
        clipboard: Mutex::new(None),
        next_command_id: AtomicU64::new(1),
        command_submissions_in_flight: 3,
        command_queue_capacity: 64,
    });
    let state = HttpState::new(
        backend.clone(),
        ApiToken::from_secret(SecretString::from("test-token")),
        Arc::from("test-process"),
        4096,
        Duration::from_secs(1),
    )
    .expect("valid test state");
    (state, backend)
}

pub(super) fn test_state(ready: bool, screenshot: MockScreenshot) -> HttpState {
    test_state_with_backend(ready, screenshot).0
}

pub(super) fn request(uri: &str) -> axum::http::request::Builder {
    HttpRequest::builder().uri(uri)
}

pub(super) async fn json_body(response: axum::response::Response) -> Value {
    let bytes = to_bytes(response.into_body(), 64 * 1024)
        .await
        .expect("bounded response body");
    serde_json::from_slice(&bytes).expect("JSON response")
}

pub(super) fn authenticated_json_request(
    method: &str,
    uri: &str,
    value: serde_json::Value,
) -> axum::http::Request<Body> {
    request(uri)
        .method(method)
        .header(AUTHORIZATION, "Bearer test-token")
        .header(CONTENT_TYPE, "application/json")
        .body(Body::from(value.to_string()))
        .expect("request")
}

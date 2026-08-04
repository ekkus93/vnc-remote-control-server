//! Bounded PNG screenshot encoding over immutable framebuffer snapshots.
//!
//! Snapshot bytes are cloned by `Arc` before encoding begins, so PNG work never
//! holds the framebuffer lock. Encodes are detached onto bounded worker threads.
//! A timeout returns promptly while the encode permit remains held until that
//! worker actually exits, preventing abandoned work from bypassing concurrency
//! limits.

use crate::framebuffer::{FramebufferError, FramebufferSnapshot, FramebufferStore};
use std::error::Error;
use std::fmt;
use std::sync::mpsc::{RecvTimeoutError, sync_channel};
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread;
use std::time::Duration;

const PNG_CONTENT_TYPE: &str = "image/png";
const PNG_CACHE_CONTROL: &str = "private, no-cache, max-age=0";
const MAX_INSTANCE_ID_BYTES: usize = 64;

/// Screenshot creation failures safe for an API error envelope.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ScreenshotError {
    /// Service capacity, timeout, or process-instance configuration is invalid.
    InvalidConfiguration,
    /// The current framebuffer cannot be served.
    Framebuffer(FramebufferError),
    /// All bounded encode permits are in use.
    Busy,
    /// The encode did not complete before the configured deadline.
    Timeout,
    /// The operating system rejected creation of the bounded encode thread.
    ThreadSpawn,
    /// The maintained PNG encoder rejected the snapshot or failed to write it.
    Encoding,
}

impl fmt::Display for ScreenshotError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::InvalidConfiguration => "invalid screenshot service configuration",
            Self::Framebuffer(error) => return error.fmt(formatter),
            Self::Busy => "screenshot encoder is busy",
            Self::Timeout => "screenshot encoding timed out",
            Self::ThreadSpawn => "screenshot worker could not be started",
            Self::Encoding => "screenshot encoding failed",
        };
        formatter.write_str(message)
    }
}

impl Error for ScreenshotError {}

impl From<FramebufferError> for ScreenshotError {
    fn from(error: FramebufferError) -> Self {
        Self::Framebuffer(error)
    }
}

/// HTTP metadata shared by a PNG response and a conditional `304` response.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ScreenshotHeaders {
    /// Strong entity tag tied to one process instance and framebuffer revision.
    pub etag: String,
    /// PNG response media type.
    pub content_type: &'static str,
    /// Revalidation policy; screenshots are never treated as immutable assets.
    pub cache_control: &'static str,
}

/// Result of evaluating a screenshot request.
pub enum ScreenshotOutcome {
    /// The caller already has the current process-local framebuffer revision.
    NotModified {
        /// Headers that must accompany the `304` response.
        headers: ScreenshotHeaders,
    },
    /// Newly encoded PNG bytes.
    Png {
        /// Headers that must accompany the PNG response.
        headers: ScreenshotHeaders,
        /// Exact framebuffer width encoded into the PNG.
        width: u32,
        /// Exact framebuffer height encoded into the PNG.
        height: u32,
        /// Process-local coherent framebuffer revision.
        revision: u64,
        /// Complete PNG file bytes.
        bytes: Vec<u8>,
    },
}

impl ScreenshotOutcome {
    /// Returns response headers for either outcome.
    pub const fn headers(&self) -> &ScreenshotHeaders {
        match self {
            Self::NotModified { headers } | Self::Png { headers, .. } => headers,
        }
    }
}

trait SnapshotEncoder: Send + Sync {
    fn encode(&self, snapshot: &FramebufferSnapshot) -> Result<Vec<u8>, ScreenshotError>;
}

struct MaintainedPngEncoder;

impl SnapshotEncoder for MaintainedPngEncoder {
    fn encode(&self, snapshot: &FramebufferSnapshot) -> Result<Vec<u8>, ScreenshotError> {
        encode_png(snapshot)
    }
}

struct PermitPool {
    maximum: usize,
    available: Mutex<usize>,
}

impl PermitPool {
    fn new(maximum: usize) -> Result<Arc<Self>, ScreenshotError> {
        if maximum == 0 {
            return Err(ScreenshotError::InvalidConfiguration);
        }
        Ok(Arc::new(Self {
            maximum,
            available: Mutex::new(maximum),
        }))
    }

    fn try_acquire(self: &Arc<Self>) -> Option<EncodePermit> {
        let mut available = lock_unpoisoned(&self.available);
        if *available == 0 {
            return None;
        }
        *available -= 1;
        Some(EncodePermit {
            pool: Arc::clone(self),
        })
    }
}

struct EncodePermit {
    pool: Arc<PermitPool>,
}

impl Drop for EncodePermit {
    fn drop(&mut self) {
        let mut available = lock_unpoisoned(&self.pool.available);
        if *available < self.pool.maximum {
            *available += 1;
        }
    }
}

/// Bounded screenshot service suitable for an HTTP route adapter.
#[derive(Clone)]
pub struct ScreenshotService {
    framebuffer: FramebufferStore,
    process_instance: Arc<str>,
    encode_timeout: Duration,
    permits: Arc<PermitPool>,
    encoder: Arc<dyn SnapshotEncoder>,
}

impl ScreenshotService {
    /// Creates a screenshot service with a stable process-instance identifier.
    ///
    /// The identifier may contain only ASCII letters, digits, `.`, `_`, and
    /// `-`, and is intentionally supplied by process startup so every restart
    /// changes the generated ETag namespace.
    pub fn new(
        framebuffer: FramebufferStore,
        process_instance: &str,
        maximum_concurrent_encodes: usize,
        encode_timeout: Duration,
    ) -> Result<Self, ScreenshotError> {
        Self::with_encoder(
            framebuffer,
            process_instance,
            maximum_concurrent_encodes,
            encode_timeout,
            Arc::new(MaintainedPngEncoder),
        )
    }

    /// Encodes the current coherent framebuffer or returns `NotModified` when
    /// the supplied `If-None-Match` value includes the current strong ETag.
    pub fn capture(
        &self,
        if_none_match: Option<&str>,
    ) -> Result<ScreenshotOutcome, ScreenshotError> {
        let snapshot = self.framebuffer.current_snapshot()?;
        let headers = ScreenshotHeaders {
            etag: etag_for(&self.process_instance, snapshot.revision()),
            content_type: PNG_CONTENT_TYPE,
            cache_control: PNG_CACHE_CONTROL,
        };
        if if_none_match.is_some_and(|value| if_none_match_matches(value, &headers.etag)) {
            return Ok(ScreenshotOutcome::NotModified { headers });
        }

        let permit = self.permits.try_acquire().ok_or(ScreenshotError::Busy)?;
        let encoder = Arc::clone(&self.encoder);
        let width = snapshot.width();
        let height = snapshot.height();
        let revision = snapshot.revision();
        let (sender, receiver) = sync_channel(1);
        thread::Builder::new()
            .name(format!("png-encode-{revision}"))
            .spawn(move || {
                let _permit = permit;
                let result = encoder.encode(&snapshot);
                let _ = sender.send(result);
            })
            .map_err(|_| ScreenshotError::ThreadSpawn)?;

        match receiver.recv_timeout(self.encode_timeout) {
            Ok(Ok(bytes)) => Ok(ScreenshotOutcome::Png {
                headers,
                width,
                height,
                revision,
                bytes,
            }),
            Ok(Err(error)) => Err(error),
            Err(RecvTimeoutError::Timeout) => Err(ScreenshotError::Timeout),
            Err(RecvTimeoutError::Disconnected) => Err(ScreenshotError::Encoding),
        }
    }

    fn with_encoder(
        framebuffer: FramebufferStore,
        process_instance: &str,
        maximum_concurrent_encodes: usize,
        encode_timeout: Duration,
        encoder: Arc<dyn SnapshotEncoder>,
    ) -> Result<Self, ScreenshotError> {
        if !valid_process_instance(process_instance) || encode_timeout.is_zero() {
            return Err(ScreenshotError::InvalidConfiguration);
        }
        Ok(Self {
            framebuffer,
            process_instance: Arc::from(process_instance),
            encode_timeout,
            permits: PermitPool::new(maximum_concurrent_encodes)?,
            encoder,
        })
    }
}

/// Evaluates an HTTP `If-None-Match` value against one current strong ETag.
///
/// Weak validators match for GET-style cache revalidation, as required by the
/// weak comparison semantics of `If-None-Match`.
pub fn if_none_match_matches(header: &str, current_etag: &str) -> bool {
    header.split(',').map(str::trim).any(|candidate| {
        candidate == "*"
            || candidate == current_etag
            || candidate.strip_prefix("W/") == Some(current_etag)
    })
}

fn valid_process_instance(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_INSTANCE_ID_BYTES
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
}

fn etag_for(process_instance: &str, revision: u64) -> String {
    format!("\"{process_instance}-{revision:016x}\"")
}

fn encode_png(snapshot: &FramebufferSnapshot) -> Result<Vec<u8>, ScreenshotError> {
    let mut output = Vec::new();
    {
        let mut encoder = png::Encoder::new(&mut output, snapshot.width(), snapshot.height());
        encoder.set_color(png::ColorType::Rgba);
        encoder.set_depth(png::BitDepth::Eight);
        encoder.set_compression(png::Compression::Fast);
        let mut writer = encoder
            .write_header()
            .map_err(|_| ScreenshotError::Encoding)?;
        writer
            .write_image_data(snapshot.rgba())
            .map_err(|_| ScreenshotError::Encoding)?;
    }
    Ok(output)
}

fn lock_unpoisoned<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::time::Instant;

    fn store_with_pixels() -> FramebufferStore {
        let store = FramebufferStore::default();
        store
            .replace_rgba(2, 1, vec![1, 2, 3, 255, 4, 5, 6, 128])
            .expect("complete frame");
        store
    }

    fn png_bytes(outcome: ScreenshotOutcome) -> Vec<u8> {
        match outcome {
            ScreenshotOutcome::Png { bytes, .. } => bytes,
            ScreenshotOutcome::NotModified { .. } => panic!("expected PNG"),
        }
    }

    #[test]
    fn png_has_exact_dimensions_and_rgba_pixels() {
        let service = ScreenshotService::new(
            store_with_pixels(),
            "test-process",
            1,
            Duration::from_secs(1),
        )
        .expect("service");
        let bytes = png_bytes(service.capture(None).expect("capture"));
        assert_eq!(&bytes[..8], b"\x89PNG\r\n\x1a\n");

        let decoder = png::Decoder::new(Cursor::new(bytes));
        let mut reader = decoder.read_info().expect("PNG header");
        let mut output = vec![0; reader.output_buffer_size().expect("bounded output")];
        let info = reader.next_frame(&mut output).expect("PNG frame");
        assert_eq!(info.width, 2);
        assert_eq!(info.height, 1);
        assert_eq!(info.color_type, png::ColorType::Rgba);
        assert_eq!(info.bit_depth, png::BitDepth::Eight);
        assert_eq!(&output[..info.buffer_size()], &[1, 2, 3, 255, 4, 5, 6, 128]);
    }

    #[test]
    fn conditional_request_returns_not_modified_without_encoding() {
        let service = ScreenshotService::new(
            store_with_pixels(),
            "test-process",
            1,
            Duration::from_secs(1),
        )
        .expect("service");
        let first = service.capture(None).expect("capture");
        let etag = first.headers().etag.clone();
        let second = service
            .capture(Some(&format!("\"other\", W/{etag}")))
            .expect("conditional capture");
        assert!(matches!(second, ScreenshotOutcome::NotModified { .. }));
        assert_eq!(second.headers().content_type, "image/png");
        assert_eq!(
            second.headers().cache_control,
            "private, no-cache, max-age=0"
        );
    }

    struct SlowFirstEncoder {
        calls: AtomicUsize,
    }

    impl SnapshotEncoder for SlowFirstEncoder {
        fn encode(&self, snapshot: &FramebufferSnapshot) -> Result<Vec<u8>, ScreenshotError> {
            if self.calls.fetch_add(1, Ordering::SeqCst) == 0 {
                thread::sleep(Duration::from_millis(40));
            }
            encode_png(snapshot)
        }
    }

    #[test]
    fn timeout_keeps_permit_held_until_abandoned_encode_exits() {
        let encoder = Arc::new(SlowFirstEncoder {
            calls: AtomicUsize::new(0),
        });
        let service = ScreenshotService::with_encoder(
            store_with_pixels(),
            "test-process",
            1,
            Duration::from_millis(5),
            encoder,
        )
        .expect("service");

        let started = Instant::now();
        assert_eq!(service.capture(None).err(), Some(ScreenshotError::Timeout));
        assert!(started.elapsed() < Duration::from_millis(30));
        assert_eq!(service.capture(None).err(), Some(ScreenshotError::Busy));

        thread::sleep(Duration::from_millis(50));
        assert!(matches!(
            service.capture(None),
            Ok(ScreenshotOutcome::Png { .. })
        ));
    }

    #[test]
    fn rejects_invalid_configuration_and_unavailable_frames() {
        assert!(matches!(
            ScreenshotService::new(
                FramebufferStore::default(),
                "bad id",
                1,
                Duration::from_secs(1)
            ),
            Err(ScreenshotError::InvalidConfiguration)
        ));
        let service = ScreenshotService::new(
            FramebufferStore::default(),
            "test-process",
            1,
            Duration::from_secs(1),
        )
        .expect("service");
        assert_eq!(
            service.capture(None).err(),
            Some(ScreenshotError::Framebuffer(FramebufferError::Unavailable))
        );
    }

    #[test]
    fn etags_change_with_process_instance_and_revision() {
        let store = store_with_pixels();
        let first = ScreenshotService::new(store.clone(), "process-a", 1, Duration::from_secs(1))
            .expect("service")
            .capture(None)
            .expect("capture")
            .headers()
            .etag
            .clone();
        store
            .replace_rgba(2, 1, vec![6, 5, 4, 255, 3, 2, 1, 255])
            .expect("next frame");
        let second = ScreenshotService::new(store.clone(), "process-a", 1, Duration::from_secs(1))
            .expect("service")
            .capture(None)
            .expect("capture")
            .headers()
            .etag
            .clone();
        let restarted = ScreenshotService::new(store, "process-b", 1, Duration::from_secs(1))
            .expect("service")
            .capture(None)
            .expect("capture")
            .headers()
            .etag
            .clone();
        assert_ne!(first, second);
        assert_ne!(second, restarted);
    }
}

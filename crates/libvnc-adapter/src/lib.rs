//! Narrow safe wrapper around the project-owned LibVNCClient C shim.
//!
//! Raw pointers and foreign calls are confined to this crate. The C shim owns
//! LibVNCClient callbacks and never calls Rust, so Rust panics cannot cross the
//! native callback boundary.

use remote_desktop_core::{Coordinate, DesktopError, KeyboardKey, validate_clipboard};
use std::error::Error;
use std::ffi::{CStr, CString, c_char, c_int, c_uint};
use std::fmt;
use std::ptr::NonNull;
use std::time::Duration;

const STATUS_OK: c_int = 0;
const STATUS_INVALID_ARGUMENT: c_int = 1;
const STATUS_ALLOCATION_FAILED: c_int = 2;
const STATUS_NATIVE_FAILURE: c_int = 3;
const STATUS_TIMEOUT: c_int = 4;
const STATUS_DISCONNECTED: c_int = 5;
const STATUS_FRAMEBUFFER_UNAVAILABLE: c_int = 6;
const STATUS_BUFFER_TOO_SMALL: c_int = 7;
const STATUS_CLIPBOARD_UNAVAILABLE: c_int = 8;

#[repr(C)]
struct VrcClient {
    _private: [u8; 0],
}

unsafe extern "C" {
    fn vrc_client_create(
        host: *const c_char,
        port: c_int,
        password: *const c_char,
        connect_timeout_seconds: c_uint,
        read_timeout_seconds: c_uint,
    ) -> *mut VrcClient;
    fn vrc_client_connect(client: *mut VrcClient) -> c_int;
    fn vrc_client_poll(client: *mut VrcClient, timeout_microseconds: c_uint) -> c_int;
    fn vrc_client_request_full_refresh(client: *mut VrcClient) -> c_int;
    fn vrc_client_send_pointer(
        client: *mut VrcClient,
        x: c_int,
        y: c_int,
        button_mask: c_int,
    ) -> c_int;
    fn vrc_client_send_key(client: *mut VrcClient, keysym: u32, pressed: c_int) -> c_int;
    fn vrc_client_send_clipboard(
        client: *mut VrcClient,
        text: *const c_char,
        text_length: usize,
    ) -> c_int;
    fn vrc_client_dimensions(
        client: *const VrcClient,
        width: *mut u32,
        height: *mut u32,
        revision: *mut u64,
        complete: *mut c_int,
    ) -> c_int;
    fn vrc_client_framebuffer_length(client: *const VrcClient, length: *mut usize) -> c_int;
    fn vrc_client_copy_framebuffer(
        client: *const VrcClient,
        destination: *mut u8,
        destination_length: usize,
        revision: *mut u64,
    ) -> c_int;
    fn vrc_client_clipboard_length(
        client: *const VrcClient,
        length: *mut usize,
        revision: *mut u64,
    ) -> c_int;
    fn vrc_client_copy_clipboard(
        client: *const VrcClient,
        destination: *mut c_char,
        destination_length: usize,
        revision: *mut u64,
    ) -> c_int;
    fn vrc_client_protocol_major(client: *const VrcClient) -> c_int;
    fn vrc_client_last_error(client: *const VrcClient) -> *const c_char;
    fn vrc_client_destroy(client: *mut VrcClient);
}

/// Configuration copied into one native client.
#[derive(Clone, PartialEq, Eq)]
pub struct NativeClientConfig {
    /// VNC server hostname on the private deployment network.
    pub host: String,
    /// Raw VNC TCP port.
    pub port: u16,
    /// VNC password. `Debug` is intentionally not implemented.
    pub password: String,
    /// Connect timeout in whole seconds.
    pub connect_timeout: Duration,
    /// Read timeout in whole seconds.
    pub read_timeout: Duration,
}

/// Bounded native adapter failures that do not contain credentials or payloads.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum NativeError {
    /// A public argument violated the native boundary contract.
    InvalidArgument,
    /// Native allocation failed.
    AllocationFailed,
    /// LibVNCClient reported a bounded native failure.
    NativeFailure {
        /// Bounded message produced only by the project-owned shim.
        message: String,
    },
    /// The transport is disconnected.
    Disconnected,
    /// No complete framebuffer is available.
    FramebufferUnavailable,
    /// A destination buffer was smaller than the reported source size.
    BufferTooSmall,
    /// No inbound clipboard value has been observed.
    ClipboardUnavailable,
    /// Native clipboard bytes were not valid UTF-8.
    ClipboardNotUtf8,
    /// A configuration string contained an embedded NUL.
    EmbeddedNul,
}

impl fmt::Display for NativeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidArgument => formatter.write_str("native argument rejected"),
            Self::AllocationFailed => formatter.write_str("native allocation failed"),
            Self::NativeFailure { message } => {
                write!(formatter, "native VNC operation failed: {message}")
            }
            Self::Disconnected => formatter.write_str("native VNC transport is disconnected"),
            Self::FramebufferUnavailable => {
                formatter.write_str("native framebuffer is unavailable")
            }
            Self::BufferTooSmall => formatter.write_str("native destination buffer is too small"),
            Self::ClipboardUnavailable => formatter.write_str("native clipboard is unavailable"),
            Self::ClipboardNotUtf8 => formatter.write_str("native clipboard is not valid UTF-8"),
            Self::EmbeddedNul => {
                formatter.write_str("native configuration contains an embedded NUL")
            }
        }
    }
}

impl Error for NativeError {}

impl From<NativeError> for DesktopError {
    fn from(error: NativeError) -> Self {
        match error {
            NativeError::InvalidArgument | NativeError::EmbeddedNul => {
                Self::Configuration("native adapter rejected configuration".to_owned())
            }
            NativeError::AllocationFailed
            | NativeError::NativeFailure { .. }
            | NativeError::BufferTooSmall
            | NativeError::ClipboardNotUtf8 => Self::Native,
            NativeError::Disconnected => Self::Transport,
            NativeError::FramebufferUnavailable => Self::FramebufferUnavailable,
            NativeError::ClipboardUnavailable => Self::ClipboardUnavailable,
        }
    }
}

/// Result of one bounded native poll.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PollOutcome {
    /// One server message was processed.
    MessageProcessed,
    /// No message arrived before the requested poll timeout.
    TimedOut,
}

/// Metadata read from the native framebuffer state.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NativeDisplayInfo {
    /// Width in pixels.
    pub width: u32,
    /// Height in pixels.
    pub height: u32,
    /// Native framebuffer revision.
    pub revision: u64,
    /// Whether a complete update has been processed.
    pub complete: bool,
}

/// Coherent raw 32-bit framebuffer copy from the native shim.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NativeFramebuffer {
    /// Width in pixels.
    pub width: u32,
    /// Height in pixels.
    pub height: u32,
    /// Native framebuffer revision.
    pub revision: u64,
    /// Raw LibVNCClient bytes. Canonical RGBA conversion is a later layer.
    pub bytes: Vec<u8>,
}

/// Last inbound clipboard copy.
#[derive(Clone, PartialEq, Eq)]
pub struct NativeClipboard {
    /// UTF-8 clipboard text. `Debug` is intentionally not implemented.
    pub text: String,
    /// Native clipboard revision.
    pub revision: u64,
}

/// One exclusively owned LibVNCClient connection.
pub struct NativeClient {
    pointer: NonNull<VrcClient>,
}

impl NativeClient {
    /// Allocates and authenticates one native VNC client.
    pub fn connect(config: &NativeClientConfig) -> Result<Self, NativeError> {
        let host = CString::new(config.host.as_str()).map_err(|_| NativeError::EmbeddedNul)?;
        let password =
            CString::new(config.password.as_str()).map_err(|_| NativeError::EmbeddedNul)?;
        let connect_timeout = whole_seconds(config.connect_timeout)?;
        let read_timeout = whole_seconds(config.read_timeout)?;

        // SAFETY: both C strings remain valid for the call; the shim copies them.
        let pointer = unsafe {
            vrc_client_create(
                host.as_ptr(),
                c_int::from(config.port),
                password.as_ptr(),
                connect_timeout,
                read_timeout,
            )
        };
        let pointer = NonNull::new(pointer).ok_or(NativeError::AllocationFailed)?;
        let client = Self { pointer };

        // SAFETY: `client` exclusively owns the live opaque handle.
        let status = unsafe { vrc_client_connect(client.pointer.as_ptr()) };
        client.status_to_result(status)?;
        Ok(client)
    }

    /// Returns the LibVNCClient version resolved by `pkg-config` at build time.
    pub const fn library_version() -> &'static str {
        env!("VRC_LIBVNCCLIENT_VERSION")
    }

    /// Returns the negotiated RFB protocol major version.
    pub fn protocol_major(&self) -> i32 {
        // SAFETY: the opaque handle is live for `self`.
        unsafe { vrc_client_protocol_major(self.pointer.as_ptr()) }
    }

    /// Processes at most one server message within a bounded wait.
    pub fn poll(&mut self, timeout: Duration) -> Result<PollOutcome, NativeError> {
        let microseconds =
            u32::try_from(timeout.as_micros()).map_err(|_| NativeError::InvalidArgument)?;
        // SAFETY: mutable access guarantees exclusive native use.
        let status = unsafe { vrc_client_poll(self.pointer.as_ptr(), microseconds) };
        match status {
            STATUS_OK => Ok(PollOutcome::MessageProcessed),
            STATUS_TIMEOUT => Ok(PollOutcome::TimedOut),
            other => Err(self.error_for_status(other)),
        }
    }

    /// Requests one non-incremental full framebuffer update.
    pub fn request_full_refresh(&mut self) -> Result<(), NativeError> {
        // SAFETY: mutable access guarantees exclusive native use.
        let status = unsafe { vrc_client_request_full_refresh(self.pointer.as_ptr()) };
        self.status_to_result(status)
    }

    /// Sends one pointer event with the complete current RFB button mask.
    pub fn send_pointer(
        &mut self,
        coordinate: Coordinate,
        button_mask: u8,
    ) -> Result<(), NativeError> {
        let x = i32::try_from(coordinate.x).map_err(|_| NativeError::InvalidArgument)?;
        let y = i32::try_from(coordinate.y).map_err(|_| NativeError::InvalidArgument)?;
        // SAFETY: mutable access guarantees exclusive native use.
        let status = unsafe {
            vrc_client_send_pointer(self.pointer.as_ptr(), x, y, c_int::from(button_mask))
        };
        self.status_to_result(status)
    }

    /// Sends one symbolic key transition.
    pub fn send_key(&mut self, key: KeyboardKey, pressed: bool) -> Result<(), NativeError> {
        let pressed = if pressed { 1 } else { 0 };
        // SAFETY: mutable access guarantees exclusive native use.
        let status = unsafe { vrc_client_send_key(self.pointer.as_ptr(), key.keysym(), pressed) };
        self.status_to_result(status)
    }

    /// Sends preflight-validated outbound clipboard text.
    pub fn send_clipboard(&mut self, text: &str) -> Result<(), NativeError> {
        validate_clipboard(text).map_err(|_| NativeError::InvalidArgument)?;
        // SAFETY: the byte slice remains valid for the duration of the call; the shim copies it.
        let status = unsafe {
            vrc_client_send_clipboard(
                self.pointer.as_ptr(),
                text.as_ptr().cast::<c_char>(),
                text.len(),
            )
        };
        self.status_to_result(status)
    }

    /// Reads current native display metadata.
    pub fn display_info(&self) -> Result<NativeDisplayInfo, NativeError> {
        let mut width = 0_u32;
        let mut height = 0_u32;
        let mut revision = 0_u64;
        let mut complete = 0_c_int;
        // SAFETY: output pointers are valid and the opaque handle is live.
        let status = unsafe {
            vrc_client_dimensions(
                self.pointer.as_ptr(),
                &mut width,
                &mut height,
                &mut revision,
                &mut complete,
            )
        };
        self.status_to_result(status)?;
        Ok(NativeDisplayInfo {
            width,
            height,
            revision,
            complete: complete != 0,
        })
    }

    /// Copies one coherent complete raw native framebuffer.
    pub fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {
        let display = self.display_info()?;
        let mut length = 0_usize;
        // SAFETY: output pointer is valid and the opaque handle is live.
        let status = unsafe { vrc_client_framebuffer_length(self.pointer.as_ptr(), &mut length) };
        self.status_to_result(status)?;
        let mut bytes = vec![0_u8; length];
        let mut revision = 0_u64;
        // SAFETY: destination spans exactly `length` initialized writable bytes.
        let status = unsafe {
            vrc_client_copy_framebuffer(
                self.pointer.as_ptr(),
                bytes.as_mut_ptr(),
                bytes.len(),
                &mut revision,
            )
        };
        self.status_to_result(status)?;
        if revision != display.revision {
            return Err(NativeError::NativeFailure {
                message: "framebuffer revision changed during copy".to_owned(),
            });
        }
        Ok(NativeFramebuffer {
            width: display.width,
            height: display.height,
            revision,
            bytes,
        })
    }

    /// Copies the last inbound UTF-8 clipboard value.
    pub fn clipboard(&self) -> Result<NativeClipboard, NativeError> {
        let mut length = 0_usize;
        let mut announced_revision = 0_u64;
        // SAFETY: output pointers are valid and the opaque handle is live.
        let status = unsafe {
            vrc_client_clipboard_length(self.pointer.as_ptr(), &mut length, &mut announced_revision)
        };
        self.status_to_result(status)?;
        let capacity = length.checked_add(1).ok_or(NativeError::AllocationFailed)?;
        let mut bytes = vec![0_u8; capacity];
        let mut revision = 0_u64;
        // SAFETY: destination spans `capacity` initialized writable bytes.
        let status = unsafe {
            vrc_client_copy_clipboard(
                self.pointer.as_ptr(),
                bytes.as_mut_ptr().cast::<c_char>(),
                bytes.len(),
                &mut revision,
            )
        };
        self.status_to_result(status)?;
        if revision != announced_revision {
            return Err(NativeError::NativeFailure {
                message: "clipboard revision changed during copy".to_owned(),
            });
        }
        bytes.truncate(length);
        let text = String::from_utf8(bytes).map_err(|_| NativeError::ClipboardNotUtf8)?;
        Ok(NativeClipboard { text, revision })
    }

    fn status_to_result(&self, status: c_int) -> Result<(), NativeError> {
        if status == STATUS_OK {
            Ok(())
        } else {
            Err(self.error_for_status(status))
        }
    }

    fn error_for_status(&self, status: c_int) -> NativeError {
        match status {
            STATUS_INVALID_ARGUMENT => NativeError::InvalidArgument,
            STATUS_ALLOCATION_FAILED => NativeError::AllocationFailed,
            STATUS_NATIVE_FAILURE => NativeError::NativeFailure {
                message: self.last_error(),
            },
            STATUS_DISCONNECTED => NativeError::Disconnected,
            STATUS_FRAMEBUFFER_UNAVAILABLE => NativeError::FramebufferUnavailable,
            STATUS_BUFFER_TOO_SMALL => NativeError::BufferTooSmall,
            STATUS_CLIPBOARD_UNAVAILABLE => NativeError::ClipboardUnavailable,
            STATUS_TIMEOUT => NativeError::NativeFailure {
                message: "unexpected timeout status".to_owned(),
            },
            _ => NativeError::NativeFailure {
                message: "unknown native status".to_owned(),
            },
        }
    }

    fn last_error(&self) -> String {
        // SAFETY: the shim returns a NUL-terminated string owned by the live handle.
        let pointer = unsafe { vrc_client_last_error(self.pointer.as_ptr()) };
        if pointer.is_null() {
            return "native adapter did not provide an error".to_owned();
        }
        // SAFETY: non-null pointer is guaranteed NUL-terminated by the shim.
        let value = unsafe { CStr::from_ptr(pointer) };
        value.to_string_lossy().into_owned()
    }
}

impl Drop for NativeClient {
    fn drop(&mut self) {
        // SAFETY: this is the sole destruction path for the exclusively owned handle.
        unsafe { vrc_client_destroy(self.pointer.as_ptr()) };
    }
}

fn whole_seconds(duration: Duration) -> Result<c_uint, NativeError> {
    let seconds = duration.as_secs();
    if seconds == 0 || duration.subsec_nanos() != 0 {
        return Err(NativeError::InvalidArgument);
    }
    c_uint::try_from(seconds).map_err(|_| NativeError::InvalidArgument)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn native_library_version_is_recorded() {
        assert!(!NativeClient::library_version().is_empty());
    }

    #[test]
    fn timeouts_must_be_nonzero_whole_seconds() {
        assert_eq!(
            whole_seconds(Duration::ZERO),
            Err(NativeError::InvalidArgument)
        );
        assert_eq!(
            whole_seconds(Duration::from_millis(1500)),
            Err(NativeError::InvalidArgument)
        );
        assert_eq!(whole_seconds(Duration::from_secs(3)), Ok(3));
    }

    #[test]
    fn native_configuration_rejects_embedded_nul_without_connecting() {
        let config = NativeClientConfig {
            host: "desk\0top".to_owned(),
            port: 5901,
            password: "secret".to_owned(),
            connect_timeout: Duration::from_secs(2),
            read_timeout: Duration::from_secs(2),
        };
        assert!(matches!(
            NativeClient::connect(&config),
            Err(NativeError::EmbeddedNul)
        ));
    }
}

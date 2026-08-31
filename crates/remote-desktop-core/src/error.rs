use thiserror::Error;

/// Public domain error taxonomy, independent from HTTP.
#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum DesktopError {
    /// The current display dimensions are not known.
    #[error("display dimensions are unavailable")]
    DisplayUnavailable,
    /// A coordinate was outside the current display.
    #[error("coordinate ({x}, {y}) is outside {width}x{height}")]
    InvalidCoordinate {
        /// Requested horizontal coordinate.
        x: u32,
        /// Requested vertical coordinate.
        y: u32,
        /// Current display width.
        width: u32,
        /// Current display height.
        height: u32,
    },
    /// A rectangle is invalid for the current display.
    #[error("framebuffer rectangle is outside the display")]
    InvalidRectangle,
    /// Framebuffer dimensions are zero, overflow, or exceed the configured bound.
    #[error("invalid framebuffer dimensions")]
    InvalidFramebufferDimensions,
    /// A chord exceeds the configured maximum.
    #[error("key chord exceeds {maximum} keys")]
    ChordTooLong {
        /// Configured maximum key count.
        maximum: usize,
    },
    /// Text exceeds the configured maximum UTF-8 byte length.
    #[error("text exceeds {maximum} bytes")]
    TextTooLarge {
        /// Configured maximum byte count.
        maximum: usize,
    },
    /// Clipboard text exceeds the configured maximum UTF-8 byte length.
    #[error("clipboard exceeds {maximum} bytes")]
    ClipboardTooLarge {
        /// Configured maximum byte count.
        maximum: usize,
    },
    /// Text contains a character outside the supported v0.1 set.
    #[error("unsupported text character at index {index}: U+{codepoint:04X}")]
    UnsupportedTextCharacter {
        /// Character index, not UTF-8 byte offset.
        index: usize,
        /// Unicode scalar value.
        codepoint: u32,
    },
    /// Clipboard content contains an embedded NUL.
    #[error("clipboard contains an embedded NUL byte")]
    ClipboardContainsNul,
    /// A scroll delta exceeds the bounded step count.
    #[error("scroll delta exceeds {maximum} steps")]
    ScrollTooLarge {
        /// Configured maximum absolute step count.
        maximum: i32,
    },
    /// The bounded worker command queue is full.
    #[error("command queue is full")]
    CommandQueueFull,
    /// The bounded command-outcome registry cannot retain another unresolved command.
    #[error("command outcome capacity is full")]
    CommandOutcomeCapacityFull,
    /// The process-local command identifier sequence is permanently exhausted.
    #[error("command identifier sequence is exhausted")]
    CommandIdExhausted,
    /// The worker is shutting down or has stopped.
    #[error("desktop worker is unavailable")]
    WorkerUnavailable,
    /// No complete framebuffer is currently available.
    #[error("framebuffer is unavailable")]
    FramebufferUnavailable,
    /// No inbound clipboard value has been observed.
    #[error("clipboard is unavailable")]
    ClipboardUnavailable,
    /// An operation exceeded its deadline.
    #[error("operation timed out")]
    Timeout,
    /// A reconnect request was rate limited.
    #[error("reconnect request is rate limited")]
    ReconnectRateLimited,
    /// Configuration is invalid.
    #[error("invalid configuration: {0}")]
    Configuration(String),
    /// VNC authentication failed.
    #[error("VNC authentication failed")]
    AuthenticationFailed,
    /// VNC transport failed.
    #[error("VNC transport failed")]
    Transport,
    /// The remote peer violated the protocol contract.
    #[error("VNC protocol error")]
    Protocol,
    /// A native adapter operation failed without exposing payload data.
    #[error("native VNC adapter error")]
    Native,
}

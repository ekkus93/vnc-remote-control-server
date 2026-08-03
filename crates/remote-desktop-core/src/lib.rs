//! Domain types and validation for the VNC remote control server.
#![forbid(unsafe_code)]

use serde::{Deserialize, Serialize};
use std::fmt;
use std::sync::Arc;
use std::time::SystemTime;
use thiserror::Error;

/// The canonical v0.1 display width.
pub const DEFAULT_DISPLAY_WIDTH: u32 = 1_280;
/// The canonical v0.1 display height.
pub const DEFAULT_DISPLAY_HEIGHT: u32 = 800;
/// Bytes per pixel in the canonical RGBA8 framebuffer.
pub const RGBA_BYTES_PER_PIXEL: usize = 4;
/// Maximum number of keys accepted in one chord.
pub const MAX_CHORD_KEYS: usize = 16;
/// Maximum UTF-8 byte length accepted by text input.
pub const MAX_TEXT_BYTES: usize = 16 * 1_024;
/// Maximum UTF-8 byte length accepted by clipboard input.
pub const MAX_CLIPBOARD_BYTES: usize = 1024 * 1024;
/// Maximum absolute wheel steps accepted by one request.
pub const MAX_SCROLL_STEPS: i32 = 100;
/// Maximum allowed framebuffer allocation in bytes.
pub const MAX_FRAMEBUFFER_BYTES: usize = 64 * 1024 * 1024;

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

/// Current display metadata.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct DisplayInfo {
    /// Width in pixels.
    pub width: u32,
    /// Height in pixels.
    pub height: u32,
    /// Color depth reported by the deployment contract.
    pub depth: u8,
    /// Process-local framebuffer revision.
    pub revision: u64,
    /// Whether the framebuffer represents a complete current frame.
    pub complete: bool,
}

impl DisplayInfo {
    /// Creates validated display metadata.
    pub fn new(
        width: u32,
        height: u32,
        depth: u8,
        revision: u64,
        complete: bool,
    ) -> Result<Self, DesktopError> {
        checked_rgba_len(width, height)?;
        if depth == 0 {
            return Err(DesktopError::InvalidFramebufferDimensions);
        }
        Ok(Self {
            width,
            height,
            depth,
            revision,
            complete,
        })
    }

    /// Validates coordinates against this display.
    pub fn validate_coordinate(self, x: u32, y: u32) -> Result<Coordinate, DesktopError> {
        Coordinate::new(x, y, self)
    }
}

/// A coordinate that has been validated against a display.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Coordinate {
    /// Horizontal coordinate.
    pub x: u32,
    /// Vertical coordinate.
    pub y: u32,
}

impl Coordinate {
    /// Creates a coordinate only when it is inside `display`.
    pub fn new(x: u32, y: u32, display: DisplayInfo) -> Result<Self, DesktopError> {
        if x >= display.width || y >= display.height {
            return Err(DesktopError::InvalidCoordinate {
                x,
                y,
                width: display.width,
                height: display.height,
            });
        }
        Ok(Self { x, y })
    }
}

/// A framebuffer rectangle with checked bounds.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FramebufferRect {
    /// Horizontal origin.
    pub x: u32,
    /// Vertical origin.
    pub y: u32,
    /// Rectangle width.
    pub width: u32,
    /// Rectangle height.
    pub height: u32,
}

impl FramebufferRect {
    /// Creates a non-empty rectangle contained in `display`.
    pub fn new(
        x: u32,
        y: u32,
        width: u32,
        height: u32,
        display: DisplayInfo,
    ) -> Result<Self, DesktopError> {
        if width == 0 || height == 0 {
            return Err(DesktopError::InvalidRectangle);
        }
        let right = x.checked_add(width).ok_or(DesktopError::InvalidRectangle)?;
        let bottom = y
            .checked_add(height)
            .ok_or(DesktopError::InvalidRectangle)?;
        if right > display.width || bottom > display.height {
            return Err(DesktopError::InvalidRectangle);
        }
        Ok(Self {
            x,
            y,
            width,
            height,
        })
    }
}

/// Computes a bounded RGBA8 allocation length.
pub fn checked_rgba_len(width: u32, height: u32) -> Result<usize, DesktopError> {
    if width == 0 || height == 0 {
        return Err(DesktopError::InvalidFramebufferDimensions);
    }
    let pixels = usize::try_from(width)
        .ok()
        .and_then(|w| usize::try_from(height).ok().and_then(|h| w.checked_mul(h)))
        .ok_or(DesktopError::InvalidFramebufferDimensions)?;
    let bytes = pixels
        .checked_mul(RGBA_BYTES_PER_PIXEL)
        .ok_or(DesktopError::InvalidFramebufferDimensions)?;
    if bytes > MAX_FRAMEBUFFER_BYTES {
        return Err(DesktopError::InvalidFramebufferDimensions);
    }
    Ok(bytes)
}

/// Supported mouse buttons.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MouseButton {
    /// Primary button.
    Left,
    /// Middle button.
    Middle,
    /// Secondary button.
    Right,
}

impl MouseButton {
    /// Returns the RFB pointer mask bit.
    pub const fn rfb_mask(self) -> u8 {
        match self {
            Self::Left => 1,
            Self::Middle => 2,
            Self::Right => 4,
        }
    }
}

/// Key transition requested by the public API.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum KeyAction {
    /// Press the key.
    Down,
    /// Release the key.
    Up,
}

/// Stable symbolic keyboard keys exposed by v0.1.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum KeyboardKey {
    /// Left Control.
    CtrlLeft,
    /// Left Alt.
    AltLeft,
    /// Left Shift.
    ShiftLeft,
    /// Left Meta/Super.
    MetaLeft,
    /// Enter/Return.
    Enter,
    /// Tab.
    Tab,
    /// Escape.
    Escape,
    /// Backspace.
    Backspace,
    /// Delete.
    Delete,
    /// Home.
    Home,
    /// End.
    End,
    /// Page Up.
    PageUp,
    /// Page Down.
    PageDown,
    /// Up arrow.
    ArrowUp,
    /// Down arrow.
    ArrowDown,
    /// Left arrow.
    ArrowLeft,
    /// Right arrow.
    ArrowRight,
    /// Function key F1.
    F1,
    /// Function key F2.
    F2,
    /// Function key F3.
    F3,
    /// Function key F4.
    F4,
    /// Function key F5.
    F5,
    /// Function key F6.
    F6,
    /// Function key F7.
    F7,
    /// Function key F8.
    F8,
    /// Function key F9.
    F9,
    /// Function key F10.
    F10,
    /// Function key F11.
    F11,
    /// Function key F12.
    F12,
    /// Printable ASCII character used in a chord.
    Printable(char),
}

impl KeyboardKey {
    /// Returns the corresponding X11 keysym.
    pub const fn keysym(self) -> u32 {
        match self {
            Self::CtrlLeft => 0xFFE3,
            Self::AltLeft => 0xFFE9,
            Self::ShiftLeft => 0xFFE1,
            Self::MetaLeft => 0xFFEB,
            Self::Enter => 0xFF0D,
            Self::Tab => 0xFF09,
            Self::Escape => 0xFF1B,
            Self::Backspace => 0xFF08,
            Self::Delete => 0xFFFF,
            Self::Home => 0xFF50,
            Self::End => 0xFF57,
            Self::PageUp => 0xFF55,
            Self::PageDown => 0xFF56,
            Self::ArrowUp => 0xFF52,
            Self::ArrowDown => 0xFF54,
            Self::ArrowLeft => 0xFF51,
            Self::ArrowRight => 0xFF53,
            Self::F1 => 0xFFBE,
            Self::F2 => 0xFFBF,
            Self::F3 => 0xFFC0,
            Self::F4 => 0xFFC1,
            Self::F5 => 0xFFC2,
            Self::F6 => 0xFFC3,
            Self::F7 => 0xFFC4,
            Self::F8 => 0xFFC5,
            Self::F9 => 0xFFC6,
            Self::F10 => 0xFFC7,
            Self::F11 => 0xFFC8,
            Self::F12 => 0xFFC9,
            Self::Printable(value) => value as u32,
        }
    }

    /// Parses a stable symbolic key name or one printable ASCII character.
    pub fn parse_name(value: &str) -> Result<Self, DesktopError> {
        let key = match value {
            "CTRL_LEFT" => Self::CtrlLeft,
            "ALT_LEFT" => Self::AltLeft,
            "SHIFT_LEFT" => Self::ShiftLeft,
            "META_LEFT" => Self::MetaLeft,
            "ENTER" => Self::Enter,
            "TAB" => Self::Tab,
            "ESCAPE" => Self::Escape,
            "BACKSPACE" => Self::Backspace,
            "DELETE" => Self::Delete,
            "HOME" => Self::Home,
            "END" => Self::End,
            "PAGE_UP" => Self::PageUp,
            "PAGE_DOWN" => Self::PageDown,
            "ARROW_UP" => Self::ArrowUp,
            "ARROW_DOWN" => Self::ArrowDown,
            "ARROW_LEFT" => Self::ArrowLeft,
            "ARROW_RIGHT" => Self::ArrowRight,
            "F1" => Self::F1,
            "F2" => Self::F2,
            "F3" => Self::F3,
            "F4" => Self::F4,
            "F5" => Self::F5,
            "F6" => Self::F6,
            "F7" => Self::F7,
            "F8" => Self::F8,
            "F9" => Self::F9,
            "F10" => Self::F10,
            "F11" => Self::F11,
            "F12" => Self::F12,
            _ => {
                let mut characters = value.chars();
                match (characters.next(), characters.next()) {
                    (Some(character), None) if character.is_ascii_graphic() || character == ' ' => {
                        Self::Printable(character)
                    }
                    _ => {
                        return Err(DesktopError::Configuration(format!(
                            "unknown symbolic key: {value}"
                        )));
                    }
                }
            }
        };
        Ok(key)
    }
}

impl fmt::Display for KeyboardKey {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Printable(character) => write!(formatter, "{character}"),
            value => write!(formatter, "{value:?}"),
        }
    }
}

/// Externally visible connection states.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ConnectionState {
    /// Worker initialization has begun.
    Starting,
    /// A connection attempt is active.
    Connecting,
    /// The authenticated VNC transport is healthy.
    Connected,
    /// The transport exists but has failed a health condition.
    Degraded,
    /// Automatic reconnection is active.
    Reconnecting,
    /// No transport is active.
    Disconnected,
    /// Authentication failed and retry is backoff-safe.
    AuthenticationFailed,
    /// The worker is stopping or stopped.
    Stopped,
}

impl ConnectionState {
    /// Returns whether a state transition is allowed by the v0.1 lifecycle.
    pub const fn can_transition_to(self, next: Self) -> bool {
        use ConnectionState::{
            AuthenticationFailed, Connected, Connecting, Degraded, Disconnected, Reconnecting,
            Starting, Stopped,
        };
        matches!(
            (self, next),
            (Starting, Connecting)
                | (Starting, Stopped)
                | (Connecting, Connected)
                | (Connecting, AuthenticationFailed)
                | (Connecting, Disconnected)
                | (Connecting, Stopped)
                | (Connected, Degraded)
                | (Connected, Disconnected)
                | (Connected, Reconnecting)
                | (Connected, Stopped)
                | (Degraded, Reconnecting)
                | (Degraded, Disconnected)
                | (Degraded, Stopped)
                | (Disconnected, Reconnecting)
                | (Disconnected, Connecting)
                | (Disconnected, Stopped)
                | (AuthenticationFailed, Reconnecting)
                | (AuthenticationFailed, Stopped)
                | (Reconnecting, Connected)
                | (Reconnecting, AuthenticationFailed)
                | (Reconnecting, Disconnected)
                | (Reconnecting, Stopped)
        ) || self == next
    }
}

/// Immutable current framebuffer data.
#[derive(Debug, Clone)]
pub struct FramebufferSnapshot {
    /// Width in pixels.
    pub width: u32,
    /// Height in pixels.
    pub height: u32,
    /// Process-local revision.
    pub revision: u64,
    /// Whether the image is complete and current.
    pub complete: bool,
    /// Last update time.
    pub updated_at: SystemTime,
    /// Canonical RGBA8 pixels.
    pub rgba: Arc<[u8]>,
}

impl FramebufferSnapshot {
    /// Constructs a validated immutable snapshot.
    pub fn new(
        width: u32,
        height: u32,
        revision: u64,
        complete: bool,
        updated_at: SystemTime,
        rgba: Arc<[u8]>,
    ) -> Result<Self, DesktopError> {
        if rgba.len() != checked_rgba_len(width, height)? {
            return Err(DesktopError::InvalidFramebufferDimensions);
        }
        Ok(Self {
            width,
            height,
            revision,
            complete,
            updated_at,
            rgba,
        })
    }
}

/// Last inbound clipboard snapshot.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ClipboardSnapshot {
    /// UTF-8 clipboard text.
    pub text: Arc<str>,
    /// Process-local clipboard revision.
    pub revision: u64,
    /// Observation time.
    pub updated_at: SystemTime,
}

/// Input and lifecycle commands accepted by the worker.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WorkerCommand {
    /// Move the pointer while preserving the current button mask.
    MovePointer { coordinate: Coordinate },
    /// Set a mouse button state.
    SetButton {
        /// Target coordinate.
        coordinate: Coordinate,
        /// Button.
        button: MouseButton,
        /// Whether the button is pressed.
        pressed: bool,
    },
    /// Send one complete click atomically.
    Click {
        /// Target coordinate.
        coordinate: Coordinate,
        /// Button.
        button: MouseButton,
    },
    /// Send two complete clicks atomically.
    DoubleClick {
        /// Target coordinate.
        coordinate: Coordinate,
        /// Button.
        button: MouseButton,
        /// Interval between clicks.
        interval_ms: u64,
    },
    /// Send bounded horizontal and vertical wheel steps atomically.
    Scroll {
        /// Target coordinate.
        coordinate: Coordinate,
        /// Horizontal signed steps.
        delta_x: i32,
        /// Vertical signed steps.
        delta_y: i32,
    },
    /// Set one key state.
    SetKey {
        /// Symbolic key.
        key: KeyboardKey,
        /// Whether the key is pressed.
        pressed: bool,
    },
    /// Press keys in order and release them in reverse order.
    Chord { keys: Vec<KeyboardKey> },
    /// Enter preflight-validated text.
    TypeText { text: String },
    /// Set outbound clipboard text.
    SetClipboard { text: String },
    /// Request one non-incremental framebuffer refresh.
    RequestFullRefresh,
    /// Request a rate-limited reconnect.
    Reconnect,
    /// Stop the worker.
    Shutdown,
}

/// Public event kinds. Payload text and pixels are intentionally absent.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum DesktopEventKind {
    /// Connection state changed.
    ConnectionState { state: ConnectionState },
    /// A coherent framebuffer revision was committed.
    FramebufferRevision { revision: u64 },
    /// Current framebuffer data became invalid.
    FramebufferInvalidated,
    /// Inbound clipboard revision changed.
    ClipboardRevision { revision: u64 },
    /// A bounded queue rejected work.
    Overload,
    /// A protocol failure occurred.
    ProtocolError,
}

/// Preflight-validates a v0.1 text value.
pub fn validate_text(text: &str) -> Result<usize, DesktopError> {
    if text.len() > MAX_TEXT_BYTES {
        return Err(DesktopError::TextTooLarge {
            maximum: MAX_TEXT_BYTES,
        });
    }
    for (index, character) in text.chars().enumerate() {
        if !(character == '\n'
            || character == '\t'
            || character == '\r'
            || (' '..='~').contains(&character))
        {
            return Err(DesktopError::UnsupportedTextCharacter {
                index,
                codepoint: character as u32,
            });
        }
    }
    Ok(text.chars().count())
}

/// Preflight-validates outbound clipboard text.
pub fn validate_clipboard(text: &str) -> Result<(), DesktopError> {
    if text.len() > MAX_CLIPBOARD_BYTES {
        return Err(DesktopError::ClipboardTooLarge {
            maximum: MAX_CLIPBOARD_BYTES,
        });
    }
    if text.as_bytes().contains(&0) {
        return Err(DesktopError::ClipboardContainsNul);
    }
    Ok(())
}

/// Validates chord length.
pub fn validate_chord(keys: &[KeyboardKey]) -> Result<(), DesktopError> {
    if keys.len() > MAX_CHORD_KEYS {
        return Err(DesktopError::ChordTooLong {
            maximum: MAX_CHORD_KEYS,
        });
    }
    Ok(())
}

/// Validates bounded signed scroll steps.
pub fn validate_scroll(delta_x: i32, delta_y: i32) -> Result<(), DesktopError> {
    if delta_x.unsigned_abs() > MAX_SCROLL_STEPS.unsigned_abs()
        || delta_y.unsigned_abs() > MAX_SCROLL_STEPS.unsigned_abs()
    {
        return Err(DesktopError::ScrollTooLarge {
            maximum: MAX_SCROLL_STEPS,
        });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;

    fn display() -> DisplayInfo {
        DisplayInfo::new(1_280, 800, 24, 1, true).expect("valid display")
    }

    #[test]
    fn coordinate_boundaries_are_strict() {
        assert_eq!(
            Coordinate::new(0, 0, display()).expect("origin is valid"),
            Coordinate { x: 0, y: 0 }
        );
        assert!(Coordinate::new(1_279, 799, display()).is_ok());
        assert!(Coordinate::new(1_280, 799, display()).is_err());
        assert!(Coordinate::new(1_279, 800, display()).is_err());
    }

    #[test]
    fn zero_and_oversized_dimensions_are_rejected() {
        assert!(checked_rgba_len(0, 1).is_err());
        assert!(checked_rgba_len(1, 0).is_err());
        assert!(checked_rgba_len(u32::MAX, u32::MAX).is_err());
    }

    #[test]
    fn mouse_button_deserialization_rejects_unknown_values() {
        let error = serde_json::from_str::<MouseButton>("\"side\"")
            .expect_err("unsupported button must fail");
        assert!(error.to_string().contains("unknown variant"));
    }

    #[test]
    fn symbolic_keys_and_printable_keys_parse() {
        assert_eq!(
            KeyboardKey::parse_name("CTRL_LEFT").expect("known key"),
            KeyboardKey::CtrlLeft
        );
        assert_eq!(
            KeyboardKey::parse_name("A").expect("printable key"),
            KeyboardKey::Printable('A')
        );
        assert!(KeyboardKey::parse_name("NOT_A_KEY").is_err());
    }

    #[test]
    fn chord_text_clipboard_and_scroll_limits_are_enforced() {
        assert!(validate_chord(&[KeyboardKey::Enter; MAX_CHORD_KEYS]).is_ok());
        assert!(validate_chord(&[KeyboardKey::Enter; MAX_CHORD_KEYS + 1]).is_err());
        assert!(validate_text(&"a".repeat(MAX_TEXT_BYTES)).is_ok());
        assert!(validate_text(&"a".repeat(MAX_TEXT_BYTES + 1)).is_err());
        assert!(validate_text("hello\nworld\t").is_ok());
        assert!(validate_text("snowman: ☃").is_err());
        assert!(validate_clipboard(&"x".repeat(MAX_CLIPBOARD_BYTES)).is_ok());
        assert!(validate_clipboard(&"x".repeat(MAX_CLIPBOARD_BYTES + 1)).is_err());
        assert!(validate_clipboard("a\0b").is_err());
        assert!(validate_scroll(MAX_SCROLL_STEPS, -MAX_SCROLL_STEPS).is_ok());
        assert!(validate_scroll(MAX_SCROLL_STEPS + 1, 0).is_err());
    }

    #[test]
    fn connection_transition_contract_is_explicit() {
        assert!(ConnectionState::Starting.can_transition_to(ConnectionState::Connecting));
        assert!(ConnectionState::Connecting.can_transition_to(ConnectionState::Connected));
        assert!(!ConnectionState::Starting.can_transition_to(ConnectionState::Connected));
        assert!(!ConnectionState::Stopped.can_transition_to(ConnectionState::Connecting));
    }

    proptest! {
        #[test]
        fn contained_rectangles_validate(
            x in 0_u32..1_280,
            y in 0_u32..800,
            width in 1_u32..=1_280,
            height in 1_u32..=800,
        ) {
            let expected = x.checked_add(width).is_some_and(|right| right <= 1_280)
                && y.checked_add(height).is_some_and(|bottom| bottom <= 800);
            prop_assert_eq!(FramebufferRect::new(x, y, width, height, display()).is_ok(), expected);
        }

        #[test]
        fn allocation_math_never_wraps(width in any::<u32>(), height in any::<u32>()) {
            if let Ok(length) = checked_rgba_len(width, height) {
                prop_assert!(length <= MAX_FRAMEBUFFER_BYTES);
                prop_assert_eq!(length % RGBA_BYTES_PER_PIXEL, 0);
            }
        }
    }
}

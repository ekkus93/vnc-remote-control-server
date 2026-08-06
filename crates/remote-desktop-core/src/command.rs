use crate::connection::ConnectionState;
use crate::geometry::Coordinate;
use crate::input::{KeyboardKey, MouseButton};
use serde::{Deserialize, Serialize};
use std::fmt;

/// Input and lifecycle commands accepted by the worker.
#[derive(Clone, PartialEq, Eq)]
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

impl fmt::Debug for WorkerCommand {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MovePointer { coordinate } => formatter
                .debug_struct("MovePointer")
                .field("coordinate", coordinate)
                .finish(),
            Self::SetButton {
                coordinate,
                button,
                pressed,
            } => formatter
                .debug_struct("SetButton")
                .field("coordinate", coordinate)
                .field("button", button)
                .field("pressed", pressed)
                .finish(),
            Self::Click { coordinate, button } => formatter
                .debug_struct("Click")
                .field("coordinate", coordinate)
                .field("button", button)
                .finish(),
            Self::DoubleClick {
                coordinate,
                button,
                interval_ms,
            } => formatter
                .debug_struct("DoubleClick")
                .field("coordinate", coordinate)
                .field("button", button)
                .field("interval_ms", interval_ms)
                .finish(),
            Self::Scroll {
                coordinate,
                delta_x,
                delta_y,
            } => formatter
                .debug_struct("Scroll")
                .field("coordinate", coordinate)
                .field("delta_x", delta_x)
                .field("delta_y", delta_y)
                .finish(),
            Self::SetKey { key, pressed } => formatter
                .debug_struct("SetKey")
                .field("key", key)
                .field("pressed", pressed)
                .finish(),
            Self::Chord { keys } => formatter.debug_struct("Chord").field("keys", keys).finish(),
            Self::TypeText { text } => formatter
                .debug_struct("TypeText")
                .field("text_bytes", &text.len())
                .finish(),
            Self::SetClipboard { text } => formatter
                .debug_struct("SetClipboard")
                .field("text_bytes", &text.len())
                .finish(),
            Self::RequestFullRefresh => formatter.write_str("RequestFullRefresh"),
            Self::Reconnect => formatter.write_str("Reconnect"),
            Self::Shutdown => formatter.write_str("Shutdown"),
        }
    }
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

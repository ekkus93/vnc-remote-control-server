//! Domain types and validation for the VNC remote control server.
#![forbid(unsafe_code)]

mod command;
mod connection;
mod error;
mod framebuffer;
mod geometry;
mod input;
#[cfg(test)]
mod tests;
mod validate;

pub use command::{DesktopEventKind, WorkerCommand};
pub use connection::ConnectionState;
pub use error::DesktopError;
pub use framebuffer::{ClipboardSnapshot, FramebufferSnapshot};
pub use geometry::{Coordinate, DisplayInfo, FramebufferRect, checked_rgba_len};
pub use input::{KeyAction, KeyboardKey, MouseButton};
pub use validate::{validate_chord, validate_clipboard, validate_scroll, validate_text};

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

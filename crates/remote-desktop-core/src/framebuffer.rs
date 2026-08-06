use crate::error::DesktopError;
use crate::geometry::checked_rgba_len;
use std::sync::Arc;
use std::time::SystemTime;

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

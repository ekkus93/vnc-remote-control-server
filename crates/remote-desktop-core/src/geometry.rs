use crate::MAX_FRAMEBUFFER_BYTES;
use crate::RGBA_BYTES_PER_PIXEL;
use crate::error::DesktopError;
use serde::{Deserialize, Serialize};

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

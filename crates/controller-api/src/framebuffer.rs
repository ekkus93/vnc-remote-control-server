//! Canonical RGBA8 framebuffer storage and coherent snapshot semantics.
//!
//! The store has one process-local revision sequence. A revision increments
//! exactly once after framebuffer contents or availability become a new coherent
//! frame. Byte-identical commits with unchanged availability keep the existing
//! revision so HTTP validators do not churn on duplicate native updates.
//! Invalidation does not increment the revision; it changes availability to
//! stale so old pixels cannot be served as current.
//! Snapshot creation clones an `Arc` while holding a read lock and releases the
//! lock before callers perform expensive work such as PNG encoding.

use remote_desktop_core::{
    DesktopError, DisplayInfo, FramebufferRect, MAX_FRAMEBUFFER_BYTES, RGBA_BYTES_PER_PIXEL,
    checked_rgba_len,
};
use std::error::Error;
use std::fmt;
use std::sync::{Arc, RwLock, RwLockReadGuard, RwLockWriteGuard};
use std::time::SystemTime;

/// Public framebuffer availability state.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FramebufferStatus {
    /// No dimensions or pixels have been observed.
    Unavailable,
    /// Dimensions exist, but no coherent complete frame is available.
    Incomplete,
    /// Pixels represent the current complete remote framebuffer.
    Current,
    /// Pixels are retained for diagnostics, but the remote connection ended.
    Stale,
}

/// Framebuffer validation and storage failures.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FramebufferError {
    /// Dimensions are zero, overflow, exceed the global limit, or exceed the
    /// configured store limit.
    InvalidDimensions,
    /// A full-frame source buffer has the wrong length.
    InvalidBufferLength,
    /// A dirty update has an invalid row stride or insufficient source bytes.
    InvalidStride,
    /// A dirty rectangle is empty, overflows, or falls outside the display.
    InvalidRectangle,
    /// No complete current frame exists.
    Unavailable,
    /// Retained pixels are stale after disconnect.
    Stale,
    /// A dirty update was requested before dimensions were established.
    DimensionsUnavailable,
    /// A dirty batch contained no updates.
    EmptyUpdate,
    /// The process-local revision counter was exhausted.
    RevisionOverflow,
}

impl fmt::Display for FramebufferError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::InvalidDimensions => "invalid framebuffer dimensions",
            Self::InvalidBufferLength => "invalid framebuffer buffer length",
            Self::InvalidStride => "invalid framebuffer row stride",
            Self::InvalidRectangle => "invalid framebuffer rectangle",
            Self::Unavailable => "framebuffer is unavailable",
            Self::Stale => "framebuffer is stale",
            Self::DimensionsUnavailable => "framebuffer dimensions are unavailable",
            Self::EmptyUpdate => "framebuffer update batch is empty",
            Self::RevisionOverflow => "framebuffer revision overflow",
        };
        formatter.write_str(message)
    }
}

impl Error for FramebufferError {}

impl From<FramebufferError> for DesktopError {
    fn from(error: FramebufferError) -> Self {
        match error {
            FramebufferError::InvalidDimensions | FramebufferError::InvalidBufferLength => {
                Self::InvalidFramebufferDimensions
            }
            FramebufferError::InvalidStride
            | FramebufferError::InvalidRectangle
            | FramebufferError::EmptyUpdate => Self::InvalidRectangle,
            FramebufferError::Unavailable
            | FramebufferError::Stale
            | FramebufferError::DimensionsUnavailable => Self::FramebufferUnavailable,
            FramebufferError::RevisionOverflow => Self::Protocol,
        }
    }
}

/// One owned RGBA8 dirty rectangle.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DirtyRectangle {
    /// Destination rectangle in the current framebuffer.
    pub rect: FramebufferRect,
    /// Source row stride in bytes.
    pub row_stride: usize,
    /// Source RGBA8 bytes.
    pub rgba: Vec<u8>,
}

impl DirtyRectangle {
    /// Creates a dirty update after validating stride and source length.
    pub fn new(
        rect: FramebufferRect,
        row_stride: usize,
        rgba: Vec<u8>,
    ) -> Result<Self, FramebufferError> {
        validate_dirty_source(rect, row_stride, rgba.len())?;
        Ok(Self {
            rect,
            row_stride,
            rgba,
        })
    }
}

/// Immutable coherent framebuffer snapshot.
#[derive(Clone)]
pub struct FramebufferSnapshot {
    width: u32,
    height: u32,
    revision: u64,
    updated_at: SystemTime,
    rgba: Arc<[u8]>,
}

impl FramebufferSnapshot {
    /// Snapshot width in pixels.
    pub const fn width(&self) -> u32 {
        self.width
    }

    /// Snapshot height in pixels.
    pub const fn height(&self) -> u32 {
        self.height
    }

    /// Process-local coherent framebuffer revision.
    pub const fn revision(&self) -> u64 {
        self.revision
    }

    /// Time at which this revision committed.
    pub const fn updated_at(&self) -> SystemTime {
        self.updated_at
    }

    /// Immutable canonical RGBA8 pixels.
    pub fn rgba(&self) -> &[u8] {
        &self.rgba
    }

    /// Validated display metadata for this snapshot.
    pub fn display_info(&self) -> DisplayInfo {
        DisplayInfo {
            width: self.width,
            height: self.height,
            depth: 24,
            revision: self.revision,
            complete: true,
        }
    }
}

/// Coherent metadata available without copying pixel bytes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FramebufferMetadata {
    /// Current availability state.
    pub status: FramebufferStatus,
    /// Known width, when dimensions have been observed.
    pub width: Option<u32>,
    /// Known height, when dimensions have been observed.
    pub height: Option<u32>,
    /// Last committed process-local revision.
    pub revision: u64,
    /// Time of the most recent coherent pixel commit.
    pub updated_at: Option<SystemTime>,
}

#[derive(Clone)]
struct StoredFrame {
    status: FramebufferStatus,
    width: Option<u32>,
    height: Option<u32>,
    revision: u64,
    updated_at: Option<SystemTime>,
    rgba: Arc<[u8]>,
}

impl Default for StoredFrame {
    fn default() -> Self {
        Self {
            status: FramebufferStatus::Unavailable,
            width: None,
            height: None,
            revision: 0,
            updated_at: None,
            rgba: Arc::from([]),
        }
    }
}

/// Thread-safe canonical framebuffer store.
#[derive(Clone)]
pub struct FramebufferStore {
    maximum_bytes: usize,
    inner: Arc<RwLock<StoredFrame>>,
}

impl FramebufferStore {
    /// Creates a store with a configured bound no larger than the global limit.
    pub fn new(maximum_bytes: usize) -> Result<Self, FramebufferError> {
        if maximum_bytes == 0 || maximum_bytes > MAX_FRAMEBUFFER_BYTES {
            return Err(FramebufferError::InvalidDimensions);
        }
        Ok(Self {
            maximum_bytes,
            inner: Arc::new(RwLock::new(StoredFrame::default())),
        })
    }

    /// Returns a coherent metadata snapshot.
    pub fn metadata(&self) -> FramebufferMetadata {
        let current = read_unpoisoned(&self.inner);
        FramebufferMetadata {
            status: current.status,
            width: current.width,
            height: current.height,
            revision: current.revision,
            updated_at: current.updated_at,
        }
    }

    /// Establishes dimensions while explicitly withholding complete-frame
    /// availability.
    pub fn begin_incomplete(&self, width: u32, height: u32) -> Result<(), FramebufferError> {
        let length = self.validate_dimensions(width, height)?;
        let mut current = write_unpoisoned(&self.inner);
        current.status = FramebufferStatus::Incomplete;
        current.width = Some(width);
        current.height = Some(height);
        current.rgba = vec![0_u8; length].into();
        Ok(())
    }

    /// Replaces the current frame from the selected native RGBX byte layout.
    ///
    /// The native adapter currently supports little-endian Linux and requests
    /// 32-bit true-color pixels with red, green, and blue in the first three
    /// bytes. The unused fourth byte is replaced with opaque alpha.
    pub fn replace_native_rgbx(
        &self,
        width: u32,
        height: u32,
        rgbx: &[u8],
    ) -> Result<u64, FramebufferError> {
        let length = self.validate_dimensions(width, height)?;
        if rgbx.len() != length {
            return Err(FramebufferError::InvalidBufferLength);
        }
        let mut rgba = Vec::with_capacity(length);
        for pixel in rgbx.chunks_exact(RGBA_BYTES_PER_PIXEL) {
            rgba.extend_from_slice(&[pixel[0], pixel[1], pixel[2], u8::MAX]);
        }
        self.replace_rgba(width, height, rgba)
    }

    /// Replaces the current frame with one complete canonical RGBA8 image.
    ///
    /// A byte-identical replacement for an already-current frame returns the
    /// existing revision without updating timestamps or advancing validators.
    pub fn replace_rgba(
        &self,
        width: u32,
        height: u32,
        rgba: Vec<u8>,
    ) -> Result<u64, FramebufferError> {
        let length = self.validate_dimensions(width, height)?;
        if rgba.len() != length {
            return Err(FramebufferError::InvalidBufferLength);
        }
        let mut current = write_unpoisoned(&self.inner);
        if current.status == FramebufferStatus::Current
            && current.width == Some(width)
            && current.height == Some(height)
            && current.rgba.as_ref() == rgba.as_slice()
        {
            return Ok(current.revision);
        }
        let revision = next_revision(current.revision)?;
        current.status = FramebufferStatus::Current;
        current.width = Some(width);
        current.height = Some(height);
        current.revision = revision;
        current.updated_at = Some(SystemTime::now());
        current.rgba = rgba.into();
        Ok(revision)
    }

    /// Atomically applies a batch of canonical RGBA8 dirty rectangles.
    ///
    /// All rectangles are validated before the coherent replacement becomes
    /// visible. The batch increments the revision exactly once when pixels or
    /// availability change. A byte-identical dirty batch for the current
    /// availability state returns the existing revision without updating
    /// timestamps or advancing validators.
    pub fn commit_dirty(
        &self,
        updates: &[DirtyRectangle],
        complete: bool,
    ) -> Result<u64, FramebufferError> {
        if updates.is_empty() {
            return Err(FramebufferError::EmptyUpdate);
        }
        let mut current = write_unpoisoned(&self.inner);
        let width = current
            .width
            .ok_or(FramebufferError::DimensionsUnavailable)?;
        let height = current
            .height
            .ok_or(FramebufferError::DimensionsUnavailable)?;
        if matches!(
            current.status,
            FramebufferStatus::Unavailable | FramebufferStatus::Stale
        ) {
            return Err(FramebufferError::DimensionsUnavailable);
        }
        let expected_length = self.validate_dimensions(width, height)?;
        if current.rgba.len() != expected_length {
            return Err(FramebufferError::InvalidBufferLength);
        }

        for update in updates {
            validate_rect_for_dimensions(update.rect, width, height)?;
            validate_dirty_source(update.rect, update.row_stride, update.rgba.len())?;
        }

        let mut next_pixels = current.rgba.to_vec();
        let destination_stride = usize::try_from(width)
            .ok()
            .and_then(|value| value.checked_mul(RGBA_BYTES_PER_PIXEL))
            .ok_or(FramebufferError::InvalidDimensions)?;
        for update in updates {
            copy_dirty_rectangle(&mut next_pixels, destination_stride, update)?;
        }

        let target_status = if complete {
            FramebufferStatus::Current
        } else {
            FramebufferStatus::Incomplete
        };
        if current.status == target_status && next_pixels.as_slice() == current.rgba.as_ref() {
            return Ok(current.revision);
        }

        let revision = next_revision(current.revision)?;
        current.status = target_status;
        current.revision = revision;
        current.updated_at = Some(SystemTime::now());
        current.rgba = next_pixels.into();
        Ok(revision)
    }

    /// Returns a current complete immutable snapshot.
    pub fn current_snapshot(&self) -> Result<FramebufferSnapshot, FramebufferError> {
        let current = read_unpoisoned(&self.inner);
        match current.status {
            FramebufferStatus::Current => {
                let width = current
                    .width
                    .ok_or(FramebufferError::DimensionsUnavailable)?;
                let height = current
                    .height
                    .ok_or(FramebufferError::DimensionsUnavailable)?;
                let updated_at = current.updated_at.ok_or(FramebufferError::Unavailable)?;
                Ok(FramebufferSnapshot {
                    width,
                    height,
                    revision: current.revision,
                    updated_at,
                    rgba: Arc::clone(&current.rgba),
                })
            }
            FramebufferStatus::Stale => Err(FramebufferError::Stale),
            FramebufferStatus::Unavailable | FramebufferStatus::Incomplete => {
                Err(FramebufferError::Unavailable)
            }
        }
    }

    /// Marks retained pixels stale after connection loss.
    ///
    /// The last revision and pixels remain available only through metadata and
    /// internal diagnostics; `current_snapshot` fails closed.
    pub fn invalidate(&self) -> bool {
        let mut current = write_unpoisoned(&self.inner);
        let changed = matches!(
            current.status,
            FramebufferStatus::Current | FramebufferStatus::Incomplete
        );
        if changed {
            current.status = FramebufferStatus::Stale;
        }
        changed
    }

    /// Removes dimensions and retained pixels without resetting the monotonic
    /// revision sequence.
    pub fn clear(&self) {
        let mut current = write_unpoisoned(&self.inner);
        current.status = FramebufferStatus::Unavailable;
        current.width = None;
        current.height = None;
        current.updated_at = None;
        current.rgba = Arc::from([]);
    }

    fn validate_dimensions(&self, width: u32, height: u32) -> Result<usize, FramebufferError> {
        let length =
            checked_rgba_len(width, height).map_err(|_| FramebufferError::InvalidDimensions)?;
        if length > self.maximum_bytes {
            return Err(FramebufferError::InvalidDimensions);
        }
        Ok(length)
    }
}

impl Default for FramebufferStore {
    fn default() -> Self {
        Self::new(MAX_FRAMEBUFFER_BYTES).expect("global framebuffer limit is valid")
    }
}

fn validate_rect_for_dimensions(
    rect: FramebufferRect,
    width: u32,
    height: u32,
) -> Result<(), FramebufferError> {
    if rect.width == 0 || rect.height == 0 {
        return Err(FramebufferError::InvalidRectangle);
    }
    let right = rect
        .x
        .checked_add(rect.width)
        .ok_or(FramebufferError::InvalidRectangle)?;
    let bottom = rect
        .y
        .checked_add(rect.height)
        .ok_or(FramebufferError::InvalidRectangle)?;
    if right > width || bottom > height {
        return Err(FramebufferError::InvalidRectangle);
    }
    Ok(())
}

fn validate_dirty_source(
    rect: FramebufferRect,
    row_stride: usize,
    source_length: usize,
) -> Result<(), FramebufferError> {
    let row_bytes = usize::try_from(rect.width)
        .ok()
        .and_then(|value| value.checked_mul(RGBA_BYTES_PER_PIXEL))
        .ok_or(FramebufferError::InvalidRectangle)?;
    if row_stride < row_bytes {
        return Err(FramebufferError::InvalidStride);
    }
    let rows_before_last = usize::try_from(rect.height.saturating_sub(1))
        .map_err(|_| FramebufferError::InvalidRectangle)?;
    let required = rows_before_last
        .checked_mul(row_stride)
        .and_then(|value| value.checked_add(row_bytes))
        .ok_or(FramebufferError::InvalidStride)?;
    if source_length < required {
        return Err(FramebufferError::InvalidStride);
    }
    Ok(())
}

fn copy_dirty_rectangle(
    destination: &mut [u8],
    destination_stride: usize,
    update: &DirtyRectangle,
) -> Result<(), FramebufferError> {
    let x_bytes = usize::try_from(update.rect.x)
        .ok()
        .and_then(|value| value.checked_mul(RGBA_BYTES_PER_PIXEL))
        .ok_or(FramebufferError::InvalidRectangle)?;
    let row_bytes = usize::try_from(update.rect.width)
        .ok()
        .and_then(|value| value.checked_mul(RGBA_BYTES_PER_PIXEL))
        .ok_or(FramebufferError::InvalidRectangle)?;
    for row in 0..update.rect.height {
        let row = usize::try_from(row).map_err(|_| FramebufferError::InvalidRectangle)?;
        let destination_start = usize::try_from(update.rect.y)
            .ok()
            .and_then(|value| value.checked_add(row))
            .and_then(|value| value.checked_mul(destination_stride))
            .and_then(|value| value.checked_add(x_bytes))
            .ok_or(FramebufferError::InvalidRectangle)?;
        let destination_end = destination_start
            .checked_add(row_bytes)
            .ok_or(FramebufferError::InvalidRectangle)?;
        let source_start = row
            .checked_mul(update.row_stride)
            .ok_or(FramebufferError::InvalidStride)?;
        let source_end = source_start
            .checked_add(row_bytes)
            .ok_or(FramebufferError::InvalidStride)?;
        let destination_row = destination
            .get_mut(destination_start..destination_end)
            .ok_or(FramebufferError::InvalidRectangle)?;
        let source_row = update
            .rgba
            .get(source_start..source_end)
            .ok_or(FramebufferError::InvalidStride)?;
        destination_row.copy_from_slice(source_row);
    }
    Ok(())
}

fn next_revision(current: u64) -> Result<u64, FramebufferError> {
    current
        .checked_add(1)
        .ok_or(FramebufferError::RevisionOverflow)
}

fn read_unpoisoned<T>(lock: &RwLock<T>) -> RwLockReadGuard<'_, T> {
    lock.read().unwrap_or_else(|poisoned| poisoned.into_inner())
}

fn write_unpoisoned<T>(lock: &RwLock<T>) -> RwLockWriteGuard<'_, T> {
    lock.write()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Barrier;
    use std::thread;

    fn display(width: u32, height: u32) -> DisplayInfo {
        DisplayInfo::new(width, height, 24, 0, false).expect("valid display")
    }

    fn pixel(snapshot: &FramebufferSnapshot, x: u32, y: u32) -> &[u8] {
        let offset = (usize::try_from(y).expect("y")
            * usize::try_from(snapshot.width()).expect("width")
            + usize::try_from(x).expect("x"))
            * RGBA_BYTES_PER_PIXEL;
        &snapshot.rgba()[offset..offset + RGBA_BYTES_PER_PIXEL]
    }

    fn solid(width: u32, height: u32, value: u8) -> Vec<u8> {
        vec![value; checked_rgba_len(width, height).expect("valid length")]
    }

    #[test]
    fn native_rgbx_conversion_forces_opaque_alpha() {
        let store = FramebufferStore::new(16).expect("store");
        let revision = store
            .replace_native_rgbx(2, 1, &[1, 2, 3, 0, 4, 5, 6, 17])
            .expect("replace");
        assert_eq!(revision, 1);
        assert_eq!(
            store.current_snapshot().expect("snapshot").rgba(),
            &[1, 2, 3, 255, 4, 5, 6, 255]
        );
    }

    #[test]
    fn configured_memory_limit_is_enforced_at_boundary() {
        let store = FramebufferStore::new(16).expect("store");
        assert!(store.replace_rgba(2, 2, solid(2, 2, 1)).is_ok());
        assert_eq!(
            store.replace_rgba(3, 2, solid(3, 2, 1)),
            Err(FramebufferError::InvalidDimensions)
        );
    }

    #[test]
    fn incomplete_and_stale_frames_fail_closed() {
        let store = FramebufferStore::default();
        assert_eq!(
            store.current_snapshot().err(),
            Some(FramebufferError::Unavailable)
        );
        store.begin_incomplete(2, 2).expect("dimensions");
        assert_eq!(store.metadata().status, FramebufferStatus::Incomplete);
        assert_eq!(
            store.current_snapshot().err(),
            Some(FramebufferError::Unavailable)
        );
        store.replace_rgba(2, 2, solid(2, 2, 2)).expect("complete");
        assert!(store.invalidate());
        assert_eq!(store.metadata().status, FramebufferStatus::Stale);
        assert_eq!(
            store.current_snapshot().err(),
            Some(FramebufferError::Stale)
        );
    }

    #[test]
    fn dirty_batch_updates_all_four_edges_once() {
        let store = FramebufferStore::default();
        store
            .replace_rgba(4, 4, solid(4, 4, 0))
            .expect("initial frame");
        let updates = [
            DirtyRectangle::new(
                FramebufferRect::new(0, 0, 1, 1, display(4, 4)).expect("top left"),
                4,
                vec![1, 0, 0, 255],
            )
            .expect("update"),
            DirtyRectangle::new(
                FramebufferRect::new(3, 0, 1, 1, display(4, 4)).expect("top right"),
                4,
                vec![2, 0, 0, 255],
            )
            .expect("update"),
            DirtyRectangle::new(
                FramebufferRect::new(0, 3, 1, 1, display(4, 4)).expect("bottom left"),
                4,
                vec![3, 0, 0, 255],
            )
            .expect("update"),
            DirtyRectangle::new(
                FramebufferRect::new(3, 3, 1, 1, display(4, 4)).expect("bottom right"),
                4,
                vec![4, 0, 0, 255],
            )
            .expect("update"),
        ];
        assert_eq!(store.commit_dirty(&updates, true).expect("commit"), 2);
        let snapshot = store.current_snapshot().expect("snapshot");
        assert_eq!(pixel(&snapshot, 0, 0), &[1, 0, 0, 255]);
        assert_eq!(pixel(&snapshot, 3, 0), &[2, 0, 0, 255]);
        assert_eq!(pixel(&snapshot, 0, 3), &[3, 0, 0, 255]);
        assert_eq!(pixel(&snapshot, 3, 3), &[4, 0, 0, 255]);
        assert_eq!(snapshot.revision(), 2);
    }

    #[test]
    fn malformed_overflow_and_out_of_bounds_rectangles_are_rejected() {
        let store = FramebufferStore::default();
        store.begin_incomplete(4, 4).expect("dimensions");
        for rect in [
            FramebufferRect {
                x: u32::MAX,
                y: 0,
                width: 2,
                height: 1,
            },
            FramebufferRect {
                x: 4,
                y: 0,
                width: 1,
                height: 1,
            },
            FramebufferRect {
                x: 0,
                y: 0,
                width: 0,
                height: 1,
            },
        ] {
            let update = DirtyRectangle {
                rect,
                row_stride: 8,
                rgba: vec![0; 8],
            };
            assert_eq!(
                store.commit_dirty(&[update], true),
                Err(FramebufferError::InvalidRectangle)
            );
        }
    }

    #[test]
    fn dirty_source_stride_and_length_are_checked() {
        let rect = FramebufferRect::new(0, 0, 2, 2, display(2, 2)).expect("rect");
        assert_eq!(
            DirtyRectangle::new(rect, 7, vec![0; 16]),
            Err(FramebufferError::InvalidStride)
        );
        assert_eq!(
            DirtyRectangle::new(rect, 8, vec![0; 15]),
            Err(FramebufferError::InvalidStride)
        );
        assert!(DirtyRectangle::new(rect, 12, vec![0; 20]).is_ok());
    }

    #[test]
    fn snapshots_are_immutable_across_later_commits() {
        let store = FramebufferStore::default();
        store.replace_rgba(2, 2, solid(2, 2, 1)).expect("first");
        let first = store.current_snapshot().expect("first snapshot");
        store.replace_rgba(2, 2, solid(2, 2, 2)).expect("second");
        let second = store.current_snapshot().expect("second snapshot");
        assert!(first.rgba().iter().all(|value| *value == 1));
        assert!(second.rgba().iter().all(|value| *value == 2));
        assert_eq!(first.revision(), 1);
        assert_eq!(second.revision(), 2);
    }

    #[test]
    fn identical_full_frame_replacement_keeps_revision_and_timestamp() {
        let store = FramebufferStore::default();
        assert_eq!(store.replace_rgba(2, 2, solid(2, 2, 7)), Ok(1));
        let first = store.current_snapshot().expect("first snapshot");
        assert_eq!(store.replace_rgba(2, 2, solid(2, 2, 7)), Ok(1));
        let second = store.current_snapshot().expect("second snapshot");
        assert_eq!(second.revision(), first.revision());
        assert_eq!(second.updated_at(), first.updated_at());
        assert_eq!(second.rgba(), first.rgba());
    }

    #[test]
    fn identical_dirty_update_keeps_revision_and_timestamp_when_status_unchanged() {
        let store = FramebufferStore::default();
        assert_eq!(store.replace_rgba(2, 2, solid(2, 2, 7)), Ok(1));
        let first = store.current_snapshot().expect("first snapshot");
        let update = DirtyRectangle::new(
            FramebufferRect::new(0, 0, 1, 1, display(2, 2)).expect("rect"),
            4,
            vec![7, 7, 7, 7],
        )
        .expect("update");
        assert_eq!(store.commit_dirty(&[update], true), Ok(1));
        let second = store.current_snapshot().expect("second snapshot");
        assert_eq!(second.revision(), first.revision());
        assert_eq!(second.updated_at(), first.updated_at());
        assert_eq!(second.rgba(), first.rgba());
    }

    #[test]
    fn changed_dirty_update_advances_revision() {
        let store = FramebufferStore::default();
        assert_eq!(store.replace_rgba(2, 2, solid(2, 2, 7)), Ok(1));
        let update = DirtyRectangle::new(
            FramebufferRect::new(1, 1, 1, 1, display(2, 2)).expect("rect"),
            4,
            vec![8, 8, 8, 8],
        )
        .expect("update");
        assert_eq!(store.commit_dirty(&[update], true), Ok(2));
        let snapshot = store.current_snapshot().expect("snapshot");
        assert_eq!(snapshot.revision(), 2);
        assert_eq!(pixel(&snapshot, 1, 1), &[8, 8, 8, 8]);
    }

    #[test]
    fn dirty_update_completing_incomplete_frame_advances_even_with_identical_pixels() {
        let store = FramebufferStore::default();
        store.begin_incomplete(1, 1).expect("dimensions");
        let update = DirtyRectangle::new(
            FramebufferRect::new(0, 0, 1, 1, display(1, 1)).expect("rect"),
            4,
            vec![0, 0, 0, 0],
        )
        .expect("update");
        assert_eq!(store.commit_dirty(&[update], true), Ok(1));
        let snapshot = store.current_snapshot().expect("snapshot");
        assert_eq!(snapshot.revision(), 1);
        assert_eq!(snapshot.rgba(), &[0, 0, 0, 0]);
    }

    #[test]
    fn reconnect_commit_keeps_revision_monotonic() {
        let store = FramebufferStore::default();
        assert_eq!(store.replace_rgba(1, 1, vec![1, 1, 1, 255]), Ok(1));
        assert!(store.invalidate());
        assert_eq!(store.replace_rgba(1, 1, vec![2, 2, 2, 255]), Ok(2));
    }

    #[test]
    fn concurrent_snapshots_never_observe_partial_commits() {
        let store = FramebufferStore::default();
        store.replace_rgba(8, 8, solid(8, 8, 0)).expect("initial");
        let start = Arc::new(Barrier::new(2));
        let writer_store = store.clone();
        let writer_start = Arc::clone(&start);
        let writer = thread::spawn(move || {
            writer_start.wait();
            for value in 1..=100_u8 {
                writer_store
                    .replace_rgba(8, 8, solid(8, 8, value))
                    .expect("replace");
            }
        });
        start.wait();
        while !writer.is_finished() {
            let snapshot = store.current_snapshot().expect("snapshot");
            let first = snapshot.rgba()[0];
            assert!(snapshot.rgba().iter().all(|value| *value == first));
        }
        writer.join().expect("writer joins");
        let snapshot = store.current_snapshot().expect("final snapshot");
        assert!(snapshot.rgba().iter().all(|value| *value == 100));
        assert_eq!(snapshot.revision(), 101);
    }
}

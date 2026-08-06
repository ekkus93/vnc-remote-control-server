use crate::MAX_CHORD_KEYS;
use crate::MAX_CLIPBOARD_BYTES;
use crate::MAX_SCROLL_STEPS;
use crate::MAX_TEXT_BYTES;
use crate::error::DesktopError;
use crate::input::KeyboardKey;

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

use crate::error::DesktopError;
use serde::{Deserialize, Serialize};
use std::fmt;

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

//! Stable JSON request types for the public v0.1 API.
//!
//! Keyboard keys are represented as one JSON string. Symbolic keys use the
//! documented screaming-snake-case names, while printable chord keys use one
//! printable ASCII character. Raw numeric keysyms and Serde's derived enum
//! object representation are intentionally not part of the public contract.
//!
//! Text input accepts horizontal tab, carriage return, line feed, and printable
//! ASCII (`U+0020` through `U+007E`). Clipboard input accepts UTF-8 up to the
//! configured byte limit but rejects embedded NUL bytes before enqueue.

use crate::input::{MAX_DOUBLE_CLICK_INTERVAL_MS, MIN_DOUBLE_CLICK_INTERVAL_MS};
use remote_desktop_core::{
    DesktopError, DisplayInfo, KeyAction, KeyboardKey, MouseButton, WorkerCommand, validate_chord,
    validate_clipboard, validate_scroll, validate_text,
};
use serde::{Deserialize, Deserializer, Serialize, Serializer, de};

/// One stable public keyboard key.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct ApiKeyboardKey(KeyboardKey);

impl ApiKeyboardKey {
    /// Returns the validated internal key.
    pub const fn into_domain(self) -> KeyboardKey {
        self.0
    }

    fn symbolic_name(self) -> Option<&'static str> {
        match self.0 {
            KeyboardKey::CtrlLeft => Some("CTRL_LEFT"),
            KeyboardKey::AltLeft => Some("ALT_LEFT"),
            KeyboardKey::ShiftLeft => Some("SHIFT_LEFT"),
            KeyboardKey::MetaLeft => Some("META_LEFT"),
            KeyboardKey::Enter => Some("ENTER"),
            KeyboardKey::Tab => Some("TAB"),
            KeyboardKey::Escape => Some("ESCAPE"),
            KeyboardKey::Backspace => Some("BACKSPACE"),
            KeyboardKey::Delete => Some("DELETE"),
            KeyboardKey::Home => Some("HOME"),
            KeyboardKey::End => Some("END"),
            KeyboardKey::PageUp => Some("PAGE_UP"),
            KeyboardKey::PageDown => Some("PAGE_DOWN"),
            KeyboardKey::ArrowUp => Some("ARROW_UP"),
            KeyboardKey::ArrowDown => Some("ARROW_DOWN"),
            KeyboardKey::ArrowLeft => Some("ARROW_LEFT"),
            KeyboardKey::ArrowRight => Some("ARROW_RIGHT"),
            KeyboardKey::F1 => Some("F1"),
            KeyboardKey::F2 => Some("F2"),
            KeyboardKey::F3 => Some("F3"),
            KeyboardKey::F4 => Some("F4"),
            KeyboardKey::F5 => Some("F5"),
            KeyboardKey::F6 => Some("F6"),
            KeyboardKey::F7 => Some("F7"),
            KeyboardKey::F8 => Some("F8"),
            KeyboardKey::F9 => Some("F9"),
            KeyboardKey::F10 => Some("F10"),
            KeyboardKey::F11 => Some("F11"),
            KeyboardKey::F12 => Some("F12"),
            KeyboardKey::Printable(_) => None,
        }
    }
}

impl Serialize for ApiKeyboardKey {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        if let Some(name) = self.symbolic_name() {
            serializer.serialize_str(name)
        } else if let KeyboardKey::Printable(character) = self.0 {
            serializer.serialize_char(character)
        } else {
            unreachable!("all keyboard variants are covered")
        }
    }
}

impl<'de> Deserialize<'de> for ApiKeyboardKey {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        KeyboardKey::parse_name(&value)
            .map(Self)
            .map_err(|_| de::Error::custom("unknown public keyboard key"))
    }
}

/// Public pointer movement request.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct PointerMoveRequest {
    /// Horizontal coordinate in the current display.
    pub x: u32,
    /// Vertical coordinate in the current display.
    pub y: u32,
}

impl PointerMoveRequest {
    /// Converts a completely validated request into a worker command.
    pub fn into_command(self, display: DisplayInfo) -> Result<WorkerCommand, DesktopError> {
        Ok(WorkerCommand::MovePointer {
            coordinate: display.validate_coordinate(self.x, self.y)?,
        })
    }
}

/// Public explicit mouse-button transition request.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct PointerButtonRequest {
    /// Horizontal coordinate in the current display.
    pub x: u32,
    /// Vertical coordinate in the current display.
    pub y: u32,
    /// Mouse button to update.
    pub button: MouseButton,
    /// Whether the button must be held after the operation.
    pub pressed: bool,
}

impl PointerButtonRequest {
    /// Converts a completely validated request into a worker command.
    pub fn into_command(self, display: DisplayInfo) -> Result<WorkerCommand, DesktopError> {
        Ok(WorkerCommand::SetButton {
            coordinate: display.validate_coordinate(self.x, self.y)?,
            button: self.button,
            pressed: self.pressed,
        })
    }
}

/// Public single-click request.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct PointerClickRequest {
    /// Horizontal coordinate in the current display.
    pub x: u32,
    /// Vertical coordinate in the current display.
    pub y: u32,
    /// Mouse button to click.
    pub button: MouseButton,
}

impl PointerClickRequest {
    /// Converts a completely validated request into a worker command.
    pub fn into_command(self, display: DisplayInfo) -> Result<WorkerCommand, DesktopError> {
        Ok(WorkerCommand::Click {
            coordinate: display.validate_coordinate(self.x, self.y)?,
            button: self.button,
        })
    }
}

/// Public atomic double-click request.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct PointerDoubleClickRequest {
    /// Horizontal coordinate in the current display.
    pub x: u32,
    /// Vertical coordinate in the current display.
    pub y: u32,
    /// Mouse button to click twice.
    pub button: MouseButton,
    /// Bounded delay between complete clicks.
    pub interval_ms: u64,
}

impl PointerDoubleClickRequest {
    /// Converts a completely validated request into a worker command.
    pub fn into_command(self, display: DisplayInfo) -> Result<WorkerCommand, DesktopError> {
        if !(MIN_DOUBLE_CLICK_INTERVAL_MS..=MAX_DOUBLE_CLICK_INTERVAL_MS)
            .contains(&self.interval_ms)
        {
            return Err(DesktopError::Configuration(
                "double-click interval is outside the supported range".to_owned(),
            ));
        }
        Ok(WorkerCommand::DoubleClick {
            coordinate: display.validate_coordinate(self.x, self.y)?,
            button: self.button,
            interval_ms: self.interval_ms,
        })
    }
}

/// Public vertical wheel request. Horizontal scrolling is not part of v0.1.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct PointerScrollRequest {
    /// Horizontal coordinate in the current display.
    pub x: u32,
    /// Vertical coordinate in the current display.
    pub y: u32,
    /// Signed horizontal wheel steps. Nonzero values are rejected in v0.1.
    #[serde(default)]
    pub delta_x: i32,
    /// Signed vertical wheel steps.
    pub delta_y: i32,
}

impl PointerScrollRequest {
    /// Converts a completely validated request into a worker command.
    pub fn into_command(self, display: DisplayInfo) -> Result<WorkerCommand, DesktopError> {
        validate_scroll(self.delta_x, self.delta_y)?;
        Ok(WorkerCommand::Scroll {
            coordinate: display.validate_coordinate(self.x, self.y)?,
            delta_x: self.delta_x,
            delta_y: self.delta_y,
        })
    }
}

/// Public key transition request.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct KeyRequest {
    /// Stable key string.
    pub key: ApiKeyboardKey,
    /// Requested transition.
    pub action: KeyAction,
}

impl KeyRequest {
    /// Converts this validated public key request into a worker command.
    pub fn into_command(self) -> WorkerCommand {
        WorkerCommand::SetKey {
            key: self.key.into_domain(),
            pressed: self.action == KeyAction::Down,
        }
    }
}

/// Public chord request.
#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChordRequest {
    /// Keys pressed in this order and released in reverse order.
    pub keys: Vec<ApiKeyboardKey>,
}

impl ChordRequest {
    /// Converts a completely validated request into domain keys.
    pub fn into_domain(self) -> Result<Vec<KeyboardKey>, DesktopError> {
        let keys = self
            .keys
            .into_iter()
            .map(ApiKeyboardKey::into_domain)
            .collect::<Vec<_>>();
        validate_chord(&keys)?;
        Ok(keys)
    }
}

/// Public text request. `Debug` is deliberately not implemented to avoid
/// accidental payload logging.
#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TextRequest {
    /// Complete text value to preflight before enqueue.
    pub text: String,
}

impl TextRequest {
    /// Validates the complete request and returns its accepted character count.
    pub fn validate(&self) -> Result<usize, DesktopError> {
        validate_text(&self.text)
    }
}

/// Public clipboard request. `Debug` is deliberately not implemented to avoid
/// accidental payload logging.
#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ClipboardRequest {
    /// UTF-8 clipboard value. Embedded NUL bytes are rejected.
    pub text: String,
}

impl ClipboardRequest {
    /// Validates the complete clipboard request before enqueue.
    pub fn validate(&self) -> Result<(), DesktopError> {
        validate_clipboard(&self.text)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use remote_desktop_core::{
        DisplayInfo, FramebufferRect, FramebufferSnapshot, MAX_CHORD_KEYS, MAX_CLIPBOARD_BYTES,
        MAX_TEXT_BYTES,
    };
    use std::sync::Arc;
    use std::time::SystemTime;

    const SYMBOLIC_KEYS: [(&str, KeyboardKey); 29] = [
        ("CTRL_LEFT", KeyboardKey::CtrlLeft),
        ("ALT_LEFT", KeyboardKey::AltLeft),
        ("SHIFT_LEFT", KeyboardKey::ShiftLeft),
        ("META_LEFT", KeyboardKey::MetaLeft),
        ("ENTER", KeyboardKey::Enter),
        ("TAB", KeyboardKey::Tab),
        ("ESCAPE", KeyboardKey::Escape),
        ("BACKSPACE", KeyboardKey::Backspace),
        ("DELETE", KeyboardKey::Delete),
        ("HOME", KeyboardKey::Home),
        ("END", KeyboardKey::End),
        ("PAGE_UP", KeyboardKey::PageUp),
        ("PAGE_DOWN", KeyboardKey::PageDown),
        ("ARROW_UP", KeyboardKey::ArrowUp),
        ("ARROW_DOWN", KeyboardKey::ArrowDown),
        ("ARROW_LEFT", KeyboardKey::ArrowLeft),
        ("ARROW_RIGHT", KeyboardKey::ArrowRight),
        ("F1", KeyboardKey::F1),
        ("F2", KeyboardKey::F2),
        ("F3", KeyboardKey::F3),
        ("F4", KeyboardKey::F4),
        ("F5", KeyboardKey::F5),
        ("F6", KeyboardKey::F6),
        ("F7", KeyboardKey::F7),
        ("F8", KeyboardKey::F8),
        ("F9", KeyboardKey::F9),
        ("F10", KeyboardKey::F10),
        ("F11", KeyboardKey::F11),
        ("F12", KeyboardKey::F12),
    ];

    #[test]
    fn every_symbolic_key_has_a_stable_string_round_trip() {
        for (name, key) in SYMBOLIC_KEYS {
            let json = format!("\"{name}\"");
            let parsed: ApiKeyboardKey = serde_json::from_str(&json).expect("known key parses");
            assert_eq!(parsed.into_domain(), key);
            assert_eq!(
                serde_json::to_string(&parsed).expect("key serializes"),
                json
            );
        }
    }

    #[test]
    fn printable_ascii_keys_are_deliberate_single_character_strings() {
        for character in [' ', '!', 'A', 'z', '~'] {
            let json = serde_json::to_string(&character.to_string()).expect("fixture serializes");
            let key: ApiKeyboardKey = serde_json::from_str(&json).expect("printable key parses");
            assert_eq!(key.into_domain(), KeyboardKey::Printable(character));
            assert_eq!(serde_json::to_string(&key).expect("key serializes"), json);
        }
    }

    #[test]
    fn raw_keysyms_and_derived_enum_shape_are_rejected() {
        assert!(serde_json::from_str::<ApiKeyboardKey>("65").is_err());
        assert!(serde_json::from_str::<ApiKeyboardKey>(r#"{"Printable":"A"}"#).is_err());
        assert!(serde_json::from_str::<ApiKeyboardKey>("\"NOT_A_KEY\"").is_err());
        assert!(serde_json::from_str::<ApiKeyboardKey>("\"é\"").is_err());
    }

    #[test]
    fn chord_limit_is_enforced_after_complete_conversion() {
        let request = ChordRequest {
            keys: vec![ApiKeyboardKey(KeyboardKey::Enter); MAX_CHORD_KEYS],
        };
        assert_eq!(
            request.into_domain().expect("maximum chord accepted").len(),
            MAX_CHORD_KEYS
        );

        let request = ChordRequest {
            keys: vec![ApiKeyboardKey(KeyboardKey::Enter); MAX_CHORD_KEYS + 1],
        };
        assert!(matches!(
            request.into_domain(),
            Err(DesktopError::ChordTooLong { .. })
        ));
    }

    #[test]
    fn horizontal_scroll_is_recognized_and_rejected_explicitly() {
        let display = DisplayInfo {
            width: 1280,
            height: 800,
            depth: 24,
            revision: 1,
            complete: true,
        };
        let vertical: PointerScrollRequest =
            serde_json::from_str(r#"{"x":1,"y":1,"delta_y":1}"#).expect("vertical request parses");
        assert_eq!(vertical.delta_x, 0);
        assert!(vertical.into_command(display).is_ok());

        let horizontal: PointerScrollRequest =
            serde_json::from_str(r#"{"x":1,"y":1,"delta_x":1,"delta_y":0}"#)
                .expect("horizontal field is recognized");
        assert!(matches!(
            horizontal.into_command(display),
            Err(DesktopError::Configuration(_))
        ));
    }

    #[test]
    fn text_support_matrix_and_byte_boundary_are_explicit() {
        let supported = TextRequest {
            text: "\t\r\n !Az~".to_owned(),
        };
        assert_eq!(supported.validate().expect("supported text"), 8);

        for unsupported in ["\u{001f}", "\u{007f}", "é", "☃"] {
            let request = TextRequest {
                text: unsupported.to_owned(),
            };
            assert!(matches!(
                request.validate(),
                Err(DesktopError::UnsupportedTextCharacter { .. })
            ));
        }

        assert!(
            TextRequest {
                text: "a".repeat(MAX_TEXT_BYTES)
            }
            .validate()
            .is_ok()
        );
        assert!(matches!(
            TextRequest {
                text: "a".repeat(MAX_TEXT_BYTES + 1)
            }
            .validate(),
            Err(DesktopError::TextTooLarge { .. })
        ));
    }

    #[test]
    fn unsupported_text_is_rejected_by_complete_preflight() {
        let request = TextRequest {
            text: "prefix☃suffix".to_owned(),
        };
        let error = request.validate().expect_err("unsupported text must fail");
        assert_eq!(
            error,
            DesktopError::UnsupportedTextCharacter {
                index: 6,
                codepoint: '☃' as u32,
            }
        );
    }

    #[test]
    fn clipboard_boundary_and_embedded_nul_policy_are_explicit() {
        assert!(
            ClipboardRequest {
                text: "x".repeat(MAX_CLIPBOARD_BYTES)
            }
            .validate()
            .is_ok()
        );
        assert!(matches!(
            ClipboardRequest {
                text: "x".repeat(MAX_CLIPBOARD_BYTES + 1)
            }
            .validate(),
            Err(DesktopError::ClipboardTooLarge { .. })
        ));
        assert_eq!(
            ClipboardRequest {
                text: "a\0b".to_owned()
            }
            .validate(),
            Err(DesktopError::ClipboardContainsNul)
        );
    }

    #[test]
    fn framebuffer_fixture_and_every_edge_rectangle_validate() {
        let pixels: Arc<[u8]> = Arc::from([
            255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 255, 255,
        ]);
        let snapshot = FramebufferSnapshot::new(2, 2, 7, true, SystemTime::UNIX_EPOCH, pixels)
            .expect("known RGBA fixture is valid");
        assert_eq!(snapshot.rgba.len(), 16);

        let display = DisplayInfo::new(2, 2, 24, 7, true).expect("display is valid");
        assert!(FramebufferRect::new(0, 0, 2, 1, display).is_ok());
        assert!(FramebufferRect::new(0, 1, 2, 1, display).is_ok());
        assert!(FramebufferRect::new(0, 0, 1, 2, display).is_ok());
        assert!(FramebufferRect::new(1, 0, 1, 2, display).is_ok());
        assert!(FramebufferRect::new(2, 0, 1, 1, display).is_err());
        assert!(FramebufferRect::new(0, 2, 1, 1, display).is_err());
        assert!(FramebufferRect::new(u32::MAX, 0, 2, 1, display).is_err());
        assert!(FramebufferRect::new(0, u32::MAX, 1, 2, display).is_err());
        assert!(FramebufferRect::new(0, 0, 0, 1, display).is_err());
        assert!(FramebufferRect::new(0, 0, 1, 0, display).is_err());
    }

    #[test]
    fn pointer_requests_preflight_complete_coordinates_and_bounds() {
        let display = DisplayInfo::new(1_280, 800, 24, 1, true).expect("valid display");
        assert_eq!(
            PointerMoveRequest { x: 1, y: 2 }
                .into_command(display)
                .expect("valid move"),
            WorkerCommand::MovePointer {
                coordinate: display.validate_coordinate(1, 2).expect("known coordinate"),
            }
        );
        assert!(matches!(
            PointerClickRequest {
                x: display.width,
                y: 0,
                button: MouseButton::Left,
            }
            .into_command(display),
            Err(DesktopError::InvalidCoordinate { .. })
        ));
    }

    #[test]
    fn pointer_double_click_and_vertical_scroll_limits_are_explicit() {
        let display = DisplayInfo::new(1_280, 800, 24, 1, true).expect("valid display");
        assert!(
            PointerDoubleClickRequest {
                x: 0,
                y: 0,
                button: MouseButton::Left,
                interval_ms: MIN_DOUBLE_CLICK_INTERVAL_MS,
            }
            .into_command(display)
            .is_ok()
        );
        assert!(
            PointerDoubleClickRequest {
                x: 0,
                y: 0,
                button: MouseButton::Left,
                interval_ms: MAX_DOUBLE_CLICK_INTERVAL_MS + 1,
            }
            .into_command(display)
            .is_err()
        );
        assert!(
            PointerScrollRequest {
                x: 0,
                y: 0,
                delta_y: remote_desktop_core::MAX_SCROLL_STEPS,
            }
            .into_command(display)
            .is_ok()
        );
        assert!(matches!(
            PointerScrollRequest {
                x: 0,
                y: 0,
                delta_y: remote_desktop_core::MAX_SCROLL_STEPS + 1,
            }
            .into_command(display),
            Err(DesktopError::ScrollTooLarge { .. })
        ));
    }
}

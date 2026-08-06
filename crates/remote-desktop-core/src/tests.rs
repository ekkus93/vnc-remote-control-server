use crate::{ConnectionState, MAX_CHORD_KEYS, MAX_CLIPBOARD_BYTES, MAX_FRAMEBUFFER_BYTES};
use crate::{
    Coordinate, DisplayInfo, FramebufferRect, KeyboardKey, MouseButton, WorkerCommand,
    checked_rgba_len, validate_chord, validate_clipboard, validate_scroll, validate_text,
};
use crate::{MAX_SCROLL_STEPS, MAX_TEXT_BYTES, RGBA_BYTES_PER_PIXEL};
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
    let error =
        serde_json::from_str::<MouseButton>("\"side\"").expect_err("unsupported button must fail");
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
fn worker_command_debug_redacts_text_and_clipboard_payloads() {
    let typed = format!(
        "{:?}",
        WorkerCommand::TypeText {
            text: "typed secret".to_owned(),
        }
    );
    assert!(!typed.contains("typed secret"));
    assert!(typed.contains("text_bytes"));

    let clipboard = format!(
        "{:?}",
        WorkerCommand::SetClipboard {
            text: "clipboard secret".to_owned(),
        }
    );
    assert!(!clipboard.contains("clipboard secret"));
    assert!(clipboard.contains("text_bytes"));
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

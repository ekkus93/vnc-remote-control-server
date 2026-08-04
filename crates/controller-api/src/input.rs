//! Atomic pointer, mouse, wheel, and keyboard command execution.
//!
//! Every compound command is fully validated before the first native event.
//! The controller maintains the complete RFB button mask and locally pressed
//! key order. Partial failures trigger best-effort releases while preserving
//! unresolved local state so disconnect cleanup can retry releases.

use libvnc_adapter::NativeError;
use remote_desktop_core::{
    Coordinate, DesktopError, DisplayInfo, KeyboardKey, MouseButton, validate_chord,
    validate_scroll, validate_text,
};
use std::collections::HashSet;
use std::thread;
use std::time::Duration;

/// Smallest accepted interval between atomic double-clicks.
pub const MIN_DOUBLE_CLICK_INTERVAL_MS: u64 = 20;
/// Largest accepted interval between atomic double-clicks.
pub const MAX_DOUBLE_CLICK_INTERVAL_MS: u64 = 1_000;

const WHEEL_UP_MASK: u8 = 1 << 3;
const WHEEL_DOWN_MASK: u8 = 1 << 4;

/// Narrow native event surface required by the input controller.
pub(crate) trait InputSink {
    fn send_pointer(&mut self, coordinate: Coordinate, button_mask: u8) -> Result<(), NativeError>;

    fn send_key(&mut self, key: KeyboardKey, pressed: bool) -> Result<(), NativeError>;
}

/// Worker-owned input state.
#[derive(Default)]
pub(crate) struct InputController {
    button_mask: u8,
    last_coordinate: Option<Coordinate>,
    pressed_keys: Vec<KeyboardKey>,
}

impl InputController {
    /// Sends one strictly validated pointer movement with the full current mask.
    pub(crate) fn move_pointer<S: InputSink>(
        &mut self,
        sink: &mut S,
        requested: Coordinate,
        display: DisplayInfo,
    ) -> Result<(), DesktopError> {
        let coordinate = validate_coordinate(requested, display)?;
        sink.send_pointer(coordinate, self.button_mask)?;
        self.last_coordinate = Some(coordinate);
        Ok(())
    }

    /// Applies one explicit button transition while preserving every other bit.
    pub(crate) fn set_button<S: InputSink>(
        &mut self,
        sink: &mut S,
        requested: Coordinate,
        display: DisplayInfo,
        button: MouseButton,
        pressed: bool,
    ) -> Result<(), DesktopError> {
        let coordinate = validate_coordinate(requested, display)?;
        let bit = button.rfb_mask();
        let next_mask = if pressed {
            self.button_mask | bit
        } else {
            self.button_mask & !bit
        };
        sink.send_pointer(coordinate, next_mask)?;
        self.button_mask = next_mask;
        self.last_coordinate = Some(coordinate);
        Ok(())
    }

    /// Sends one move/down/up click sequence without command interleaving.
    pub(crate) fn click<S: InputSink>(
        &mut self,
        sink: &mut S,
        requested: Coordinate,
        display: DisplayInfo,
        button: MouseButton,
    ) -> Result<(), DesktopError> {
        let coordinate = validate_coordinate(requested, display)?;
        let bit = button.rfb_mask();
        if self.button_mask & bit != 0 {
            return Err(DesktopError::Configuration(
                "cannot click a mouse button that is already pressed".to_owned(),
            ));
        }

        sink.send_pointer(coordinate, self.button_mask)?;
        self.last_coordinate = Some(coordinate);
        let base_mask = self.button_mask;
        let pressed_mask = base_mask | bit;
        sink.send_pointer(coordinate, pressed_mask)?;
        self.button_mask = pressed_mask;

        match sink.send_pointer(coordinate, base_mask) {
            Ok(()) => {
                self.button_mask = base_mask;
                Ok(())
            }
            Err(error) => {
                if sink.send_pointer(coordinate, base_mask).is_ok() {
                    self.button_mask = base_mask;
                }
                Err(error.into())
            }
        }
    }

    /// Sends two complete click sequences with a bounded interval.
    pub(crate) fn double_click<S: InputSink>(
        &mut self,
        sink: &mut S,
        requested: Coordinate,
        display: DisplayInfo,
        button: MouseButton,
        interval_ms: u64,
    ) -> Result<(), DesktopError> {
        validate_double_click_interval(interval_ms)?;
        self.click(sink, requested, display, button)?;
        thread::sleep(Duration::from_millis(interval_ms));
        self.click(sink, requested, display, button)
    }

    /// Sends bounded vertical wheel steps atomically.
    ///
    /// Positive `delta_y` maps to X button 4 and negative `delta_y` maps to X
    /// button 5. Horizontal steps are rejected before pointer movement because
    /// TigerVNC interoperability has not been verified for v0.1.
    pub(crate) fn scroll<S: InputSink>(
        &mut self,
        sink: &mut S,
        requested: Coordinate,
        display: DisplayInfo,
        delta_x: i32,
        delta_y: i32,
    ) -> Result<(), DesktopError> {
        validate_scroll(delta_x, delta_y)?;
        if delta_x != 0 {
            return Err(DesktopError::Configuration(
                "horizontal scrolling is not supported by v0.1".to_owned(),
            ));
        }
        let coordinate = validate_coordinate(requested, display)?;
        sink.send_pointer(coordinate, self.button_mask)?;
        self.last_coordinate = Some(coordinate);

        let wheel_mask = if delta_y >= 0 {
            WHEEL_UP_MASK
        } else {
            WHEEL_DOWN_MASK
        };
        for _ in 0..delta_y.unsigned_abs() {
            sink.send_pointer(coordinate, self.button_mask | wheel_mask)?;
            if let Err(error) = sink.send_pointer(coordinate, self.button_mask) {
                let _ = sink.send_pointer(coordinate, self.button_mask);
                return Err(error.into());
            }
        }
        Ok(())
    }

    /// Applies one idempotent explicit key transition.
    pub(crate) fn set_key<S: InputSink>(
        &mut self,
        sink: &mut S,
        key: KeyboardKey,
        pressed: bool,
    ) -> Result<(), DesktopError> {
        if pressed && self.pressed_keys.contains(&key) {
            return Ok(());
        }
        sink.send_key(key, pressed)?;
        if pressed {
            self.pressed_keys.push(key);
        } else if let Some(index) = self
            .pressed_keys
            .iter()
            .position(|candidate| *candidate == key)
        {
            self.pressed_keys.remove(index);
        }
        Ok(())
    }

    /// Presses keys in order and releases newly pressed keys in reverse order.
    pub(crate) fn chord<S: InputSink>(
        &mut self,
        sink: &mut S,
        keys: &[KeyboardKey],
    ) -> Result<(), DesktopError> {
        validate_chord(keys)?;
        if keys.is_empty() {
            return Err(DesktopError::Configuration(
                "key chord must contain at least one key".to_owned(),
            ));
        }
        let mut unique = HashSet::with_capacity(keys.len());
        if keys.iter().any(|key| !unique.insert(*key)) {
            return Err(DesktopError::Configuration(
                "key chord contains a duplicate key".to_owned(),
            ));
        }

        let mut newly_pressed = Vec::with_capacity(keys.len());
        for key in keys {
            if self.pressed_keys.contains(key) {
                continue;
            }
            if let Err(error) = sink.send_key(*key, true) {
                self.release_new_keys(sink, &newly_pressed);
                return Err(error.into());
            }
            self.pressed_keys.push(*key);
            newly_pressed.push(*key);
        }

        let mut first_error = None;
        for key in newly_pressed.iter().rev() {
            match sink.send_key(*key, false) {
                Ok(()) => self.remove_pressed_key(*key),
                Err(error) if first_error.is_none() => first_error = Some(error),
                Err(_) => {}
            }
        }
        first_error.map_or(Ok(()), |error| Err(error.into()))
    }

    /// Enters one completely preflighted v0.1 text value.
    pub(crate) fn type_text<S: InputSink>(
        &mut self,
        sink: &mut S,
        text: &str,
    ) -> Result<usize, DesktopError> {
        let character_count = validate_text(text)?;
        for character in text.chars() {
            let key = match character {
                '\n' | '\r' => KeyboardKey::Enter,
                '\t' => KeyboardKey::Tab,
                value => KeyboardKey::Printable(value),
            };
            self.set_key(sink, key, true)?;
            if let Err(error) = self.set_key(sink, key, false) {
                let _ = self.set_key(sink, key, false);
                return Err(error);
            }
        }
        Ok(character_count)
    }

    /// Best-effort releases every locally tracked input and clears local state.
    pub(crate) fn release_all<S: InputSink>(&mut self, sink: &mut S) {
        if self.button_mask != 0
            && let Some(coordinate) = self.last_coordinate
        {
            let _ = sink.send_pointer(coordinate, 0);
        }
        for key in self.pressed_keys.iter().rev() {
            let _ = sink.send_key(*key, false);
        }
        self.clear();
    }

    /// Clears local state when no native session exists.
    pub(crate) fn clear(&mut self) {
        self.button_mask = 0;
        self.last_coordinate = None;
        self.pressed_keys.clear();
    }

    fn release_new_keys<S: InputSink>(&mut self, sink: &mut S, keys: &[KeyboardKey]) {
        for key in keys.iter().rev() {
            if sink.send_key(*key, false).is_ok() {
                self.remove_pressed_key(*key);
            }
        }
    }

    fn remove_pressed_key(&mut self, key: KeyboardKey) {
        if let Some(index) = self
            .pressed_keys
            .iter()
            .position(|candidate| *candidate == key)
        {
            self.pressed_keys.remove(index);
        }
    }
}

fn validate_coordinate(
    requested: Coordinate,
    display: DisplayInfo,
) -> Result<Coordinate, DesktopError> {
    if !display.complete {
        return Err(DesktopError::DisplayUnavailable);
    }
    display.validate_coordinate(requested.x, requested.y)
}

fn validate_double_click_interval(interval_ms: u64) -> Result<(), DesktopError> {
    if !(MIN_DOUBLE_CLICK_INTERVAL_MS..=MAX_DOUBLE_CLICK_INTERVAL_MS).contains(&interval_ms) {
        return Err(DesktopError::Configuration(format!(
            "double-click interval must be between {MIN_DOUBLE_CLICK_INTERVAL_MS} and {MAX_DOUBLE_CLICK_INTERVAL_MS} milliseconds"
        )));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use remote_desktop_core::{MAX_SCROLL_STEPS, MouseButton};

    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    enum Event {
        Pointer(Coordinate, u8),
        Key(KeyboardKey, bool),
    }

    #[derive(Default)]
    struct RecordingSink {
        events: Vec<Event>,
        call_count: usize,
        fail_on_call: Option<usize>,
    }

    impl RecordingSink {
        fn fail_on(call: usize) -> Self {
            Self {
                fail_on_call: Some(call),
                ..Self::default()
            }
        }

        fn record(&mut self, event: Event) -> Result<(), NativeError> {
            self.call_count += 1;
            if self.fail_on_call == Some(self.call_count) {
                return Err(NativeError::NativeFailure {
                    message: "test-only input failure".to_owned(),
                });
            }
            self.events.push(event);
            Ok(())
        }
    }

    impl InputSink for RecordingSink {
        fn send_pointer(
            &mut self,
            coordinate: Coordinate,
            button_mask: u8,
        ) -> Result<(), NativeError> {
            self.record(Event::Pointer(coordinate, button_mask))
        }

        fn send_key(&mut self, key: KeyboardKey, pressed: bool) -> Result<(), NativeError> {
            self.record(Event::Key(key, pressed))
        }
    }

    fn display() -> DisplayInfo {
        DisplayInfo::new(4, 3, 24, 1, true).expect("display")
    }

    fn coordinate(x: u32, y: u32) -> Coordinate {
        Coordinate { x, y }
    }

    #[test]
    fn pointer_validates_all_edges_and_never_clamps() {
        let mut controller = InputController::default();
        let mut sink = RecordingSink::default();
        for point in [
            coordinate(0, 0),
            coordinate(3, 0),
            coordinate(0, 2),
            coordinate(3, 2),
        ] {
            controller
                .move_pointer(&mut sink, point, display())
                .expect("edge is valid");
        }
        let prior = sink.events.len();
        assert!(
            controller
                .move_pointer(&mut sink, coordinate(4, 2), display())
                .is_err()
        );
        assert!(
            controller
                .move_pointer(&mut sink, coordinate(3, 3), display())
                .is_err()
        );
        assert_eq!(sink.events.len(), prior);

        let incomplete = DisplayInfo::new(4, 3, 24, 1, false).expect("display");
        assert_eq!(
            controller
                .move_pointer(&mut sink, coordinate(0, 0), incomplete)
                .expect_err("incomplete display fails"),
            DesktopError::DisplayUnavailable
        );
    }

    #[test]
    fn explicit_buttons_preserve_full_mask() {
        let mut controller = InputController::default();
        let mut sink = RecordingSink::default();
        let point = coordinate(1, 1);
        controller
            .set_button(&mut sink, point, display(), MouseButton::Left, true)
            .expect("left down");
        controller
            .set_button(&mut sink, point, display(), MouseButton::Right, true)
            .expect("right down");
        controller
            .set_button(&mut sink, point, display(), MouseButton::Left, false)
            .expect("left up");
        assert_eq!(
            sink.events,
            vec![
                Event::Pointer(point, 1),
                Event::Pointer(point, 5),
                Event::Pointer(point, 4),
            ]
        );
    }

    #[test]
    fn click_is_atomic_and_preserves_other_buttons() {
        let mut controller = InputController::default();
        let mut sink = RecordingSink::default();
        controller
            .set_button(
                &mut sink,
                coordinate(0, 0),
                display(),
                MouseButton::Right,
                true,
            )
            .expect("right down");
        sink.events.clear();
        let point = coordinate(2, 1);
        controller
            .click(&mut sink, point, display(), MouseButton::Left)
            .expect("click");
        assert_eq!(
            sink.events,
            vec![
                Event::Pointer(point, 4),
                Event::Pointer(point, 5),
                Event::Pointer(point, 4),
            ]
        );
    }

    #[test]
    fn failed_click_release_is_retried() {
        let mut controller = InputController::default();
        let mut sink = RecordingSink::fail_on(3);
        let point = coordinate(1, 1);
        assert!(
            controller
                .click(&mut sink, point, display(), MouseButton::Left)
                .is_err()
        );
        assert_eq!(
            sink.events,
            vec![
                Event::Pointer(point, 0),
                Event::Pointer(point, 1),
                Event::Pointer(point, 0),
            ]
        );
    }

    #[test]
    fn double_click_interval_is_preflighted() {
        let mut controller = InputController::default();
        let mut sink = RecordingSink::default();
        let point = coordinate(1, 1);
        assert!(
            controller
                .double_click(&mut sink, point, display(), MouseButton::Left, 0)
                .is_err()
        );
        assert!(
            controller
                .double_click(
                    &mut sink,
                    point,
                    display(),
                    MouseButton::Left,
                    MAX_DOUBLE_CLICK_INTERVAL_MS + 1,
                )
                .is_err()
        );
        assert!(sink.events.is_empty());
        controller
            .double_click(
                &mut sink,
                point,
                display(),
                MouseButton::Left,
                MIN_DOUBLE_CLICK_INTERVAL_MS,
            )
            .expect("valid double click");
        assert_eq!(sink.events.len(), 6);
    }

    #[test]
    fn vertical_scroll_is_bounded_atomic_and_preserves_mask() {
        let mut controller = InputController::default();
        let mut sink = RecordingSink::default();
        let point = coordinate(1, 1);
        controller
            .set_button(&mut sink, point, display(), MouseButton::Left, true)
            .expect("left down");
        sink.events.clear();
        controller
            .scroll(&mut sink, point, display(), 0, 2)
            .expect("scroll up");
        assert_eq!(
            sink.events,
            vec![
                Event::Pointer(point, 1),
                Event::Pointer(point, 9),
                Event::Pointer(point, 1),
                Event::Pointer(point, 9),
                Event::Pointer(point, 1),
            ]
        );
        sink.events.clear();
        controller
            .scroll(&mut sink, point, display(), 0, -1)
            .expect("scroll down");
        assert_eq!(
            sink.events,
            vec![
                Event::Pointer(point, 1),
                Event::Pointer(point, 17),
                Event::Pointer(point, 1)
            ]
        );
        sink.events.clear();
        assert!(
            controller
                .scroll(&mut sink, point, display(), 1, 0)
                .is_err()
        );
        assert!(sink.events.is_empty());
        assert!(
            controller
                .scroll(&mut sink, point, display(), 0, MAX_SCROLL_STEPS + 1)
                .is_err()
        );
        assert!(sink.events.is_empty());
    }

    #[test]
    fn chord_orders_presses_and_reverse_releases_without_duplicate_corruption() {
        let mut controller = InputController::default();
        let mut sink = RecordingSink::default();
        controller
            .set_key(&mut sink, KeyboardKey::CtrlLeft, true)
            .expect("held control");
        sink.events.clear();
        controller
            .chord(
                &mut sink,
                &[
                    KeyboardKey::CtrlLeft,
                    KeyboardKey::AltLeft,
                    KeyboardKey::Printable('T'),
                ],
            )
            .expect("chord");
        assert_eq!(
            sink.events,
            vec![
                Event::Key(KeyboardKey::AltLeft, true),
                Event::Key(KeyboardKey::Printable('T'), true),
                Event::Key(KeyboardKey::Printable('T'), false),
                Event::Key(KeyboardKey::AltLeft, false),
            ]
        );
        sink.events.clear();
        assert!(
            controller
                .chord(&mut sink, &[KeyboardKey::AltLeft, KeyboardKey::AltLeft])
                .is_err()
        );
        assert!(sink.events.is_empty());
        controller
            .set_key(&mut sink, KeyboardKey::CtrlLeft, false)
            .expect("control up");
        assert_eq!(sink.events, vec![Event::Key(KeyboardKey::CtrlLeft, false)]);
    }

    #[test]
    fn partial_chord_failure_releases_prior_keys() {
        let mut controller = InputController::default();
        let mut sink = RecordingSink::fail_on(2);
        assert!(
            controller
                .chord(&mut sink, &[KeyboardKey::CtrlLeft, KeyboardKey::AltLeft],)
                .is_err()
        );
        assert_eq!(
            sink.events,
            vec![
                Event::Key(KeyboardKey::CtrlLeft, true),
                Event::Key(KeyboardKey::CtrlLeft, false),
            ]
        );
    }

    #[test]
    fn text_is_fully_preflighted_and_sent_in_order() {
        let mut controller = InputController::default();
        let mut sink = RecordingSink::default();
        assert_eq!(
            controller
                .type_text(&mut sink, "A\n\t!")
                .expect("supported text"),
            4
        );
        assert_eq!(
            sink.events,
            vec![
                Event::Key(KeyboardKey::Printable('A'), true),
                Event::Key(KeyboardKey::Printable('A'), false),
                Event::Key(KeyboardKey::Enter, true),
                Event::Key(KeyboardKey::Enter, false),
                Event::Key(KeyboardKey::Tab, true),
                Event::Key(KeyboardKey::Tab, false),
                Event::Key(KeyboardKey::Printable('!'), true),
                Event::Key(KeyboardKey::Printable('!'), false),
            ]
        );

        sink.events.clear();
        assert!(controller.type_text(&mut sink, "ok☃").is_err());
        assert!(sink.events.is_empty());
    }

    #[test]
    fn text_release_failure_is_retried_and_reported() {
        let mut controller = InputController::default();
        let mut sink = RecordingSink::fail_on(2);
        assert!(controller.type_text(&mut sink, "A").is_err());
        assert_eq!(
            sink.events,
            vec![
                Event::Key(KeyboardKey::Printable('A'), true),
                Event::Key(KeyboardKey::Printable('A'), false),
            ]
        );
    }

    #[test]
    fn disconnect_release_clears_buttons_and_keys() {
        let mut controller = InputController::default();
        let mut sink = RecordingSink::default();
        let point = coordinate(1, 1);
        controller
            .set_button(&mut sink, point, display(), MouseButton::Middle, true)
            .expect("button down");
        controller
            .set_key(&mut sink, KeyboardKey::CtrlLeft, true)
            .expect("control down");
        controller
            .set_key(&mut sink, KeyboardKey::AltLeft, true)
            .expect("alt down");
        sink.events.clear();
        controller.release_all(&mut sink);
        assert_eq!(
            sink.events,
            vec![
                Event::Pointer(point, 0),
                Event::Key(KeyboardKey::AltLeft, false),
                Event::Key(KeyboardKey::CtrlLeft, false),
            ]
        );
        sink.events.clear();
        controller.release_all(&mut sink);
        assert!(sink.events.is_empty());
    }
}

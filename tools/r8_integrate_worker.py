#!/usr/bin/env python3
"""Apply the reviewed R8 worker integration deterministically."""

from pathlib import Path

PATH = Path("crates/controller-api/src/worker.rs")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one required anchor and fail closed if it is absent or duplicated."""
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = PATH.read_text()

    text = replace_once(
        text,
        "use crate::screenshot::{ScreenshotError, ScreenshotService};",
        "use crate::input::{InputController, InputSink};\n"
        "use crate::screenshot::{ScreenshotError, ScreenshotService};",
        "input import",
    )
    text = replace_once(
        text,
        "ConnectionState, Coordinate, DesktopError, DesktopEventKind, KeyboardKey,\n"
        "    MAX_FRAMEBUFFER_BYTES, WorkerCommand,",
        "ConnectionState, Coordinate, DesktopError, DesktopEventKind, DisplayInfo, KeyboardKey,\n"
        "    MAX_FRAMEBUFFER_BYTES, WorkerCommand,",
        "DisplayInfo import",
    )
    text = replace_once(text, "use std::collections::HashSet;\n", "", "HashSet import")

    text = replace_once(
        text,
        "}\n\nstruct LoopState<'a, S> {",
        """}

impl<T: WorkerSession> InputSink for T {
    fn send_pointer(
        &mut self,
        coordinate: Coordinate,
        button_mask: u8,
    ) -> Result<(), NativeError> {
        WorkerSession::send_pointer(self, coordinate, button_mask)
    }

    fn send_key(&mut self, key: KeyboardKey, pressed: bool) -> Result<(), NativeError> {
        WorkerSession::send_key(self, key, pressed)
    }
}

struct LoopState<'a, S> {""",
        "WorkerSession implementation",
    )

    text = replace_once(
        text,
        """    session: Option<S>,
    last_native_revision: Option<u64>,
    button_mask: u8,
    last_coordinate: Option<Coordinate>,
    pressed_keys: HashSet<KeyboardKey>,
    next_connect: Option<Instant>,
""",
        """    session: Option<S>,
    last_native_revision: Option<u64>,
    input: InputController,
    next_connect: Option<Instant>,
""",
        "LoopState input fields",
    )

    release_start = text.index("    fn release_input(&mut self) {")
    release_end = text.index("\n    fn invalidate(&mut self) {", release_start)
    text = (
        text[:release_start]
        + """    fn release_input(&mut self) {
        if let Some(session) = self.session.as_mut() {
            self.input.release_all(session);
        } else {
            self.input.clear();
        }
    }
"""
        + text[release_end:]
    )

    execute_start = text.index(
        "    fn execute(&mut self, command: WorkerCommand) -> Result<(), DesktopError> {"
    )
    execute_end = text.index("\n    fn poll(&mut self)", execute_start)
    text = (
        text[:execute_start]
        + """    fn current_display(&self) -> Result<DisplayInfo, DesktopError> {
        if self.session.is_none() {
            return Err(DesktopError::WorkerUnavailable);
        }
        Ok(self.framebuffer.current_snapshot()?.display_info())
    }

    fn execute(&mut self, command: WorkerCommand) -> Result<(), DesktopError> {
        match command {
            WorkerCommand::MovePointer { coordinate } => {
                let display = self.current_display()?;
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input.move_pointer(session, coordinate, display)
            }
            WorkerCommand::SetButton {
                coordinate,
                button,
                pressed,
            } => {
                let display = self.current_display()?;
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input
                    .set_button(session, coordinate, display, button, pressed)
            }
            WorkerCommand::Click { coordinate, button } => {
                let display = self.current_display()?;
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input.click(session, coordinate, display, button)
            }
            WorkerCommand::DoubleClick {
                coordinate,
                button,
                interval_ms,
            } => {
                let display = self.current_display()?;
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input
                    .double_click(session, coordinate, display, button, interval_ms)
            }
            WorkerCommand::Scroll {
                coordinate,
                delta_x,
                delta_y,
            } => {
                let display = self.current_display()?;
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input
                    .scroll(session, coordinate, display, delta_x, delta_y)
            }
            WorkerCommand::SetKey { key, pressed } => {
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input.set_key(session, key, pressed)
            }
            WorkerCommand::Chord { keys } => {
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input.chord(session, &keys)
            }
            WorkerCommand::SetClipboard { text } => self
                .session
                .as_mut()
                .ok_or(DesktopError::WorkerUnavailable)?
                .send_clipboard(&text)
                .map_err(DesktopError::from),
            WorkerCommand::RequestFullRefresh => self
                .session
                .as_mut()
                .ok_or(DesktopError::WorkerUnavailable)?
                .request_full_refresh()
                .map_err(DesktopError::from),
            WorkerCommand::TypeText { .. } => Err(DesktopError::Configuration(
                "text input is not enabled until the text milestone".to_owned(),
            )),
            WorkerCommand::Reconnect | WorkerCommand::Shutdown => Err(DesktopError::Protocol),
        }
    }
"""
        + text[execute_end:]
    )

    text = replace_once(
        text,
        """        session: None,
        last_native_revision: None,
        button_mask: 0,
        last_coordinate: None,
        pressed_keys: HashSet::new(),
        next_connect: Some(Instant::now()),
""",
        """        session: None,
        last_native_revision: None,
        input: InputController::default(),
        next_connect: Some(Instant::now()),
""",
        "LoopState initializer",
    )

    text = replace_once(
        text,
        "use remote_desktop_core::DisplayInfo;",
        "use remote_desktop_core::{DisplayInfo, MouseButton};",
        "test imports",
    )

    helper_anchor = "    fn settings() -> WorkerSettings {"
    helpers = """    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    enum InputEvent {
        Pointer(Coordinate, u8),
        Key(KeyboardKey, bool),
    }

    struct RecordingSession {
        events: Arc<Mutex<Vec<InputEvent>>>,
        input_calls: usize,
        fail_on_input_call: Option<usize>,
    }

    impl RecordingSession {
        fn new(
            events: Arc<Mutex<Vec<InputEvent>>>,
            fail_on_input_call: Option<usize>,
        ) -> Self {
            Self {
                events,
                input_calls: 0,
                fail_on_input_call,
            }
        }

        fn record(&mut self, event: InputEvent) -> Result<(), NativeError> {
            self.input_calls += 1;
            if self.fail_on_input_call == Some(self.input_calls) {
                return Err(NativeError::NativeFailure {
                    message: "test-only worker input failure".to_owned(),
                });
            }
            lock_unpoisoned(&self.events).push(event);
            Ok(())
        }
    }

    impl WorkerSession for RecordingSession {
        fn poll(&mut self, timeout: Duration) -> Result<PollOutcome, NativeError> {
            thread::sleep(timeout);
            Ok(PollOutcome::MessageProcessed)
        }

        fn request_full_refresh(&mut self) -> Result<(), NativeError> {
            Ok(())
        }

        fn display_info(&self) -> Result<NativeDisplayInfo, NativeError> {
            Ok(NativeDisplayInfo {
                width: 2,
                height: 2,
                revision: 1,
                complete: true,
            })
        }

        fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {
            Ok(NativeFramebuffer {
                width: 2,
                height: 2,
                revision: 1,
                bytes: vec![1, 2, 3, 0, 4, 5, 6, 0, 7, 8, 9, 0, 10, 11, 12, 0],
            })
        }

        fn send_pointer(
            &mut self,
            coordinate: Coordinate,
            button_mask: u8,
        ) -> Result<(), NativeError> {
            self.record(InputEvent::Pointer(coordinate, button_mask))
        }

        fn send_key(&mut self, key: KeyboardKey, pressed: bool) -> Result<(), NativeError> {
            self.record(InputEvent::Key(key, pressed))
        }

        fn send_clipboard(&mut self, _text: &str) -> Result<(), NativeError> {
            Ok(())
        }
    }

"""
    text = replace_once(text, helper_anchor, helpers + helper_anchor, "test helper")

    text = replace_once(
        text,
        """        let display = DisplayInfo::new(1_280, 800, 24, 1, true).expect("display");
        let coordinate = Coordinate::new(10, 10, display).expect("coordinate");
""",
        """        let display = snapshot.display_info();
        let coordinate = Coordinate::new(1, 1, display).expect("coordinate");
""",
        "existing pointer test",
    )

    test_anchor = "    #[test]\n    fn transport_failure_reconnects_with_bounded_backoff() {"
    tests = """    #[test]
    fn worker_routes_atomic_input_through_single_owned_session() {
        let events = Arc::new(Mutex::new(Vec::new()));
        let factory_events = Arc::clone(&events);
        let worker = DesktopWorker::spawn_with_factory(settings(), move || {
            Ok(RecordingSession::new(Arc::clone(&factory_events), None))
        })
        .expect("worker spawns");
        let client = worker.client();
        wait_for_state(&client, ConnectionState::Connected);
        let point = Coordinate { x: 1, y: 1 };

        for command in [
            WorkerCommand::SetButton {
                coordinate: point,
                button: MouseButton::Right,
                pressed: true,
            },
            WorkerCommand::Click {
                coordinate: point,
                button: MouseButton::Left,
            },
            WorkerCommand::Scroll {
                coordinate: point,
                delta_x: 0,
                delta_y: 1,
            },
            WorkerCommand::Chord {
                keys: vec![
                    KeyboardKey::CtrlLeft,
                    KeyboardKey::AltLeft,
                    KeyboardKey::Printable('T'),
                ],
            },
            WorkerCommand::SetButton {
                coordinate: point,
                button: MouseButton::Right,
                pressed: false,
            },
        ] {
            client
                .submit(command)
                .expect("accepted")
                .wait(Duration::from_secs(1))
                .expect("executed");
        }

        assert_eq!(
            *lock_unpoisoned(&events),
            vec![
                InputEvent::Pointer(point, 4),
                InputEvent::Pointer(point, 4),
                InputEvent::Pointer(point, 5),
                InputEvent::Pointer(point, 4),
                InputEvent::Pointer(point, 4),
                InputEvent::Pointer(point, 12),
                InputEvent::Pointer(point, 4),
                InputEvent::Key(KeyboardKey::CtrlLeft, true),
                InputEvent::Key(KeyboardKey::AltLeft, true),
                InputEvent::Key(KeyboardKey::Printable('T'), true),
                InputEvent::Key(KeyboardKey::Printable('T'), false),
                InputEvent::Key(KeyboardKey::AltLeft, false),
                InputEvent::Key(KeyboardKey::CtrlLeft, false),
                InputEvent::Pointer(point, 0),
            ]
        );
        worker
            .shutdown(Duration::from_secs(1))
            .expect("worker joins");
    }

    #[test]
    fn worker_rejects_invalid_coordinate_before_native_mutation() {
        let events = Arc::new(Mutex::new(Vec::new()));
        let factory_events = Arc::clone(&events);
        let worker = DesktopWorker::spawn_with_factory(settings(), move || {
            Ok(RecordingSession::new(Arc::clone(&factory_events), None))
        })
        .expect("worker spawns");
        let client = worker.client();
        wait_for_state(&client, ConnectionState::Connected);

        let error = client
            .submit(WorkerCommand::MovePointer {
                coordinate: Coordinate { x: 2, y: 1 },
            })
            .expect("accepted")
            .wait(Duration::from_secs(1))
            .expect_err("out-of-range coordinate must fail");
        assert!(matches!(error, DesktopError::CoordinateOutOfRange { .. }));
        assert!(lock_unpoisoned(&events).is_empty());
        worker
            .shutdown(Duration::from_secs(1))
            .expect("worker joins");
    }

    #[test]
    fn worker_returns_partial_input_failure_after_release_retry() {
        let events = Arc::new(Mutex::new(Vec::new()));
        let factory_events = Arc::clone(&events);
        let worker = DesktopWorker::spawn_with_factory(settings(), move || {
            Ok(RecordingSession::new(Arc::clone(&factory_events), Some(3)))
        })
        .expect("worker spawns");
        let client = worker.client();
        wait_for_state(&client, ConnectionState::Connected);
        let point = Coordinate { x: 1, y: 1 };

        client
            .submit(WorkerCommand::Click {
                coordinate: point,
                button: MouseButton::Left,
            })
            .expect("accepted")
            .wait(Duration::from_secs(1))
            .expect_err("native release failure must reach caller");
        assert_eq!(
            *lock_unpoisoned(&events),
            vec![
                InputEvent::Pointer(point, 0),
                InputEvent::Pointer(point, 1),
                InputEvent::Pointer(point, 0),
            ]
        );
        worker
            .shutdown(Duration::from_secs(1))
            .expect("worker joins");
    }

    #[test]
    fn shutdown_releases_tracked_buttons_and_keys() {
        let events = Arc::new(Mutex::new(Vec::new()));
        let factory_events = Arc::clone(&events);
        let worker = DesktopWorker::spawn_with_factory(settings(), move || {
            Ok(RecordingSession::new(Arc::clone(&factory_events), None))
        })
        .expect("worker spawns");
        let client = worker.client();
        wait_for_state(&client, ConnectionState::Connected);
        let point = Coordinate { x: 1, y: 1 };

        client
            .submit(WorkerCommand::SetButton {
                coordinate: point,
                button: MouseButton::Left,
                pressed: true,
            })
            .expect("accepted")
            .wait(Duration::from_secs(1))
            .expect("button down");
        client
            .submit(WorkerCommand::SetKey {
                key: KeyboardKey::CtrlLeft,
                pressed: true,
            })
            .expect("accepted")
            .wait(Duration::from_secs(1))
            .expect("key down");
        worker
            .shutdown(Duration::from_secs(1))
            .expect("worker joins");

        assert_eq!(
            *lock_unpoisoned(&events),
            vec![
                InputEvent::Pointer(point, 1),
                InputEvent::Key(KeyboardKey::CtrlLeft, true),
                InputEvent::Pointer(point, 0),
                InputEvent::Key(KeyboardKey::CtrlLeft, false),
            ]
        );
    }

"""
    text = replace_once(text, test_anchor, tests + test_anchor, "worker tests")
    PATH.write_text(text)


if __name__ == "__main__":
    main()

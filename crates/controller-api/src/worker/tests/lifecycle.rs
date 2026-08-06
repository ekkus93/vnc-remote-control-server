use super::*;
use crate::framebuffer::FramebufferError;
use remote_desktop_core::{KeyboardKey, MouseButton, WorkerCommand};
use std::time::Duration;

#[test]
fn settings_reject_zero_capacities_invalid_frame_limit_and_delay_order() {
    let mut candidate = settings();
    candidate.command_capacity = 0;
    assert!(candidate.validate().is_err());

    let mut candidate = settings();
    candidate.maximum_framebuffer_bytes = 0;
    assert!(candidate.validate().is_err());

    let mut candidate = settings();
    candidate.reconnect_min_delay = Duration::from_secs(2);
    candidate.reconnect_max_delay = Duration::from_secs(1);
    assert!(candidate.validate().is_err());
}

#[test]
fn worker_commits_frame_accepts_commands_and_joins_shutdown() {
    let worker = DesktopWorker::spawn_with_factory(settings(), || Ok(healthy_session()))
        .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);
    let snapshot = client.framebuffer_snapshot().expect("current frame");
    assert_eq!(snapshot.width(), 2);
    assert_eq!(snapshot.height(), 2);
    assert_eq!(snapshot.revision(), 1);
    assert_eq!(&snapshot.rgba()[0..4], &[1, 2, 3, 255]);

    let display = snapshot.display_info();
    let coordinate = Coordinate::new(1, 1, display).expect("coordinate");
    client
        .submit(WorkerCommand::MovePointer { coordinate })
        .expect("accepted")
        .wait(Duration::from_secs(1))
        .expect("executed");
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
    assert_eq!(client.snapshot().state, ConnectionState::Stopped);
    assert_eq!(
        client.framebuffer_snapshot().err(),
        Some(FramebufferError::Stale)
    );
}

#[test]
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
fn worker_routes_preflighted_text_and_clipboard_without_payload_loss() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let factory_events = Arc::clone(&events);
    let worker = DesktopWorker::spawn_with_factory(settings(), move || {
        Ok(RecordingSession::new(Arc::clone(&factory_events), None))
    })
    .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);

    client
        .submit(WorkerCommand::TypeText {
            text: "A\n".to_owned(),
        })
        .expect("accepted")
        .wait(Duration::from_secs(1))
        .expect("text executed");
    client
        .submit(WorkerCommand::SetClipboard {
            text: "clipboard value".to_owned(),
        })
        .expect("accepted")
        .wait(Duration::from_secs(1))
        .expect("clipboard sent");

    assert_eq!(
        *lock_unpoisoned(&events),
        vec![
            InputEvent::Key(KeyboardKey::Printable('A'), true),
            InputEvent::Key(KeyboardKey::Printable('A'), false),
            InputEvent::Key(KeyboardKey::Enter, true),
            InputEvent::Key(KeyboardKey::Enter, false),
            InputEvent::Clipboard("clipboard value".to_owned()),
        ]
    );

    lock_unpoisoned(&events).clear();
    client
        .submit(WorkerCommand::TypeText {
            text: "ok☃".to_owned(),
        })
        .expect("accepted")
        .wait(Duration::from_secs(1))
        .expect_err("unsupported text rejected");
    client
        .submit(WorkerCommand::SetClipboard {
            text: "a\0b".to_owned(),
        })
        .expect("accepted")
        .wait(Duration::from_secs(1))
        .expect_err("NUL clipboard rejected");
    assert!(lock_unpoisoned(&events).is_empty());

    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

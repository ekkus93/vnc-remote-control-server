use super::*;
use remote_desktop_core::{
    DesktopError, DesktopEventKind, KeyboardKey, MouseButton, WorkerCommand,
};
use std::time::Duration;

#[test]
fn worker_publishes_last_valid_inbound_clipboard_snapshot() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let factory_events = Arc::clone(&events);
    let worker = DesktopWorker::spawn_with_factory(settings(), move || {
        Ok(RecordingSession::with_clipboard(
            Arc::clone(&factory_events),
            "from desktop",
            7,
        ))
    })
    .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);

    let deadline = Instant::now() + Duration::from_secs(1);
    let clipboard = loop {
        match client.clipboard_snapshot() {
            Ok(snapshot) => break snapshot,
            Err(DesktopError::ClipboardUnavailable) if Instant::now() < deadline => {
                thread::sleep(Duration::from_millis(1));
            }
            other => panic!("clipboard snapshot unavailable: {other:?}"),
        }
    };
    assert_eq!(clipboard.text.as_ref(), "from desktop");
    assert_eq!(clipboard.revision, 1);

    let mut saw_revision = false;
    while let Ok(event) = worker.events().recv_timeout(Duration::from_millis(20)) {
        if matches!(
            event.kind,
            DesktopEventKind::ClipboardRevision { revision: 1 }
        ) {
            saw_revision = true;
            break;
        }
    }
    assert!(saw_revision);
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
    assert!(matches!(error, DesktopError::InvalidCoordinate { .. }));
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

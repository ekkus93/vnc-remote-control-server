use super::*;
use crate::framebuffer::{FramebufferError, FramebufferStore};
use crate::input::InputController;
use crate::worker::loop_state::LoopState;
use crate::worker::snapshot::{WorkerEvent, WorkerSnapshot};
use remote_desktop_core::{
    ClipboardSnapshot, DesktopEventKind, KeyboardKey, MouseButton, WorkerCommand,
};
use std::sync::mpsc::{SyncSender, sync_channel};
use std::time::{Duration, Instant, SystemTime};

fn test_snapshot() -> Arc<Mutex<WorkerSnapshot>> {
    Arc::new(Mutex::new(WorkerSnapshot {
        state: ConnectionState::Connected,
        started_at: SystemTime::now(),
        connected_at: Some(SystemTime::now()),
        last_message_at: Some(SystemTime::now()),
        reconnect_attempts: 0,
        last_failure: None,
        framebuffer_revision: None,
        rejected_commands: 0,
        dropped_events: 0,
        fatal_exit: false,
    }))
}

fn test_loop_state<'a>(
    settings: &'a WorkerSettings,
    snapshot: &'a Arc<Mutex<WorkerSnapshot>>,
    event_sender: &'a SyncSender<WorkerEvent>,
    clipboard: &'a Arc<Mutex<Option<ClipboardSnapshot>>>,
    event_sequence: u64,
) -> LoopState<'a, MockSession> {
    LoopState {
        settings,
        snapshot,
        events: event_sender,
        framebuffer: FramebufferStore::new(settings.maximum_framebuffer_bytes)
            .expect("test framebuffer store"),
        clipboard,
        event_sequence,
        event_terminal_failure: false,
        shutdown_cleanup: false,
        session: None,
        last_native_revision: None,
        last_native_clipboard_revision: None,
        clipboard_revision: 0,
        clipboard_decode_failed: false,
        input: InputController::default(),
        next_connect: None,
        reconnect_attempt: 0,
        connected_since: None,
        last_message: Instant::now(),
        probe_sent: None,
        last_manual_reconnect: None,
    }
}

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

#[test]
fn worker_event_queue_full_is_bounded_nonfatal_overload() {
    let settings = settings();
    let snapshot = test_snapshot();
    let clipboard = Arc::new(Mutex::new(None));
    let (sender, _receiver) = sync_channel(1);
    let mut state = test_loop_state(&settings, &snapshot, &sender, &clipboard, 0);

    state
        .publish(DesktopEventKind::Overload)
        .expect("first event fits");
    state
        .publish(DesktopEventKind::Overload)
        .expect("full queue remains a bounded nonfatal drop");

    let current = lock_unpoisoned(&snapshot);
    assert_eq!(current.dropped_events, 1);
    assert!(!current.fatal_exit);
    assert!(!state.event_terminal_failure());
    assert_eq!(state.event_sequence, 2);
}

#[test]
fn worker_event_receiver_disconnect_is_terminal() {
    let settings = settings();
    let snapshot = test_snapshot();
    let clipboard = Arc::new(Mutex::new(None));
    let (sender, receiver) = sync_channel(1);
    drop(receiver);
    let mut state = test_loop_state(&settings, &snapshot, &sender, &clipboard, 7);

    assert!(state.publish(DesktopEventKind::Overload).is_err());
    assert!(state.event_terminal_failure());
    assert!(lock_unpoisoned(&snapshot).fatal_exit);
    let sequence_after_failure = state.event_sequence;
    assert!(state.publish(DesktopEventKind::Overload).is_err());
    assert_eq!(state.event_sequence, sequence_after_failure);
}

#[test]
fn worker_event_sequence_exhaustion_is_terminal_without_wrap() {
    let settings = settings();
    let snapshot = test_snapshot();
    let clipboard = Arc::new(Mutex::new(None));
    let (sender, _receiver) = sync_channel(1);
    let mut state = test_loop_state(&settings, &snapshot, &sender, &clipboard, u64::MAX);

    assert!(state.publish(DesktopEventKind::Overload).is_err());
    assert!(state.event_terminal_failure());
    assert!(lock_unpoisoned(&snapshot).fatal_exit);
    assert_eq!(state.event_sequence, u64::MAX);
    assert!(state.publish(DesktopEventKind::Overload).is_err());
    assert_eq!(state.event_sequence, u64::MAX);
}

#[test]
fn orderly_shutdown_cleanup_tolerates_event_receiver_teardown() {
    let settings = settings();
    let snapshot = test_snapshot();
    let clipboard = Arc::new(Mutex::new(None));
    let (sender, receiver) = sync_channel(1);
    drop(receiver);
    let mut state = test_loop_state(&settings, &snapshot, &sender, &clipboard, 9);
    state.begin_shutdown_cleanup();

    state
        .publish(DesktopEventKind::Overload)
        .expect("receiver teardown is expected after shutdown is authoritative");
    assert!(!state.event_terminal_failure());
    assert!(!lock_unpoisoned(&snapshot).fatal_exit);
}

#[test]
fn dropped_worker_event_receiver_stops_command_service() {
    let mut worker = DesktopWorker::spawn_with_factory(settings(), || Ok(healthy_session()))
        .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);

    let event_receiver = worker.take_events().expect("single event receiver");
    drop(event_receiver);

    client
        .submit(WorkerCommand::Reconnect)
        .expect("reconnect reaches worker")
        .wait(Duration::from_secs(1))
        .expect_err("event receiver loss fails the triggering command");
    wait_for_state(&client, ConnectionState::Stopped);
    assert!(client.snapshot().fatal_exit);
    assert!(client.submit(WorkerCommand::RequestFullRefresh).is_err());

    worker
        .shutdown(Duration::from_secs(1))
        .expect("already-exited worker joins cleanly");
}

#[test]
fn command_id_exhaustion_is_shared_terminal_and_never_enqueues() {
    let worker = DesktopWorker::spawn_with_factory(settings(), || Ok(healthy_session()))
        .expect("worker spawns");
    let client = worker.client();
    let clone = client.clone();
    wait_for_state(&client, ConnectionState::Connected);
    client.force_command_sequence_for_test(u64::MAX);

    let ((first, second), logs) = crate::test_support::capture_logs(|| {
        (
            client.submit(WorkerCommand::RequestFullRefresh),
            clone.submit(WorkerCommand::RequestFullRefresh),
        )
    });

    assert_eq!(first.err(), Some(DesktopError::CommandIdExhausted));
    assert_eq!(second.err(), Some(DesktopError::CommandIdExhausted));
    assert!(client.command_id_exhausted());
    assert!(clone.command_id_exhausted());
    assert!(client.snapshot().fatal_exit);
    assert_eq!(logs.matches("worker_command_id_sequence_exhausted").count(), 1);
    assert_eq!(client.command_submissions_in_flight(), 0);

    worker
        .shutdown(Duration::from_secs(1))
        .expect("out-of-band shutdown remains available after ID exhaustion");
}

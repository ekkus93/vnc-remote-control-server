use super::*;
use crate::framebuffer::FramebufferStore;
use remote_desktop_core::{DesktopError, KeyboardKey, MouseButton, WorkerCommand};
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::mpsc::sync_channel;
use std::time::{Duration, SystemTime};

use super::super::snapshot::WorkerSnapshot;

#[test]
fn bounded_command_queue_tracks_depth_and_rejection_without_payload_logging() {
    let (command_tx, _command_rx) = sync_channel(1);
    let snapshot = Arc::new(Mutex::new(WorkerSnapshot {
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
    }));
    let command_queue_depth = Arc::new(AtomicUsize::new(0));
    let pending_overload = Arc::new(AtomicU64::new(0));
    let client = WorkerClient {
        commands: command_tx,
        snapshot: Arc::clone(&snapshot),
        framebuffer: FramebufferStore::default(),
        clipboard: Arc::new(Mutex::new(None)),
        next_command_id: Arc::new(AtomicU64::new(1)),
        command_queue_depth: Arc::clone(&command_queue_depth),
        command_queue_capacity: 1,
        pending_overload: Arc::clone(&pending_overload),
        shutdown_requested: Arc::new(AtomicBool::new(false)),
    };

    let _first = client
        .submit(WorkerCommand::RequestFullRefresh)
        .expect("first command fits");
    assert_eq!(client.command_queue_depth(), 1);
    assert_eq!(client.command_queue_capacity(), 1);
    assert!(matches!(
        client.submit(WorkerCommand::TypeText {
            text: "queue-secret".to_owned(),
        }),
        Err(DesktopError::CommandQueueFull)
    ));
    assert_eq!(command_queue_depth.load(Ordering::Acquire), 1);
    assert_eq!(pending_overload.load(Ordering::Acquire), 1);
    assert_eq!(lock_unpoisoned(&snapshot).rejected_commands, 1);
}

#[test]
fn submit_rejects_after_shutdown_request_without_queue_mutation() {
    let (command_tx, _command_rx) = sync_channel(4);
    let snapshot = Arc::new(Mutex::new(WorkerSnapshot {
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
    }));
    let command_queue_depth = Arc::new(AtomicUsize::new(0));
    let pending_overload = Arc::new(AtomicU64::new(0));
    let client = WorkerClient {
        commands: command_tx,
        snapshot: Arc::clone(&snapshot),
        framebuffer: FramebufferStore::default(),
        clipboard: Arc::new(Mutex::new(None)),
        next_command_id: Arc::new(AtomicU64::new(1)),
        command_queue_depth: Arc::clone(&command_queue_depth),
        command_queue_capacity: 4,
        pending_overload: Arc::clone(&pending_overload),
        shutdown_requested: Arc::new(AtomicBool::new(false)),
    };

    client.request_shutdown();

    assert!(matches!(
        client.submit(WorkerCommand::RequestFullRefresh),
        Err(DesktopError::WorkerUnavailable)
    ));
    assert_eq!(command_queue_depth.load(Ordering::Acquire), 0);
    assert_eq!(pending_overload.load(Ordering::Acquire), 0);
    assert_eq!(lock_unpoisoned(&snapshot).rejected_commands, 0);
}

#[test]
fn shutdown_does_not_require_command_queue_capacity() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let factory_events = Arc::clone(&events);
    let mut config = settings();
    config.command_capacity = 1;
    // Wide enough that the worker thread is reliably still inside one
    // bounded native poll call (which always sleeps for the full
    // interval before returning) when the test fills the queue below,
    // without relying on microsecond-scale timing.
    config.poll_interval = Duration::from_millis(150);
    let worker = DesktopWorker::spawn_with_factory(config, move || {
        Ok(RecordingSession::new(Arc::clone(&factory_events), None))
    })
    .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);

    // The worker is now inside its next (bounded) poll call and is not
    // draining the command queue, so this submission reliably saturates
    // the single-slot queue instead of racing the drain loop.
    let stuck = client
        .submit(WorkerCommand::RequestFullRefresh)
        .expect("first command fits the single-slot queue");
    assert!(matches!(
        client.submit(WorkerCommand::RequestFullRefresh),
        Err(DesktopError::CommandQueueFull)
    ));

    worker
        .shutdown(Duration::from_secs(1))
        .expect("shutdown succeeds despite a saturated queue");

    assert_eq!(client.snapshot().state, ConnectionState::Stopped);
    assert!(!client.snapshot().fatal_exit);
    // The stuck ticket must resolve, not hang until its own timeout.
    assert!(matches!(
        stuck.wait(Duration::from_secs(1)),
        Err(DesktopError::WorkerUnavailable)
    ));
}

#[test]
fn drop_does_not_depend_on_shutdown_command_enqueue() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let factory_events = Arc::clone(&events);
    let mut config = settings();
    config.command_capacity = 1;
    config.poll_interval = Duration::from_millis(150);
    let worker = DesktopWorker::spawn_with_factory(config, move || {
        Ok(RecordingSession::new(Arc::clone(&factory_events), None))
    })
    .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);

    // Saturate the queue while the worker is stuck in a bounded poll
    // call, so a normal `WorkerCommand::Shutdown` enqueue would fail.
    let _stuck = client
        .submit(WorkerCommand::RequestFullRefresh)
        .expect("first command fits the single-slot queue");
    assert!(matches!(
        client.submit(WorkerCommand::RequestFullRefresh),
        Err(DesktopError::CommandQueueFull)
    ));

    let (done_tx, done_rx) = std::sync::mpsc::channel();
    let drop_thread = thread::spawn(move || {
        drop(worker);
        let _ = done_tx.send(());
    });
    done_rx
        .recv_timeout(Duration::from_secs(2))
        .expect("drop must not hang behind a saturated queue");
    drop_thread.join().expect("drop thread does not panic");

    wait_for_state(&client, ConnectionState::Stopped);
    assert!(!client.snapshot().fatal_exit);
}

#[test]
fn out_of_band_shutdown_releases_tracked_buttons_and_keys() {
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

    // Request shutdown directly through the out-of-band signal, not
    // through `DesktopWorker::shutdown()`, to prove the flag alone
    // drives cleanup.
    client.request_shutdown();
    wait_for_state(&client, ConnectionState::Stopped);

    assert_eq!(
        *lock_unpoisoned(&events),
        vec![
            InputEvent::Pointer(point, 1),
            InputEvent::Key(KeyboardKey::CtrlLeft, true),
            InputEvent::Pointer(point, 0),
            InputEvent::Key(KeyboardKey::CtrlLeft, false),
        ]
    );
    assert!(!client.snapshot().fatal_exit);

    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

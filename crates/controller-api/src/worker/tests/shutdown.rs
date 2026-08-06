use super::*;
use crate::framebuffer::FramebufferStore;
use remote_desktop_core::{DesktopError, KeyboardKey, MouseButton, WorkerCommand};
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::mpsc::{channel, sync_channel};
use std::time::{Duration, SystemTime};

use super::super::command::CommandEnvelope;
use super::super::desktop_worker::cleanup_startup_worker_after_timeout;
use super::super::run::{ReceivedCommandAction, classify_received_command};
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

#[test]
fn shutdown_timeout_is_enforced_when_worker_does_not_exit() {
    let (control, entered_rx, release_tx) = ControlledPoll::new();
    let factory_control = Arc::clone(&control);
    let worker = DesktopWorker::spawn_with_factory(settings(), move || {
        Ok(ControlledPollSession::new(Arc::clone(&factory_control)))
    })
    .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);
    entered_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("worker enters controlled poll");

    let started = Instant::now();
    assert!(matches!(
        worker.shutdown(Duration::from_millis(30)),
        Err(DesktopError::Timeout)
    ));
    assert!(started.elapsed() < Duration::from_secs(1));

    release_tx.send(()).expect("release controlled poll");
    wait_for_state(&client, ConnectionState::Stopped);
}

#[test]
fn startup_timeout_cleanup_does_not_unbounded_join() {
    let (exited_tx, exited_rx) = sync_channel(1);
    let (release_tx, release_rx) = sync_channel(1);
    let join = thread::spawn(move || {
        let _keep_exit_sender_open = exited_tx;
        let _ = release_rx.recv();
    });

    let started = Instant::now();
    cleanup_startup_worker_after_timeout(join, exited_rx, Duration::from_millis(25));
    assert!(started.elapsed() < Duration::from_secs(1));
    release_tx
        .send(())
        .expect("release detached cleanup thread");
}

#[test]
fn queued_command_received_after_shutdown_is_rejected_without_execution() {
    let (pending_tx, pending_rx) = sync_channel(4);
    let command_queue_depth = AtomicUsize::new(1);
    let shutdown_requested = AtomicBool::new(true);
    let (pending_completion_tx, pending_completion_rx) = sync_channel(1);
    pending_tx
        .send(CommandEnvelope {
            command: WorkerCommand::RequestFullRefresh,
            completion: pending_completion_tx,
        })
        .expect("pending command queued");
    let (received_completion_tx, received_completion_rx) = sync_channel(1);

    let action = classify_received_command(
        CommandEnvelope {
            command: WorkerCommand::SetClipboard {
                text: "must-not-execute".to_owned(),
            },
            completion: received_completion_tx,
        },
        &shutdown_requested,
        &pending_rx,
        &command_queue_depth,
    );

    assert!(matches!(action, ReceivedCommandAction::Stop));
    assert!(matches!(
        received_completion_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("received command completed"),
        Err(DesktopError::WorkerUnavailable)
    ));
    assert!(matches!(
        pending_completion_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("pending command completed"),
        Err(DesktopError::WorkerUnavailable)
    ));
    assert_eq!(command_queue_depth.load(Ordering::Acquire), 0);
}

#[test]
fn drop_logs_or_records_worker_join_timeout_without_blocking() {
    let (control, entered_rx, release_tx) = ControlledPoll::new();
    let factory_control = Arc::clone(&control);
    let worker = DesktopWorker::spawn_with_factory(settings(), move || {
        Ok(ControlledPollSession::new(Arc::clone(&factory_control)))
    })
    .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);
    entered_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("worker enters controlled poll");

    let (done_tx, done_rx) = channel();
    let started = Instant::now();
    thread::spawn(move || {
        drop(worker);
        let _ = done_tx.send(());
    });
    done_rx
        .recv_timeout(Duration::from_secs(3))
        .expect("drop returns after bounded timeout");
    assert!(started.elapsed() < Duration::from_secs(3));

    release_tx.send(()).expect("release controlled poll");
    wait_for_state(&client, ConnectionState::Stopped);
}

#[test]
fn deterministic_saturated_queue_shutdown_still_completes() {
    let (control, entered_rx, release_tx) = ControlledPoll::new();
    let factory_control = Arc::clone(&control);
    let mut config = settings();
    config.command_capacity = 1;
    let worker = DesktopWorker::spawn_with_factory(config, move || {
        Ok(ControlledPollSession::new(Arc::clone(&factory_control)))
    })
    .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);
    entered_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("worker enters controlled poll");

    let stuck = client
        .submit(WorkerCommand::RequestFullRefresh)
        .expect("first command fits the single-slot queue");
    assert!(matches!(
        client.submit(WorkerCommand::RequestFullRefresh),
        Err(DesktopError::CommandQueueFull)
    ));

    client.request_shutdown();
    release_tx.send(()).expect("release controlled poll");
    worker
        .shutdown(Duration::from_secs(1))
        .expect("shutdown completes after controlled poll release");

    assert_eq!(client.snapshot().state, ConnectionState::Stopped);
    assert!(!client.snapshot().fatal_exit);
    assert!(matches!(
        stuck.wait(Duration::from_secs(1)),
        Err(DesktopError::WorkerUnavailable)
    ));
    assert_eq!(control.command_calls(), 0);
}

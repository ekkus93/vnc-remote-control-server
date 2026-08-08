use super::*;
use crate::events::EventHub;
use crate::framebuffer::FramebufferStore;
use crate::observability::Metrics;
use crate::shutdown::{ProcessShutdownError, finalize_runtime};
use remote_desktop_core::{DesktopError, KeyboardKey, MouseButton, WorkerCommand};
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::mpsc::{TrySendError, channel, sync_channel};
use std::time::{Duration, SystemTime};

use super::super::command::CommandEnvelope;
use super::super::run::drain_pending_commands;
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
    let command_submissions_in_flight = Arc::new(AtomicUsize::new(0));
    let pending_overload = Arc::new(AtomicU64::new(0));
    let client = WorkerClient {
        commands: command_tx,
        snapshot: Arc::clone(&snapshot),
        framebuffer: FramebufferStore::default(),
        clipboard: Arc::new(Mutex::new(None)),
        next_command_id: Arc::new(AtomicU64::new(1)),
        command_id_exhausted: Arc::new(AtomicBool::new(false)),
        command_submissions_in_flight: Arc::clone(&command_submissions_in_flight),
        command_queue_capacity: 1,
        pending_overload: Arc::clone(&pending_overload),
        shutdown_requested: Arc::new(AtomicBool::new(false)),
    };

    let _first = client
        .submit(WorkerCommand::RequestFullRefresh)
        .expect("first command fits");
    assert_eq!(client.command_submissions_in_flight(), 1);
    assert_eq!(client.command_queue_capacity(), 1);
    assert!(matches!(
        client.submit(WorkerCommand::TypeText {
            text: "queue-secret".to_owned(),
        }),
        Err(DesktopError::CommandQueueFull)
    ));
    assert_eq!(command_submissions_in_flight.load(Ordering::Acquire), 1);
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
    let command_submissions_in_flight = Arc::new(AtomicUsize::new(0));
    let pending_overload = Arc::new(AtomicU64::new(0));
    let client = WorkerClient {
        commands: command_tx,
        snapshot: Arc::clone(&snapshot),
        framebuffer: FramebufferStore::default(),
        clipboard: Arc::new(Mutex::new(None)),
        next_command_id: Arc::new(AtomicU64::new(1)),
        command_id_exhausted: Arc::new(AtomicBool::new(false)),
        command_submissions_in_flight: Arc::clone(&command_submissions_in_flight),
        command_queue_capacity: 4,
        pending_overload: Arc::clone(&pending_overload),
        shutdown_requested: Arc::new(AtomicBool::new(false)),
    };

    client.request_shutdown();

    assert!(matches!(
        client.submit(WorkerCommand::RequestFullRefresh),
        Err(DesktopError::WorkerUnavailable)
    ));
    assert_eq!(command_submissions_in_flight.load(Ordering::Acquire), 0);
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
    let mut config = settings();
    config.startup_timeout = Duration::from_millis(25);
    let (hook_entered_tx, hook_entered_rx) = sync_channel(1);
    let (release_tx, release_rx) = sync_channel(1);

    let ((result, elapsed), logs) = crate::test_support::capture_logs(|| {
        let dispatch = crate::test_support::current_dispatch();
        let (result_tx, result_rx) = channel();
        let spawn_thread = thread::spawn(move || {
            let started = Instant::now();
            let result = tracing::dispatcher::with_default(&dispatch, || {
                DesktopWorker::spawn_with_factory_and_startup_hook(
                    config,
                    || Ok(healthy_session()),
                    move || {
                        let _ = hook_entered_tx.send(());
                        let _ = release_rx.recv();
                    },
                )
            });
            let _ = result_tx.send((result, started.elapsed()));
        });
        hook_entered_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("worker reaches startup hook");
        let result = result_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("public spawn returns before outer deadline");
        spawn_thread
            .join()
            .expect("startup harness thread does not panic");
        result
    });

    assert!(matches!(result, Err(DesktopError::Timeout)));
    assert!(elapsed < Duration::from_secs(1));
    assert!(logs.contains("desktop_worker_startup_cleanup_timeout"));
    release_tx
        .send(())
        .expect("release detached startup worker");
}

#[test]
fn queued_command_received_after_shutdown_is_rejected_without_execution() {
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

    let ticket = client
        .submit(WorkerCommand::SetClipboard {
            text: "must-not-execute".to_owned(),
        })
        .expect("command queues");
    client.request_shutdown();
    release_tx.send(()).expect("release controlled poll");
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker exits through requested shutdown");

    assert!(matches!(
        ticket.wait(Duration::from_secs(1)),
        Err(DesktopError::WorkerUnavailable)
    ));
    assert_eq!(control.command_calls(), 0);
    assert_eq!(client.command_submissions_in_flight(), 0);
    assert_eq!(client.snapshot().state, ConnectionState::Stopped);
    assert!(!client.snapshot().fatal_exit);
}

#[test]
fn drop_logs_or_records_worker_join_timeout_without_blocking() {
    let (((client, release_tx), elapsed), logs) = crate::test_support::capture_logs(|| {
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

        let dispatch = crate::test_support::current_dispatch();
        let (done_tx, done_rx) = channel();
        let started = Instant::now();
        let drop_thread = thread::spawn(move || {
            tracing::dispatcher::with_default(&dispatch, || drop(worker));
            let _ = done_tx.send(());
        });
        done_rx
            .recv_timeout(Duration::from_secs(3))
            .expect("drop returns after bounded timeout");
        drop_thread
            .join()
            .expect("worker drop thread does not panic");
        ((client, release_tx), started.elapsed())
    });

    assert!(elapsed < Duration::from_secs(3));
    assert!(logs.contains("desktop_worker_drop_shutdown_timeout"));
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

    let initial_refresh_calls = control.refresh_calls();
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
    assert_eq!(control.refresh_calls(), initial_refresh_calls);
    assert_eq!(client.command_submissions_in_flight(), 0);
}

#[test]
fn process_shutdown_remains_bounded_after_worker_timeout() {
    let (control, entered_rx, release_tx) = ControlledPoll::new();
    let factory_control = Arc::clone(&control);
    let mut worker = DesktopWorker::spawn_with_factory(settings(), move || {
        Ok(ControlledPollSession::new(Arc::clone(&factory_control)))
    })
    .expect("worker spawns");
    let client = worker.client();
    let worker_events = worker.take_events().expect("worker events transfer");
    let (_hub, bridge) = EventHub::start(
        worker_events,
        16,
        2,
        Duration::from_secs(1),
        Duration::from_secs(3),
        Metrics::default(),
    )
    .expect("event bridge starts");
    wait_for_state(&client, ConnectionState::Connected);
    entered_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("worker enters controlled poll");

    let started = Instant::now();
    let result = finalize_runtime(Ok(()), worker, bridge, Duration::from_millis(100));

    assert!(matches!(
        result,
        Err(ProcessShutdownError::Worker(DesktopError::Timeout))
    ));
    assert!(started.elapsed() < Duration::from_secs(1));
    release_tx.send(()).expect("release detached worker");
    wait_for_state(&client, ConnectionState::Stopped);
}

#[test]
fn startup_worker_panic_is_not_hidden_as_timeout() {
    let (result, logs) = crate::test_support::capture_logs(|| {
        DesktopWorker::spawn_with_factory_and_startup_hook(
            settings(),
            || Ok(healthy_session()),
            || panic!("test-only startup panic"),
        )
    });

    assert!(matches!(result, Err(DesktopError::WorkerUnavailable)));
    assert!(logs.contains("desktop_worker_join_failed"));
    assert!(logs.contains("desktop_worker_startup_join_failed"));
}

#[test]
fn internal_shutdown_envelope_cannot_underflow_queue_depth() {
    let depth = Arc::new(AtomicUsize::new(0));
    let envelope = CommandEnvelope::shutdown_without_waiter(Arc::clone(&depth));
    assert_eq!(depth.load(Ordering::Acquire), 1);
    drop(envelope);
    assert_eq!(depth.load(Ordering::Acquire), 0);
}

#[test]
fn compatibility_shutdown_drains_commands_behind_it_and_depth_returns_to_zero() {
    let (control, entered_rx, release_tx) = ControlledPoll::new();
    let factory_control = Arc::clone(&control);
    let mut config = settings();
    config.command_capacity = 4;
    let worker = DesktopWorker::spawn_with_factory(config, move || {
        Ok(ControlledPollSession::new(Arc::clone(&factory_control)))
    })
    .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);
    entered_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("worker enters controlled poll");

    let shutdown_ticket = client
        .submit(WorkerCommand::Shutdown)
        .expect("compatibility shutdown queues");
    let pending_ticket = client
        .submit(WorkerCommand::SetClipboard {
            text: "must-not-execute".to_owned(),
        })
        .expect("ordinary command queues behind shutdown");
    assert_eq!(client.command_submissions_in_flight(), 2);

    release_tx.send(()).expect("release controlled poll");
    wait_for_state(&client, ConnectionState::Stopped);

    shutdown_ticket
        .wait(Duration::from_secs(1))
        .expect("compatibility shutdown is acknowledged");
    worker
        .shutdown(Duration::from_secs(1))
        .expect("stopped worker joins after compatibility shutdown");
    assert!(matches!(
        pending_ticket.wait(Duration::from_secs(1)),
        Err(DesktopError::WorkerUnavailable)
    ));
    assert_eq!(control.command_calls(), 0);
    assert_eq!(client.command_submissions_in_flight(), 0);
    assert_eq!(client.snapshot().state, ConnectionState::Stopped);
    assert!(!client.snapshot().fatal_exit);
}

#[test]
fn receiver_drop_releases_all_queue_depth_permits() {
    let depth = Arc::new(AtomicUsize::new(0));
    let (sender, receiver) = sync_channel(4);
    for _ in 0..3 {
        let (completion, _result) = sync_channel(1);
        sender
            .send(CommandEnvelope::new(
                WorkerCommand::RequestFullRefresh,
                completion,
                Arc::clone(&depth),
            ))
            .expect("envelope queues");
    }
    assert_eq!(depth.load(Ordering::Acquire), 3);
    drop(receiver);
    assert_eq!(depth.load(Ordering::Acquire), 0);
}

#[test]
fn send_failure_releases_queue_depth_permit() {
    let full_depth = Arc::new(AtomicUsize::new(0));
    let (full_tx, full_rx) = sync_channel(1);
    let (first_completion, _first_result) = sync_channel(1);
    full_tx
        .send(CommandEnvelope::new(
            WorkerCommand::RequestFullRefresh,
            first_completion,
            Arc::clone(&full_depth),
        ))
        .expect("first envelope queues");
    let (second_completion, _second_result) = sync_channel(1);
    assert!(matches!(
        full_tx.try_send(CommandEnvelope::new(
            WorkerCommand::RequestFullRefresh,
            second_completion,
            Arc::clone(&full_depth),
        )),
        Err(TrySendError::Full(_))
    ));
    assert_eq!(full_depth.load(Ordering::Acquire), 1);
    drop(full_rx);
    assert_eq!(full_depth.load(Ordering::Acquire), 0);

    let disconnected_depth = Arc::new(AtomicUsize::new(0));
    let (disconnected_tx, disconnected_rx) = sync_channel(1);
    drop(disconnected_rx);
    let (completion, _result) = sync_channel(1);
    assert!(matches!(
        disconnected_tx.try_send(CommandEnvelope::new(
            WorkerCommand::RequestFullRefresh,
            completion,
            Arc::clone(&disconnected_depth),
        )),
        Err(TrySendError::Disconnected(_))
    ));
    assert_eq!(disconnected_depth.load(Ordering::Acquire), 0);
}

#[test]
fn envelope_enqueued_after_final_drain_releases_on_receiver_drop() {
    let depth = Arc::new(AtomicUsize::new(0));
    let (sender, receiver) = sync_channel(1);
    drain_pending_commands(&receiver);
    let (completion, _result) = sync_channel(1);
    sender
        .send(CommandEnvelope::new(
            WorkerCommand::RequestFullRefresh,
            completion,
            Arc::clone(&depth),
        ))
        .expect("envelope races after final drain");
    assert_eq!(depth.load(Ordering::Acquire), 1);
    drop(receiver);
    assert_eq!(depth.load(Ordering::Acquire), 0);
}

#[test]
fn submit_racing_final_shutdown_drain_converges_depth_to_zero() {
    let (control, entered_rx, release_poll_tx) = ControlledPoll::new();
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
    let initial_refresh_calls = control.refresh_calls();

    let submitting_client = client.clone();
    let (before_send_tx, before_send_rx) = sync_channel(1);
    let (release_send_tx, release_send_rx) = sync_channel(1);
    let (result_tx, result_rx) = channel();
    let submitter = thread::spawn(move || {
        let result = submitting_client.submit_with_before_send_hook(
            WorkerCommand::RequestFullRefresh,
            move || {
                let _ = before_send_tx.send(());
                let _ = release_send_rx.recv();
            },
        );
        let _ = result_tx.send(result);
    });
    before_send_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("submitter pauses after final shutdown check");

    client.request_shutdown();
    release_poll_tx.send(()).expect("release worker poll");
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker closes receiver after final drain");
    assert_eq!(client.snapshot().state, ConnectionState::Stopped);

    release_send_tx.send(()).expect("release paused submitter");
    assert!(matches!(
        result_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("submitter returns"),
        Err(DesktopError::WorkerUnavailable)
    ));
    submitter.join().expect("submitter does not panic");
    assert_eq!(client.command_submissions_in_flight(), 0);
    assert_eq!(control.refresh_calls(), initial_refresh_calls);
}

#[test]
fn shutdown_logs_incomplete_input_release_without_payloads() {
    let ((), logs) = crate::test_support::capture_logs(|| {
        let events = Arc::new(Mutex::new(Vec::new()));
        let factory_events = Arc::clone(&events);
        let worker = DesktopWorker::spawn_with_factory(settings(), move || {
            Ok(RecordingSession::new(Arc::clone(&factory_events), Some(2)))
        })
        .expect("worker spawns");
        let client = worker.client();
        wait_for_state(&client, ConnectionState::Connected);
        client
            .submit(WorkerCommand::SetKey {
                key: KeyboardKey::CtrlLeft,
                pressed: true,
            })
            .expect("key down queues")
            .wait(Duration::from_secs(1))
            .expect("key down executes");
        worker
            .shutdown(Duration::from_secs(1))
            .expect("shutdown remains non-panicking after release failure");
    });

    assert!(logs.contains("worker_input_release_incomplete"));
    assert!(logs.contains("worker_input_release_abandoned"));
    assert!(!logs.contains("CtrlLeft"));
}

#[test]
fn successful_shutdown_release_clears_all_tracked_input_without_failure_log() {
    let ((), logs) = crate::test_support::capture_logs(|| {
        let events = Arc::new(Mutex::new(Vec::new()));
        let factory_events = Arc::clone(&events);
        let worker = DesktopWorker::spawn_with_factory(settings(), move || {
            Ok(RecordingSession::new(Arc::clone(&factory_events), None))
        })
        .expect("worker spawns");
        let client = worker.client();
        wait_for_state(&client, ConnectionState::Connected);
        client
            .submit(WorkerCommand::SetKey {
                key: KeyboardKey::CtrlLeft,
                pressed: true,
            })
            .expect("key down queues")
            .wait(Duration::from_secs(1))
            .expect("key down executes");
        worker
            .shutdown(Duration::from_secs(1))
            .expect("shutdown succeeds");
    });

    assert!(!logs.contains("worker_input_release_incomplete"));
    assert!(!logs.contains("worker_input_release_abandoned"));
}

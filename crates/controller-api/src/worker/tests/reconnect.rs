use super::*;
use crate::framebuffer::{FramebufferError, FramebufferStore};
use crate::input::InputController;
use remote_desktop_core::{ClipboardSnapshot, Coordinate, DesktopError, KeyboardKey};
use std::collections::VecDeque;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc::sync_channel;
use std::time::Duration;

use super::super::helpers::reconnect_delay;
use super::super::loop_state::LoopState;
use super::super::snapshot::{WorkerEvent, WorkerSnapshot};

#[test]
fn transport_failure_reconnects_with_bounded_backoff() {
    let calls = Arc::new(AtomicUsize::new(0));
    let calls_for_factory = Arc::clone(&calls);
    let worker = DesktopWorker::spawn_with_factory(settings(), move || {
        if calls_for_factory.fetch_add(1, Ordering::SeqCst) == 0 {
            Err(NativeError::Disconnected)
        } else {
            Ok(healthy_session())
        }
    })
    .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);
    assert!(calls.load(Ordering::SeqCst) >= 2);
    assert_eq!(client.framebuffer_snapshot().expect("frame").revision(), 1);
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

#[test]
fn authentication_failure_waits_for_manual_reconnect() {
    let calls = Arc::new(AtomicUsize::new(0));
    let calls_for_factory = Arc::clone(&calls);
    let worker = DesktopWorker::spawn_with_factory(settings(), move || {
        calls_for_factory.fetch_add(1, Ordering::SeqCst);
        Err::<MockSession, _>(NativeError::NativeFailure {
            message: "VNC protocol initialization failed".to_owned(),
        })
    })
    .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::AuthenticationFailed);
    thread::sleep(Duration::from_millis(30));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        client.framebuffer_snapshot().err(),
        Some(FramebufferError::Unavailable)
    );
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

#[test]
fn confirmed_stall_invalidates_reconnects_and_advances_revision() {
    let calls = Arc::new(AtomicUsize::new(0));
    let calls_for_factory = Arc::clone(&calls);
    let modes = Arc::new(Mutex::new(VecDeque::from([
        MockMode::FirstMessageThenStall(false),
        MockMode::Healthy,
    ])));
    let modes_for_factory = Arc::clone(&modes);
    let worker = DesktopWorker::spawn_with_factory(settings(), move || {
        calls_for_factory.fetch_add(1, Ordering::SeqCst);
        let mode = lock_unpoisoned(&modes_for_factory)
            .pop_front()
            .unwrap_or(MockMode::Healthy);
        Ok(MockSession {
            mode: Arc::new(Mutex::new(mode)),
        })
    })
    .expect("worker spawns");
    let client = worker.client();
    let deadline = Instant::now() + Duration::from_secs(1);
    while Instant::now() < deadline && calls.load(Ordering::SeqCst) < 2 {
        thread::yield_now();
    }
    assert!(calls.load(Ordering::SeqCst) >= 2);
    wait_for_state(&client, ConnectionState::Connected);
    assert_eq!(client.framebuffer_snapshot().expect("frame").revision(), 2);
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

struct NeverCompleteSession;

impl WorkerSession for NeverCompleteSession {
    fn poll(&mut self, timeout: Duration) -> Result<PollOutcome, NativeError> {
        thread::sleep(timeout);
        Ok(PollOutcome::TimedOut)
    }

    fn request_full_refresh(&mut self) -> Result<(), NativeError> {
        Ok(())
    }

    fn display_info(&self) -> Result<NativeDisplayInfo, NativeError> {
        Ok(NativeDisplayInfo {
            width: 2,
            height: 2,
            revision: 0,
            complete: false,
        })
    }

    fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {
        Ok(NativeFramebuffer {
            width: 2,
            height: 2,
            revision: 0,
            bytes: vec![0; 16],
        })
    }

    fn clipboard(&self) -> Result<NativeClipboard, NativeError> {
        Err(NativeError::ClipboardUnavailable)
    }

    fn send_pointer(
        &mut self,
        _coordinate: Coordinate,
        _button_mask: u8,
    ) -> Result<(), NativeError> {
        Ok(())
    }

    fn send_key(&mut self, _key: KeyboardKey, _pressed: bool) -> Result<(), NativeError> {
        Ok(())
    }

    fn send_clipboard(&mut self, _text: &str) -> Result<(), NativeError> {
        Ok(())
    }
}

#[test]
fn pre_connected_confirmed_stall_reconnects_without_fatal_exit() {
    let calls = Arc::new(AtomicUsize::new(0));
    let calls_for_factory = Arc::clone(&calls);
    let mut config = settings();
    config.poll_interval = Duration::from_millis(2);
    config.stall_probe_after = Duration::from_millis(2);
    config.stall_confirm_after = Duration::from_millis(2);
    config.reconnect_min_delay = Duration::from_millis(1);
    config.reconnect_max_delay = Duration::from_millis(2);

    let worker = DesktopWorker::spawn_with_factory(config, move || {
        calls_for_factory.fetch_add(1, Ordering::SeqCst);
        Ok(NeverCompleteSession)
    })
    .expect("worker spawns");
    let client = worker.client();

    let deadline = Instant::now() + Duration::from_secs(1);
    while Instant::now() < deadline
        && calls.load(Ordering::SeqCst) < 2
        && client.snapshot().state != ConnectionState::Stopped
    {
        thread::yield_now();
    }

    assert!(calls.load(Ordering::SeqCst) >= 2, "stall did not reconnect");
    assert!(!client.snapshot().fatal_exit, "recoverable stall became fatal");
    assert_ne!(client.snapshot().state, ConnectionState::Stopped);
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

#[test]
fn illegal_transition_is_logged_and_does_not_silently_poison_health() {
    let settings = settings();
    let snapshot = Arc::new(Mutex::new(WorkerSnapshot {
        state: ConnectionState::Starting,
        started_at: std::time::SystemTime::now(),
        connected_at: None,
        last_message_at: None,
        reconnect_attempts: 0,
        last_failure: None,
        framebuffer_revision: None,
        rejected_commands: 0,
        dropped_events: 0,
        fatal_exit: false,
    }));
    let clipboard = Arc::new(Mutex::new(None::<ClipboardSnapshot>));
    let (events_tx, _events_rx) = sync_channel::<WorkerEvent>(4);

    let (result, logs) = crate::test_support::capture_logs(|| {
        let mut state = LoopState::<MockSession> {
            settings: &settings,
            snapshot: &snapshot,
            events: &events_tx,
            framebuffer: FramebufferStore::default(),
            clipboard: &clipboard,
            event_sequence: 0,
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
        };
        state.transition(ConnectionState::Degraded)
    });

    assert_eq!(result, Err(DesktopError::Protocol));
    assert!(!lock_unpoisoned(&snapshot).fatal_exit);
    assert!(logs.contains("worker_illegal_state_transition"));
}

#[test]
fn mismatched_native_frame_never_reaches_connected() {
    struct MismatchedSession;

    impl WorkerSession for MismatchedSession {
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
                revision: 5,
                complete: true,
            })
        }

        fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {
            Ok(NativeFramebuffer {
                width: 2,
                height: 2,
                revision: 4,
                bytes: vec![0; 16],
            })
        }

        fn clipboard(&self) -> Result<NativeClipboard, NativeError> {
            Err(NativeError::ClipboardUnavailable)
        }

        fn send_pointer(
            &mut self,
            _coordinate: Coordinate,
            _button_mask: u8,
        ) -> Result<(), NativeError> {
            Ok(())
        }

        fn send_key(&mut self, _key: KeyboardKey, _pressed: bool) -> Result<(), NativeError> {
            Ok(())
        }

        fn send_clipboard(&mut self, _text: &str) -> Result<(), NativeError> {
            Ok(())
        }
    }

    let worker = DesktopWorker::spawn_with_factory(settings(), || Ok(MismatchedSession))
        .expect("worker spawns");
    let client = worker.client();
    thread::sleep(Duration::from_millis(30));
    assert_ne!(client.snapshot().state, ConnectionState::Connected);
    assert_eq!(
        client.framebuffer_snapshot().err(),
        Some(FramebufferError::Unavailable)
    );
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

#[test]
fn reconnect_delay_is_exponential_jittered_and_bounded() {
    let settings = settings();
    let first = reconnect_delay(&settings, 1);
    let second = reconnect_delay(&settings, 2);
    let far = reconnect_delay(&settings, 30);
    assert!(first >= settings.reconnect_min_delay);
    assert!(second >= settings.reconnect_min_delay * 2);
    assert!(first <= settings.reconnect_max_delay);
    assert!(second <= settings.reconnect_max_delay);
    assert!(far <= settings.reconnect_max_delay);
}

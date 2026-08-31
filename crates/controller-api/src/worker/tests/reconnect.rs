use super::*;
use crate::framebuffer::{FramebufferError, FramebufferStore};
use crate::input::InputController;
use remote_desktop_core::{ClipboardSnapshot, Coordinate, DesktopError, KeyboardKey};
use std::collections::VecDeque;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc::{SyncSender, sync_channel};
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
fn protocol_initialization_failure_reconnects_as_protocol_failure() {
    let calls = Arc::new(AtomicUsize::new(0));
    let calls_for_factory = Arc::clone(&calls);
    let mut config = settings();
    config.reconnect_min_delay = Duration::from_millis(1);
    config.reconnect_max_delay = Duration::from_millis(2);
    let worker = DesktopWorker::spawn_with_factory(config, move || {
        if calls_for_factory.fetch_add(1, Ordering::SeqCst) == 0 {
            Err(NativeError::ProtocolInitializationFailed)
        } else {
            Ok(healthy_session())
        }
    })
    .expect("worker spawns");
    let client = worker.client();

    wait_for_state(&client, ConnectionState::Connected);
    assert!(calls.load(Ordering::SeqCst) >= 2);
    assert_ne!(
        client.snapshot().state,
        ConnectionState::AuthenticationFailed
    );
    assert!(!client.snapshot().fatal_exit);

    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

#[test]
fn confirmed_stall_invalidates_reconnects_and_advances_revision() {
    let calls = Arc::new(AtomicUsize::new(0));
    let calls_for_factory = Arc::clone(&calls);
    let (factory_call_tx, factory_call_rx) = sync_channel(4);
    let modes = Arc::new(Mutex::new(VecDeque::from([
        MockMode::FirstMessageThenStall(false),
        MockMode::Healthy,
    ])));
    let modes_for_factory = Arc::clone(&modes);
    let mut config = settings();
    config.poll_interval = Duration::from_millis(1);
    config.stall_probe_after = Duration::from_millis(1);
    config.stall_confirm_after = Duration::from_millis(1);
    config.reconnect_min_delay = Duration::from_millis(1);
    config.reconnect_max_delay = Duration::from_millis(2);

    let worker = DesktopWorker::spawn_with_factory(config, move || {
        let invocation = calls_for_factory.fetch_add(1, Ordering::SeqCst);
        factory_call_tx
            .send(invocation)
            .expect("factory invocation remains observable");
        let mode = lock_unpoisoned(&modes_for_factory)
            .pop_front()
            .unwrap_or(MockMode::Healthy);
        Ok(MockSession {
            mode: Arc::new(Mutex::new(mode)),
        })
    })
    .expect("worker spawns");
    let client = worker.client();

    assert_eq!(
        factory_call_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("initial factory invocation is observed"),
        0
    );
    assert_eq!(
        factory_call_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("stall reconnect factory invocation is observed"),
        1
    );

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
    let (factory_call_tx, factory_call_rx) = sync_channel(4);
    let mut config = settings();
    config.poll_interval = Duration::from_millis(1);
    config.stall_probe_after = Duration::from_millis(1);
    config.stall_confirm_after = Duration::from_millis(1);
    config.reconnect_min_delay = Duration::from_millis(1);
    config.reconnect_max_delay = Duration::from_millis(2);

    let worker = DesktopWorker::spawn_with_factory(config, move || {
        let invocation = calls_for_factory.fetch_add(1, Ordering::SeqCst);
        factory_call_tx
            .send(invocation)
            .expect("factory invocation remains observable");
        if invocation == 0 {
            Ok(NeverCompleteSession)
        } else {
            Ok(NeverCompleteSession)
        }
    })
    .expect("worker spawns");
    let client = worker.client();

    assert_eq!(
        factory_call_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("initial factory invocation is observed"),
        0
    );
    assert_eq!(
        factory_call_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("stall reconnect factory invocation is observed"),
        1
    );
    assert!(!client.snapshot().fatal_exit);
    assert!(calls.load(Ordering::SeqCst) >= 2);

    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

#[test]
fn reconnect_delay_is_exponential_jittered_and_bounded() {
    let min = Duration::from_millis(100);
    let max = Duration::from_millis(800);
    let jitter = 100;
    let one = reconnect_delay(min, max, jitter, 1);
    let two = reconnect_delay(min, max, jitter, 2);
    let many = reconnect_delay(min, max, jitter, 100);
    assert!(one >= min && one <= Duration::from_millis(110));
    assert!(two >= Duration::from_millis(200) && two <= Duration::from_millis(220));
    assert!(many >= max && many <= Duration::from_millis(880));
}

#[test]
fn matching_native_frame_positive_control_reaches_connected() {
    let settings = settings();
    let mut session = MockSession::new(MockMode::Healthy);
    let (events_tx, _events_rx) = sync_channel(8);
    let snapshot = Arc::new(Mutex::new(WorkerSnapshot::starting()));
    let framebuffer = FramebufferStore::new(1024);
    let clipboard = Arc::new(Mutex::new(None::<ClipboardSnapshot>));
    let mut state = LoopState::new(
        &mut session,
        &events_tx,
        Arc::clone(&snapshot),
        &framebuffer,
        &clipboard,
        &settings,
    );

    state.on_connected().expect("matching frame connects");
    assert_eq!(state.connection_state(), ConnectionState::Connected);
    assert!(framebuffer.snapshot().is_ok());
}

#[test]
fn mismatched_native_frame_never_reaches_connected() {
    let settings = settings();
    let mut session = MockSession::new(MockMode::MismatchedFramebuffer);
    let (events_tx, _events_rx) = sync_channel(8);
    let snapshot = Arc::new(Mutex::new(WorkerSnapshot::starting()));
    let framebuffer = FramebufferStore::new(1024);
    let clipboard = Arc::new(Mutex::new(None::<ClipboardSnapshot>));
    let mut state = LoopState::new(
        &mut session,
        &events_tx,
        Arc::clone(&snapshot),
        &framebuffer,
        &clipboard,
        &settings,
    );

    let error = state.on_connected().expect_err("mismatch is rejected");
    assert!(matches!(error, DesktopError::Protocol));
    assert_ne!(state.connection_state(), ConnectionState::Connected);
    assert!(matches!(
        framebuffer.snapshot(),
        Err(FramebufferError::Unavailable)
    ));
}

#[test]
fn illegal_transition_is_logged_and_does_not_silently_poison_health() {
    let settings = settings();
    let mut session = MockSession::new(MockMode::Healthy);
    let (events_tx, _events_rx) = sync_channel(8);
    let snapshot = Arc::new(Mutex::new(WorkerSnapshot::starting()));
    let framebuffer = FramebufferStore::new(1024);
    let clipboard = Arc::new(Mutex::new(None::<ClipboardSnapshot>));
    let mut state = LoopState::new(
        &mut session,
        &events_tx,
        Arc::clone(&snapshot),
        &framebuffer,
        &clipboard,
        &settings,
    );

    let (_, logs) = crate::test_support::capture_logs(|| {
        state
            .transition(ConnectionState::AuthenticationFailed)
            .expect("starting to authentication failed is legal");
        state
            .transition(ConnectionState::Connected)
            .expect_err("terminal auth state rejects transition");
    });
    assert_eq!(
        lock_unpoisoned(&snapshot).state,
        ConnectionState::AuthenticationFailed
    );
    assert!(logs.contains("worker_illegal_state_transition"));
}

use super::*;
use crate::framebuffer::FramebufferError;
use remote_desktop_core::{Coordinate, KeyboardKey};
use std::collections::VecDeque;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Duration;

use super::super::helpers::reconnect_delay;

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
        thread::sleep(Duration::from_millis(1));
    }
    assert!(calls.load(Ordering::SeqCst) >= 2);
    wait_for_state(&client, ConnectionState::Connected);
    assert_eq!(client.framebuffer_snapshot().expect("frame").revision(), 2);
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
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

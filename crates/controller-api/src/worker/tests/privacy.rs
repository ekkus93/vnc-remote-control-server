use super::*;
use crate::framebuffer::FramebufferStore;
use crate::input::InputController;
use crate::worker::WorkerFailureKind;
use libvnc_adapter::{
    NativeClipboard, NativeDisplayInfo, NativeError, NativeFramebuffer, PollOutcome,
};
use remote_desktop_core::{
    ClipboardSnapshot, ConnectionState, Coordinate, DisplayInfo, KeyboardKey, MouseButton,
};
use std::sync::mpsc::sync_channel;
use std::time::{Duration, Instant, SystemTime};

use super::super::loop_state::LoopState;
use super::super::snapshot::{WorkerEvent, WorkerSnapshot};

const X_SENTINEL: u32 = 3_001;
const Y_SENTINEL: u32 = 3_007;
const KEY_SENTINEL: char = '§';
const PASSWORD_SENTINEL: &str = "vnc-password-private-e74a91c3";

struct ReleaseFailingSession {
    fail_releases: bool,
}

impl WorkerSession for ReleaseFailingSession {
    fn poll(&mut self, _timeout: Duration) -> Result<PollOutcome, NativeError> {
        Ok(PollOutcome::TimedOut)
    }

    fn request_full_refresh(&mut self) -> Result<(), NativeError> {
        Ok(())
    }

    fn display_info(&self) -> Result<NativeDisplayInfo, NativeError> {
        Err(NativeError::FramebufferUnavailable)
    }

    fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {
        Err(NativeError::FramebufferUnavailable)
    }

    fn clipboard(&self) -> Result<NativeClipboard, NativeError> {
        Err(NativeError::ClipboardUnavailable)
    }

    fn send_pointer(
        &mut self,
        _coordinate: Coordinate,
        _button_mask: u8,
    ) -> Result<(), NativeError> {
        if self.fail_releases {
            Err(NativeError::NativeFailure {
                message: "test-only release failure".to_owned(),
            })
        } else {
            Ok(())
        }
    }

    fn send_key(&mut self, _key: KeyboardKey, _pressed: bool) -> Result<(), NativeError> {
        if self.fail_releases {
            Err(NativeError::NativeFailure {
                message: "test-only release failure".to_owned(),
            })
        } else {
            Ok(())
        }
    }

    fn send_clipboard(&mut self, _text: &str) -> Result<(), NativeError> {
        Ok(())
    }
}

#[test]
fn input_release_json_logs_exclude_key_and_coordinate_sentinels() {
    let settings = settings();
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
    let clipboard = Arc::new(Mutex::new(None::<ClipboardSnapshot>));
    let (events_tx, _events_rx) = sync_channel::<WorkerEvent>(8);
    let display = DisplayInfo::new(4_096, 4_096, 24, 1, true).expect("bounded display");
    let coordinate = Coordinate::new(X_SENTINEL, Y_SENTINEL, display).expect("sentinel coordinate");
    let mut session = ReleaseFailingSession {
        fail_releases: false,
    };
    let mut input = InputController::default();
    input
        .set_button(&mut session, coordinate, display, MouseButton::Left, true)
        .expect("button press tracked");
    input
        .set_key(&mut session, KeyboardKey::Printable(KEY_SENTINEL), true)
        .expect("key press tracked");
    session.fail_releases = true;

    let mut state = LoopState {
        settings: &settings,
        snapshot: &snapshot,
        events: &events_tx,
        framebuffer: FramebufferStore::default(),
        clipboard: &clipboard,
        event_sequence: 0,
        event_terminal_failure: false,
        shutdown_cleanup: false,
        session: Some(session),
        last_native_revision: None,
        last_native_clipboard_revision: None,
        clipboard_revision: 0,
        clipboard_decode_failed: false,
        input,
        next_connect: None,
        reconnect_attempt: 0,
        connected_since: Some(Instant::now()),
        last_message: Instant::now(),
        probe_sent: None,
        last_manual_reconnect: None,
    };

    let (result, records) = crate::test_support::capture_json_logs(|| state.invalidate());
    result.expect("cleanup publishes without event-channel failure");

    assert!(crate::test_support::json_logs_contain(
        &records,
        "worker_input_release_incomplete"
    ));
    assert!(crate::test_support::json_logs_contain(
        &records,
        "worker_input_release_abandoned"
    ));
    for sentinel in [
        KEY_SENTINEL.to_string(),
        X_SENTINEL.to_string(),
        Y_SENTINEL.to_string(),
    ] {
        assert!(
            !crate::test_support::json_logs_contain(&records, &sentinel),
            "structured log leaked sentinel"
        );
    }
}

#[test]
fn protocol_initialization_failure_logs_exclude_vnc_password_sentinel() {
    let mut config = settings();
    config.native.password = SecretString::from(PASSWORD_SENTINEL);
    config.reconnect_min_delay = Duration::from_secs(1);
    config.reconnect_max_delay = Duration::from_secs(1);

    let (failure_snapshot, records) = crate::test_support::capture_json_logs(|| {
        let worker = DesktopWorker::spawn_with_factory(config, || {
            Err::<MockSession, _>(NativeError::ProtocolInitializationFailed)
        })
        .expect("worker spawns");
        let client = worker.client();
        let deadline = Instant::now() + Duration::from_secs(1);
        loop {
            let snapshot = client.snapshot();
            if snapshot.last_failure == Some(WorkerFailureKind::Protocol) {
                break;
            }
            assert!(
                Instant::now() < deadline,
                "protocol failure was not recorded"
            );
            thread::yield_now();
        }
        let failure_snapshot = client.snapshot();
        worker
            .shutdown(Duration::from_secs(1))
            .expect("worker joins after protocol failure");
        failure_snapshot
    });

    assert_eq!(
        failure_snapshot.last_failure,
        Some(WorkerFailureKind::Protocol)
    );
    assert!(crate::test_support::json_logs_contain(
        &records,
        "worker_failure_recorded"
    ));
    assert!(
        !crate::test_support::json_logs_contain(&records, PASSWORD_SENTINEL),
        "structured worker log leaked VNC password sentinel"
    );
}

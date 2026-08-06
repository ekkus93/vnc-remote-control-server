use super::*;
use crate::framebuffer::FramebufferStore;
use crate::input::InputController;
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

const X_SENTINEL: u32 = 1_234_567;
const Y_SENTINEL: u32 = 1_345_678;
const KEY_SENTINEL: char = '§';

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
    let display = DisplayInfo::new(2_000_000, 2_000_000, 24, 1, true).expect("large display");
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

    let ((), records) = crate::test_support::capture_json_logs(|| state.invalidate());

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

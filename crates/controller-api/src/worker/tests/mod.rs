use super::client::WorkerClient;
use super::desktop_worker::DesktopWorker;
use super::helpers::lock_unpoisoned;
use super::session::WorkerSession;
use super::settings::WorkerSettings;
use libvnc_adapter::{
    NativeClientConfig, NativeClipboard, NativeDisplayInfo, NativeError, NativeFramebuffer,
    PollOutcome, SecretString,
};
use remote_desktop_core::{ConnectionState, Coordinate, KeyboardKey, MAX_FRAMEBUFFER_BYTES};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc::{Receiver, SyncSender, sync_channel};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

mod clipboard_and_input;
mod lifecycle;
mod metric_semantics;
mod outcome_panic;
mod privacy;
mod reconnect;
mod shutdown;
mod v2_regressions;

pub(super) struct MockSession {
    mode: Arc<Mutex<MockMode>>,
}

pub(super) enum MockMode {
    Healthy,
    FirstMessageThenStall(bool),
}

impl WorkerSession for MockSession {
    fn poll(&mut self, timeout: Duration) -> Result<PollOutcome, NativeError> {
        thread::sleep(timeout);
        let mut mode = lock_unpoisoned(&self.mode);
        match &mut *mode {
            MockMode::Healthy => Ok(PollOutcome::MessageProcessed),
            MockMode::FirstMessageThenStall(sent) if !*sent => {
                *sent = true;
                Ok(PollOutcome::MessageProcessed)
            }
            MockMode::FirstMessageThenStall(_) => Ok(PollOutcome::TimedOut),
        }
    }

    fn request_full_refresh(&mut self) -> Result<(), NativeError> {
        Ok(())
    }

    fn display_info(&self) -> Result<NativeDisplayInfo, NativeError> {
        Ok(NativeDisplayInfo {
            width: 2,
            height: 2,
            revision: 1,
            complete: true,
        })
    }

    fn clipboard(&self) -> Result<NativeClipboard, NativeError> {
        Err(NativeError::ClipboardUnavailable)
    }

    fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {
        Ok(NativeFramebuffer {
            width: 2,
            height: 2,
            revision: 1,
            bytes: vec![1, 2, 3, 0, 4, 5, 6, 0, 7, 8, 9, 0, 10, 11, 12, 0],
        })
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

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) enum InputEvent {
    Pointer(Coordinate, u8),
    Key(KeyboardKey, bool),
    Clipboard(String),
}

pub(super) struct RecordingSession {
    events: Arc<Mutex<Vec<InputEvent>>>,
    input_calls: usize,
    fail_on_input_call: Option<usize>,
    clipboard: Option<NativeClipboard>,
}

impl RecordingSession {
    pub(super) fn new(
        events: Arc<Mutex<Vec<InputEvent>>>,
        fail_on_input_call: Option<usize>,
    ) -> Self {
        Self {
            events,
            input_calls: 0,
            fail_on_input_call,
            clipboard: None,
        }
    }

    pub(super) fn with_clipboard(
        events: Arc<Mutex<Vec<InputEvent>>>,
        text: &str,
        revision: u64,
    ) -> Self {
        Self {
            events,
            input_calls: 0,
            fail_on_input_call: None,
            clipboard: Some(NativeClipboard {
                text: text.to_owned(),
                revision,
            }),
        }
    }

    fn record(&mut self, event: InputEvent) -> Result<(), NativeError> {
        self.input_calls += 1;
        if self.fail_on_input_call == Some(self.input_calls) {
            return Err(NativeError::NativeFailure {
                message: "test-only worker input failure".to_owned(),
            });
        }
        lock_unpoisoned(&self.events).push(event);
        Ok(())
    }
}

impl WorkerSession for RecordingSession {
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
            revision: 1,
            complete: true,
        })
    }

    fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {
        Ok(NativeFramebuffer {
            width: 2,
            height: 2,
            revision: 1,
            bytes: vec![1, 2, 3, 0, 4, 5, 6, 0, 7, 8, 9, 0, 10, 11, 12, 0],
        })
    }

    fn clipboard(&self) -> Result<NativeClipboard, NativeError> {
        self.clipboard
            .clone()
            .ok_or(NativeError::ClipboardUnavailable)
    }

    fn send_pointer(&mut self, coordinate: Coordinate, button_mask: u8) -> Result<(), NativeError> {
        self.record(InputEvent::Pointer(coordinate, button_mask))
    }

    fn send_key(&mut self, key: KeyboardKey, pressed: bool) -> Result<(), NativeError> {
        self.record(InputEvent::Key(key, pressed))
    }

    fn send_clipboard(&mut self, text: &str) -> Result<(), NativeError> {
        self.record(InputEvent::Clipboard(text.to_owned()))
    }
}

pub(super) struct ControlledPoll {
    entered_tx: Mutex<SyncSender<usize>>,
    release_rx: Mutex<Receiver<()>>,
    poll_count: AtomicUsize,
    command_calls: AtomicUsize,
    refresh_calls: AtomicUsize,
}

impl ControlledPoll {
    pub(super) fn new() -> (Arc<Self>, Receiver<usize>, SyncSender<()>) {
        let (entered_tx, entered_rx) = sync_channel(8);
        let (release_tx, release_rx) = sync_channel(8);
        (
            Arc::new(Self {
                entered_tx: Mutex::new(entered_tx),
                release_rx: Mutex::new(release_rx),
                poll_count: AtomicUsize::new(0),
                command_calls: AtomicUsize::new(0),
                refresh_calls: AtomicUsize::new(0),
            }),
            entered_rx,
            release_tx,
        )
    }

    pub(super) fn command_calls(&self) -> usize {
        self.command_calls.load(Ordering::Acquire)
    }

    pub(super) fn refresh_calls(&self) -> usize {
        self.refresh_calls.load(Ordering::Acquire)
    }
}

pub(super) struct ControlledPollSession {
    control: Arc<ControlledPoll>,
}

impl ControlledPollSession {
    pub(super) fn new(control: Arc<ControlledPoll>) -> Self {
        Self { control }
    }
}

impl WorkerSession for ControlledPollSession {
    fn poll(&mut self, _timeout: Duration) -> Result<PollOutcome, NativeError> {
        let poll_number = self.control.poll_count.fetch_add(1, Ordering::AcqRel) + 1;
        if poll_number == 1 {
            return Ok(PollOutcome::MessageProcessed);
        }
        let _ = lock_unpoisoned(&self.control.entered_tx).send(poll_number);
        let _ = lock_unpoisoned(&self.control.release_rx).recv();
        Ok(PollOutcome::TimedOut)
    }

    fn request_full_refresh(&mut self) -> Result<(), NativeError> {
        self.control.refresh_calls.fetch_add(1, Ordering::AcqRel);
        Ok(())
    }

    fn display_info(&self) -> Result<NativeDisplayInfo, NativeError> {
        Ok(NativeDisplayInfo {
            width: 2,
            height: 2,
            revision: 1,
            complete: true,
        })
    }

    fn clipboard(&self) -> Result<NativeClipboard, NativeError> {
        Err(NativeError::ClipboardUnavailable)
    }

    fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {
        Ok(NativeFramebuffer {
            width: 2,
            height: 2,
            revision: 1,
            bytes: vec![1, 2, 3, 0, 4, 5, 6, 0, 7, 8, 9, 0, 10, 11, 12, 0],
        })
    }

    fn send_pointer(
        &mut self,
        _coordinate: Coordinate,
        _button_mask: u8,
    ) -> Result<(), NativeError> {
        self.control.command_calls.fetch_add(1, Ordering::AcqRel);
        Ok(())
    }

    fn send_key(&mut self, _key: KeyboardKey, _pressed: bool) -> Result<(), NativeError> {
        self.control.command_calls.fetch_add(1, Ordering::AcqRel);
        Ok(())
    }

    fn send_clipboard(&mut self, _text: &str) -> Result<(), NativeError> {
        self.control.command_calls.fetch_add(1, Ordering::AcqRel);
        Ok(())
    }
}

pub(super) fn settings() -> WorkerSettings {
    WorkerSettings {
        native: NativeClientConfig {
            host: "desktop".to_owned(),
            port: 5901,
            password: SecretString::from("test-only"),
            connect_timeout: Duration::from_secs(1),
            read_timeout: Duration::from_secs(1),
        },
        command_capacity: 4,
        event_capacity: 16,
        maximum_framebuffer_bytes: MAX_FRAMEBUFFER_BYTES,
        poll_interval: Duration::from_millis(1),
        startup_timeout: Duration::from_secs(1),
        reconnect_min_delay: Duration::from_millis(2),
        reconnect_max_delay: Duration::from_millis(20),
        reconnect_jitter_per_mille: 100,
        stable_connection_reset: Duration::from_millis(20),
        manual_reconnect_interval: Duration::from_millis(50),
        stall_probe_after: Duration::from_millis(5),
        stall_confirm_after: Duration::from_millis(5),
    }
}

pub(super) fn healthy_session() -> MockSession {
    MockSession {
        mode: Arc::new(Mutex::new(MockMode::Healthy)),
    }
}

pub(super) fn wait_for_state(client: &WorkerClient, expected: ConnectionState) {
    let deadline = Instant::now() + Duration::from_secs(1);
    while Instant::now() < deadline {
        if client.snapshot().state == expected {
            return;
        }
        thread::sleep(Duration::from_millis(1));
    }
    panic!("worker did not reach {expected:?}: {:?}", client.snapshot());
}

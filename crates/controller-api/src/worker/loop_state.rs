use super::helpers::{
    classify_native_error, lock_unpoisoned, reconnect_delay, validate_native_frame,
};
use super::session::WorkerSession;
use super::snapshot::{WorkerEvent, WorkerSnapshot};
use super::{WorkerFailureKind, WorkerSettings};
use crate::framebuffer::FramebufferStore;
use crate::input::InputController;
use libvnc_adapter::{NativeDisplayInfo, NativeError, PollOutcome};
use remote_desktop_core::{
    ClipboardSnapshot, ConnectionState, DesktopError, DesktopEventKind, DisplayInfo, WorkerCommand,
    validate_clipboard,
};
use std::sync::mpsc::{SyncSender, TrySendError};
use std::sync::{Arc, Mutex};
use std::time::{Instant, SystemTime};

pub(super) struct LoopState<'a, S> {
    pub(super) settings: &'a WorkerSettings,
    pub(super) snapshot: &'a Arc<Mutex<WorkerSnapshot>>,
    pub(super) events: &'a SyncSender<WorkerEvent>,
    pub(super) framebuffer: FramebufferStore,
    pub(super) clipboard: &'a Arc<Mutex<Option<ClipboardSnapshot>>>,
    pub(super) event_sequence: u64,
    pub(super) session: Option<S>,
    pub(super) last_native_revision: Option<u64>,
    pub(super) last_native_clipboard_revision: Option<u64>,
    pub(super) clipboard_revision: u64,
    pub(super) clipboard_decode_failed: bool,
    pub(super) input: InputController,
    pub(super) next_connect: Option<Instant>,
    pub(super) reconnect_attempt: u32,
    pub(super) connected_since: Option<Instant>,
    pub(super) last_message: Instant,
    pub(super) probe_sent: Option<Instant>,
    pub(super) last_manual_reconnect: Option<Instant>,
}

impl<S: WorkerSession> LoopState<'_, S> {
    pub(super) fn transition(&mut self, next: ConnectionState) -> Result<(), DesktopError> {
        let previous = {
            let mut current = lock_unpoisoned(self.snapshot);
            if !current.state.can_transition_to(next) {
                current.fatal_exit = true;
                return Err(DesktopError::Protocol);
            }
            let previous = current.state;
            current.state = next;
            previous
        };
        tracing::info!(from = ?previous, to = ?next, "worker_state_transition");
        self.publish(DesktopEventKind::ConnectionState { state: next });
        Ok(())
    }

    pub(super) fn publish(&mut self, kind: DesktopEventKind) {
        let Some(sequence) = self.event_sequence.checked_add(1) else {
            lock_unpoisoned(self.snapshot).fatal_exit = true;
            return;
        };
        self.event_sequence = sequence;
        let event = WorkerEvent {
            sequence,
            observed_at: SystemTime::now(),
            kind,
        };
        match self.events.try_send(event) {
            Ok(()) => {}
            Err(TrySendError::Full(_)) => {
                let mut current = lock_unpoisoned(self.snapshot);
                current.dropped_events = current.dropped_events.saturating_add(1);
                tracing::warn!("worker_event_queue_saturated");
            }
            Err(TrySendError::Disconnected(_)) => {}
        }
    }

    pub(super) fn record_failure(&self, failure: WorkerFailureKind) {
        lock_unpoisoned(self.snapshot).last_failure = Some(failure);
        tracing::warn!(failure = ?failure, "worker_failure_recorded");
    }

    pub(super) fn begin_connect(&mut self) -> Result<(), DesktopError> {
        let state = if self.reconnect_attempt == 0 {
            ConnectionState::Connecting
        } else {
            ConnectionState::Reconnecting
        };
        self.transition(state)
    }

    pub(super) fn connected_message(
        &mut self,
        display: NativeDisplayInfo,
    ) -> Result<(), DesktopError> {
        self.last_message = Instant::now();
        self.probe_sent = None;
        lock_unpoisoned(self.snapshot).last_message_at = Some(SystemTime::now());

        if display.complete && self.last_native_revision != Some(display.revision) {
            let native = self
                .session
                .as_ref()
                .ok_or(DesktopError::WorkerUnavailable)?
                .framebuffer()?;
            validate_native_frame(display, &native)?;
            let revision =
                self.framebuffer
                    .replace_native_rgbx(native.width, native.height, &native.bytes)?;
            self.last_native_revision = Some(native.revision);
            let mut snapshot = lock_unpoisoned(self.snapshot);
            let previous_revision = snapshot.framebuffer_revision.replace(revision);
            drop(snapshot);
            if previous_revision != Some(revision) {
                self.publish(DesktopEventKind::FramebufferRevision { revision });
            }
        }

        if display.complete
            && self.last_native_revision == Some(display.revision)
            && lock_unpoisoned(self.snapshot).state != ConnectionState::Connected
        {
            self.transition(ConnectionState::Connected)?;
            let mut current = lock_unpoisoned(self.snapshot);
            current.connected_at = Some(SystemTime::now());
            current.last_failure = None;
            self.connected_since = Some(Instant::now());
        }
        self.refresh_clipboard()?;

        if self.connected_since.is_some_and(|since| {
            Instant::now().saturating_duration_since(since) >= self.settings.stable_connection_reset
        }) {
            self.reconnect_attempt = 0;
            lock_unpoisoned(self.snapshot).reconnect_attempts = 0;
        }
        Ok(())
    }

    pub(super) fn refresh_clipboard(&mut self) -> Result<(), DesktopError> {
        let clipboard = self
            .session
            .as_ref()
            .ok_or(DesktopError::WorkerUnavailable)?
            .clipboard();
        match clipboard {
            Ok(native) if self.last_native_clipboard_revision == Some(native.revision) => Ok(()),
            Ok(native) => {
                self.last_native_clipboard_revision = Some(native.revision);
                self.clipboard_decode_failed = false;
                if validate_clipboard(&native.text).is_err() {
                    self.record_failure(WorkerFailureKind::Protocol);
                    self.publish(DesktopEventKind::ProtocolError);
                    return Ok(());
                }
                let revision = self
                    .clipboard_revision
                    .checked_add(1)
                    .ok_or(DesktopError::Protocol)?;
                self.clipboard_revision = revision;
                *lock_unpoisoned(self.clipboard) = Some(ClipboardSnapshot {
                    text: Arc::from(native.text),
                    revision,
                    updated_at: SystemTime::now(),
                });
                self.publish(DesktopEventKind::ClipboardRevision { revision });
                Ok(())
            }
            Err(NativeError::ClipboardUnavailable) => Ok(()),
            Err(NativeError::ClipboardNotUtf8) => {
                if !self.clipboard_decode_failed {
                    self.clipboard_decode_failed = true;
                    self.record_failure(WorkerFailureKind::Protocol);
                    self.publish(DesktopEventKind::ProtocolError);
                }
                Ok(())
            }
            Err(error) => Err(error.into()),
        }
    }

    pub(super) fn release_input(&mut self) {
        if let Some(session) = self.session.as_mut() {
            let report = self.input.release_all(session);
            if !report.is_complete() {
                tracing::warn!(
                    pointer_release_failed = report.pointer_release_failed(),
                    key_release_failures = report.key_release_failures(),
                    "worker_input_release_incomplete"
                );
            }
        }
    }

    fn abandon_input(&mut self) {
        let report = self.input.abandon();
        if !report.is_complete() {
            tracing::warn!(
                pointer_release_abandoned = report.pointer_release_failed(),
                key_releases_abandoned = report.key_release_failures(),
                "worker_input_release_abandoned"
            );
        }
    }

    pub(super) fn invalidate(&mut self) {
        self.release_input();
        self.session = None;
        self.abandon_input();
        self.last_native_revision = None;
        self.last_native_clipboard_revision = None;
        self.clipboard_decode_failed = false;
        let store_changed = self.framebuffer.invalidate();
        let had_frame = lock_unpoisoned(self.snapshot)
            .framebuffer_revision
            .take()
            .is_some();
        if store_changed || had_frame {
            self.publish(DesktopEventKind::FramebufferInvalidated);
        }
        self.connected_since = None;
        self.probe_sent = None;
    }

    pub(super) fn schedule_reconnect(&mut self) {
        self.reconnect_attempt = self.reconnect_attempt.saturating_add(1);
        lock_unpoisoned(self.snapshot).reconnect_attempts = self.reconnect_attempt;
        if lock_unpoisoned(self.snapshot).state != ConnectionState::Disconnected {
            let _ = self.transition(ConnectionState::Disconnected);
        }
        let _ = self.transition(ConnectionState::Reconnecting);
        let delay = reconnect_delay(self.settings, self.reconnect_attempt);
        tracing::info!(
            attempt = self.reconnect_attempt,
            delay_ms = u64::try_from(delay.as_millis()).unwrap_or(u64::MAX),
            "worker_reconnect_scheduled"
        );
        self.next_connect = Some(Instant::now() + delay);
    }

    pub(super) fn manual_reconnect(&mut self) -> Result<(), DesktopError> {
        let now = Instant::now();
        if self.last_manual_reconnect.is_some_and(|last| {
            now.saturating_duration_since(last) < self.settings.manual_reconnect_interval
        }) {
            return Err(DesktopError::ReconnectRateLimited);
        }
        let state = lock_unpoisoned(self.snapshot).state;
        if matches!(
            state,
            ConnectionState::Starting | ConnectionState::Connecting
        ) {
            return Err(DesktopError::WorkerUnavailable);
        }
        self.last_manual_reconnect = Some(now);
        self.invalidate();
        self.reconnect_attempt = self.reconnect_attempt.saturating_add(1);
        lock_unpoisoned(self.snapshot).reconnect_attempts = self.reconnect_attempt;
        self.transition(ConnectionState::Reconnecting)?;
        self.next_connect = Some(now);
        Ok(())
    }

    pub(super) fn current_display(&self) -> Result<DisplayInfo, DesktopError> {
        if self.session.is_none() {
            return Err(DesktopError::WorkerUnavailable);
        }
        Ok(self.framebuffer.current_snapshot()?.display_info())
    }

    pub(super) fn execute(&mut self, command: WorkerCommand) -> Result<(), DesktopError> {
        match command {
            WorkerCommand::MovePointer { coordinate } => {
                let display = self.current_display()?;
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input.move_pointer(session, coordinate, display)
            }
            WorkerCommand::SetButton {
                coordinate,
                button,
                pressed,
            } => {
                let display = self.current_display()?;
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input
                    .set_button(session, coordinate, display, button, pressed)
            }
            WorkerCommand::Click { coordinate, button } => {
                let display = self.current_display()?;
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input.click(session, coordinate, display, button)
            }
            WorkerCommand::DoubleClick {
                coordinate,
                button,
                interval_ms,
            } => {
                let display = self.current_display()?;
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input
                    .double_click(session, coordinate, display, button, interval_ms)
            }
            WorkerCommand::Scroll {
                coordinate,
                delta_x,
                delta_y,
            } => {
                let display = self.current_display()?;
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input
                    .scroll(session, coordinate, display, delta_x, delta_y)
            }
            WorkerCommand::SetKey { key, pressed } => {
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input.set_key(session, key, pressed)
            }
            WorkerCommand::Chord { keys } => {
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input.chord(session, &keys)
            }
            WorkerCommand::SetClipboard { text } => {
                validate_clipboard(&text)?;
                self.session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?
                    .send_clipboard(&text)
                    .map_err(DesktopError::from)
            }
            WorkerCommand::RequestFullRefresh => self
                .session
                .as_mut()
                .ok_or(DesktopError::WorkerUnavailable)?
                .request_full_refresh()
                .map_err(DesktopError::from),
            WorkerCommand::TypeText { text } => {
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input.type_text(session, &text).map(|_| ())
            }
            WorkerCommand::Reconnect | WorkerCommand::Shutdown => Err(DesktopError::Protocol),
        }
    }

    pub(super) fn poll(&mut self) -> Result<(), DesktopError> {
        let outcome = self
            .session
            .as_mut()
            .ok_or(DesktopError::WorkerUnavailable)?
            .poll(self.settings.poll_interval);
        match outcome {
            Ok(PollOutcome::MessageProcessed) => {
                let display = self
                    .session
                    .as_ref()
                    .ok_or(DesktopError::WorkerUnavailable)?
                    .display_info()?;
                if self.connected_message(display).is_err() {
                    self.record_failure(WorkerFailureKind::Protocol);
                    self.invalidate();
                    self.schedule_reconnect();
                }
                Ok(())
            }
            Ok(PollOutcome::TimedOut) => {
                let now = Instant::now();
                let idle = now.saturating_duration_since(self.last_message);
                if self.probe_sent.is_none() && idle >= self.settings.stall_probe_after {
                    self.session
                        .as_mut()
                        .ok_or(DesktopError::WorkerUnavailable)?
                        .request_full_refresh()?;
                    self.probe_sent = Some(now);
                } else if self.probe_sent.is_some_and(|sent| {
                    now.saturating_duration_since(sent) >= self.settings.stall_confirm_after
                }) {
                    self.record_failure(WorkerFailureKind::Timeout);
                    tracing::warn!("worker_stall_timeout");
                    self.transition(ConnectionState::Degraded)?;
                    self.invalidate();
                    self.schedule_reconnect();
                }
                Ok(())
            }
            Err(error) => {
                self.record_failure(classify_native_error(&error));
                self.invalidate();
                self.schedule_reconnect();
                Ok(())
            }
        }
    }
}

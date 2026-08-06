use super::command::CommandEnvelope;
use super::helpers::lock_unpoisoned;
use super::snapshot::WorkerSnapshot;
use crate::framebuffer::{
    FramebufferError, FramebufferMetadata, FramebufferSnapshot, FramebufferStore,
};
use crate::screenshot::{ScreenshotError, ScreenshotService};
use remote_desktop_core::{ClipboardSnapshot, DesktopError, WorkerCommand};
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::mpsc::{Receiver, RecvTimeoutError, SyncSender, TrySendError, sync_channel};
use std::sync::{Arc, Mutex};
use std::time::Duration;

/// Accepted worker command and its completion receiver.
pub struct CommandTicket {
    id: u64,
    completion: Receiver<Result<(), DesktopError>>,
}

impl CommandTicket {
    /// Process-local command identifier.
    pub const fn id(&self) -> u64 {
        self.id
    }

    /// Waits for command execution completion within a caller-supplied deadline.
    pub fn wait(self, timeout: Duration) -> Result<(), DesktopError> {
        match self.completion.recv_timeout(timeout) {
            Ok(result) => result,
            Err(RecvTimeoutError::Timeout) => Err(DesktopError::Timeout),
            Err(RecvTimeoutError::Disconnected) => Err(DesktopError::WorkerUnavailable),
        }
    }
}

/// Cloneable bounded command, status, and framebuffer-read handle.
#[derive(Clone)]
pub struct WorkerClient {
    pub(super) commands: SyncSender<CommandEnvelope>,
    pub(super) snapshot: Arc<Mutex<WorkerSnapshot>>,
    pub(super) framebuffer: FramebufferStore,
    pub(super) clipboard: Arc<Mutex<Option<ClipboardSnapshot>>>,
    pub(super) next_command_id: Arc<AtomicU64>,
    pub(super) command_submissions_in_flight: Arc<AtomicUsize>,
    pub(super) command_queue_capacity: usize,
    pub(super) pending_overload: Arc<AtomicU64>,
    /// Out-of-band shutdown signal. Authoritative for shutdown correctness:
    /// unlike enqueueing `WorkerCommand::Shutdown`, storing into this flag
    /// can never fail because the normal bounded command queue is full.
    pub(super) shutdown_requested: Arc<AtomicBool>,
}

impl WorkerClient {
    /// Requests shutdown out-of-band. Never fails and never touches the
    /// bounded command queue.
    pub(super) fn request_shutdown(&self) {
        self.shutdown_requested.store(true, Ordering::Release);
    }

    /// Returns whether out-of-band shutdown has been requested.
    pub(super) fn shutdown_requested(&self) -> bool {
        self.shutdown_requested.load(Ordering::Acquire)
    }

    /// Submits one command without touching native adapter state.
    pub fn submit(&self, command: WorkerCommand) -> Result<CommandTicket, DesktopError> {
        self.submit_inner(command, || {})
    }

    #[cfg(test)]
    pub(super) fn submit_with_before_send_hook<F>(
        &self,
        command: WorkerCommand,
        before_send: F,
    ) -> Result<CommandTicket, DesktopError>
    where
        F: FnOnce(),
    {
        self.submit_inner(command, before_send)
    }

    fn submit_inner<F>(
        &self,
        command: WorkerCommand,
        before_send: F,
    ) -> Result<CommandTicket, DesktopError>
    where
        F: FnOnce(),
    {
        if self.shutdown_requested() {
            return Err(DesktopError::WorkerUnavailable);
        }
        let id = self
            .next_command_id
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
                value.checked_add(1)
            })
            .map_err(|_| DesktopError::WorkerUnavailable)?;
        let (completion_tx, completion_rx) = sync_channel(1);
        let envelope = CommandEnvelope::new(
            command,
            completion_tx,
            Arc::clone(&self.command_submissions_in_flight),
        );
        // Re-check immediately before enqueueing to narrow the race between
        // a concurrent shutdown request and this submission.
        if self.shutdown_requested() {
            return Err(DesktopError::WorkerUnavailable);
        }
        before_send();
        match self.commands.try_send(envelope) {
            Ok(()) => Ok(CommandTicket {
                id,
                completion: completion_rx,
            }),
            Err(TrySendError::Full(_)) => {
                self.pending_overload.fetch_add(1, Ordering::Relaxed);
                let mut current = lock_unpoisoned(&self.snapshot);
                current.rejected_commands = current.rejected_commands.saturating_add(1);
                tracing::warn!(
                    queue_capacity = self.command_queue_capacity,
                    "worker_command_queue_saturated"
                );
                Err(DesktopError::CommandQueueFull)
            }
            Err(TrySendError::Disconnected(_)) => Err(DesktopError::WorkerUnavailable),
        }
    }

    /// Returns one coherent status snapshot.
    pub fn snapshot(&self) -> WorkerSnapshot {
        lock_unpoisoned(&self.snapshot).clone()
    }

    /// Returns the number of command submissions whose permit remains owned.
    /// This includes submissions between envelope construction and `try_send`
    /// and can therefore transiently exceed the channel capacity.
    pub fn command_submissions_in_flight(&self) -> usize {
        self.command_submissions_in_flight.load(Ordering::Acquire)
    }

    /// Returns the configured bounded command queue capacity.
    pub const fn command_queue_capacity(&self) -> usize {
        self.command_queue_capacity
    }

    /// Returns coherent framebuffer metadata without copying pixels.
    pub fn framebuffer_metadata(&self) -> FramebufferMetadata {
        self.framebuffer.metadata()
    }

    /// Returns one immutable complete current framebuffer snapshot.
    pub fn framebuffer_snapshot(&self) -> Result<FramebufferSnapshot, FramebufferError> {
        self.framebuffer.current_snapshot()
    }

    /// Returns the last valid inbound clipboard snapshot.
    pub fn clipboard_snapshot(&self) -> Result<ClipboardSnapshot, DesktopError> {
        lock_unpoisoned(&self.clipboard)
            .clone()
            .ok_or(DesktopError::ClipboardUnavailable)
    }

    /// Creates a bounded screenshot service over the worker-owned framebuffer.
    pub fn screenshot_service(
        &self,
        process_instance: &str,
        maximum_concurrent_encodes: usize,
        encode_timeout: Duration,
    ) -> Result<ScreenshotService, ScreenshotError> {
        ScreenshotService::new(
            self.framebuffer.clone(),
            process_instance,
            maximum_concurrent_encodes,
            encode_timeout,
        )
    }
}

use super::command::CommandEnvelope;
use super::helpers::lock_unpoisoned;
use super::outcome::{CommandOutcomeLookup, CommandOutcomeRegistry};
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
    ///
    /// A timeout only means this waiter did not observe a terminal result in
    /// time. The command remains represented in the shared outcome registry and
    /// may still complete afterward.
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
    pub(super) command_id_exhausted: Arc<AtomicBool>,
    pub(super) command_submissions_in_flight: Arc<AtomicUsize>,
    pub(super) command_queue_capacity: usize,
    pub(super) pending_overload: Arc<AtomicU64>,
    pub(super) command_outcomes: CommandOutcomeRegistry,
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

    /// Returns whether the process-local command identifier sequence is terminal.
    pub fn command_id_exhausted(&self) -> bool {
        self.command_id_exhausted.load(Ordering::Acquire)
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

    #[cfg(test)]
    pub(super) fn force_command_sequence_for_test(&self, next: u64) {
        self.next_command_id.store(next, Ordering::Release);
        self.command_id_exhausted.store(false, Ordering::Release);
    }

    fn mark_command_id_exhausted(&self) {
        if !self.command_id_exhausted.swap(true, Ordering::AcqRel) {
            lock_unpoisoned(&self.snapshot).fatal_exit = true;
            tracing::error!("worker_command_id_sequence_exhausted");
        }
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
        if self.command_id_exhausted() {
            return Err(DesktopError::CommandIdExhausted);
        }

        // Reserve retention capacity and allocate the sequence value under one
        // registry lock. Capacity failure therefore cannot consume an ID that
        // was never retained and later make that numerical hole look expired.
        let id = match self.command_outcomes.reserve_next(&self.next_command_id) {
            Ok(id) => id,
            Err(DesktopError::CommandIdExhausted) => {
                self.mark_command_id_exhausted();
                return Err(DesktopError::CommandIdExhausted);
            }
            Err(error) => return Err(error),
        };

        let (completion_tx, completion_rx) = sync_channel(1);
        let envelope = CommandEnvelope::new_with_id(
            id,
            command,
            completion_tx,
            Arc::clone(&self.command_submissions_in_flight),
        );
        // Re-check immediately before enqueueing to narrow the race between
        // a concurrent shutdown request and this submission.
        if self.shutdown_requested() {
            let error = DesktopError::WorkerUnavailable;
            self.command_outcomes.mark_rejected(id, &error);
            return Err(error);
        }
        if self.command_id_exhausted() {
            let error = DesktopError::CommandIdExhausted;
            self.command_outcomes.mark_rejected(id, &error);
            return Err(error);
        }
        before_send();

        // Publish queue admission state before `try_send`: the receiving worker
        // can dequeue immediately once the send succeeds. A failed send below
        // replaces this transient state with an explicit pre-admission reject.
        self.command_outcomes.mark_queued(id);
        match self.commands.try_send(envelope) {
            Ok(()) => Ok(CommandTicket {
                id,
                completion: completion_rx,
            }),
            Err(TrySendError::Full(_)) => {
                let error = DesktopError::CommandQueueFull;
                self.command_outcomes.mark_rejected(id, &error);
                self.pending_overload.fetch_add(1, Ordering::Relaxed);
                let mut current = lock_unpoisoned(&self.snapshot);
                current.rejected_commands = current.rejected_commands.saturating_add(1);
                tracing::warn!(
                    queue_capacity = self.command_queue_capacity,
                    "worker_command_queue_saturated"
                );
                Err(error)
            }
            Err(TrySendError::Disconnected(_)) => {
                let error = DesktopError::WorkerUnavailable;
                self.command_outcomes.mark_rejected(id, &error);
                Err(error)
            }
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

    /// Returns one sanitized retained command outcome.
    pub fn command_outcome(&self, command_id: u64) -> CommandOutcomeLookup {
        self.command_outcomes.lookup(command_id)
    }

    /// Returns the fixed retained command-outcome capacity.
    pub fn command_outcome_capacity(&self) -> usize {
        self.command_outcomes.capacity()
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

use remote_desktop_core::{DesktopError, WorkerCommand};
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc::{SyncSender, sync_channel};

/// Ownership token for one envelope counted in the bounded command queue.
///
/// The counter is incremented exactly once at construction and decremented
/// exactly once when the envelope is dequeued, rejected, drained, or dropped
/// with the receiver. This keeps accounting coherent across shutdown races.
pub(super) struct QueueDepthPermit {
    depth: Arc<AtomicUsize>,
    released: bool,
}

impl QueueDepthPermit {
    fn acquire(depth: Arc<AtomicUsize>) -> Self {
        depth.fetch_add(1, Ordering::AcqRel);
        Self {
            depth,
            released: false,
        }
    }

    fn release(&mut self) {
        if self.released {
            return;
        }
        self.released = true;
        if self
            .depth
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |current| {
                current.checked_sub(1)
            })
            .is_err()
        {
            tracing::error!("worker_command_queue_depth_underflow");
        }
    }
}

impl Drop for QueueDepthPermit {
    fn drop(&mut self) {
        self.release();
    }
}

pub(super) struct CommandEnvelope {
    pub(super) command: WorkerCommand,
    pub(super) completion: SyncSender<Result<(), DesktopError>>,
    queue_depth: Option<QueueDepthPermit>,
}

impl CommandEnvelope {
    pub(super) fn new(
        command: WorkerCommand,
        completion: SyncSender<Result<(), DesktopError>>,
        command_queue_depth: Arc<AtomicUsize>,
    ) -> Self {
        Self {
            command,
            completion,
            queue_depth: Some(QueueDepthPermit::acquire(command_queue_depth)),
        }
    }

    pub(super) fn shutdown_without_waiter(command_queue_depth: Arc<AtomicUsize>) -> Self {
        let (completion, _receiver) = sync_channel(1);
        Self::new(WorkerCommand::Shutdown, completion, command_queue_depth)
    }

    /// Releases queue ownership immediately after a successful dequeue.
    pub(super) fn release_queue_depth(&mut self) {
        drop(self.queue_depth.take());
    }
}

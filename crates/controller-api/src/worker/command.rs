use remote_desktop_core::{DesktopError, WorkerCommand};
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc::{SyncSender, sync_channel};

/// Ownership token for one command submission in flight.
///
/// The counter is incremented exactly once at construction and decremented
/// exactly once when the envelope is dequeued, rejected, drained, or dropped
/// with the receiver. It intentionally includes the interval before `try_send`
/// and therefore does not represent channel occupancy.
pub(super) struct SubmissionPermit {
    submissions_in_flight: Arc<AtomicUsize>,
    released: bool,
}

impl SubmissionPermit {
    fn acquire(submissions_in_flight: Arc<AtomicUsize>) -> Self {
        submissions_in_flight.fetch_add(1, Ordering::AcqRel);
        Self {
            submissions_in_flight,
            released: false,
        }
    }

    fn release(&mut self) {
        if self.released {
            return;
        }
        self.released = true;
        if self
            .submissions_in_flight
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |current| {
                current.checked_sub(1)
            })
            .is_err()
        {
            tracing::error!("worker_command_submissions_in_flight_underflow");
        }
    }
}

impl Drop for SubmissionPermit {
    fn drop(&mut self) {
        self.release();
    }
}

pub(super) struct CommandEnvelope {
    pub(super) command: WorkerCommand,
    pub(super) completion: SyncSender<Result<(), DesktopError>>,
    submission: Option<SubmissionPermit>,
}

impl CommandEnvelope {
    pub(super) fn new(
        command: WorkerCommand,
        completion: SyncSender<Result<(), DesktopError>>,
        submissions_in_flight: Arc<AtomicUsize>,
    ) -> Self {
        Self {
            command,
            completion,
            submission: Some(SubmissionPermit::acquire(submissions_in_flight)),
        }
    }

    pub(super) fn shutdown_without_waiter(submissions_in_flight: Arc<AtomicUsize>) -> Self {
        let (completion, _receiver) = sync_channel(1);
        Self::new(WorkerCommand::Shutdown, completion, submissions_in_flight)
    }

    /// Releases submission ownership immediately after a successful dequeue.
    pub(super) fn release_submission(&mut self) {
        drop(self.submission.take());
    }
}

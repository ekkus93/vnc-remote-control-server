use super::WorkerFailureKind;
use remote_desktop_core::{ConnectionState, DesktopEventKind};
use std::sync::mpsc::{Receiver, RecvError, RecvTimeoutError};
use std::time::{Duration, SystemTime};

/// Read-only worker status snapshot.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkerSnapshot {
    /// Current public lifecycle state.
    pub state: ConnectionState,
    /// Worker start time.
    pub started_at: SystemTime,
    /// Most recent successful connection time.
    pub connected_at: Option<SystemTime>,
    /// Most recent processed server message time.
    pub last_message_at: Option<SystemTime>,
    /// Consecutive reconnect attempts.
    pub reconnect_attempts: u32,
    /// Last bounded failure category.
    pub last_failure: Option<WorkerFailureKind>,
    /// Current coherent process-local framebuffer revision, when available.
    pub framebuffer_revision: Option<u64>,
    /// Commands rejected because the bounded queue was full.
    pub rejected_commands: u64,
    /// Events dropped because the bounded event queue was full.
    pub dropped_events: u64,
    /// Whether the worker exited without an orderly shutdown command.
    pub fatal_exit: bool,
}

/// One redacted worker event.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkerEvent {
    /// Monotonically increasing process-local event sequence.
    pub sequence: u64,
    /// Event observation time.
    pub observed_at: SystemTime,
    /// Payload-free public event kind.
    pub kind: DesktopEventKind,
}

/// Event receiver separated from the cloneable command client.
pub struct WorkerEvents {
    pub(super) receiver: Receiver<WorkerEvent>,
}

impl WorkerEvents {
    /// Waits indefinitely for one worker event.
    pub fn recv(&self) -> Result<WorkerEvent, RecvError> {
        self.receiver.recv()
    }

    /// Waits for one worker event.
    pub fn recv_timeout(&self, timeout: Duration) -> Result<WorkerEvent, RecvTimeoutError> {
        self.receiver.recv_timeout(timeout)
    }
}

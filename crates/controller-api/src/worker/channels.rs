use super::command::CommandEnvelope;
use super::snapshot::WorkerEvent;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize};
use std::sync::mpsc::{Receiver, SyncSender};

pub(super) struct WorkerChannels {
    pub(super) commands: Receiver<CommandEnvelope>,
    pub(super) events: SyncSender<WorkerEvent>,
    pub(super) startup: SyncSender<()>,
    pub(super) command_queue_depth: Arc<AtomicUsize>,
    pub(super) pending_overload: Arc<AtomicU64>,
    pub(super) shutdown_requested: Arc<AtomicBool>,
    pub(super) worker_exited: SyncSender<()>,
}

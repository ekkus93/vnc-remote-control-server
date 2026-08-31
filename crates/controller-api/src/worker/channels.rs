use super::command::CommandEnvelope;
use super::outcome::CommandOutcomeRegistry;
use super::snapshot::WorkerEvent;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU64};
use std::sync::mpsc::{Receiver, SyncSender};

pub(super) struct WorkerChannels {
    pub(super) commands: Receiver<CommandEnvelope>,
    pub(super) events: SyncSender<WorkerEvent>,
    pub(super) startup: SyncSender<()>,
    pub(super) pending_overload: Arc<AtomicU64>,
    pub(super) shutdown_requested: Arc<AtomicBool>,
    pub(super) command_outcomes: CommandOutcomeRegistry,
    pub(super) worker_exited: SyncSender<()>,
}

use remote_desktop_core::{DesktopError, WorkerCommand};
use std::sync::mpsc::{SyncSender, sync_channel};

pub(super) struct CommandEnvelope {
    pub(super) command: WorkerCommand,
    pub(super) completion: SyncSender<Result<(), DesktopError>>,
}

impl CommandEnvelope {
    pub(super) fn shutdown_without_waiter() -> Self {
        let (completion, _receiver) = sync_channel(1);
        Self {
            command: WorkerCommand::Shutdown,
            completion,
        }
    }
}

//! Single-session desktop worker lifecycle.
//!
//! The worker owns the native adapter and canonical framebuffer writer on
//! exactly one dedicated thread. API and asynchronous runtime tasks interact
//! only through bounded channels, shared status snapshots, immutable
//! framebuffer snapshots, and bounded screenshot services.
//!
//! The implementation is split across submodules by responsibility:
//! configuration and status types (`settings`, `snapshot`), the cloneable
//! client handle (`client`), the owning runtime and its lifecycle
//! (`desktop_worker`), the internal command envelope and channel bundle
//! (`command`, `channels`), retained command outcomes (`outcome`), the
//! native-adapter abstraction (`session`), the single-threaded event loop state
//! machine (`loop_state`, `run`), and small pure helpers (`helpers`).

mod channels;
mod client;
mod command;
mod desktop_worker;
mod helpers;
mod loop_state;
mod outcome;
mod run;
mod session;
mod settings;
mod snapshot;
#[cfg(test)]
mod tests;

pub use client::{CommandTicket, WorkerClient};
pub use desktop_worker::DesktopWorker;
pub use outcome::{
    COMMAND_OUTCOME_CAPACITY, CommandOutcomeLookup, CommandOutcomeRecord, CommandOutcomeState,
};
pub use settings::{WorkerFailureKind, WorkerSettings};
pub use snapshot::{WorkerEvent, WorkerEvents, WorkerSnapshot};

use super::helpers::lock_unpoisoned;
use remote_desktop_core::DesktopError;
use std::collections::VecDeque;
use std::sync::{Arc, Mutex};

/// Maximum process-local command outcome records retained for later inspection.
///
/// The registry never evicts a non-terminal record. When all slots are occupied
/// by accepted commands that have not reached a terminal state, new submissions
/// fail before worker admission rather than making an unresolved command
/// uninspectable.
pub const COMMAND_OUTCOME_CAPACITY: usize = 4096;

/// Public lifecycle state for one process-local command identifier.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CommandOutcomeState {
    /// Reserved and accepted for worker admission but not yet dequeued.
    Queued,
    /// Dequeued by the worker and eligible to touch the remote desktop.
    Running,
    /// Completed successfully.
    Succeeded,
    /// Completed with a known operation failure.
    Failed,
    /// Could not reach normal completion because worker/session execution ended.
    Aborted,
    /// Rejected before worker admission.
    Rejected,
}

impl CommandOutcomeState {
    /// Stable wire name used by the authenticated command-status endpoint.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Running => "running",
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Aborted => "aborted",
            Self::Rejected => "rejected",
        }
    }

    const fn terminal(self) -> bool {
        matches!(
            self,
            Self::Succeeded | Self::Failed | Self::Aborted | Self::Rejected
        )
    }
}

/// Sanitized retained outcome. Command payloads are deliberately never stored.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommandOutcomeRecord {
    command_id: u64,
    state: CommandOutcomeState,
    failure: Option<&'static str>,
}

impl CommandOutcomeRecord {
    /// Process-local command identifier.
    pub const fn command_id(&self) -> u64 {
        self.command_id
    }

    /// Current lifecycle state.
    pub const fn state(&self) -> CommandOutcomeState {
        self.state
    }

    /// Sanitized failure classification, if this state has one.
    pub const fn failure(&self) -> Option<&'static str> {
        self.failure
    }

    /// Whether blindly retrying the original mutation is known to be safe.
    ///
    /// Only a command rejected before admission is retry-safe at this generic
    /// layer. Every accepted command is conservatively non-retry-safe even when
    /// its eventual operation failure is known.
    pub const fn retry_safe(&self) -> bool {
        matches!(self.state, CommandOutcomeState::Rejected)
    }
}

/// Result of looking up a process-local command identifier.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CommandOutcomeLookup {
    /// The retained record is still available.
    Found(CommandOutcomeRecord),
    /// The identifier was once retained but its terminal record was evicted.
    Expired,
    /// The identifier has not been reserved by this process instance.
    Unknown,
}

#[derive(Debug)]
struct CommandOutcomeRegistryState {
    entries: VecDeque<CommandOutcomeRecord>,
    expired_through: u64,
    highest_reserved: u64,
}

/// Cloneable bounded registry shared by HTTP submitters and the worker thread.
#[derive(Clone)]
pub struct CommandOutcomeRegistry {
    capacity: usize,
    state: Arc<Mutex<CommandOutcomeRegistryState>>,
}

impl CommandOutcomeRegistry {
    pub(super) fn new(capacity: usize) -> Self {
        assert!(capacity > 0, "command outcome capacity must be nonzero");
        Self {
            capacity,
            state: Arc::new(Mutex::new(CommandOutcomeRegistryState {
                entries: VecDeque::with_capacity(capacity),
                expired_through: 0,
                highest_reserved: 0,
            })),
        }
    }

    /// Reserves a record before queue admission.
    ///
    /// Terminal records may be evicted oldest-first. Non-terminal records are
    /// never evicted; if none can be removed, admission fails closed.
    pub(super) fn reserve(&self, command_id: u64) -> Result<(), DesktopError> {
        let mut state = lock_unpoisoned(&self.state);
        if state.entries.len() == self.capacity {
            let Some(index) = state.entries.iter().position(|record| record.state.terminal()) else {
                return Err(DesktopError::CommandOutcomeCapacityFull);
            };
            let expired = state
                .entries
                .remove(index)
                .expect("terminal command outcome index must exist");
            state.expired_through = state.expired_through.max(expired.command_id);
        }
        state.highest_reserved = state.highest_reserved.max(command_id);
        state.entries.push_back(CommandOutcomeRecord {
            command_id,
            state: CommandOutcomeState::Queued,
            failure: None,
        });
        Ok(())
    }

    pub(super) fn mark_running(&self, command_id: u64) {
        self.update(command_id, CommandOutcomeState::Running, None);
    }

    pub(super) fn mark_succeeded(&self, command_id: u64) {
        self.update(command_id, CommandOutcomeState::Succeeded, None);
    }

    pub(super) fn mark_failed(&self, command_id: u64, error: &DesktopError) {
        self.update(
            command_id,
            CommandOutcomeState::Failed,
            Some(command_failure_name(error)),
        );
    }

    pub(super) fn mark_aborted(&self, command_id: u64) {
        self.update(
            command_id,
            CommandOutcomeState::Aborted,
            Some("worker_unavailable"),
        );
    }

    pub(super) fn mark_rejected(&self, command_id: u64, error: &DesktopError) {
        self.update(
            command_id,
            CommandOutcomeState::Rejected,
            Some(command_failure_name(error)),
        );
    }

    /// Marks all accepted non-terminal commands as aborted during worker exit.
    pub(super) fn abort_nonterminal(&self) {
        let mut state = lock_unpoisoned(&self.state);
        for record in &mut state.entries {
            if matches!(record.state, CommandOutcomeState::Queued | CommandOutcomeState::Running) {
                record.state = CommandOutcomeState::Aborted;
                record.failure = Some("worker_unavailable");
            }
        }
    }

    /// Looks up one command without exposing command arguments or payload data.
    pub fn lookup(&self, command_id: u64) -> CommandOutcomeLookup {
        let state = lock_unpoisoned(&self.state);
        if let Some(record) = state
            .entries
            .iter()
            .find(|record| record.command_id == command_id)
        {
            return CommandOutcomeLookup::Found(record.clone());
        }
        if command_id != 0 && command_id <= state.expired_through {
            CommandOutcomeLookup::Expired
        } else {
            CommandOutcomeLookup::Unknown
        }
    }

    /// Fixed maximum number of retained outcome records.
    pub const fn capacity(&self) -> usize {
        self.capacity
    }

    fn update(
        &self,
        command_id: u64,
        next: CommandOutcomeState,
        failure: Option<&'static str>,
    ) {
        let mut state = lock_unpoisoned(&self.state);
        if let Some(record) = state
            .entries
            .iter_mut()
            .find(|record| record.command_id == command_id)
        {
            record.state = next;
            record.failure = failure;
            return;
        }
        if command_id > state.expired_through && command_id <= state.highest_reserved {
            tracing::error!(command_id, "command_outcome_record_missing");
        }
    }
}

fn command_failure_name(error: &DesktopError) -> &'static str {
    match error {
        DesktopError::DisplayUnavailable => "display_unavailable",
        DesktopError::InvalidCoordinate { .. } => "invalid_coordinate",
        DesktopError::InvalidRectangle => "invalid_rectangle",
        DesktopError::InvalidFramebufferDimensions => "invalid_framebuffer_dimensions",
        DesktopError::ChordTooLong { .. } => "chord_too_long",
        DesktopError::TextTooLarge { .. } => "text_too_large",
        DesktopError::ClipboardTooLarge { .. } => "clipboard_too_large",
        DesktopError::UnsupportedTextCharacter { .. } => "unsupported_text",
        DesktopError::ClipboardContainsNul => "invalid_clipboard",
        DesktopError::ScrollTooLarge { .. } => "scroll_too_large",
        DesktopError::CommandQueueFull => "command_queue_full",
        DesktopError::CommandOutcomeCapacityFull => "command_outcome_capacity_full",
        DesktopError::CommandIdExhausted => "command_id_exhausted",
        DesktopError::WorkerUnavailable => "worker_unavailable",
        DesktopError::FramebufferUnavailable => "framebuffer_unavailable",
        DesktopError::ClipboardUnavailable => "clipboard_unavailable",
        DesktopError::Timeout => "timeout",
        DesktopError::ReconnectRateLimited => "reconnect_rate_limited",
        DesktopError::Configuration(_) => "configuration",
        DesktopError::AuthenticationFailed => "authentication",
        DesktopError::Transport => "transport",
        DesktopError::Protocol => "protocol",
        DesktopError::Native => "native",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn terminal_records_are_evicted_but_pending_records_are_not() {
        let registry = CommandOutcomeRegistry::new(2);
        registry.reserve(1).unwrap();
        registry.reserve(2).unwrap();
        assert_eq!(
            registry.reserve(3),
            Err(DesktopError::CommandOutcomeCapacityFull)
        );

        registry.mark_succeeded(1);
        registry.reserve(3).unwrap();
        assert_eq!(registry.lookup(1), CommandOutcomeLookup::Expired);
        assert!(matches!(
            registry.lookup(2),
            CommandOutcomeLookup::Found(CommandOutcomeRecord {
                state: CommandOutcomeState::Queued,
                ..
            })
        ));
    }

    #[test]
    fn retained_records_never_store_payloads_and_abort_nonterminal() {
        let registry = CommandOutcomeRegistry::new(4);
        registry.reserve(1).unwrap();
        registry.reserve(2).unwrap();
        registry.mark_running(2);
        registry.abort_nonterminal();
        for id in [1, 2] {
            let CommandOutcomeLookup::Found(record) = registry.lookup(id) else {
                panic!("record must remain retained");
            };
            assert_eq!(record.state(), CommandOutcomeState::Aborted);
            assert_eq!(record.failure(), Some("worker_unavailable"));
            assert!(!record.retry_safe());
        }
    }

    #[test]
    fn rejected_command_is_retry_safe_and_classified() {
        let registry = CommandOutcomeRegistry::new(1);
        registry.reserve(7).unwrap();
        registry.mark_rejected(7, &DesktopError::CommandQueueFull);
        let CommandOutcomeLookup::Found(record) = registry.lookup(7) else {
            panic!("record must remain retained");
        };
        assert_eq!(record.state(), CommandOutcomeState::Rejected);
        assert_eq!(record.failure(), Some("command_queue_full"));
        assert!(record.retry_safe());
    }
}

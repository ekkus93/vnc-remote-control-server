use crate::framebuffer::FramebufferMetadata;
use crate::screenshot::{ScreenshotError, ScreenshotOutcome, ScreenshotService};
use crate::worker::{CommandOutcomeLookup, WorkerClient, WorkerSnapshot};
use remote_desktop_core::{ClipboardSnapshot, DesktopError, WorkerCommand};
use std::time::Duration;

/// Failure returned by one HTTP mutation after command preflight.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CommandExecutionError {
    /// The command never entered the worker queue and cannot execute.
    NotAccepted(DesktopError),
    /// The accepted command completed with a known failure.
    Failed {
        /// Stable process-local command identifier.
        command_id: u64,
        /// Sanitized domain error returned by worker execution.
        error: DesktopError,
    },
    /// The command was accepted but this caller did not observe a terminal
    /// result before its acknowledgement deadline. The command may still run.
    OutcomeUnknown {
        /// Stable process-local command identifier for later status lookup.
        command_id: u64,
    },
}

impl From<DesktopError> for CommandExecutionError {
    fn from(error: DesktopError) -> Self {
        Self::NotAccepted(error)
    }
}

/// Backend required by the authenticated HTTP surface.
pub trait HttpBackend: Send + Sync + 'static {
    /// Returns one redacted worker lifecycle snapshot.
    fn snapshot(&self) -> WorkerSnapshot;
    /// Returns coherent framebuffer metadata without copying pixels.
    fn framebuffer_metadata(&self) -> FramebufferMetadata;
    /// Captures or conditionally validates the current PNG screenshot.
    fn capture_screenshot(
        &self,
        if_none_match: Option<&str>,
    ) -> Result<ScreenshotOutcome, ScreenshotError>;
    /// Executes one queued command and waits for bounded worker acknowledgement.
    fn execute_command(
        &self,
        command: WorkerCommand,
        timeout: Duration,
    ) -> Result<u64, CommandExecutionError>;
    /// Returns one retained process-local command outcome.
    fn command_outcome(&self, command_id: u64) -> CommandOutcomeLookup;
    /// Returns the last valid inbound clipboard snapshot.
    fn clipboard_snapshot(&self) -> Result<ClipboardSnapshot, DesktopError>;
    /// Returns command submissions whose ownership permit remains live.
    fn command_submissions_in_flight(&self) -> usize;
    /// Returns the configured bounded command queue capacity.
    fn command_queue_capacity(&self) -> usize;
}

/// Production HTTP backend over one worker client and screenshot service.
pub struct WorkerHttpBackend {
    client: WorkerClient,
    screenshots: ScreenshotService,
}

impl WorkerHttpBackend {
    /// Creates a production backend using validated HTTP screenshot settings.
    pub fn new(
        client: WorkerClient,
        process_instance: &str,
        screenshot_concurrency: usize,
        screenshot_timeout: Duration,
    ) -> Result<Self, ScreenshotError> {
        let screenshots = client.screenshot_service(
            process_instance,
            screenshot_concurrency,
            screenshot_timeout,
        )?;
        Ok(Self {
            client,
            screenshots,
        })
    }
}

impl HttpBackend for WorkerHttpBackend {
    fn snapshot(&self) -> WorkerSnapshot {
        self.client.snapshot()
    }

    fn framebuffer_metadata(&self) -> FramebufferMetadata {
        self.client.framebuffer_metadata()
    }

    fn capture_screenshot(
        &self,
        if_none_match: Option<&str>,
    ) -> Result<ScreenshotOutcome, ScreenshotError> {
        self.screenshots.capture(if_none_match)
    }

    fn execute_command(
        &self,
        command: WorkerCommand,
        timeout: Duration,
    ) -> Result<u64, CommandExecutionError> {
        let ticket = self
            .client
            .submit(command)
            .map_err(CommandExecutionError::NotAccepted)?;
        let command_id = ticket.id();
        match ticket.wait(timeout) {
            Ok(()) => Ok(command_id),
            Err(DesktopError::Timeout) => {
                Err(CommandExecutionError::OutcomeUnknown { command_id })
            }
            Err(error) => Err(CommandExecutionError::Failed { command_id, error }),
        }
    }

    fn command_outcome(&self, command_id: u64) -> CommandOutcomeLookup {
        self.client.command_outcome(command_id)
    }

    fn clipboard_snapshot(&self) -> Result<ClipboardSnapshot, DesktopError> {
        self.client.clipboard_snapshot()
    }

    fn command_submissions_in_flight(&self) -> usize {
        self.client.command_submissions_in_flight()
    }

    fn command_queue_capacity(&self) -> usize {
        self.client.command_queue_capacity()
    }
}

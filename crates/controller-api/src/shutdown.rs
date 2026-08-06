//! Bounded process-level shutdown coordination.
//!
//! HTTP termination, worker shutdown, and event-bridge shutdown are treated as
//! separate cleanup surfaces. Every bounded cleanup attempt runs before the
//! deterministic primary error is returned.

use crate::events::{EventBridge, EventBridgeError};
use crate::worker::DesktopWorker;
use remote_desktop_core::DesktopError;
use std::error::Error;
use std::fmt;
use std::io;
use std::time::Duration;

/// Coordinates bounded worker and event-bridge cleanup after the HTTP runtime
/// has stopped accepting and draining requests.
pub fn finalize_runtime(
    server_result: io::Result<()>,
    worker: DesktopWorker,
    event_bridge: EventBridge,
    timeout: Duration,
) -> Result<(), ProcessShutdownError> {
    let worker_result = worker.shutdown(timeout);
    let bridge_result = event_bridge.shutdown(timeout);

    match server_result {
        Err(error) => {
            log_secondary_worker(&worker_result);
            log_secondary_bridge(&bridge_result);
            Err(ProcessShutdownError::Server(error))
        }
        Ok(()) => match worker_result {
            Err(error) => {
                log_secondary_bridge(&bridge_result);
                Err(ProcessShutdownError::Worker(error))
            }
            Ok(()) => bridge_result.map_err(ProcessShutdownError::EventBridge),
        },
    }
}

fn log_secondary_worker(result: &Result<(), DesktopError>) {
    if let Err(error) = result {
        tracing::error!(error = ?error, "process_shutdown_secondary_worker_failure");
    }
}

fn log_secondary_bridge(result: &Result<(), EventBridgeError>) {
    if let Err(error) = result {
        tracing::error!(error = ?error, "process_shutdown_secondary_event_bridge_failure");
    }
}

/// Deterministic primary process-shutdown failure.
#[derive(Debug)]
pub enum ProcessShutdownError {
    /// The HTTP runtime failed before or while draining.
    Server(io::Error),
    /// Worker shutdown failed after HTTP termination.
    Worker(DesktopError),
    /// Event-bridge shutdown failed after HTTP and worker cleanup.
    EventBridge(EventBridgeError),
}

impl fmt::Display for ProcessShutdownError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Server(error) => write!(formatter, "HTTP runtime shutdown failed: {error}"),
            Self::Worker(error) => write!(formatter, "desktop worker shutdown failed: {error}"),
            Self::EventBridge(error) => write!(formatter, "event bridge shutdown failed: {error}"),
        }
    }
}

impl Error for ProcessShutdownError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Server(error) => Some(error),
            Self::Worker(error) => Some(error),
            Self::EventBridge(error) => Some(error),
        }
    }
}

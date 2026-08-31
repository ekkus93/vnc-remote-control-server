//! Authenticated HTTP routing for the controller service.
//!
//! The router deliberately depends on a narrow backend trait. Production wraps
//! `WorkerClient`; unit tests use deterministic in-memory fixtures without
//! starting a native VNC thread. All `/v1/*` routes share one bearer-auth layer,
//! complete request preflight, bounded worker acknowledgements, and payload-free
//! error mapping. Liveness, readiness, and API documentation remain public
//! orchestration/developer endpoints.
//!
//! Submodules split the surface by responsibility: the backend trait and its
//! production implementation (`backend`), shared router state and its build
//! errors (`state`), route registration (`router`), the redacted request
//! identifier (`ids`), response and error payload shapes (`responses`),
//! auth/logging middleware (`middleware`), API documentation (`docs_ui`), the
//! route handlers themselves (`handlers`), and small pure helpers shared across
//! handlers (`support`).

mod backend;
mod docs_ui;
mod handlers;
mod ids;
mod middleware;
mod responses;
mod router;
mod state;
mod support;
#[cfg(test)]
mod tests;

pub use backend::{CommandExecutionError, HttpBackend, WorkerHttpBackend};
pub use router::router;
pub use state::{HttpBuildError, HttpState, HttpWorkerSettings};

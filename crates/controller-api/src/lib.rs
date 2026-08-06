//! Public API contract types and single-session worker for the VNC remote control server.
#![forbid(unsafe_code)]

pub mod api_contract;
pub mod config;
pub mod events;
pub mod framebuffer;
pub mod http;
pub mod input;
pub mod observability;
pub mod runtime;
pub mod screenshot;
pub mod shutdown;
pub mod worker;
#[cfg(test)]
pub(crate) mod test_support;

use serde::{Deserialize, Serialize};

/// Externally visible connection states.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ConnectionState {
    /// Worker initialization has begun.
    Starting,
    /// A connection attempt is active.
    Connecting,
    /// The authenticated VNC transport is healthy.
    Connected,
    /// The transport exists but has failed a health condition.
    Degraded,
    /// Automatic reconnection is active.
    Reconnecting,
    /// No transport is active.
    Disconnected,
    /// Authentication failed and retry is backoff-safe.
    AuthenticationFailed,
    /// The worker is stopping or stopped.
    Stopped,
}

impl ConnectionState {
    /// Returns whether a state transition is allowed by the v0.1 lifecycle.
    pub fn can_transition_to(self, next: Self) -> bool {
        use ConnectionState::{
            AuthenticationFailed, Connected, Connecting, Degraded, Disconnected, Reconnecting,
            Starting, Stopped,
        };
        matches!(
            (self, next),
            (Starting, Connecting)
                | (Starting, Stopped)
                | (Connecting, Connected)
                | (Connecting, AuthenticationFailed)
                | (Connecting, Disconnected)
                | (Connecting, Stopped)
                | (Connected, Degraded)
                | (Connected, Disconnected)
                | (Connected, Reconnecting)
                | (Connected, Stopped)
                | (Degraded, Reconnecting)
                | (Degraded, Disconnected)
                | (Degraded, Stopped)
                | (Disconnected, Reconnecting)
                | (Disconnected, Connecting)
                | (Disconnected, Stopped)
                | (AuthenticationFailed, Reconnecting)
                | (AuthenticationFailed, Stopped)
                | (Reconnecting, Connected)
                | (Reconnecting, AuthenticationFailed)
                | (Reconnecting, Disconnected)
                | (Reconnecting, Stopped)
        ) || self == next
    }
}

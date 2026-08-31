use libvnc_adapter::NativeClientConfig;
use remote_desktop_core::{DesktopError, MAX_FRAMEBUFFER_BYTES};
use std::time::Duration;

const MIN_WORKER_DURATION: Duration = Duration::from_millis(1);
const MAX_WORKER_DURATION: Duration = Duration::from_secs(24 * 60 * 60);

/// Native worker timing and capacity configuration.
#[derive(PartialEq, Eq)]
pub struct WorkerSettings {
    /// Native VNC connection configuration. It contains the password and is
    /// intentionally not `Debug`.
    pub native: NativeClientConfig,
    /// Maximum commands waiting for the native thread.
    pub command_capacity: usize,
    /// Maximum events waiting for the event consumer.
    pub event_capacity: usize,
    /// Maximum canonical RGBA framebuffer allocation.
    pub maximum_framebuffer_bytes: usize,
    /// Maximum native poll duration before command processing resumes.
    pub poll_interval: Duration,
    /// Maximum wait for thread startup acknowledgement.
    pub startup_timeout: Duration,
    /// Initial automatic reconnect delay.
    pub reconnect_min_delay: Duration,
    /// Maximum automatic reconnect delay.
    pub reconnect_max_delay: Duration,
    /// Maximum positive reconnect jitter in per-mille of the base delay.
    pub reconnect_jitter_per_mille: u16,
    /// Connected duration required before reconnect backoff resets.
    pub stable_connection_reset: Duration,
    /// Minimum interval between accepted manual reconnect requests.
    pub manual_reconnect_interval: Duration,
    /// Idle duration before a full-refresh probe is sent.
    pub stall_probe_after: Duration,
    /// Additional duration without a server message after a probe before the
    /// transport is considered stalled.
    pub stall_confirm_after: Duration,
}

impl WorkerSettings {
    /// Validates all settings before a thread is spawned.
    pub fn validate(&self) -> Result<(), DesktopError> {
        if self.native.host.is_empty()
            || self.native.password.expose_secret().is_empty()
            || self.native.port == 0
        {
            return Err(DesktopError::Configuration(
                "native worker endpoint and credentials must be nonempty".to_owned(),
            ));
        }
        if self.command_capacity == 0 || self.event_capacity == 0 {
            return Err(DesktopError::Configuration(
                "worker channel capacities must be nonzero".to_owned(),
            ));
        }
        if self.maximum_framebuffer_bytes == 0
            || self.maximum_framebuffer_bytes > MAX_FRAMEBUFFER_BYTES
        {
            return Err(DesktopError::Configuration(
                "worker framebuffer limit is invalid".to_owned(),
            ));
        }
        for (name, value) in [
            ("native connect timeout", self.native.connect_timeout),
            ("native read timeout", self.native.read_timeout),
        ] {
            if value < Duration::from_secs(1)
                || value > MAX_WORKER_DURATION
                || value.subsec_nanos() != 0
            {
                return Err(DesktopError::Configuration(format!(
                    "{name} must be a positive whole-second value representable by the native adapter"
                )));
            }
        }
        for (name, value) in [
            ("poll_interval", self.poll_interval),
            ("startup_timeout", self.startup_timeout),
            ("reconnect_min_delay", self.reconnect_min_delay),
            ("reconnect_max_delay", self.reconnect_max_delay),
            ("stable_connection_reset", self.stable_connection_reset),
            ("manual_reconnect_interval", self.manual_reconnect_interval),
            ("stall_probe_after", self.stall_probe_after),
            ("stall_confirm_after", self.stall_confirm_after),
        ] {
            if value < MIN_WORKER_DURATION || value > MAX_WORKER_DURATION {
                return Err(DesktopError::Configuration(format!(
                    "{name} must be between 1ms and 24h"
                )));
            }
        }
        if u32::try_from(self.poll_interval.as_micros()).is_err() {
            return Err(DesktopError::Configuration(
                "poll_interval must fit the native u32 microsecond wait field".to_owned(),
            ));
        }
        if self.reconnect_min_delay > self.reconnect_max_delay {
            return Err(DesktopError::Configuration(
                "minimum reconnect delay exceeds maximum".to_owned(),
            ));
        }
        if self.reconnect_jitter_per_mille > 500 {
            return Err(DesktopError::Configuration(
                "reconnect jitter must not exceed 500 per-mille".to_owned(),
            ));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use libvnc_adapter::SecretString;

    fn settings() -> WorkerSettings {
        WorkerSettings {
            native: NativeClientConfig {
                host: "desktop".to_owned(),
                port: 5901,
                password: SecretString::from("secret"),
                connect_timeout: Duration::from_secs(10),
                read_timeout: Duration::from_secs(10),
            },
            command_capacity: 1,
            event_capacity: 1,
            maximum_framebuffer_bytes: MAX_FRAMEBUFFER_BYTES,
            poll_interval: Duration::from_millis(10),
            startup_timeout: Duration::from_secs(10),
            reconnect_min_delay: Duration::from_millis(250),
            reconnect_max_delay: Duration::from_secs(30),
            reconnect_jitter_per_mille: 100,
            stable_connection_reset: Duration::from_secs(10),
            manual_reconnect_interval: Duration::from_secs(2),
            stall_probe_after: Duration::from_secs(30),
            stall_confirm_after: Duration::from_secs(10),
        }
    }

    #[test]
    fn native_timeouts_must_be_exact_whole_seconds_before_worker_spawn() {
        let mut value = settings();
        value.native.connect_timeout = Duration::from_millis(1500);
        assert!(value.validate().is_err());

        value.native.connect_timeout = Duration::from_secs(1);
        value.native.read_timeout = MAX_WORKER_DURATION;
        assert!(value.validate().is_ok());

        value.native.read_timeout = MAX_WORKER_DURATION + Duration::from_secs(1);
        assert!(value.validate().is_err());
    }

    #[test]
    fn poll_interval_respects_exact_native_microsecond_boundary() {
        let mut value = settings();
        value.poll_interval = Duration::from_micros(u64::from(u32::MAX));
        assert!(value.validate().is_ok());

        value.poll_interval = Duration::from_micros(u64::from(u32::MAX) + 1);
        assert!(value.validate().is_err());
    }

    #[test]
    fn worker_deadline_durations_are_bounded() {
        let mut value = settings();
        value.startup_timeout = MAX_WORKER_DURATION;
        assert!(value.validate().is_ok());

        value.startup_timeout = MAX_WORKER_DURATION + Duration::from_millis(1);
        assert!(value.validate().is_err());
    }
}

/// Coarse failure category safe for status, events, and metrics.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkerFailureKind {
    /// Credentials were rejected during VNC protocol initialization.
    Authentication,
    /// Static configuration is invalid and must not be retried.
    Configuration,
    /// The TCP transport failed or disconnected.
    Transport,
    /// A refresh probe exceeded its deadline.
    Timeout,
    /// The remote framebuffer or protocol contract failed.
    Protocol,
    /// Another bounded native adapter operation failed.
    Native,
}

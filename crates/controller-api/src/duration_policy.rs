//! Central startup validation for all externally configured durations.
//!
//! Environment parsing produces `Duration` values, but some downstream APIs
//! have narrower or platform-sensitive representations. This module is the
//! process startup choke point: it rejects unreasonable or non-representable
//! durations before sockets, worker threads, or native VNC clients are started.

use crate::config::{ConfigError, ControllerConfig};
use std::time::Duration;

/// Smallest controller-owned duration accepted by startup validation.
pub const MIN_CONTROLLER_DURATION: Duration = Duration::from_millis(1);
/// Largest controller-owned duration accepted by startup validation.
pub const MAX_CONTROLLER_DURATION: Duration = Duration::from_secs(24 * 60 * 60);

/// Validates every controller-owned duration before runtime startup.
///
/// Worker/native durations are validated by `WorkerSettings::validate`, which
/// `ControllerConfig::load_from` invokes before producing a configuration.
pub fn validate_startup_durations(config: &ControllerConfig) -> Result<(), ConfigError> {
    for (name, value) in [
        ("VRC_COMMAND_ACK_TIMEOUT_MS", config.command_ack_timeout),
        ("VRC_SHUTDOWN_TIMEOUT_MS", config.shutdown_timeout),
        ("VRC_SCREENSHOT_TIMEOUT_MS", config.screenshot_timeout),
        (
            "VRC_WEBSOCKET_PING_INTERVAL_MS",
            config.websocket_ping_interval,
        ),
        (
            "VRC_WEBSOCKET_IDLE_TIMEOUT_MS",
            config.websocket_idle_timeout,
        ),
    ] {
        if value < MIN_CONTROLLER_DURATION || value > MAX_CONTROLLER_DURATION {
            return Err(ConfigError::InvalidValue(name));
        }
    }
    config.worker.validate().map_err(ConfigError::Worker)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{EnvironmentReadError, EnvironmentSource, SecretReader};
    use libvnc_adapter::SecretString;
    use std::collections::HashMap;
    use std::path::Path;

    struct Environment(HashMap<String, String>);

    impl EnvironmentSource for Environment {
        fn get(&self, name: &str) -> Result<Option<String>, EnvironmentReadError> {
            Ok(self.0.get(name).cloned())
        }
    }

    struct Secrets;

    impl SecretReader for Secrets {
        fn read_secret(&self, _path: &Path) -> Result<SecretString, ConfigError> {
            Ok(SecretString::from("test-secret"))
        }
    }

    fn load(values: &[(&str, &str)]) -> Result<ControllerConfig, ConfigError> {
        let environment = Environment(
            values
                .iter()
                .map(|(name, value)| ((*name).to_owned(), (*value).to_owned()))
                .collect(),
        );
        ControllerConfig::load_from(&environment, &Secrets)
    }

    #[test]
    fn environment_derived_native_fractional_seconds_fail_before_startup() {
        for name in ["VRC_VNC_CONNECT_TIMEOUT_MS", "VRC_VNC_READ_TIMEOUT_MS"] {
            let error = load(&[(name, "1500")]).expect_err("fractional native second rejected");
            assert!(matches!(error, ConfigError::Worker(_)));
        }
    }

    #[test]
    fn environment_derived_poll_interval_honors_u32_microsecond_boundary() {
        let accepted = load(&[("VRC_POLL_INTERVAL_MS", "4294967")])
            .expect("largest whole-millisecond poll value fits");
        validate_startup_durations(&accepted).expect("boundary remains valid at startup");

        let error = load(&[("VRC_POLL_INTERVAL_MS", "4294968")])
            .expect_err("one millisecond above native boundary is rejected");
        assert!(matches!(error, ConfigError::Worker(_)));
    }

    #[test]
    fn controller_duration_maximum_is_explicit_and_checked() {
        let accepted = load(&[("VRC_COMMAND_ACK_TIMEOUT_MS", "86400000")])
            .expect("parser accepts maximum");
        validate_startup_durations(&accepted).expect("24h maximum is valid");

        let rejected = load(&[("VRC_COMMAND_ACK_TIMEOUT_MS", "86400001")])
            .expect("parser still represents value without narrowing");
        let error = validate_startup_durations(&rejected).expect_err("above maximum rejected");
        assert!(matches!(
            error,
            ConfigError::InvalidValue("VRC_COMMAND_ACK_TIMEOUT_MS")
        ));
    }

    #[test]
    fn controller_duration_minimum_is_one_millisecond() {
        let accepted = load(&[("VRC_SCREENSHOT_TIMEOUT_MS", "1")])
            .expect("one millisecond parses");
        validate_startup_durations(&accepted).expect("one millisecond is valid");

        let error = load(&[("VRC_SCREENSHOT_TIMEOUT_MS", "0")])
            .expect_err("zero duration rejected by parser");
        assert!(matches!(
            error,
            ConfigError::InvalidValue("VRC_SCREENSHOT_TIMEOUT_MS")
        ));
    }
}

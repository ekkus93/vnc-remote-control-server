//! Typed, validated controller configuration and file-backed secret loading.
//!
//! Production credentials are read only from files. Environment variables may
//! select secret file paths but never contain secret values. `Debug` output is
//! implemented manually and omits both secret values.

use crate::worker::WorkerSettings;
use libvnc_adapter::NativeClientConfig;
use remote_desktop_core::{DesktopError, MAX_FRAMEBUFFER_BYTES};
use std::collections::HashMap;
use std::env;
use std::error::Error;
use std::fmt;
use std::fs;
use std::io;
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const DEFAULT_LISTEN_ADDRESS: &str = "127.0.0.1:8080";
const DEFAULT_API_TOKEN_FILE: &str = "/run/secrets/api_token";
const DEFAULT_VNC_HOST: &str = "desktop";
const DEFAULT_VNC_PORT: u16 = 5901;
const DEFAULT_VNC_PASSWORD_FILE: &str = "/run/secrets/vnc_password";
const DEFAULT_COMMAND_CAPACITY: usize = 64;
const DEFAULT_EVENT_CAPACITY: usize = 256;
const DEFAULT_MAXIMUM_JSON_BYTES: usize = 1024 * 1024;
const DEFAULT_COMMAND_ACK_TIMEOUT_MS: u64 = 5_000;
const DEFAULT_SCREENSHOT_CONCURRENCY: usize = 2;
const DEFAULT_SCREENSHOT_TIMEOUT_MS: u64 = 5_000;
const DEFAULT_POLL_INTERVAL_MS: u64 = 10;
const DEFAULT_STARTUP_TIMEOUT_MS: u64 = 10_000;
const DEFAULT_RECONNECT_MIN_MS: u64 = 250;
const DEFAULT_RECONNECT_MAX_MS: u64 = 30_000;
const DEFAULT_RECONNECT_JITTER_PER_MILLE: u16 = 100;
const DEFAULT_STABLE_CONNECTION_RESET_MS: u64 = 10_000;
const DEFAULT_MANUAL_RECONNECT_INTERVAL_MS: u64 = 2_000;
const DEFAULT_STALL_PROBE_AFTER_MS: u64 = 30_000;
const DEFAULT_STALL_CONFIRM_AFTER_MS: u64 = 10_000;
const MAX_SECRET_BYTES: u64 = 4 * 1024;
const MAX_JSON_BYTES: usize = 2 * 1024 * 1024;
const MAX_CHANNEL_CAPACITY: usize = 65_536;
const MAX_SCREENSHOT_CONCURRENCY: usize = 64;

/// Fully validated process configuration.
#[derive(Clone, PartialEq, Eq)]
pub struct ControllerConfig {
    /// HTTP listener address.
    pub listen_address: SocketAddr,
    /// Static bearer token. The value is intentionally not `Debug`.
    pub api_token: Arc<str>,
    /// Stable identifier used to namespace screenshot ETags for this process.
    pub process_instance: Arc<str>,
    /// Maximum accepted JSON request body size.
    pub maximum_json_bytes: usize,
    /// Maximum wait for worker command completion.
    pub command_ack_timeout: Duration,
    /// Maximum simultaneous screenshot encodes.
    pub screenshot_concurrency: usize,
    /// Screenshot encode deadline.
    pub screenshot_timeout: Duration,
    /// Native worker configuration.
    pub worker: WorkerSettings,
}

impl fmt::Debug for ControllerConfig {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ControllerConfig")
            .field("listen_address", &self.listen_address)
            .field("api_token", &"[REDACTED]")
            .field("process_instance", &self.process_instance)
            .field("maximum_json_bytes", &self.maximum_json_bytes)
            .field("command_ack_timeout", &self.command_ack_timeout)
            .field("screenshot_concurrency", &self.screenshot_concurrency)
            .field("screenshot_timeout", &self.screenshot_timeout)
            .field("vnc_host", &self.worker.native.host)
            .field("vnc_port", &self.worker.native.port)
            .field("vnc_password", &"[REDACTED]")
            .field("command_capacity", &self.worker.command_capacity)
            .field("event_capacity", &self.worker.event_capacity)
            .finish_non_exhaustive()
    }
}

impl ControllerConfig {
    /// Loads configuration from the current process environment and filesystem.
    pub fn load() -> Result<Self, ConfigError> {
        Self::load_from(&ProcessEnvironment, &SystemSecretReader)
    }

    /// Loads configuration through injectable sources for deterministic tests.
    pub fn load_from<E, S>(environment: &E, secrets: &S) -> Result<Self, ConfigError>
    where
        E: EnvironmentSource,
        S: SecretReader,
    {
        let listen_address = value_or(environment, "VRC_LISTEN_ADDR", DEFAULT_LISTEN_ADDRESS)
            .parse::<SocketAddr>()
            .map_err(|_| ConfigError::InvalidValue("VRC_LISTEN_ADDR"))?;
        if listen_address.port() == 0 {
            return Err(ConfigError::InvalidValue("VRC_LISTEN_ADDR"));
        }

        let api_token_path = PathBuf::from(value_or(
            environment,
            "VRC_API_TOKEN_FILE",
            DEFAULT_API_TOKEN_FILE,
        ));
        let vnc_password_path = PathBuf::from(value_or(
            environment,
            "VRC_VNC_PASSWORD_FILE",
            DEFAULT_VNC_PASSWORD_FILE,
        ));
        let api_token = secrets.read_secret(&api_token_path)?;
        let vnc_password = secrets.read_secret(&vnc_password_path)?;

        let process_instance = environment
            .get("VRC_PROCESS_INSTANCE")
            .unwrap_or_else(default_process_instance);
        validate_process_instance(&process_instance)?;

        let maximum_json_bytes = parse_bounded_usize(
            environment,
            "VRC_MAX_JSON_BYTES",
            DEFAULT_MAXIMUM_JSON_BYTES,
            1,
            MAX_JSON_BYTES,
        )?;
        let command_ack_timeout = parse_duration_ms(
            environment,
            "VRC_COMMAND_ACK_TIMEOUT_MS",
            DEFAULT_COMMAND_ACK_TIMEOUT_MS,
        )?;
        let screenshot_concurrency = parse_bounded_usize(
            environment,
            "VRC_SCREENSHOT_MAX_CONCURRENT",
            DEFAULT_SCREENSHOT_CONCURRENCY,
            1,
            MAX_SCREENSHOT_CONCURRENCY,
        )?;
        let screenshot_timeout = parse_duration_ms(
            environment,
            "VRC_SCREENSHOT_TIMEOUT_MS",
            DEFAULT_SCREENSHOT_TIMEOUT_MS,
        )?;

        let vnc_host = value_or(environment, "VRC_VNC_HOST", DEFAULT_VNC_HOST);
        if vnc_host.is_empty() || vnc_host.len() > 253 {
            return Err(ConfigError::InvalidValue("VRC_VNC_HOST"));
        }
        let vnc_port = parse_u16(environment, "VRC_VNC_PORT", DEFAULT_VNC_PORT)?;
        if vnc_port == 0 {
            return Err(ConfigError::InvalidValue("VRC_VNC_PORT"));
        }

        let worker = WorkerSettings {
            native: NativeClientConfig {
                host: vnc_host,
                port: vnc_port,
                password: vnc_password.to_string(),
                connect_timeout: parse_duration_ms(
                    environment,
                    "VRC_VNC_CONNECT_TIMEOUT_MS",
                    10_000,
                )?,
                read_timeout: parse_duration_ms(
                    environment,
                    "VRC_VNC_READ_TIMEOUT_MS",
                    10_000,
                )?,
            },
            command_capacity: parse_bounded_usize(
                environment,
                "VRC_COMMAND_CAPACITY",
                DEFAULT_COMMAND_CAPACITY,
                1,
                MAX_CHANNEL_CAPACITY,
            )?,
            event_capacity: parse_bounded_usize(
                environment,
                "VRC_EVENT_CAPACITY",
                DEFAULT_EVENT_CAPACITY,
                1,
                MAX_CHANNEL_CAPACITY,
            )?,
            maximum_framebuffer_bytes: parse_bounded_usize(
                environment,
                "VRC_MAX_FRAMEBUFFER_BYTES",
                MAX_FRAMEBUFFER_BYTES,
                1,
                MAX_FRAMEBUFFER_BYTES,
            )?,
            poll_interval: parse_duration_ms(
                environment,
                "VRC_POLL_INTERVAL_MS",
                DEFAULT_POLL_INTERVAL_MS,
            )?,
            startup_timeout: parse_duration_ms(
                environment,
                "VRC_STARTUP_TIMEOUT_MS",
                DEFAULT_STARTUP_TIMEOUT_MS,
            )?,
            reconnect_min_delay: parse_duration_ms(
                environment,
                "VRC_RECONNECT_MIN_MS",
                DEFAULT_RECONNECT_MIN_MS,
            )?,
            reconnect_max_delay: parse_duration_ms(
                environment,
                "VRC_RECONNECT_MAX_MS",
                DEFAULT_RECONNECT_MAX_MS,
            )?,
            reconnect_jitter_per_mille: parse_u16(
                environment,
                "VRC_RECONNECT_JITTER_PER_MILLE",
                DEFAULT_RECONNECT_JITTER_PER_MILLE,
            )?,
            stable_connection_reset: parse_duration_ms(
                environment,
                "VRC_STABLE_CONNECTION_RESET_MS",
                DEFAULT_STABLE_CONNECTION_RESET_MS,
            )?,
            manual_reconnect_interval: parse_duration_ms(
                environment,
                "VRC_MANUAL_RECONNECT_INTERVAL_MS",
                DEFAULT_MANUAL_RECONNECT_INTERVAL_MS,
            )?,
            stall_probe_after: parse_duration_ms(
                environment,
                "VRC_STALL_PROBE_AFTER_MS",
                DEFAULT_STALL_PROBE_AFTER_MS,
            )?,
            stall_confirm_after: parse_duration_ms(
                environment,
                "VRC_STALL_CONFIRM_AFTER_MS",
                DEFAULT_STALL_CONFIRM_AFTER_MS,
            )?,
        };
        worker.validate().map_err(ConfigError::Worker)?;

        Ok(Self {
            listen_address,
            api_token,
            process_instance: Arc::from(process_instance),
            maximum_json_bytes,
            command_ack_timeout,
            screenshot_concurrency,
            screenshot_timeout,
            worker,
        })
    }
}

/// Configuration loading failure that never includes secret contents.
#[derive(Debug)]
pub enum ConfigError {
    /// A configured environment value is syntactically or semantically invalid.
    InvalidValue(&'static str),
    /// A secret file could not be read or failed the file policy.
    SecretFile {
        /// Configured secret path.
        path: PathBuf,
        /// Redaction-safe reason.
        reason: &'static str,
    },
    /// Worker settings violate the worker contract.
    Worker(DesktopError),
}

impl fmt::Display for ConfigError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidValue(name) => write!(formatter, "invalid configuration value: {name}"),
            Self::SecretFile { path, reason } => {
                write!(formatter, "invalid secret file {}: {reason}", path.display())
            }
            Self::Worker(error) => write!(formatter, "invalid worker configuration: {error}"),
        }
    }
}

impl Error for ConfigError {}

/// Read-only environment abstraction used by configuration loading.
pub trait EnvironmentSource {
    /// Returns one Unicode environment value when present.
    fn get(&self, name: &str) -> Option<String>;
}

/// Current process environment source.
pub struct ProcessEnvironment;

impl EnvironmentSource for ProcessEnvironment {
    fn get(&self, name: &str) -> Option<String> {
        env::var(name).ok()
    }
}

/// File-backed secret source.
pub trait SecretReader {
    /// Reads and validates one secret without exposing it in errors.
    fn read_secret(&self, path: &Path) -> Result<Arc<str>, ConfigError>;
}

/// Production filesystem secret reader.
pub struct SystemSecretReader;

impl SecretReader for SystemSecretReader {
    fn read_secret(&self, path: &Path) -> Result<Arc<str>, ConfigError> {
        let metadata = fs::metadata(path).map_err(|_| ConfigError::SecretFile {
            path: path.to_path_buf(),
            reason: "cannot read metadata",
        })?;
        if !metadata.is_file() {
            return Err(ConfigError::SecretFile {
                path: path.to_path_buf(),
                reason: "not a regular file",
            });
        }
        if metadata.len() == 0 || metadata.len() > MAX_SECRET_BYTES {
            return Err(ConfigError::SecretFile {
                path: path.to_path_buf(),
                reason: "size is outside the accepted bound",
            });
        }
        validate_secret_permissions(path, &metadata)?;
        let bytes = fs::read(path).map_err(|_| ConfigError::SecretFile {
            path: path.to_path_buf(),
            reason: "cannot read contents",
        })?;
        let mut value = String::from_utf8(bytes).map_err(|_| ConfigError::SecretFile {
            path: path.to_path_buf(),
            reason: "contents are not UTF-8",
        })?;
        while value.ends_with('\n') || value.ends_with('\r') {
            value.pop();
        }
        if value.is_empty() || value.contains('\0') {
            return Err(ConfigError::SecretFile {
                path: path.to_path_buf(),
                reason: "contents are empty or contain NUL",
            });
        }
        Ok(Arc::from(value))
    }
}

#[cfg(unix)]
fn validate_secret_permissions(
    path: &Path,
    metadata: &fs::Metadata,
) -> Result<(), ConfigError> {
    use std::os::unix::fs::PermissionsExt;

    let mode = metadata.permissions().mode();
    if mode & 0o022 != 0 || mode & 0o111 != 0 {
        return Err(ConfigError::SecretFile {
            path: path.to_path_buf(),
            reason: "group/other write or execute permission is forbidden",
        });
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_secret_permissions(
    _path: &Path,
    _metadata: &fs::Metadata,
) -> Result<(), ConfigError> {
    Ok(())
}

fn value_or<E: EnvironmentSource>(environment: &E, name: &str, default: &str) -> String {
    environment.get(name).unwrap_or_else(|| default.to_owned())
}

fn parse_u16<E: EnvironmentSource>(
    environment: &E,
    name: &'static str,
    default: u16,
) -> Result<u16, ConfigError> {
    match environment.get(name) {
        Some(value) => value
            .parse::<u16>()
            .map_err(|_| ConfigError::InvalidValue(name)),
        None => Ok(default),
    }
}

fn parse_duration_ms<E: EnvironmentSource>(
    environment: &E,
    name: &'static str,
    default: u64,
) -> Result<Duration, ConfigError> {
    let milliseconds = match environment.get(name) {
        Some(value) => value
            .parse::<u64>()
            .map_err(|_| ConfigError::InvalidValue(name))?,
        None => default,
    };
    if milliseconds == 0 {
        return Err(ConfigError::InvalidValue(name));
    }
    Ok(Duration::from_millis(milliseconds))
}

fn parse_bounded_usize<E: EnvironmentSource>(
    environment: &E,
    name: &'static str,
    default: usize,
    minimum: usize,
    maximum: usize,
) -> Result<usize, ConfigError> {
    let value = match environment.get(name) {
        Some(value) => value
            .parse::<usize>()
            .map_err(|_| ConfigError::InvalidValue(name))?,
        None => default,
    };
    if !(minimum..=maximum).contains(&value) {
        return Err(ConfigError::InvalidValue(name));
    }
    Ok(value)
}

fn validate_process_instance(value: &str) -> Result<(), ConfigError> {
    if value.is_empty()
        || value.len() > 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
    {
        return Err(ConfigError::InvalidValue("VRC_PROCESS_INSTANCE"));
    }
    Ok(())
}

fn default_process_instance() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    format!("p{}-{nanos:x}", std::process::id())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Default)]
    struct MapEnvironment(HashMap<String, String>);

    impl EnvironmentSource for MapEnvironment {
        fn get(&self, name: &str) -> Option<String> {
            self.0.get(name).cloned()
        }
    }

    struct MapSecrets(HashMap<PathBuf, Arc<str>>);

    impl SecretReader for MapSecrets {
        fn read_secret(&self, path: &Path) -> Result<Arc<str>, ConfigError> {
            self.0
                .get(path)
                .cloned()
                .ok_or_else(|| ConfigError::SecretFile {
                    path: path.to_path_buf(),
                    reason: "fixture is missing",
                })
        }
    }

    fn secrets() -> MapSecrets {
        MapSecrets(HashMap::from([
            (PathBuf::from(DEFAULT_API_TOKEN_FILE), Arc::from("api-token")),
            (
                PathBuf::from(DEFAULT_VNC_PASSWORD_FILE),
                Arc::from("vnc-password"),
            ),
        ]))
    }

    #[test]
    fn defaults_are_valid_and_secrets_are_redacted() {
        let config = ControllerConfig::load_from(&MapEnvironment::default(), &secrets())
            .expect("defaults load");
        assert_eq!(config.listen_address, "127.0.0.1:8080".parse().unwrap());
        assert_eq!(config.worker.native.host, "desktop");
        assert_eq!(config.worker.native.port, 5901);
        assert_eq!(config.maximum_json_bytes, 1024 * 1024);

        let debug = format!("{config:?}");
        assert!(!debug.contains("api-token"));
        assert!(!debug.contains("vnc-password"));
        assert!(debug.matches("[REDACTED]").count() >= 2);
    }

    #[test]
    fn environment_can_select_paths_and_bounded_nonsecret_values() {
        let environment = MapEnvironment(HashMap::from([
            ("VRC_LISTEN_ADDR".to_owned(), "0.0.0.0:9090".to_owned()),
            ("VRC_API_TOKEN_FILE".to_owned(), "/tmp/api".to_owned()),
            (
                "VRC_VNC_PASSWORD_FILE".to_owned(),
                "/tmp/vnc".to_owned(),
            ),
            ("VRC_VNC_HOST".to_owned(), "desktop.internal".to_owned()),
            ("VRC_VNC_PORT".to_owned(), "5999".to_owned()),
            ("VRC_COMMAND_CAPACITY".to_owned(), "8".to_owned()),
            ("VRC_EVENT_CAPACITY".to_owned(), "9".to_owned()),
            ("VRC_PROCESS_INSTANCE".to_owned(), "test-instance".to_owned()),
        ]));
        let secrets = MapSecrets(HashMap::from([
            (PathBuf::from("/tmp/api"), Arc::from("selected-api")),
            (PathBuf::from("/tmp/vnc"), Arc::from("selected-vnc")),
        ]));
        let config = ControllerConfig::load_from(&environment, &secrets).expect("config loads");
        assert_eq!(config.listen_address, "0.0.0.0:9090".parse().unwrap());
        assert_eq!(config.worker.native.host, "desktop.internal");
        assert_eq!(config.worker.native.port, 5999);
        assert_eq!(config.worker.command_capacity, 8);
        assert_eq!(config.worker.event_capacity, 9);
        assert_eq!(config.process_instance.as_ref(), "test-instance");
    }

    #[test]
    fn invalid_ports_limits_and_durations_fail_closed() {
        for (name, value) in [
            ("VRC_LISTEN_ADDR", "127.0.0.1:0"),
            ("VRC_VNC_PORT", "0"),
            ("VRC_COMMAND_CAPACITY", "0"),
            ("VRC_MAX_JSON_BYTES", "2097153"),
            ("VRC_SCREENSHOT_MAX_CONCURRENT", "65"),
            ("VRC_COMMAND_ACK_TIMEOUT_MS", "0"),
            ("VRC_RECONNECT_JITTER_PER_MILLE", "501"),
        ] {
            let environment = MapEnvironment(HashMap::from([(name.to_owned(), value.to_owned())]));
            assert!(ControllerConfig::load_from(&environment, &secrets()).is_err());
        }
    }

    #[test]
    fn secret_values_cannot_be_supplied_directly_by_environment() {
        let environment = MapEnvironment(HashMap::from([
            ("VRC_API_TOKEN".to_owned(), "ignored-api-value".to_owned()),
            ("VRC_VNC_PASSWORD".to_owned(), "ignored-vnc-value".to_owned()),
        ]));
        let config = ControllerConfig::load_from(&environment, &secrets()).expect("config loads");
        assert_eq!(config.api_token.as_ref(), "api-token");
        assert_eq!(config.worker.native.password, "vnc-password");
    }

    #[test]
    fn process_instance_is_strictly_bounded() {
        for value in ["", "has space", "slash/value"] {
            let environment = MapEnvironment(HashMap::from([(
                "VRC_PROCESS_INSTANCE".to_owned(),
                value.to_owned(),
            )]));
            assert!(ControllerConfig::load_from(&environment, &secrets()).is_err());
        }
    }

    #[cfg(unix)]
    #[test]
    fn system_secret_reader_accepts_read_only_and_rejects_writable_exposure() {
        use std::os::unix::fs::PermissionsExt;

        let directory = tempfile::tempdir().expect("temporary directory");
        let secret_path = directory.path().join("secret");
        fs::write(&secret_path, "secret-value\n").expect("write secret");
        fs::set_permissions(&secret_path, fs::Permissions::from_mode(0o444))
            .expect("set read-only permissions");
        assert_eq!(
            SystemSecretReader
                .read_secret(&secret_path)
                .expect("read-only secret"),
            Arc::<str>::from("secret-value")
        );

        fs::set_permissions(&secret_path, fs::Permissions::from_mode(0o666))
            .expect("set broad permissions");
        assert!(SystemSecretReader.read_secret(&secret_path).is_err());
    }

    #[test]
    fn secret_errors_never_include_secret_contents() {
        struct FailingSecret;
        impl SecretReader for FailingSecret {
            fn read_secret(&self, path: &Path) -> Result<Arc<str>, ConfigError> {
                Err(ConfigError::SecretFile {
                    path: path.to_path_buf(),
                    reason: "fixture failed",
                })
            }
        }
        let error = ControllerConfig::load_from(&MapEnvironment::default(), &FailingSecret)
            .expect_err("secret load fails");
        let rendered = format!("{error:?} {error}");
        assert!(!rendered.contains("api-token"));
        assert!(!rendered.contains("vnc-password"));
    }

    #[test]
    fn io_error_type_is_not_exposed_by_configuration_errors() {
        let _ = io::Error::other("type-use guard");
    }
}

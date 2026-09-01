//! Typed, validated controller configuration and file-backed secret loading.
//!
//! Production credentials are read only from files. Environment variables may
//! select secret file paths but never contain secret values. `Debug` output is
//! implemented manually and omits both secret values.

use crate::events::MIN_PROCESS_SHUTDOWN_TIMEOUT_MS;
use crate::worker::WorkerSettings;
use libvnc_adapter::{NativeClientConfig, SecretString, scrub_secret_bytes};
use remote_desktop_core::{DesktopError, MAX_FRAMEBUFFER_BYTES};
use std::env;
use std::error::Error;
use std::fmt;
use std::fs;
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
const DEFAULT_SHUTDOWN_TIMEOUT_MS: u64 = 10_500;
const DEFAULT_SCREENSHOT_CONCURRENCY: usize = 2;
const DEFAULT_SCREENSHOT_TIMEOUT_MS: u64 = 5_000;
const DEFAULT_WEBSOCKET_EVENT_CAPACITY: usize = 256;
const DEFAULT_WEBSOCKET_MAX_CLIENTS: usize = 16;
const DEFAULT_WEBSOCKET_PING_INTERVAL_MS: u64 = 15_000;
const DEFAULT_WEBSOCKET_IDLE_TIMEOUT_MS: u64 = 45_000;
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

/// Process-wide API bearer token. The value is intentionally not `Debug` or
/// `Display`; cloning this handle clones an `Arc`, not the token bytes.
#[derive(Clone, PartialEq, Eq)]
pub struct ApiToken {
    inner: Arc<SecretString>,
}

impl ApiToken {
    /// Transfers one parsed file-backed secret into long-lived token ownership.
    pub fn from_secret(secret: SecretString) -> Self {
        Self {
            inner: Arc::new(secret),
        }
    }

    /// Exposes bytes only to the constant-time bearer comparison boundary.
    pub(crate) fn as_bytes(&self) -> &[u8] {
        self.inner.expose_secret().as_bytes()
    }

    /// Returns whether this token would be unusable for authentication.
    pub(crate) fn is_empty(&self) -> bool {
        self.inner.expose_secret().is_empty()
    }

    #[cfg(test)]
    fn expose_secret_for_test(&self) -> &str {
        self.inner.expose_secret()
    }
}

/// Fully validated process configuration.
///
/// This type intentionally does not implement `Clone`: it owns native worker
/// credentials. `ApiToken` remains independently cloneable because that handle
/// shares one `Arc<SecretString>` without duplicating token bytes.
#[derive(PartialEq, Eq)]
pub struct ControllerConfig {
    /// HTTP listener address.
    pub listen_address: SocketAddr,
    /// Static bearer token. The value is intentionally not `Debug`.
    pub api_token: ApiToken,
    /// Stable identifier used to namespace screenshot ETags for this process.
    pub process_instance: Arc<str>,
    /// Maximum accepted JSON request body size.
    pub maximum_json_bytes: usize,
    /// Maximum wait for worker command completion.
    pub command_ack_timeout: Duration,
    /// One total budget shared by worker and event-bridge process cleanup.
    pub shutdown_timeout: Duration,
    /// Maximum simultaneous screenshot encodes.
    pub screenshot_concurrency: usize,
    /// Screenshot encode deadline.
    pub screenshot_timeout: Duration,
    /// Per-client WebSocket event buffer capacity.
    pub websocket_event_capacity: usize,
    /// Maximum simultaneous authenticated WebSocket clients.
    pub websocket_max_clients: usize,
    /// WebSocket heartbeat interval.
    pub websocket_ping_interval: Duration,
    /// Maximum client inactivity before heartbeat cleanup.
    pub websocket_idle_timeout: Duration,
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
            .field("shutdown_timeout", &self.shutdown_timeout)
            .field("screenshot_concurrency", &self.screenshot_concurrency)
            .field("screenshot_timeout", &self.screenshot_timeout)
            .field("websocket_event_capacity", &self.websocket_event_capacity)
            .field("websocket_max_clients", &self.websocket_max_clients)
            .field("websocket_ping_interval", &self.websocket_ping_interval)
            .field("websocket_idle_timeout", &self.websocket_idle_timeout)
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
        let listen_address = value_or(environment, "VRC_LISTEN_ADDR", DEFAULT_LISTEN_ADDRESS)?
            .parse::<SocketAddr>()
            .map_err(|_| ConfigError::InvalidValue("VRC_LISTEN_ADDR"))?;
        if listen_address.port() == 0 {
            return Err(ConfigError::InvalidValue("VRC_LISTEN_ADDR"));
        }

        let api_token_path = PathBuf::from(value_or(
            environment,
            "VRC_API_TOKEN_FILE",
            DEFAULT_API_TOKEN_FILE,
        )?);
        let vnc_password_path = PathBuf::from(value_or(
            environment,
            "VRC_VNC_PASSWORD_FILE",
            DEFAULT_VNC_PASSWORD_FILE,
        )?);
        let api_token = ApiToken::from_secret(secrets.read_secret(&api_token_path)?);
        if api_token.is_empty() {
            return Err(ConfigError::SecretFile {
                path: api_token_path,
                reason: "contents are empty or contain NUL",
            });
        }
        let vnc_password = secrets.read_secret(&vnc_password_path)?;

        let process_instance = match environment_value(environment, "VRC_PROCESS_INSTANCE")? {
            Some(value) => value,
            None => default_process_instance()?,
        };
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
        let shutdown_timeout = parse_duration_ms(
            environment,
            "VRC_SHUTDOWN_TIMEOUT_MS",
            DEFAULT_SHUTDOWN_TIMEOUT_MS,
        )?;
        if shutdown_timeout < Duration::from_millis(MIN_PROCESS_SHUTDOWN_TIMEOUT_MS) {
            return Err(ConfigError::InvalidValue("VRC_SHUTDOWN_TIMEOUT_MS"));
        }
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
        let websocket_event_capacity = parse_bounded_usize(
            environment,
            "VRC_WEBSOCKET_EVENT_CAPACITY",
            DEFAULT_WEBSOCKET_EVENT_CAPACITY,
            1,
            MAX_CHANNEL_CAPACITY,
        )?;
        let websocket_max_clients = parse_bounded_usize(
            environment,
            "VRC_WEBSOCKET_MAX_CLIENTS",
            DEFAULT_WEBSOCKET_MAX_CLIENTS,
            1,
            MAX_CHANNEL_CAPACITY,
        )?;
        let websocket_ping_interval = parse_duration_ms(
            environment,
            "VRC_WEBSOCKET_PING_INTERVAL_MS",
            DEFAULT_WEBSOCKET_PING_INTERVAL_MS,
        )?;
        let websocket_idle_timeout = parse_duration_ms(
            environment,
            "VRC_WEBSOCKET_IDLE_TIMEOUT_MS",
            DEFAULT_WEBSOCKET_IDLE_TIMEOUT_MS,
        )?;
        if websocket_idle_timeout <= websocket_ping_interval {
            return Err(ConfigError::InvalidValue("VRC_WEBSOCKET_IDLE_TIMEOUT_MS"));
        }

        let vnc_host = value_or(environment, "VRC_VNC_HOST", DEFAULT_VNC_HOST)?;
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
                password: vnc_password,
                connect_timeout: parse_duration_ms(
                    environment,
                    "VRC_VNC_CONNECT_TIMEOUT_MS",
                    10_000,
                )?,
                read_timeout: parse_duration_ms(environment, "VRC_VNC_READ_TIMEOUT_MS", 10_000)?,
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
        let maximum_worker_blocking_wait = worker
            .native
            .connect_timeout
            .max(worker.native.read_timeout)
            .max(worker.poll_interval);
        let minimum_shutdown_timeout = maximum_worker_blocking_wait
            .checked_add(Duration::from_millis(MIN_PROCESS_SHUTDOWN_TIMEOUT_MS))
            .ok_or(ConfigError::InvalidValue("VRC_SHUTDOWN_TIMEOUT_MS"))?;
        if shutdown_timeout < minimum_shutdown_timeout {
            return Err(ConfigError::InvalidValue("VRC_SHUTDOWN_TIMEOUT_MS"));
        }

        Ok(Self {
            listen_address,
            api_token,
            process_instance: Arc::from(process_instance),
            maximum_json_bytes,
            command_ack_timeout,
            shutdown_timeout,
            screenshot_concurrency,
            screenshot_timeout,
            websocket_event_capacity,
            websocket_max_clients,
            websocket_ping_interval,
            websocket_idle_timeout,
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
                write!(
                    formatter,
                    "invalid secret file {}: {reason}",
                    path.display()
                )
            }
            Self::Worker(error) => write!(formatter, "invalid worker configuration: {error}"),
        }
    }
}

impl Error for ConfigError {}

/// Environment lookup failure that carries no environment value bytes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EnvironmentReadError {
    /// The variable is present but cannot be represented as Unicode.
    NotUnicode,
}

/// Read-only environment abstraction used by configuration loading.
pub trait EnvironmentSource {
    /// Distinguishes an absent value from a present non-Unicode value.
    fn get(&self, name: &str) -> Result<Option<String>, EnvironmentReadError>;
}

/// Current process environment source.
pub struct ProcessEnvironment;

impl EnvironmentSource for ProcessEnvironment {
    fn get(&self, name: &str) -> Result<Option<String>, EnvironmentReadError> {
        match env::var(name) {
            Ok(value) => Ok(Some(value)),
            Err(env::VarError::NotPresent) => Ok(None),
            Err(env::VarError::NotUnicode(_)) => Err(EnvironmentReadError::NotUnicode),
        }
    }
}

/// File-backed secret source.
pub trait SecretReader {
    /// Reads and validates one secret without exposing it in errors.
    fn read_secret(&self, path: &Path) -> Result<SecretString, ConfigError>;
}

/// Production filesystem secret reader.
pub struct SystemSecretReader;

impl SecretReader for SystemSecretReader {
    fn read_secret(&self, path: &Path) -> Result<SecretString, ConfigError> {
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
        parse_secret_bytes(path, bytes)
    }
}

fn parse_secret_bytes(path: &Path, bytes: Vec<u8>) -> Result<SecretString, ConfigError> {
    parse_secret_bytes_with_rejection_observer(path, bytes, |_| {})
}

fn parse_secret_bytes_with_rejection_observer<F>(
    path: &Path,
    mut bytes: Vec<u8>,
    observe_rejection: F,
) -> Result<SecretString, ConfigError>
where
    F: FnOnce(&[u8]),
{
    if std::str::from_utf8(&bytes).is_err() {
        return scrub_and_reject_secret_bytes(
            path,
            bytes,
            "contents are not UTF-8",
            observe_rejection,
        );
    }

    let mut trimmed_length = bytes.len();
    while trimmed_length > 0 && matches!(bytes[trimmed_length - 1], b'\n' | b'\r') {
        trimmed_length -= 1;
    }
    if trimmed_length == 0 || bytes[..trimmed_length].contains(&0) {
        return scrub_and_reject_secret_bytes(
            path,
            bytes,
            "contents are empty or contain NUL",
            observe_rejection,
        );
    }

    secure_scrub_bytes(&mut bytes[trimmed_length..]);
    bytes.truncate(trimmed_length);
    match String::from_utf8(bytes) {
        Ok(value) => Ok(SecretString::from(value)),
        Err(error) => scrub_and_reject_secret_bytes(
            path,
            error.into_bytes(),
            "contents are not UTF-8",
            observe_rejection,
        ),
    }
}

fn scrub_and_reject_secret_bytes<F>(
    path: &Path,
    mut bytes: Vec<u8>,
    reason: &'static str,
    observe_rejection: F,
) -> Result<SecretString, ConfigError>
where
    F: FnOnce(&[u8]),
{
    secure_scrub_bytes(&mut bytes);
    observe_rejection(&bytes);
    Err(ConfigError::SecretFile {
        path: path.to_path_buf(),
        reason,
    })
}

fn secure_scrub_bytes(bytes: &mut [u8]) {
    scrub_secret_bytes(bytes);
}

#[cfg(unix)]
fn validate_secret_permissions(path: &Path, metadata: &fs::Metadata) -> Result<(), ConfigError> {
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
fn validate_secret_permissions(_path: &Path, _metadata: &fs::Metadata) -> Result<(), ConfigError> {
    Ok(())
}

fn environment_value<E: EnvironmentSource>(
    environment: &E,
    name: &'static str,
) -> Result<Option<String>, ConfigError> {
    environment
        .get(name)
        .map_err(|EnvironmentReadError::NotUnicode| ConfigError::InvalidValue(name))
}

fn value_or<E: EnvironmentSource>(
    environment: &E,
    name: &'static str,
    default: &str,
) -> Result<String, ConfigError> {
    Ok(environment_value(environment, name)?.unwrap_or_else(|| default.to_owned()))
}

fn parse_u16<E: EnvironmentSource>(
    environment: &E,
    name: &'static str,
    default: u16,
) -> Result<u16, ConfigError> {
    match environment_value(environment, name)? {
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
    let milliseconds = match environment_value(environment, name)? {
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
    let value = match environment_value(environment, name)? {
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

fn default_process_instance() -> Result<String, ConfigError> {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| ConfigError::InvalidValue("VRC_PROCESS_INSTANCE"))?
        .as_nanos();
    Ok(format!("p{}-{nanos:x}", std::process::id()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::io;
    use std::sync::{Arc, Mutex};

    #[derive(Default)]
    struct MapEnvironment(HashMap<String, String>);

    impl EnvironmentSource for MapEnvironment {
        fn get(&self, name: &str) -> Result<Option<String>, EnvironmentReadError> {
            Ok(self.0.get(name).cloned())
        }
    }

    struct NonUnicodeEnvironment {
        rejected_name: &'static str,
    }

    impl EnvironmentSource for NonUnicodeEnvironment {
        fn get(&self, name: &str) -> Result<Option<String>, EnvironmentReadError> {
            if name == self.rejected_name {
                Err(EnvironmentReadError::NotUnicode)
            } else {
                Ok(None)
            }
        }
    }

    struct MapSecrets(HashMap<PathBuf, String>);

    impl SecretReader for MapSecrets {
        fn read_secret(&self, path: &Path) -> Result<SecretString, ConfigError> {
            self.0
                .get(path)
                .cloned()
                .map(SecretString::from)
                .ok_or_else(|| ConfigError::SecretFile {
                    path: path.to_path_buf(),
                    reason: "fixture is missing",
                })
        }
    }

    fn secrets() -> MapSecrets {
        MapSecrets(HashMap::from([
            (
                PathBuf::from(DEFAULT_API_TOKEN_FILE),
                "api-token".to_owned(),
            ),
            (
                PathBuf::from(DEFAULT_VNC_PASSWORD_FILE),
                "vnc-password".to_owned(),
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
        assert_eq!(config.shutdown_timeout, Duration::from_millis(10_500));

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
            ("VRC_VNC_PASSWORD_FILE".to_owned(), "/tmp/vnc".to_owned()),
            ("VRC_VNC_HOST".to_owned(), "desktop.internal".to_owned()),
            ("VRC_VNC_PORT".to_owned(), "5999".to_owned()),
            ("VRC_COMMAND_CAPACITY".to_owned(), "8".to_owned()),
            ("VRC_EVENT_CAPACITY".to_owned(), "9".to_owned()),
            ("VRC_SHUTDOWN_TIMEOUT_MS".to_owned(), "1500".to_owned()),
            ("VRC_VNC_CONNECT_TIMEOUT_MS".to_owned(), "1000".to_owned()),
            ("VRC_VNC_READ_TIMEOUT_MS".to_owned(), "1000".to_owned()),
            ("VRC_WEBSOCKET_EVENT_CAPACITY".to_owned(), "10".to_owned()),
            ("VRC_WEBSOCKET_MAX_CLIENTS".to_owned(), "3".to_owned()),
            (
                "VRC_WEBSOCKET_PING_INTERVAL_MS".to_owned(),
                "1000".to_owned(),
            ),
            (
                "VRC_WEBSOCKET_IDLE_TIMEOUT_MS".to_owned(),
                "3000".to_owned(),
            ),
            (
                "VRC_PROCESS_INSTANCE".to_owned(),
                "test-instance".to_owned(),
            ),
        ]));
        let secrets = MapSecrets(HashMap::from([
            (PathBuf::from("/tmp/api"), "selected-api".to_owned()),
            (PathBuf::from("/tmp/vnc"), "selected-vnc".to_owned()),
        ]));
        let config = ControllerConfig::load_from(&environment, &secrets).expect("config loads");
        assert_eq!(config.listen_address, "0.0.0.0:9090".parse().unwrap());
        assert_eq!(config.worker.native.host, "desktop.internal");
        assert_eq!(config.worker.native.port, 5999);
        assert_eq!(config.worker.command_capacity, 8);
        assert_eq!(config.worker.event_capacity, 9);
        assert_eq!(config.shutdown_timeout, Duration::from_millis(1500));
        assert_eq!(config.websocket_event_capacity, 10);
        assert_eq!(config.websocket_max_clients, 3);
        assert_eq!(config.websocket_ping_interval, Duration::from_secs(1));
        assert_eq!(config.websocket_idle_timeout, Duration::from_secs(3));
        assert_eq!(config.process_instance.as_ref(), "test-instance");
    }

    #[test]
    fn non_unicode_controller_environment_values_fail_closed() {
        for name in [
            "VRC_LISTEN_ADDR",
            "VRC_API_TOKEN_FILE",
            "VRC_VNC_PASSWORD_FILE",
            "VRC_PROCESS_INSTANCE",
            "VRC_MAX_JSON_BYTES",
            "VRC_COMMAND_ACK_TIMEOUT_MS",
            "VRC_SHUTDOWN_TIMEOUT_MS",
            "VRC_SCREENSHOT_MAX_CONCURRENT",
            "VRC_SCREENSHOT_TIMEOUT_MS",
            "VRC_WEBSOCKET_EVENT_CAPACITY",
            "VRC_WEBSOCKET_MAX_CLIENTS",
            "VRC_WEBSOCKET_PING_INTERVAL_MS",
            "VRC_WEBSOCKET_IDLE_TIMEOUT_MS",
            "VRC_VNC_HOST",
            "VRC_VNC_PORT",
            "VRC_VNC_CONNECT_TIMEOUT_MS",
            "VRC_VNC_READ_TIMEOUT_MS",
            "VRC_COMMAND_CAPACITY",
            "VRC_EVENT_CAPACITY",
            "VRC_MAX_FRAMEBUFFER_BYTES",
            "VRC_POLL_INTERVAL_MS",
            "VRC_STARTUP_TIMEOUT_MS",
            "VRC_RECONNECT_MIN_MS",
            "VRC_RECONNECT_MAX_MS",
            "VRC_RECONNECT_JITTER_PER_MILLE",
            "VRC_STABLE_CONNECTION_RESET_MS",
            "VRC_MANUAL_RECONNECT_INTERVAL_MS",
            "VRC_STALL_PROBE_AFTER_MS",
            "VRC_STALL_CONFIRM_AFTER_MS",
        ] {
            let error = ControllerConfig::load_from(
                &NonUnicodeEnvironment {
                    rejected_name: name,
                },
                &secrets(),
            )
            .expect_err("present non-Unicode environment value must fail");
            assert!(matches!(error, ConfigError::InvalidValue(value) if value == name));
        }
    }

    #[test]
    fn invalid_ports_limits_and_durations_fail_closed() {
        for (name, value) in [
            ("VRC_LISTEN_ADDR", "127.0.0.1:0"),
            ("VRC_VNC_PORT", "0"),
            ("VRC_COMMAND_CAPACITY", "0"),
            ("VRC_MAX_JSON_BYTES", "2097153"),
            ("VRC_SCREENSHOT_MAX_CONCURRENT", "65"),
            ("VRC_WEBSOCKET_EVENT_CAPACITY", "0"),
            ("VRC_WEBSOCKET_MAX_CLIENTS", "0"),
            ("VRC_WEBSOCKET_PING_INTERVAL_MS", "0"),
            ("VRC_COMMAND_ACK_TIMEOUT_MS", "0"),
            ("VRC_SHUTDOWN_TIMEOUT_MS", "499"),
            ("VRC_RECONNECT_JITTER_PER_MILLE", "501"),
        ] {
            let environment = MapEnvironment(HashMap::from([(name.to_owned(), value.to_owned())]));
            assert!(ControllerConfig::load_from(&environment, &secrets()).is_err());
        }
    }

    #[test]
    fn process_shutdown_budget_covers_longest_single_worker_wait_plus_cleanup_margin() {
        let common = [
            ("VRC_VNC_CONNECT_TIMEOUT_MS".to_owned(), "1000".to_owned()),
            ("VRC_VNC_READ_TIMEOUT_MS".to_owned(), "1000".to_owned()),
            ("VRC_POLL_INTERVAL_MS".to_owned(), "1000".to_owned()),
        ];
        let below = MapEnvironment(HashMap::from_iter(
            common
                .clone()
                .into_iter()
                .chain([("VRC_SHUTDOWN_TIMEOUT_MS".to_owned(), "1499".to_owned())]),
        ));
        assert!(ControllerConfig::load_from(&below, &secrets()).is_err());

        let floor = MapEnvironment(HashMap::from_iter(
            common
                .into_iter()
                .chain([("VRC_SHUTDOWN_TIMEOUT_MS".to_owned(), "1500".to_owned())]),
        ));
        let config = ControllerConfig::load_from(&floor, &secrets()).expect("floor is valid");
        assert_eq!(config.shutdown_timeout, Duration::from_millis(1500));
    }

    #[test]
    fn secret_values_cannot_be_supplied_directly_by_environment() {
        let environment = MapEnvironment(HashMap::from([
            ("VRC_API_TOKEN".to_owned(), "ignored-api-value".to_owned()),
            (
                "VRC_VNC_PASSWORD".to_owned(),
                "ignored-vnc-value".to_owned(),
            ),
        ]));
        let config = ControllerConfig::load_from(&environment, &secrets()).expect("config loads");
        assert_eq!(config.api_token.expose_secret_for_test(), "api-token");
        assert_eq!(
            config.worker.native.password.expose_secret(),
            "vnc-password"
        );
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
        let secret = SystemSecretReader
            .read_secret(&secret_path)
            .expect("read-only secret");
        assert_eq!(secret.expose_secret(), "secret-value");

        fs::set_permissions(&secret_path, fs::Permissions::from_mode(0o666))
            .expect("set broad permissions");
        assert!(SystemSecretReader.read_secret(&secret_path).is_err());
    }

    fn rejected_secret_observation(bytes: Vec<u8>) -> (Result<SecretString, ConfigError>, Vec<u8>) {
        let observed = Arc::new(Mutex::new(Vec::new()));
        let observed_for_callback = Arc::clone(&observed);
        let result = parse_secret_bytes_with_rejection_observer(
            Path::new("/tmp/secret"),
            bytes,
            move |scrubbed| {
                *observed_for_callback
                    .lock()
                    .unwrap_or_else(|poisoned| poisoned.into_inner()) = scrubbed.to_vec();
            },
        );
        let observed = observed
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .clone();
        (result, observed)
    }

    #[test]
    fn invalid_utf8_secret_bytes_are_scrubbed_before_rejection() {
        let (result, observed) = rejected_secret_observation(vec![0xff, b's', b'e', b'c']);
        assert!(matches!(
            result,
            Err(ConfigError::SecretFile {
                reason: "contents are not UTF-8",
                ..
            })
        ));
        assert_eq!(observed, vec![0, 0, 0, 0]);
    }

    #[test]
    fn nul_secret_bytes_are_scrubbed_before_rejection() {
        let (result, observed) = rejected_secret_observation(b"abc\0def".to_vec());
        assert!(matches!(
            result,
            Err(ConfigError::SecretFile {
                reason: "contents are empty or contain NUL",
                ..
            })
        ));
        assert_eq!(observed, vec![0; 7]);
    }

    #[test]
    fn empty_after_trim_secret_bytes_are_scrubbed_before_rejection() {
        let (result, observed) = rejected_secret_observation(b"\r\n".to_vec());
        assert!(matches!(
            result,
            Err(ConfigError::SecretFile {
                reason: "contents are empty or contain NUL",
                ..
            })
        ));
        assert_eq!(observed, vec![0, 0]);
    }

    #[test]
    fn secret_errors_never_include_secret_contents() {
        struct FailingSecret;
        impl SecretReader for FailingSecret {
            fn read_secret(&self, path: &Path) -> Result<SecretString, ConfigError> {
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

use controller_api::worker::{DesktopWorker, WorkerClient, WorkerSettings};
use libvnc_adapter::NativeClientConfig;
use remote_desktop_core::{
    ConnectionState, DesktopError, DesktopEventKind, MAX_FRAMEBUFFER_BYTES, WorkerCommand,
};
use std::env;
use std::error::Error;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::thread;
use std::time::{Duration, Instant};

const COMMAND_TIMEOUT: Duration = Duration::from_secs(5);
const READY_TIMEOUT: Duration = Duration::from_secs(20);
const CLIPBOARD_TIMEOUT: Duration = Duration::from_secs(20);
const SUPPORTED_TEXT: &str = "worker text 123";
const UNSUPPORTED_TEXT: &str = "blocked☃";
const OUTBOUND_CLIPBOARD: &str = "worker outbound clipboard";
const INBOUND_CLIPBOARD: &str = "desktop inbound clipboard";

fn main() {
    if let Err(error) = run() {
        eprintln!("worker text and clipboard E2E failed: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn Error>> {
    let host = required_env("VRC_VNC_HOST")?;
    let port = required_env("VRC_VNC_PORT")?.parse::<u16>()?;
    let password_path = PathBuf::from(required_env("VRC_VNC_PASSWORD_FILE")?);
    let password = read_secret(&password_path)?;

    let settings = WorkerSettings {
        native: NativeClientConfig {
            host,
            port,
            password,
            connect_timeout: Duration::from_secs(5),
            read_timeout: Duration::from_secs(5),
        },
        command_capacity: 32,
        event_capacity: 64,
        maximum_framebuffer_bytes: MAX_FRAMEBUFFER_BYTES,
        poll_interval: Duration::from_millis(10),
        startup_timeout: Duration::from_secs(5),
        reconnect_min_delay: Duration::from_millis(100),
        reconnect_max_delay: Duration::from_secs(1),
        reconnect_jitter_per_mille: 0,
        stable_connection_reset: Duration::from_secs(2),
        manual_reconnect_interval: Duration::from_secs(1),
        stall_probe_after: Duration::from_secs(10),
        stall_confirm_after: Duration::from_secs(5),
    };

    let worker = DesktopWorker::spawn(settings)?;
    let client = worker.client();
    wait_for_complete_frame(&client, READY_TIMEOUT)?;

    execute(
        &client,
        WorkerCommand::TypeText {
            text: SUPPORTED_TEXT.to_owned(),
        },
    )?;

    let unsupported_error = client
        .submit(WorkerCommand::TypeText {
            text: UNSUPPORTED_TEXT.to_owned(),
        })?
        .wait(COMMAND_TIMEOUT)
        .expect_err("unsupported text must fail before native mutation");
    if !matches!(unsupported_error, DesktopError::UnsupportedText { .. }) {
        return Err(io::Error::other("unsupported text returned the wrong error category").into());
    }

    execute(
        &client,
        WorkerCommand::SetClipboard {
            text: OUTBOUND_CLIPBOARD.to_owned(),
        },
    )?;
    println!("worker_text_clipboard_outbound_ready=1");

    let clipboard = wait_for_clipboard(&client, CLIPBOARD_TIMEOUT)?;
    let mut saw_revision_event = false;
    let event_deadline = Instant::now() + Duration::from_secs(2);
    while Instant::now() < event_deadline {
        match worker.events().recv_timeout(Duration::from_millis(50)) {
            Ok(event)
                if event.kind
                    == DesktopEventKind::ClipboardRevision {
                        revision: clipboard.revision,
                    } =>
            {
                saw_revision_event = true;
                break;
            }
            Ok(_) => {}
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {}
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
                return Err(io::Error::other("worker event channel disconnected").into());
            }
        }
    }
    if !saw_revision_event {
        return Err(io::Error::other("clipboard revision event was not observed").into());
    }

    worker.shutdown(COMMAND_TIMEOUT)?;
    println!(
        "worker_text_clipboard_e2e_complete=1 clipboard_revision={}",
        clipboard.revision
    );
    Ok(())
}

fn execute(client: &WorkerClient, command: WorkerCommand) -> Result<(), Box<dyn Error>> {
    client.submit(command)?.wait(COMMAND_TIMEOUT)?;
    Ok(())
}

fn wait_for_complete_frame(client: &WorkerClient, timeout: Duration) -> Result<(), Box<dyn Error>> {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        let snapshot = client.snapshot();
        if snapshot.state == ConnectionState::Connected && client.framebuffer_snapshot().is_ok() {
            return Ok(());
        }
        if matches!(
            snapshot.state,
            ConnectionState::AuthenticationFailed | ConnectionState::Stopped
        ) {
            return Err(io::Error::other(format!(
                "worker entered terminal state {:?}",
                snapshot.state
            ))
            .into());
        }
        thread::sleep(Duration::from_millis(20));
    }
    Err(io::Error::new(
        io::ErrorKind::TimedOut,
        "worker did not expose a complete framebuffer before deadline",
    )
    .into())
}

fn wait_for_clipboard(
    client: &WorkerClient,
    timeout: Duration,
) -> Result<remote_desktop_core::ClipboardSnapshot, Box<dyn Error>> {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        match client.clipboard_snapshot() {
            Ok(snapshot) if snapshot.text.as_ref() == INBOUND_CLIPBOARD => return Ok(snapshot),
            Ok(_) | Err(DesktopError::ClipboardUnavailable) => {}
            Err(error) => return Err(error.into()),
        }
        thread::sleep(Duration::from_millis(20));
    }
    Err(io::Error::new(
        io::ErrorKind::TimedOut,
        "worker did not receive the expected inbound clipboard before deadline",
    )
    .into())
}

fn required_env(name: &str) -> Result<String, Box<dyn Error>> {
    env::var(name).map_err(|_| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("required environment variable {name} is missing"),
        )
        .into()
    })
}

fn read_secret(path: &Path) -> Result<String, Box<dyn Error>> {
    let mut value = fs::read_to_string(path)?;
    while value.ends_with('\n') || value.ends_with('\r') {
        value.pop();
    }
    if value.is_empty() {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "VNC password is empty").into());
    }
    Ok(value)
}

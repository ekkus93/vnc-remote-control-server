use controller_api::worker::{DesktopWorker, WorkerClient, WorkerSettings};
use libvnc_adapter::NativeClientConfig;
use remote_desktop_core::{
    ConnectionState, Coordinate, KeyboardKey, MAX_FRAMEBUFFER_BYTES, MouseButton, WorkerCommand,
};
use std::env;
use std::error::Error;
use std::fs;
use std::io;
use std::path::PathBuf;
use std::thread;
use std::time::{Duration, Instant};

const COMMAND_TIMEOUT: Duration = Duration::from_secs(5);
const READY_TIMEOUT: Duration = Duration::from_secs(20);
const INPUT_COORDINATE: Coordinate = Coordinate { x: 320, y: 240 };

fn main() {
    if let Err(error) = run() {
        eprintln!("worker input E2E failed: {error}");
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
        command_capacity: 16,
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
        WorkerCommand::MovePointer {
            coordinate: INPUT_COORDINATE,
        },
    )?;
    execute(
        &client,
        WorkerCommand::Click {
            coordinate: INPUT_COORDINATE,
            button: MouseButton::Left,
        },
    )?;
    execute(
        &client,
        WorkerCommand::Scroll {
            coordinate: INPUT_COORDINATE,
            delta_x: 0,
            delta_y: 2,
        },
    )?;
    execute(
        &client,
        WorkerCommand::SetKey {
            key: KeyboardKey::F5,
            pressed: true,
        },
    )?;
    execute(
        &client,
        WorkerCommand::SetKey {
            key: KeyboardKey::F5,
            pressed: false,
        },
    )?;
    execute(
        &client,
        WorkerCommand::Chord {
            keys: vec![
                KeyboardKey::CtrlLeft,
                KeyboardKey::ShiftLeft,
                KeyboardKey::F6,
            ],
        },
    )?;

    thread::sleep(Duration::from_millis(500));
    worker.shutdown(COMMAND_TIMEOUT)?;
    println!("worker_input_e2e_complete=1");
    Ok(())
}

fn execute(client: &WorkerClient, command: WorkerCommand) -> Result<(), Box<dyn Error>> {
    client.submit(command)?.wait(COMMAND_TIMEOUT)?;
    Ok(())
}

fn wait_for_complete_frame(
    client: &WorkerClient,
    timeout: Duration,
) -> Result<(), Box<dyn Error>> {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        let snapshot = client.snapshot();
        if snapshot.state == ConnectionState::Connected
            && client.framebuffer_snapshot().is_ok()
        {
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

fn required_env(name: &str) -> Result<String, Box<dyn Error>> {
    env::var(name).map_err(|_| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("required environment variable {name} is missing"),
        )
        .into()
    })
}

fn read_secret(path: &PathBuf) -> Result<String, Box<dyn Error>> {
    let mut value = fs::read_to_string(path)?;
    while value.ends_with('\n') || value.ends_with('\r') {
        value.pop();
    }
    if value.is_empty() {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "VNC password is empty").into());
    }
    Ok(value)
}

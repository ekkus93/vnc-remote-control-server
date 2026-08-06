use controller_api::framebuffer::FramebufferError;
use controller_api::screenshot::ScreenshotOutcome;
use controller_api::worker::{DesktopWorker, WorkerClient, WorkerSettings};
use libvnc_adapter::{NativeClientConfig, SecretString};
use remote_desktop_core::{
    ConnectionState, DesktopError, DesktopEventKind, MAX_FRAMEBUFFER_BYTES, WorkerCommand,
};
use std::env;
use std::error::Error;
use std::fs;
use std::io::{self, Cursor};
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
const DOMINANT_MINIMUM: u8 = 200;
const OTHER_MAXIMUM: u8 = 60;

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
    let red = required_coordinate("VRC_RED_SWATCH_X", "VRC_RED_SWATCH_Y")?;
    let blue = required_coordinate("VRC_BLUE_SWATCH_X", "VRC_BLUE_SWATCH_Y")?;

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
    wait_for_colors(&client, red, blue, READY_TIMEOUT)?;
    println!("worker_rgbx_color_proof=1");

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
    if !matches!(
        unsupported_error,
        DesktopError::UnsupportedTextCharacter { .. }
    ) {
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
                if matches!(
                    event.kind,
                    DesktopEventKind::ClipboardRevision { revision }
                        if revision == clipboard.revision
                ) =>
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

fn wait_for_colors(
    client: &WorkerClient,
    red: (u32, u32),
    blue: (u32, u32),
    timeout: Duration,
) -> Result<(), Box<dyn Error>> {
    let deadline = Instant::now() + timeout;
    let mut last_revision = None;
    let mut last_error = String::from("no framebuffer revision was observed");
    while Instant::now() < deadline {
        match client.framebuffer_snapshot() {
            Ok(snapshot) if last_revision != Some(snapshot.revision()) => {
                last_revision = Some(snapshot.revision());
                match verify_colors(client, red, blue) {
                    Ok(()) => return Ok(()),
                    Err(error) => last_error = error.to_string(),
                }
            }
            Ok(_) | Err(FramebufferError::Unavailable | FramebufferError::Stale) => {}
            Err(error) => return Err(error.into()),
        }
        thread::sleep(Duration::from_millis(20));
    }
    Err(io::Error::new(
        io::ErrorKind::TimedOut,
        format!(
            "no framebuffer revision contained the deterministic RGBX swatches; last_revision={last_revision:?} last_error={last_error}"
        ),
    )
    .into())
}

fn verify_colors(
    client: &WorkerClient,
    red: (u32, u32),
    blue: (u32, u32),
) -> Result<(), Box<dyn Error>> {
    let snapshot = client.framebuffer_snapshot()?;
    assert_color(
        snapshot.rgba(),
        snapshot.width(),
        snapshot.height(),
        red,
        true,
    )?;
    assert_color(
        snapshot.rgba(),
        snapshot.width(),
        snapshot.height(),
        blue,
        false,
    )?;

    let service = client.screenshot_service("rgbx-e2e", 1, Duration::from_secs(5))?;
    let png_bytes = match service.capture(None)? {
        ScreenshotOutcome::Png { bytes, .. } => bytes,
        ScreenshotOutcome::NotModified { .. } => {
            return Err(io::Error::other("unconditional screenshot returned not modified").into());
        }
    };
    let decoder = png::Decoder::new(Cursor::new(png_bytes));
    let mut reader = decoder.read_info()?;
    let output_size = reader
        .output_buffer_size()
        .ok_or_else(|| io::Error::other("decoded PNG output size overflow"))?;
    let mut pixels = vec![0; output_size];
    let info = reader.next_frame(&mut pixels)?;
    if info.color_type != png::ColorType::Rgba || info.bit_depth != png::BitDepth::Eight {
        return Err(io::Error::other("screenshot PNG is not RGBA8").into());
    }
    let pixels = &pixels[..info.buffer_size()];
    assert_color(pixels, info.width, info.height, red, true)?;
    assert_color(pixels, info.width, info.height, blue, false)?;
    Ok(())
}

fn assert_color(
    rgba: &[u8],
    width: u32,
    height: u32,
    coordinate: (u32, u32),
    expect_red: bool,
) -> Result<(), Box<dyn Error>> {
    let (x, y) = coordinate;
    if x >= width || y >= height {
        return Err(io::Error::other("swatch coordinate is outside framebuffer").into());
    }
    let pixel = usize::try_from(u64::from(y) * u64::from(width) + u64::from(x))?
        .checked_mul(4)
        .ok_or_else(|| io::Error::other("pixel offset overflow"))?;
    let channels = rgba
        .get(pixel..pixel + 4)
        .ok_or_else(|| io::Error::other("pixel bytes are unavailable"))?;
    let valid = if expect_red {
        channels[0] > DOMINANT_MINIMUM && channels[1] < OTHER_MAXIMUM && channels[2] < OTHER_MAXIMUM
    } else {
        channels[2] > DOMINANT_MINIMUM && channels[0] < OTHER_MAXIMUM && channels[1] < OTHER_MAXIMUM
    };
    if !valid || channels[3] != u8::MAX {
        let expected = if expect_red { "red" } else { "blue" };
        return Err(io::Error::other(format!(
            "RGBX channel-order assertion failed: expected={expected} coordinate={x},{y} channels={:02x},{:02x},{:02x},{:02x}",
            channels[0], channels[1], channels[2], channels[3]
        ))
        .into());
    }
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

fn required_coordinate(x_name: &str, y_name: &str) -> Result<(u32, u32), Box<dyn Error>> {
    Ok((
        required_env(x_name)?.parse::<u32>()?,
        required_env(y_name)?.parse::<u32>()?,
    ))
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

fn read_secret(path: &Path) -> Result<SecretString, Box<dyn Error>> {
    let mut value = fs::read_to_string(path)?;
    while value.ends_with('\n') || value.ends_with('\r') {
        value.pop();
    }
    if value.is_empty() {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "VNC password is empty").into());
    }
    Ok(SecretString::from(value))
}

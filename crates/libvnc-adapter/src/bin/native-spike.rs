use libvnc_adapter::{NativeClient, NativeClientConfig};
use remote_desktop_core::{Coordinate, DisplayInfo, KeyboardKey, checked_rgba_len};
use std::env;
use std::error::Error;
use std::fs;
use std::io;
use std::time::{Duration, Instant};

const EXPECTED_WIDTH: u32 = 1_280;
const EXPECTED_HEIGHT: u32 = 800;
const FRAMEBUFFER_DEADLINE: Duration = Duration::from_secs(15);
const POLL_INTERVAL: Duration = Duration::from_millis(250);
const POINTER_X: u32 = 100;
const POINTER_Y: u32 = 100;
const CLIPBOARD_PROOF: &str = "native-clipboard-proof";

fn main() {
    if let Err(error) = run() {
        eprintln!("native spike failed: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn Error>> {
    let host = env::var("VRC_VNC_HOST")?;
    let port = env::var("VRC_VNC_PORT")?.parse::<u16>()?;
    let password_path = env::var("VRC_VNC_PASSWORD_FILE")?;
    let mut password = fs::read_to_string(password_path)?;
    while matches!(password.as_bytes().last(), Some(b'\n' | b'\r')) {
        password.pop();
    }
    if password.is_empty() {
        return Err(
            io::Error::new(io::ErrorKind::InvalidInput, "VNC password file is empty").into(),
        );
    }

    let config = NativeClientConfig {
        host,
        port,
        password,
        connect_timeout: Duration::from_secs(5),
        read_timeout: Duration::from_secs(5),
    };
    let mut client = NativeClient::connect(&config)?;
    if client.protocol_major() != 3 {
        return Err(io::Error::other("unexpected RFB protocol major version").into());
    }

    client.request_full_refresh()?;
    let deadline = Instant::now() + FRAMEBUFFER_DEADLINE;
    loop {
        client.poll(POLL_INTERVAL)?;

        if let Ok(display) = client.display_info()
            && display.complete
        {
            if display.width != EXPECTED_WIDTH || display.height != EXPECTED_HEIGHT {
                return Err(io::Error::other("unexpected VNC framebuffer dimensions").into());
            }
            let framebuffer = client.framebuffer()?;
            let expected_length = checked_rgba_len(framebuffer.width, framebuffer.height)?;
            if framebuffer.bytes.len() != expected_length {
                return Err(io::Error::other("unexpected VNC framebuffer byte length").into());
            }

            let domain_display = DisplayInfo::new(
                framebuffer.width,
                framebuffer.height,
                24,
                framebuffer.revision,
                true,
            )?;
            let coordinate = Coordinate::new(POINTER_X, POINTER_Y, domain_display)?;
            client.send_pointer(coordinate, 0)?;
            client.send_key(KeyboardKey::F5, true)?;
            client.send_key(KeyboardKey::F5, false)?;
            client.send_clipboard(CLIPBOARD_PROOF)?;

            println!(
                "libvncclient_version={} protocol_major={} dimensions={}x{} revision={} bytes={}",
                NativeClient::library_version(),
                client.protocol_major(),
                framebuffer.width,
                framebuffer.height,
                framebuffer.revision,
                framebuffer.bytes.len()
            );
            return Ok(());
        }

        if Instant::now() >= deadline {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "complete VNC framebuffer deadline exceeded",
            )
            .into());
        }
    }
}

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "crates/controller-api/src/worker/tests/reconnect.rs"
text = TARGET.read_text(encoding="utf-8")
anchor = "#[test]\nfn mismatched_native_frame_never_reaches_connected() {\n"
if text.count(anchor) != 1:
    raise SystemExit(f"reconnect.rs: expected one CR12 insertion anchor, found {text.count(anchor)}")
addition = r'''struct MatchingSession {
    poll_count: usize,
    poll_progress: SyncSender<usize>,
}

impl WorkerSession for MatchingSession {
    fn poll(&mut self, _timeout: Duration) -> Result<PollOutcome, NativeError> {
        self.poll_count += 1;
        let _ = self.poll_progress.try_send(self.poll_count);
        Ok(PollOutcome::MessageProcessed)
    }

    fn request_full_refresh(&mut self) -> Result<(), NativeError> {
        Ok(())
    }

    fn display_info(&self) -> Result<NativeDisplayInfo, NativeError> {
        Ok(NativeDisplayInfo {
            width: 2,
            height: 2,
            revision: 5,
            complete: true,
        })
    }

    fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {
        Ok(NativeFramebuffer {
            width: 2,
            height: 2,
            revision: 5,
            bytes: vec![
                0x11, 0x22, 0x33, 0x90,
                0x44, 0x55, 0x66, 0x80,
                0x77, 0x88, 0x99, 0x70,
                0xaa, 0xbb, 0xcc, 0x60,
            ],
        })
    }

    fn clipboard(&self) -> Result<NativeClipboard, NativeError> {
        Err(NativeError::ClipboardUnavailable)
    }

    fn send_pointer(
        &mut self,
        _coordinate: Coordinate,
        _button_mask: u8,
    ) -> Result<(), NativeError> {
        Ok(())
    }

    fn send_key(&mut self, _key: KeyboardKey, _pressed: bool) -> Result<(), NativeError> {
        Ok(())
    }

    fn send_clipboard(&mut self, _text: &str) -> Result<(), NativeError> {
        Ok(())
    }
}

/// CR12 positive control for `mismatched_native_frame_never_reaches_connected`.
/// Uses the same worker-session and causal poll-progress observation path, but a
/// matching complete native frame must become Connected and publish real pixels.
#[test]
fn matching_native_frame_positive_control_reaches_connected() {
    let (poll_tx, poll_rx) = sync_channel(8);
    let worker = DesktopWorker::spawn_with_factory(settings(), move || {
        Ok(MatchingSession {
            poll_count: 0,
            poll_progress: poll_tx.clone(),
        })
    })
    .expect("worker spawns");
    let client = worker.client();

    poll_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("positive-control fixture observes causal worker poll progress");
    wait_for_state(&client, ConnectionState::Connected);

    let frame = client
        .framebuffer_snapshot()
        .expect("matching complete native frame becomes current");
    assert_eq!(frame.width(), 2);
    assert_eq!(frame.height(), 2);
    assert_eq!(frame.revision(), 1);
    assert_eq!(client.snapshot().framebuffer_revision, Some(frame.revision()));
    assert_eq!(
        frame.rgba(),
        &[
            0x11, 0x22, 0x33, 0xff,
            0x44, 0x55, 0x66, 0xff,
            0x77, 0x88, 0x99, 0xff,
            0xaa, 0xbb, 0xcc, 0xff,
        ]
    );

    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

'''
TARGET.write_text(text.replace(anchor, addition + anchor, 1), encoding="utf-8")
Path(__file__).unlink()

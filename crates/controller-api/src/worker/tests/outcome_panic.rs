use super::*;
use super::super::outcome::{CommandOutcomeLookup, CommandOutcomeState};
use libvnc_adapter::{NativeClipboard, NativeDisplayInfo, NativeError, NativeFramebuffer, PollOutcome};
use remote_desktop_core::{DesktopError, WorkerCommand};
use std::sync::mpsc::{Receiver, SyncSender, sync_channel};
use std::time::Duration;

struct PanicAfterReleaseSession {
    entered: SyncSender<()>,
    release: Receiver<()>,
    poll_count: usize,
}

impl WorkerSession for PanicAfterReleaseSession {
    fn poll(&mut self, _timeout: Duration) -> Result<PollOutcome, NativeError> {
        self.poll_count += 1;
        if self.poll_count == 1 {
            return Ok(PollOutcome::MessageProcessed);
        }
        self.entered.send(()).expect("test observer remains present");
        self.release.recv().expect("test release remains present");
        panic!("test-only unexpected worker panic after command admission");
    }

    fn request_full_refresh(&mut self) -> Result<(), NativeError> {
        Ok(())
    }

    fn display_info(&self) -> Result<NativeDisplayInfo, NativeError> {
        Ok(NativeDisplayInfo {
            width: 2,
            height: 2,
            revision: 1,
            complete: true,
        })
    }

    fn clipboard(&self) -> Result<NativeClipboard, NativeError> {
        Err(NativeError::ClipboardUnavailable)
    }

    fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {
        Ok(NativeFramebuffer {
            width: 2,
            height: 2,
            revision: 1,
            bytes: vec![1, 2, 3, 0, 4, 5, 6, 0, 7, 8, 9, 0, 10, 11, 12, 0],
        })
    }

    fn send_pointer(
        &mut self,
        _coordinate: remote_desktop_core::Coordinate,
        _button_mask: u8,
    ) -> Result<(), NativeError> {
        Ok(())
    }

    fn send_key(
        &mut self,
        _key: remote_desktop_core::KeyboardKey,
        _pressed: bool,
    ) -> Result<(), NativeError> {
        Ok(())
    }

    fn send_clipboard(&mut self, _text: &str) -> Result<(), NativeError> {
        Ok(())
    }
}

#[test]
fn timed_out_accepted_command_is_aborted_after_unexpected_worker_panic() {
    let (entered_tx, entered_rx) = sync_channel(1);
    let (release_tx, release_rx) = sync_channel(1);
    let mut session = Some(PanicAfterReleaseSession {
        entered: entered_tx,
        release: release_rx,
        poll_count: 0,
    });
    let worker = DesktopWorker::spawn_with_factory(settings(), move || {
        session.take().ok_or_else(|| NativeError::NativeFailure {
            message: "test-only panic session factory reused".to_owned(),
        })
    })
    .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);
    entered_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("worker enters blocking poll before command admission");

    let ticket = client
        .submit(WorkerCommand::RequestFullRefresh)
        .expect("command is accepted while worker is blocked");
    let command_id = ticket.id();
    assert_eq!(ticket.wait(Duration::ZERO), Err(DesktopError::Timeout));

    let CommandOutcomeLookup::Found(pending) = client.command_outcome(command_id) else {
        panic!("timed-out accepted command must remain inspectable");
    };
    assert_eq!(pending.state(), CommandOutcomeState::Queued);
    assert!(!pending.retry_safe());

    release_tx
        .send(())
        .expect("release poll into deliberate unexpected panic");

    let deadline = std::time::Instant::now() + Duration::from_secs(1);
    loop {
        match client.command_outcome(command_id) {
            CommandOutcomeLookup::Found(record)
                if record.state() == CommandOutcomeState::Aborted =>
            {
                assert_eq!(record.command_id(), command_id);
                assert_eq!(record.failure(), Some("worker_unavailable"));
                assert!(!record.retry_safe());
                break;
            }
            CommandOutcomeLookup::Found(_) if std::time::Instant::now() < deadline => {
                std::thread::sleep(Duration::from_millis(1));
            }
            other => panic!("panic did not converge command outcome to aborted: {other:?}"),
        }
    }

    assert_eq!(
        worker.shutdown(Duration::from_secs(1)),
        Err(DesktopError::WorkerUnavailable)
    );
}

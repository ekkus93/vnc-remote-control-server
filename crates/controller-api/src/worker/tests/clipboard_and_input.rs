use super::*;
use remote_desktop_core::{
    DesktopError, DesktopEventKind, KeyboardKey, MouseButton, WorkerCommand,
};
use std::time::Duration;

#[test]
fn worker_publishes_last_valid_inbound_clipboard_snapshot() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let factory_events = Arc::clone(&events);
    let worker = DesktopWorker::spawn_with_factory(settings(), move || {
        Ok(RecordingSession::with_clipboard(
            Arc::clone(&factory_events),
            "from desktop",
            7,
        ))
    })
    .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);

    let deadline = Instant::now() + Duration::from_secs(1);
    let clipboard = loop {
        match client.clipboard_snapshot() {
            Ok(snapshot) => break snapshot,
            Err(DesktopError::ClipboardUnavailable) if Instant::now() < deadline => {
                thread::sleep(Duration::from_millis(1));
            }
            other => panic!("clipboard snapshot unavailable: {other:?}"),
        }
    };
    assert_eq!(clipboard.text.as_ref(), "from desktop");
    assert_eq!(clipboard.revision, 1);

    let mut saw_revision = false;
    while let Ok(event) = worker.events().recv_timeout(Duration::from_millis(20)) {
        if matches!(
            event.kind,
            DesktopEventKind::ClipboardRevision { revision: 1 }
        ) {
            saw_revision = true;
            break;
        }
    }
    assert!(saw_revision);
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

#[test]
fn worker_rejects_invalid_coordinate_before_native_mutation() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let factory_events = Arc::clone(&events);
    let worker = DesktopWorker::spawn_with_factory(settings(), move || {
        Ok(RecordingSession::new(Arc::clone(&factory_events), None))
    })
    .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);

    let error = client
        .submit(WorkerCommand::MovePointer {
            coordinate: Coordinate { x: 2, y: 1 },
        })
        .expect("accepted")
        .wait(Duration::from_secs(1))
        .expect_err("out-of-range coordinate must fail");
    assert!(matches!(error, DesktopError::InvalidCoordinate { .. }));
    assert!(lock_unpoisoned(&events).is_empty());
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

#[test]
fn worker_returns_partial_input_failure_after_release_retry() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let factory_events = Arc::clone(&events);
    let worker = DesktopWorker::spawn_with_factory(settings(), move || {
        Ok(RecordingSession::new(Arc::clone(&factory_events), Some(3)))
    })
    .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);
    let point = Coordinate { x: 1, y: 1 };

    client
        .submit(WorkerCommand::Click {
            coordinate: point,
            button: MouseButton::Left,
        })
        .expect("accepted")
        .wait(Duration::from_secs(1))
        .expect_err("native release failure must reach caller");
    assert_eq!(
        *lock_unpoisoned(&events),
        vec![
            InputEvent::Pointer(point, 0),
            InputEvent::Pointer(point, 1),
            InputEvent::Pointer(point, 0),
            // Aggregate V2 quarantine performs one final idempotent
            // neutralizing release before the failed session is discarded.
            InputEvent::Pointer(point, 0),
        ]
    );
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

#[test]
fn shutdown_releases_tracked_buttons_and_keys() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let factory_events = Arc::clone(&events);
    let worker = DesktopWorker::spawn_with_factory(settings(), move || {
        Ok(RecordingSession::new(Arc::clone(&factory_events), None))
    })
    .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);
    let point = Coordinate { x: 1, y: 1 };

    client
        .submit(WorkerCommand::SetButton {
            coordinate: point,
            button: MouseButton::Left,
            pressed: true,
        })
        .expect("accepted")
        .wait(Duration::from_secs(1))
        .expect("button down");
    client
        .submit(WorkerCommand::SetKey {
            key: KeyboardKey::CtrlLeft,
            pressed: true,
        })
        .expect("accepted")
        .wait(Duration::from_secs(1))
        .expect("key down");
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");

    assert_eq!(
        *lock_unpoisoned(&events),
        vec![
            InputEvent::Pointer(point, 1),
            InputEvent::Key(KeyboardKey::CtrlLeft, true),
            InputEvent::Pointer(point, 0),
            InputEvent::Key(KeyboardKey::CtrlLeft, false),
        ]
    );
}

struct ScrollRecoverySession {
    generation: usize,
    events: Arc<Mutex<Vec<(usize, InputEvent)>>>,
    pointer_calls: usize,
    fail_uncertain_pointer_recovery: bool,
}

impl ScrollRecoverySession {
    fn new(
        generation: usize,
        events: Arc<Mutex<Vec<(usize, InputEvent)>>>,
        fail_uncertain_pointer_recovery: bool,
    ) -> Self {
        Self {
            generation,
            events,
            pointer_calls: 0,
            fail_uncertain_pointer_recovery,
        }
    }

    fn record_pointer(
        &mut self,
        coordinate: Coordinate,
        button_mask: u8,
    ) -> Result<(), NativeError> {
        self.pointer_calls += 1;
        if self.fail_uncertain_pointer_recovery && matches!(self.pointer_calls, 3..=5) {
            return Err(NativeError::NativeFailure {
                message: "test-only scroll release failure".to_owned(),
            });
        }
        lock_unpoisoned(&self.events).push((
            self.generation,
            InputEvent::Pointer(coordinate, button_mask),
        ));
        Ok(())
    }

    fn record(&mut self, event: InputEvent) {
        lock_unpoisoned(&self.events).push((self.generation, event));
    }
}

impl WorkerSession for ScrollRecoverySession {
    fn poll(&mut self, timeout: Duration) -> Result<PollOutcome, NativeError> {
        thread::sleep(timeout);
        Ok(PollOutcome::MessageProcessed)
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

    fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {
        Ok(NativeFramebuffer {
            width: 2,
            height: 2,
            revision: 1,
            bytes: vec![1, 2, 3, 0, 4, 5, 6, 0, 7, 8, 9, 0, 10, 11, 12, 0],
        })
    }

    fn clipboard(&self) -> Result<NativeClipboard, NativeError> {
        Err(NativeError::ClipboardUnavailable)
    }

    fn send_pointer(&mut self, coordinate: Coordinate, button_mask: u8) -> Result<(), NativeError> {
        self.record_pointer(coordinate, button_mask)
    }

    fn send_key(&mut self, key: KeyboardKey, pressed: bool) -> Result<(), NativeError> {
        self.record(InputEvent::Key(key, pressed));
        Ok(())
    }

    fn send_clipboard(&mut self, text: &str) -> Result<(), NativeError> {
        self.record(InputEvent::Clipboard(text.to_owned()));
        Ok(())
    }
}

#[test]
fn scroll_double_release_failure_quarantines_session_and_reconnects_cleanly() {
    let events = Arc::new(Mutex::new(Vec::<(usize, InputEvent)>::new()));
    let factory_events = Arc::clone(&events);
    let generations = Arc::new(AtomicUsize::new(0));
    let factory_generations = Arc::clone(&generations);
    let worker = DesktopWorker::spawn_with_factory(settings(), move || {
        let generation = factory_generations.fetch_add(1, Ordering::AcqRel) + 1;
        Ok(ScrollRecoverySession::new(
            generation,
            Arc::clone(&factory_events),
            generation == 1,
        ))
    })
    .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);
    let point = Coordinate { x: 1, y: 1 };

    client
        .submit(WorkerCommand::SetKey {
            key: KeyboardKey::CtrlLeft,
            pressed: true,
        })
        .expect("pre-recovery key accepted")
        .wait(Duration::from_secs(1))
        .expect("pre-recovery key down");

    client
        .submit(WorkerCommand::Scroll {
            coordinate: point,
            delta_x: 0,
            delta_y: 1,
        })
        .expect("scroll accepted")
        .wait(Duration::from_secs(1))
        .expect_err("double release failure must reach caller");

    let reconnect_deadline = Instant::now() + Duration::from_secs(1);
    while Instant::now() < reconnect_deadline {
        if generations.load(Ordering::Acquire) >= 2
            && client.snapshot().state == ConnectionState::Connected
        {
            break;
        }
        thread::sleep(Duration::from_millis(1));
    }
    assert!(generations.load(Ordering::Acquire) >= 2);
    assert_eq!(client.snapshot().state, ConnectionState::Connected);

    client
        .submit(WorkerCommand::MovePointer { coordinate: point })
        .expect("post-reconnect pointer move accepted")
        .wait(Duration::from_secs(1))
        .expect("fresh session accepts pointer input");
    client
        .submit(WorkerCommand::SetKey {
            key: KeyboardKey::CtrlLeft,
            pressed: true,
        })
        .expect("post-reconnect key accepted")
        .wait(Duration::from_secs(1))
        .expect("fresh session does not retain stale key state");
    client
        .submit(WorkerCommand::SetKey {
            key: KeyboardKey::CtrlLeft,
            pressed: false,
        })
        .expect("post-reconnect key release accepted")
        .wait(Duration::from_secs(1))
        .expect("fresh session key release");

    assert_eq!(
        *lock_unpoisoned(&events),
        vec![
            (1, InputEvent::Key(KeyboardKey::CtrlLeft, true)),
            (1, InputEvent::Pointer(point, 0)),
            (1, InputEvent::Pointer(point, 1 << 3)),
            (1, InputEvent::Key(KeyboardKey::CtrlLeft, false)),
            (2, InputEvent::Pointer(point, 0)),
            (2, InputEvent::Key(KeyboardKey::CtrlLeft, true)),
            (2, InputEvent::Key(KeyboardKey::CtrlLeft, false)),
        ]
    );

    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

struct ClipboardRecoverySession {
    generation: usize,
    reject_newer: Arc<std::sync::atomic::AtomicBool>,
    enable_recovered: Arc<std::sync::atomic::AtomicBool>,
}

impl WorkerSession for ClipboardRecoverySession {
    fn poll(&mut self, timeout: Duration) -> Result<PollOutcome, NativeError> {
        thread::sleep(timeout);
        if self.generation == 1 && self.reject_newer.load(Ordering::Acquire) {
            return Err(NativeError::ClipboardTooLarge {
                bytes: remote_desktop_core::MAX_CLIPBOARD_BYTES + 1,
                maximum: remote_desktop_core::MAX_CLIPBOARD_BYTES,
            });
        }
        Ok(PollOutcome::MessageProcessed)
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

    fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {
        Ok(NativeFramebuffer {
            width: 2,
            height: 2,
            revision: 1,
            bytes: vec![1, 2, 3, 0, 4, 5, 6, 0, 7, 8, 9, 0, 10, 11, 12, 0],
        })
    }

    fn clipboard(&self) -> Result<NativeClipboard, NativeError> {
        if self.generation == 1 {
            return Ok(NativeClipboard {
                text: "old clipboard".to_owned(),
                revision: 1,
            });
        }
        if self.enable_recovered.load(Ordering::Acquire) {
            return Ok(NativeClipboard {
                text: "recovered clipboard".to_owned(),
                revision: 1,
            });
        }
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

#[test]
fn rejected_newer_clipboard_invalidates_stale_cache_and_reconnect_recovers() {
    let generations = Arc::new(AtomicUsize::new(0));
    let reject_newer = Arc::new(std::sync::atomic::AtomicBool::new(false));
    let enable_recovered = Arc::new(std::sync::atomic::AtomicBool::new(false));
    let factory_generations = Arc::clone(&generations);
    let factory_reject = Arc::clone(&reject_newer);
    let factory_recovered = Arc::clone(&enable_recovered);
    let worker = DesktopWorker::spawn_with_factory(settings(), move || {
        let generation = factory_generations.fetch_add(1, Ordering::AcqRel) + 1;
        Ok(ClipboardRecoverySession {
            generation,
            reject_newer: Arc::clone(&factory_reject),
            enable_recovered: Arc::clone(&factory_recovered),
        })
    })
    .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);

    let old_deadline = Instant::now() + Duration::from_secs(1);
    loop {
        match client.clipboard_snapshot() {
            Ok(snapshot) if snapshot.text.as_ref() == "old clipboard" => break,
            _ if Instant::now() < old_deadline => thread::sleep(Duration::from_millis(1)),
            other => panic!("initial clipboard did not become available: {other:?}"),
        }
    }

    reject_newer.store(true, Ordering::Release);
    let reconnect_deadline = Instant::now() + Duration::from_secs(1);
    while Instant::now() < reconnect_deadline {
        if generations.load(Ordering::Acquire) >= 2
            && client.snapshot().state == ConnectionState::Connected
        {
            break;
        }
        thread::sleep(Duration::from_millis(1));
    }
    assert!(generations.load(Ordering::Acquire) >= 2);
    assert_eq!(
        client.clipboard_snapshot(),
        Err(DesktopError::ClipboardUnavailable),
        "stale pre-rejection clipboard must not survive session invalidation"
    );

    enable_recovered.store(true, Ordering::Release);
    let recovered_deadline = Instant::now() + Duration::from_secs(1);
    loop {
        match client.clipboard_snapshot() {
            Ok(snapshot) if snapshot.text.as_ref() == "recovered clipboard" => break,
            _ if Instant::now() < recovered_deadline => thread::sleep(Duration::from_millis(1)),
            other => panic!("recovered clipboard did not become available: {other:?}"),
        }
    }

    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

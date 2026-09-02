use super::*;
use crate::framebuffer::FramebufferError;
use remote_desktop_core::{DesktopError, MouseButton, WorkerCommand};
use std::sync::atomic::AtomicBool;

struct PlannedFailureSession {
    generation: usize,
    events: Arc<Mutex<Vec<(usize, InputEvent)>>>,
    input_calls: usize,
    fail_calls: Vec<usize>,
}

impl PlannedFailureSession {
    fn new(
        generation: usize,
        events: Arc<Mutex<Vec<(usize, InputEvent)>>>,
        fail_calls: Vec<usize>,
    ) -> Self {
        Self {
            generation,
            events,
            input_calls: 0,
            fail_calls,
        }
    }

    fn record(&mut self, event: InputEvent) -> Result<(), NativeError> {
        self.input_calls += 1;
        if self.fail_calls.contains(&self.input_calls) {
            return Err(NativeError::NativeFailure {
                message: "test-only V2 input failure".to_owned(),
            });
        }
        lock_unpoisoned(&self.events).push((self.generation, event));
        Ok(())
    }
}

impl WorkerSession for PlannedFailureSession {
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
            revision: self.generation as u64,
            complete: true,
        })
    }

    fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {
        Ok(NativeFramebuffer {
            width: 2,
            height: 2,
            revision: self.generation as u64,
            bytes: vec![1, 2, 3, 0, 4, 5, 6, 0, 7, 8, 9, 0, 10, 11, 12, 0],
        })
    }

    fn clipboard(&self) -> Result<NativeClipboard, NativeError> {
        Err(NativeError::ClipboardUnavailable)
    }

    fn send_pointer(&mut self, coordinate: Coordinate, button_mask: u8) -> Result<(), NativeError> {
        self.record(InputEvent::Pointer(coordinate, button_mask))
    }

    fn send_key(&mut self, key: KeyboardKey, pressed: bool) -> Result<(), NativeError> {
        self.record(InputEvent::Key(key, pressed))
    }

    fn send_clipboard(&mut self, text: &str) -> Result<(), NativeError> {
        self.record(InputEvent::Clipboard(text.to_owned()))
    }
}

fn spawn_planned_failure_worker(
    first_generation_fail_calls: &[usize],
) -> (
    DesktopWorker,
    WorkerClient,
    Arc<Mutex<Vec<(usize, InputEvent)>>>,
    Arc<AtomicUsize>,
) {
    let events = Arc::new(Mutex::new(Vec::new()));
    let generations = Arc::new(AtomicUsize::new(0));
    let factory_events = Arc::clone(&events);
    let factory_generations = Arc::clone(&generations);
    let fail_calls = first_generation_fail_calls.to_vec();
    let worker = DesktopWorker::spawn_with_factory(settings(), move || {
        let generation = factory_generations.fetch_add(1, Ordering::AcqRel) + 1;
        Ok(PlannedFailureSession::new(
            generation,
            Arc::clone(&factory_events),
            if generation == 1 {
                fail_calls.clone()
            } else {
                Vec::new()
            },
        ))
    })
    .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);
    (worker, client, events, generations)
}

fn wait_for_generation(
    client: &WorkerClient,
    generations: &AtomicUsize,
    minimum_generation: usize,
) {
    let deadline = Instant::now() + Duration::from_secs(1);
    while Instant::now() < deadline {
        if generations.load(Ordering::Acquire) >= minimum_generation
            && client.snapshot().state == ConnectionState::Connected
        {
            return;
        }
        thread::sleep(Duration::from_millis(1));
    }
    panic!(
        "worker did not reach generation {minimum_generation}: {:?}",
        client.snapshot()
    );
}

#[test]
fn explicit_button_release_failure_quarantines_generation() {
    let (worker, client, events, generations) = spawn_planned_failure_worker(&[2]);
    let point = Coordinate { x: 1, y: 1 };

    client
        .submit(WorkerCommand::SetButton {
            coordinate: point,
            button: MouseButton::Left,
            pressed: true,
        })
        .expect("button-down accepted")
        .wait(Duration::from_secs(1))
        .expect("button-down succeeds");
    client
        .submit(WorkerCommand::SetButton {
            coordinate: point,
            button: MouseButton::Left,
            pressed: false,
        })
        .expect("button-up accepted")
        .wait(Duration::from_secs(1))
        .expect_err("ambiguous button-up failure reaches caller");

    wait_for_generation(&client, &generations, 2);
    assert_eq!(
        *lock_unpoisoned(&events),
        vec![
            (1, InputEvent::Pointer(point, MouseButton::Left.rfb_mask())),
            (1, InputEvent::Pointer(point, 0)),
        ]
    );
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

#[test]
fn click_press_failure_quarantines_generation() {
    let (worker, client, events, generations) = spawn_planned_failure_worker(&[2]);
    let point = Coordinate { x: 1, y: 1 };

    client
        .submit(WorkerCommand::Click {
            coordinate: point,
            button: MouseButton::Left,
        })
        .expect("click accepted")
        .wait(Duration::from_secs(1))
        .expect_err("ambiguous click press failure reaches caller");

    wait_for_generation(&client, &generations, 2);
    assert_eq!(
        *lock_unpoisoned(&events),
        vec![
            (1, InputEvent::Pointer(point, 0)),
            (1, InputEvent::Pointer(point, 0)),
        ]
    );
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

#[test]
fn click_release_double_failure_still_quarantines_generation() {
    let (worker, client, events, generations) = spawn_planned_failure_worker(&[3, 4]);
    let point = Coordinate { x: 1, y: 1 };

    client
        .submit(WorkerCommand::Click {
            coordinate: point,
            button: MouseButton::Left,
        })
        .expect("click accepted")
        .wait(Duration::from_secs(1))
        .expect_err("double release failure reaches caller");

    wait_for_generation(&client, &generations, 2);
    assert_eq!(
        *lock_unpoisoned(&events),
        vec![
            (1, InputEvent::Pointer(point, 0)),
            (1, InputEvent::Pointer(point, MouseButton::Left.rfb_mask())),
            (1, InputEvent::Pointer(point, 0)),
        ]
    );
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

#[test]
fn double_click_second_sequence_failure_quarantines_generation() {
    let (worker, client, events, generations) = spawn_planned_failure_worker(&[5]);
    let point = Coordinate { x: 1, y: 1 };

    client
        .submit(WorkerCommand::DoubleClick {
            coordinate: point,
            button: MouseButton::Left,
            interval_ms: crate::input::MIN_DOUBLE_CLICK_INTERVAL_MS,
        })
        .expect("double-click accepted")
        .wait(Duration::from_secs(1))
        .expect_err("second click failure reaches caller");

    wait_for_generation(&client, &generations, 2);
    assert_eq!(
        *lock_unpoisoned(&events),
        vec![
            (1, InputEvent::Pointer(point, 0)),
            (1, InputEvent::Pointer(point, MouseButton::Left.rfb_mask())),
            (1, InputEvent::Pointer(point, 0)),
            (1, InputEvent::Pointer(point, 0)),
            (1, InputEvent::Pointer(point, 0)),
        ]
    );
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

#[test]
fn explicit_key_release_failure_quarantines_generation() {
    let (worker, client, events, generations) = spawn_planned_failure_worker(&[2]);

    client
        .submit(WorkerCommand::SetKey {
            key: KeyboardKey::CtrlLeft,
            pressed: true,
        })
        .expect("key-down accepted")
        .wait(Duration::from_secs(1))
        .expect("key-down succeeds");
    client
        .submit(WorkerCommand::SetKey {
            key: KeyboardKey::CtrlLeft,
            pressed: false,
        })
        .expect("key-up accepted")
        .wait(Duration::from_secs(1))
        .expect_err("ambiguous key-up failure reaches caller");

    wait_for_generation(&client, &generations, 2);
    assert_eq!(
        *lock_unpoisoned(&events),
        vec![
            (1, InputEvent::Key(KeyboardKey::CtrlLeft, true)),
            (1, InputEvent::Key(KeyboardKey::CtrlLeft, false)),
        ]
    );
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

#[test]
fn partial_chord_cleanup_failure_remains_quarantined_until_session_drop() {
    let (worker, client, events, generations) = spawn_planned_failure_worker(&[2, 3]);

    client
        .submit(WorkerCommand::Chord {
            keys: vec![KeyboardKey::CtrlLeft, KeyboardKey::AltLeft],
        })
        .expect("chord accepted")
        .wait(Duration::from_secs(1))
        .expect_err("partial chord cleanup failure reaches caller");

    wait_for_generation(&client, &generations, 2);
    assert_eq!(
        *lock_unpoisoned(&events),
        vec![
            (1, InputEvent::Key(KeyboardKey::CtrlLeft, true)),
            (1, InputEvent::Key(KeyboardKey::CtrlLeft, false)),
            (1, InputEvent::Key(KeyboardKey::AltLeft, false)),
        ]
    );
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

struct QueuedFailureSession {
    generation: usize,
    events: Arc<Mutex<Vec<(usize, InputEvent)>>>,
    input_calls: usize,
    entered: Option<SyncSender<()>>,
    release: Option<Receiver<()>>,
}

impl WorkerSession for QueuedFailureSession {
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
            revision: self.generation as u64,
            complete: true,
        })
    }

    fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {
        Ok(NativeFramebuffer {
            width: 2,
            height: 2,
            revision: self.generation as u64,
            bytes: vec![1, 2, 3, 0, 4, 5, 6, 0, 7, 8, 9, 0, 10, 11, 12, 0],
        })
    }

    fn clipboard(&self) -> Result<NativeClipboard, NativeError> {
        Err(NativeError::ClipboardUnavailable)
    }

    fn send_pointer(&mut self, coordinate: Coordinate, button_mask: u8) -> Result<(), NativeError> {
        self.input_calls += 1;
        if self.generation == 1 && self.input_calls == 1 {
            if let Some(entered) = &self.entered {
                entered.send(()).expect("test waits for blocked failure");
            }
            if let Some(release) = &self.release {
                release.recv().expect("test releases blocked failure");
            }
            return Err(NativeError::NativeFailure {
                message: "test-only queued input failure".to_owned(),
            });
        }
        lock_unpoisoned(&self.events).push((
            self.generation,
            InputEvent::Pointer(coordinate, button_mask),
        ));
        Ok(())
    }

    fn send_key(&mut self, key: KeyboardKey, pressed: bool) -> Result<(), NativeError> {
        lock_unpoisoned(&self.events).push((
            self.generation,
            InputEvent::Key(key, pressed),
        ));
        Ok(())
    }

    fn send_clipboard(&mut self, text: &str) -> Result<(), NativeError> {
        lock_unpoisoned(&self.events).push((
            self.generation,
            InputEvent::Clipboard(text.to_owned()),
        ));
        Ok(())
    }
}

#[test]
fn queued_next_mutation_never_executes_on_tainted_generation() {
    let events = Arc::new(Mutex::new(Vec::<(usize, InputEvent)>::new()));
    let generations = Arc::new(AtomicUsize::new(0));
    let (entered_tx, entered_rx) = sync_channel(1);
    let (release_tx, release_rx) = sync_channel(1);
    let factory_events = Arc::clone(&events);
    let factory_generations = Arc::clone(&generations);
    let mut first_release = Some(release_rx);
    let worker = DesktopWorker::spawn_with_factory(settings(), move || {
        let generation = factory_generations.fetch_add(1, Ordering::AcqRel) + 1;
        Ok(QueuedFailureSession {
            generation,
            events: Arc::clone(&factory_events),
            input_calls: 0,
            entered: (generation == 1).then(|| entered_tx.clone()),
            release: if generation == 1 {
                first_release.take()
            } else {
                None
            },
        })
    })
    .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);
    let failed_point = Coordinate { x: 0, y: 0 };
    let queued_point = Coordinate { x: 1, y: 1 };

    let failed = client
        .submit(WorkerCommand::MovePointer {
            coordinate: failed_point,
        })
        .expect("first mutation accepted");
    entered_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("first mutation reaches blocked native send");
    let queued = client
        .submit(WorkerCommand::MovePointer {
            coordinate: queued_point,
        })
        .expect("second mutation is already queued");
    release_tx.send(()).expect("release first failure");

    failed
        .wait(Duration::from_secs(1))
        .expect_err("first mutation fails ambiguously");
    let queued_result = queued.wait(Duration::from_secs(1));
    if queued_result.is_ok() {
        wait_for_generation(&client, &generations, 2);
    } else {
        assert!(matches!(queued_result, Err(DesktopError::WorkerUnavailable)));
    }

    assert!(
        !lock_unpoisoned(&events).iter().any(|(generation, event)| {
            *generation == 1
                && matches!(event, InputEvent::Pointer(coordinate, _) if *coordinate == queued_point)
        }),
        "queued mutation must never execute on the tainted generation"
    );
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

struct FramebufferExhaustionSession {
    generation: usize,
    trigger: Arc<AtomicBool>,
    first_message: bool,
}

impl WorkerSession for FramebufferExhaustionSession {
    fn poll(&mut self, timeout: Duration) -> Result<PollOutcome, NativeError> {
        thread::sleep(timeout);
        if !self.first_message {
            self.first_message = true;
            return Ok(PollOutcome::MessageProcessed);
        }
        if self.generation == 1 && self.trigger.load(Ordering::Acquire) {
            return Err(NativeError::FramebufferRevisionExhausted);
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
            revision: self.generation as u64,
            complete: true,
        })
    }

    fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {
        Ok(NativeFramebuffer {
            width: 2,
            height: 2,
            revision: self.generation as u64,
            bytes: vec![1, 2, 3, 0, 4, 5, 6, 0, 7, 8, 9, 0, 10, 11, 12, 0],
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

#[test]
fn framebuffer_revision_exhaustion_invalidates_before_replacement_connects() {
    let trigger = Arc::new(AtomicBool::new(false));
    let generations = Arc::new(AtomicUsize::new(0));
    let (replacement_entered_tx, replacement_entered_rx) = sync_channel(1);
    let (replacement_release_tx, replacement_release_rx) = sync_channel(1);
    let factory_trigger = Arc::clone(&trigger);
    let factory_generations = Arc::clone(&generations);
    let mut replacement_release = Some(replacement_release_rx);
    let worker = DesktopWorker::spawn_with_factory(settings(), move || {
        let generation = factory_generations.fetch_add(1, Ordering::AcqRel) + 1;
        if generation == 2 {
            replacement_entered_tx
                .send(())
                .expect("test observes replacement factory entry");
            replacement_release
                .take()
                .expect("replacement gate exists")
                .recv()
                .expect("test releases replacement factory");
        }
        Ok(FramebufferExhaustionSession {
            generation,
            trigger: Arc::clone(&factory_trigger),
            first_message: false,
        })
    })
    .expect("worker spawns");
    let client = worker.client();
    wait_for_state(&client, ConnectionState::Connected);
    assert_eq!(
        client.framebuffer_snapshot().expect("initial frame").revision(),
        1
    );

    trigger.store(true, Ordering::Release);
    replacement_entered_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("replacement connect starts after exhaustion");
    assert_eq!(
        client.framebuffer_snapshot().err(),
        Some(FramebufferError::Stale),
        "old framebuffer must lose current authority before replacement returns"
    );

    replacement_release_tx
        .send(())
        .expect("allow replacement connection");
    wait_for_generation(&client, &generations, 2);
    assert_eq!(
        client
            .framebuffer_snapshot()
            .expect("replacement frame")
            .revision(),
        2
    );
    worker
        .shutdown(Duration::from_secs(1))
        .expect("worker joins");
}

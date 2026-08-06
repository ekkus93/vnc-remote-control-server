use super::*;
use crate::framebuffer::FramebufferStore;
use remote_desktop_core::{DesktopError, WorkerCommand};
use std::sync::Barrier;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::mpsc::{channel, sync_channel};
use std::time::SystemTime;

use super::super::snapshot::WorkerSnapshot;

#[test]
fn in_flight_depth_can_exceed_capacity_and_still_converges_to_zero() {
    let (command_tx, command_rx) = sync_channel(1);
    let snapshot = Arc::new(Mutex::new(WorkerSnapshot {
        state: ConnectionState::Connected,
        started_at: SystemTime::now(),
        connected_at: Some(SystemTime::now()),
        last_message_at: Some(SystemTime::now()),
        reconnect_attempts: 0,
        last_failure: None,
        framebuffer_revision: None,
        rejected_commands: 0,
        dropped_events: 0,
        fatal_exit: false,
    }));
    let submissions = Arc::new(AtomicUsize::new(0));
    let client = WorkerClient {
        commands: command_tx,
        snapshot,
        framebuffer: FramebufferStore::default(),
        clipboard: Arc::new(Mutex::new(None)),
        next_command_id: Arc::new(AtomicU64::new(1)),
        command_submissions_in_flight: Arc::clone(&submissions),
        command_queue_capacity: 1,
        pending_overload: Arc::new(AtomicU64::new(0)),
        shutdown_requested: Arc::new(AtomicBool::new(false)),
    };

    let parked = Arc::new(Barrier::new(3));
    let release = Arc::new(Barrier::new(3));
    let (result_tx, result_rx) = channel();
    let mut submitters = Vec::new();
    for _ in 0..2 {
        let client = client.clone();
        let parked = Arc::clone(&parked);
        let release = Arc::clone(&release);
        let result_tx = result_tx.clone();
        submitters.push(thread::spawn(move || {
            let result = client.submit_with_before_send_hook(
                WorkerCommand::RequestFullRefresh,
                move || {
                    parked.wait();
                    release.wait();
                },
            );
            result_tx.send(result).expect("submit result is observed");
        }));
    }
    drop(result_tx);

    parked.wait();
    assert_eq!(client.command_queue_capacity(), 1);
    assert_eq!(client.command_submissions_in_flight(), 2);
    assert!(client.command_submissions_in_flight() > client.command_queue_capacity());

    release.wait();
    let results = [
        result_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("first submitter returns"),
        result_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("second submitter returns"),
    ];
    for submitter in submitters {
        submitter.join().expect("submitter does not panic");
    }

    assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
    assert_eq!(
        results
            .iter()
            .filter(|result| matches!(result, Err(DesktopError::CommandQueueFull)))
            .count(),
        1
    );
    assert_eq!(submissions.load(Ordering::Acquire), 1);

    drop(command_rx);
    assert_eq!(client.command_submissions_in_flight(), 0);
}

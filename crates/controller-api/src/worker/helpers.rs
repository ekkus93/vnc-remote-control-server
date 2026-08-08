use super::{WorkerFailureKind, WorkerSettings};
use libvnc_adapter::{NativeDisplayInfo, NativeError, NativeFramebuffer};
use remote_desktop_core::DesktopError;
use std::sync::{Mutex, MutexGuard};
use std::time::Duration;

pub(super) fn validate_native_frame(
    display: NativeDisplayInfo,
    native: &NativeFramebuffer,
) -> Result<(), DesktopError> {
    if !display.complete
        || native.width != display.width
        || native.height != display.height
        || native.revision != display.revision
    {
        return Err(DesktopError::Protocol);
    }
    Ok(())
}

pub(super) fn reconnect_delay(settings: &WorkerSettings, attempt: u32) -> Duration {
    let exponent = attempt.saturating_sub(1).min(31);
    let multiplier = 1_u128 << exponent;
    let minimum_ms = settings.reconnect_min_delay.as_millis();
    let maximum_ms = settings.reconnect_max_delay.as_millis();
    let base_ms = minimum_ms.saturating_mul(multiplier).min(maximum_ms);
    let jitter_bound =
        base_ms.saturating_mul(u128::from(settings.reconnect_jitter_per_mille)) / 1_000;
    let jitter = if jitter_bound == 0 {
        0
    } else {
        u128::from(attempt.wrapping_mul(1_103_515_245).wrapping_add(12_345)) % (jitter_bound + 1)
    };
    let delay_ms = base_ms.saturating_add(jitter).min(maximum_ms);
    Duration::from_millis(u64::try_from(delay_ms).unwrap_or(u64::MAX))
}

pub(super) fn classify_native_error(error: &NativeError) -> WorkerFailureKind {
    match error {
        NativeError::InvalidArgument | NativeError::EmbeddedNul => WorkerFailureKind::Configuration,
        NativeError::Disconnected => WorkerFailureKind::Transport,
        NativeError::ProtocolInitializationFailed
        | NativeError::FramebufferUnavailable
        | NativeError::BufferTooSmall
        | NativeError::ClipboardUnavailable
        | NativeError::ClipboardNotUtf8 => WorkerFailureKind::Protocol,
        NativeError::AllocationFailed | NativeError::NativeFailure { .. } => WorkerFailureKind::Native,
    }
}

/// Locks authoritative worker state. Poison means another thread panicked while
/// mutating the protected value, so normal service cannot safely resume from it.
/// Emit a fixed payload-free invariant diagnostic and unwind this service path;
/// the poisoned mutex remains poisoned, making later normal accesses fail closed.
pub(super) fn lock_unpoisoned<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    match mutex.lock() {
        Ok(guard) => guard,
        Err(_) => {
            tracing::error!("worker_authoritative_mutex_poisoned");
            panic!("worker authoritative mutex poisoned");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::panic::{AssertUnwindSafe, catch_unwind};
    use std::sync::Arc;
    use std::thread;

    #[test]
    fn protocol_initialization_failure_is_protocol_regardless_of_message_text() {
        assert_eq!(
            classify_native_error(&NativeError::ProtocolInitializationFailed),
            WorkerFailureKind::Protocol
        );
        assert_eq!(
            classify_native_error(&NativeError::NativeFailure {
                message: "VNC protocol initialization failed".to_owned(),
            }),
            WorkerFailureKind::Native
        );
    }

    #[test]
    fn poisoned_worker_mutex_does_not_resume_normal_service() {
        let value = Arc::new(Mutex::new(0_u8));
        let poisoned = Arc::clone(&value);
        let join = thread::spawn(move || {
            let _guard = poisoned.lock().expect("initial lock is healthy");
            panic!("test-only poison");
        });
        assert!(join.join().is_err());

        let result = catch_unwind(AssertUnwindSafe(|| {
            let _guard = lock_unpoisoned(&value);
        }));
        assert!(result.is_err());
    }
}

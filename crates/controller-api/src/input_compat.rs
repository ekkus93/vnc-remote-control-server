//! Temporary crate-local bridge for the V1 scroll-specific uncertainty probe.
//!
//! V2 makes `InputController::input_state_uncertain()` authoritative for all
//! input operations and centralizes quarantine in the worker dispatch loop. The
//! older scroll arm still calls its former pointer-specific probe; this bridge
//! keeps that stale call compile-compatible but deliberately inert so scroll is
//! quarantined only by the same aggregate post-command policy as every other
//! input mutation.

use crate::input::InputController;

impl InputController {
    pub(crate) const fn pointer_state_uncertain(&self) -> bool {
        false
    }
}

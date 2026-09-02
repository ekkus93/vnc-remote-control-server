//! Temporary crate-local bridge for the V1 scroll-specific uncertainty probe.
//!
//! V2 makes `InputController::input_state_uncertain()` authoritative for all
//! input operations and centralizes quarantine in the worker dispatch loop. The
//! older scroll arm still probes its former pointer-specific method; this bridge
//! deliberately aliases that probe to the aggregate state until the large
//! worker loop module can be simplified without a broad unrelated rewrite.

use crate::input::InputController;

impl InputController {
    pub(crate) const fn pointer_state_uncertain(&self) -> bool {
        self.input_state_uncertain()
    }
}

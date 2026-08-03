//! LibVNCClient adapter crate.
//!
//! The production native wrapper is introduced by milestone M3. Until then,
//! this crate provides only a typed marker so workspace boundaries compile.

/// Returns the adapter implementation phase.
pub const fn implementation_phase() -> &'static str {
    "ffi-spike-pending"
}

#[cfg(test)]
mod tests {
    use super::implementation_phase;

    #[test]
    fn phase_is_explicit() {
        assert_eq!(implementation_phase(), "ffi-spike-pending");
    }
}

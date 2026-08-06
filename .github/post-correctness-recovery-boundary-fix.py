from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{relative}: expected one boundary-fix anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "crates/libvnc-adapter/src/lib.rs",
    '''fn secure_scrub(bytes: &mut [u8]) {
    for byte in bytes {
        // SAFETY: every pointer originates from the live mutable slice and is
        // written exactly once while exclusively borrowed.
        unsafe { std::ptr::write_volatile(byte, 0) };
    }
    compiler_fence(Ordering::SeqCst);
}
''',
    '''fn secure_scrub(bytes: &mut [u8]) {
    for byte in bytes {
        // SAFETY: every pointer originates from the live mutable slice and is
        // written exactly once while exclusively borrowed.
        unsafe { std::ptr::write_volatile(byte, 0) };
    }
    compiler_fence(Ordering::SeqCst);
}

/// Scrubs a live project-owned secret byte buffer with volatile writes.
///
/// This safe entry point keeps volatile pointer operations confined to the
/// native-boundary crate while allowing configuration parsing to scrub rejected
/// file contents without introducing unsafe code into `controller-api`.
pub fn scrub_secret_bytes(bytes: &mut [u8]) {
    secure_scrub(bytes);
}
''',
)
replace_once(
    "crates/controller-api/src/config.rs",
    '''use libvnc_adapter::{NativeClientConfig, SecretString};
''',
    '''use libvnc_adapter::{NativeClientConfig, SecretString, scrub_secret_bytes};
''',
)
replace_once(
    "crates/controller-api/src/config.rs",
    '''use std::sync::atomic::{Ordering, compiler_fence};
''',
    '''''',
)
replace_once(
    "crates/controller-api/src/config.rs",
    '''fn secure_scrub_bytes(bytes: &mut [u8]) {
    for byte in bytes {
        // SAFETY: every pointer comes from the live, exclusively borrowed slice.
        unsafe { std::ptr::write_volatile(byte, 0) };
    }
    compiler_fence(Ordering::SeqCst);
}
''',
    '''fn secure_scrub_bytes(bytes: &mut [u8]) {
    scrub_secret_bytes(bytes);
}
''',
)

(ROOT / ".github/post-correctness-recovery-boundary-fix.py").unlink()

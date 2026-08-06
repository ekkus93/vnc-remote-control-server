#![allow(unsafe_code)]

use controller_api::framebuffer::FramebufferStore;
use std::alloc::{GlobalAlloc, Layout, System};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Instant;

const WIDTH: u32 = 1_920;
const HEIGHT: u32 = 1_080;
const BYTES: usize = WIDTH as usize * HEIGHT as usize * 4;

struct CountingAllocator;

static ALLOCATIONS: AtomicU64 = AtomicU64::new(0);
static ALLOCATED_BYTES: AtomicU64 = AtomicU64::new(0);

unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        ALLOCATIONS.fetch_add(1, Ordering::Relaxed);
        ALLOCATED_BYTES.fetch_add(layout.size() as u64, Ordering::Relaxed);
        // SAFETY: delegation preserves the allocator contract.
        unsafe { System.alloc(layout) }
    }

    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        // SAFETY: delegation preserves the allocator contract.
        unsafe { System.dealloc(pointer, layout) }
    }

    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        ALLOCATIONS.fetch_add(1, Ordering::Relaxed);
        ALLOCATED_BYTES.fetch_add(layout.size() as u64, Ordering::Relaxed);
        // SAFETY: delegation preserves the allocator contract.
        unsafe { System.alloc_zeroed(layout) }
    }

    unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, new_size: usize) -> *mut u8 {
        ALLOCATIONS.fetch_add(1, Ordering::Relaxed);
        ALLOCATED_BYTES.fetch_add(new_size as u64, Ordering::Relaxed);
        // SAFETY: delegation preserves the allocator contract.
        unsafe { System.realloc(pointer, layout, new_size) }
    }
}

#[global_allocator]
static GLOBAL: CountingAllocator = CountingAllocator;

fn reset_counts() {
    ALLOCATIONS.store(0, Ordering::SeqCst);
    ALLOCATED_BYTES.store(0, Ordering::SeqCst);
}

fn counts() -> (u64, u64) {
    (
        ALLOCATIONS.load(Ordering::SeqCst),
        ALLOCATED_BYTES.load(Ordering::SeqCst),
    )
}

#[test]
#[ignore = "explicit reproducible performance evidence utility"]
fn measure_representative_frame_pipeline() {
    let source = vec![0x7f_u8; BYTES];
    let store = FramebufferStore::new(BYTES).expect("representative store");

    reset_counts();
    let started = Instant::now();
    let native_copy = source.clone();
    let revision = store
        .replace_native_rgbx(WIDTH, HEIGHT, &native_copy)
        .expect("first frame");
    let changed_elapsed = started.elapsed();
    let (changed_allocations, changed_bytes) = counts();
    assert_eq!(revision, 1);

    reset_counts();
    let started = Instant::now();
    let duplicate_native_copy = source.clone();
    let duplicate_revision = store
        .replace_native_rgbx(WIDTH, HEIGHT, &duplicate_native_copy)
        .expect("duplicate frame");
    let duplicate_elapsed = started.elapsed();
    let (duplicate_allocations, duplicate_bytes) = counts();
    assert_eq!(duplicate_revision, revision);

    println!(
        "framebuffer_measurement width={WIDTH} height={HEIGHT} frame_bytes={BYTES} changed_allocations={changed_allocations} changed_allocated_bytes={changed_bytes} changed_elapsed_ns={} duplicate_allocations={duplicate_allocations} duplicate_allocated_bytes={duplicate_bytes} duplicate_elapsed_ns={}",
        changed_elapsed.as_nanos(),
        duplicate_elapsed.as_nanos()
    );
}

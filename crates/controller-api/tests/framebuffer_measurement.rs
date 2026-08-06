#![allow(unsafe_code)]

use controller_api::framebuffer::FramebufferStore;
use std::alloc::{GlobalAlloc, Layout, System};
use std::hint::black_box;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, RwLock};
use std::time::Instant;

const WIDTH: u32 = 1_920;
const HEIGHT: u32 = 1_080;
const BYTES: usize = WIDTH as usize * HEIGHT as usize * 4;
const REPETITIONS: usize = 12;

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

#[derive(Clone, Copy)]
struct Sample {
    elapsed_ns: u128,
    allocations: u64,
    allocated_bytes: u64,
}

#[derive(Clone, Copy)]
struct Summary {
    elapsed_ns_min: u128,
    elapsed_ns_median: u128,
    elapsed_ns_max: u128,
    allocations_min: u64,
    allocations_median: u64,
    allocations_max: u64,
    allocated_bytes_min: u64,
    allocated_bytes_median: u64,
    allocated_bytes_max: u64,
}

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

fn measure_once<F, R>(action: F) -> Sample
where
    F: FnOnce() -> R,
{
    reset_counts();
    let started = Instant::now();
    let result = black_box(action());
    let elapsed_ns = started.elapsed().as_nanos();
    let (allocations, allocated_bytes) = counts();
    black_box(&result);
    drop(result);
    Sample {
        elapsed_ns,
        allocations,
        allocated_bytes,
    }
}

fn summarize(samples: &[Sample]) -> Summary {
    assert_eq!(samples.len(), REPETITIONS);
    let mut elapsed: Vec<_> = samples.iter().map(|sample| sample.elapsed_ns).collect();
    let mut allocations: Vec<_> = samples.iter().map(|sample| sample.allocations).collect();
    let mut allocated_bytes: Vec<_> = samples
        .iter()
        .map(|sample| sample.allocated_bytes)
        .collect();
    elapsed.sort_unstable();
    allocations.sort_unstable();
    allocated_bytes.sort_unstable();
    let median = REPETITIONS / 2;
    Summary {
        elapsed_ns_min: elapsed[0],
        elapsed_ns_median: elapsed[median],
        elapsed_ns_max: elapsed[REPETITIONS - 1],
        allocations_min: allocations[0],
        allocations_median: allocations[median],
        allocations_max: allocations[REPETITIONS - 1],
        allocated_bytes_min: allocated_bytes[0],
        allocated_bytes_median: allocated_bytes[median],
        allocated_bytes_max: allocated_bytes[REPETITIONS - 1],
    }
}

fn print_summary(stage: &str, summary: Summary) {
    println!(
        "framebuffer_measurement_v1 stage={stage} width={WIDTH} height={HEIGHT} frame_bytes={BYTES} repetitions={REPETITIONS} elapsed_ns_min={} elapsed_ns_median={} elapsed_ns_max={} allocations_min={} allocations_median={} allocations_max={} allocated_bytes_min={} allocated_bytes_median={} allocated_bytes_max={}",
        summary.elapsed_ns_min,
        summary.elapsed_ns_median,
        summary.elapsed_ns_max,
        summary.allocations_min,
        summary.allocations_median,
        summary.allocations_max,
        summary.allocated_bytes_min,
        summary.allocated_bytes_median,
        summary.allocated_bytes_max,
    );
}

fn convert_rgbx_to_rgba(rgbx: &[u8]) -> Vec<u8> {
    let mut rgba = Vec::with_capacity(rgbx.len());
    for pixel in rgbx.chunks_exact(4) {
        rgba.extend_from_slice(&[pixel[0], pixel[1], pixel[2], u8::MAX]);
    }
    rgba
}

#[test]
fn native_rgbx_conversion_preserves_channel_order() {
    let store = FramebufferStore::new(8).expect("two-pixel store");
    let revision = store
        .replace_native_rgbx(2, 1, &[0x11, 0x22, 0x33, 0, 0xaa, 0xbb, 0xcc, 0x7f])
        .expect("native frame converts");
    assert_eq!(revision, 1);
    let snapshot = store.current_snapshot().expect("canonical frame");
    assert_eq!(
        snapshot.rgba(),
        &[0x11, 0x22, 0x33, 0xff, 0xaa, 0xbb, 0xcc, 0xff]
    );
}

#[test]
#[ignore = "explicit reproducible performance evidence utility"]
fn measure_representative_frame_pipeline() {
    let source = vec![0x7f_u8; BYTES];
    let equal_source = source.clone();
    let lock = RwLock::new(Arc::<[u8]>::from(vec![0_u8; BYTES]));
    let replacement = Arc::<[u8]>::from(source.clone());

    let native_copy: Vec<_> = (0..REPETITIONS)
        .map(|_| measure_once(|| source.clone()))
        .collect();
    print_summary("native_copy", summarize(&native_copy));

    let rgbx_conversion: Vec<_> = (0..REPETITIONS)
        .map(|_| measure_once(|| convert_rgbx_to_rgba(&source)))
        .collect();
    print_summary("rgbx_to_rgba", summarize(&rgbx_conversion));

    let equality: Vec<_> = (0..REPETITIONS)
        .map(|_| measure_once(|| source.as_slice() == equal_source.as_slice()))
        .collect();
    print_summary("byte_equality", summarize(&equality));

    let write_lock: Vec<_> = (0..REPETITIONS)
        .map(|_| {
            measure_once(|| {
                let mut guard = lock.write().expect("measurement lock is not poisoned");
                *guard = Arc::clone(&replacement);
            })
        })
        .collect();
    print_summary("representative_write_lock", summarize(&write_lock));

    let vec_to_arc: Vec<_> = (0..REPETITIONS)
        .map(|_| {
            let input = source.clone();
            measure_once(|| Arc::<[u8]>::from(input))
        })
        .collect();
    print_summary("vec_to_arc_slice", summarize(&vec_to_arc));

    let changed_store: Vec<_> = (0..REPETITIONS)
        .map(|_| {
            let store = FramebufferStore::new(BYTES).expect("representative store");
            measure_once(|| {
                store
                    .replace_native_rgbx(WIDTH, HEIGHT, &source)
                    .expect("first production frame")
            })
        })
        .collect();
    print_summary("production_changed_frame", summarize(&changed_store));

    let duplicate_store = FramebufferStore::new(BYTES).expect("representative store");
    let revision = duplicate_store
        .replace_native_rgbx(WIDTH, HEIGHT, &source)
        .expect("initial production frame");
    let duplicate: Vec<_> = (0..REPETITIONS)
        .map(|_| {
            measure_once(|| {
                duplicate_store
                    .replace_native_rgbx(WIDTH, HEIGHT, &source)
                    .expect("duplicate production frame")
            })
        })
        .collect();
    assert!(duplicate.iter().all(|_| {
        duplicate_store
            .current_snapshot()
            .expect("duplicate frame remains current")
            .revision()
            == revision
    }));
    print_summary("production_duplicate_frame", summarize(&duplicate));
}

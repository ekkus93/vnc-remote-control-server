# Framebuffer Measurement Utility

This utility records reproducible allocation and timing evidence for representative 1920×1080 RGBA framebuffer operations. It is deliberately excluded from normal CI because the timing values describe a particular runner and allocator rather than a release acceptance threshold.

## Exact command

Run from the repository root with the pinned `rust-toolchain.toml` toolchain:

```bash
cargo test --locked \
  --package controller-api \
  --test framebuffer_measurement \
  measure_representative_frame_pipeline \
  -- \
  --ignored \
  --exact \
  --nocapture \
  --test-threads=1
```

Record the environment alongside the output:

```bash
rustc --version --verbose
cargo --version --verbose
ldd --version | head -n 1
uname -a
```

The integration-test executable is a dedicated process with a counting global allocator that delegates to `std::alloc::System`. No other test is run in that process when the exact command above is used.

## Fixed workload

- Resolution: 1920×1080.
- Pixel width: 4 bytes.
- Frame size: 8,294,400 bytes.
- Repetitions: 12 per stage.
- Source layout: native `[R,G,B,X]`.
- Canonical layout: `[R,G,B,255]`.

## Measured stages

- `native_copy`: one full native framebuffer `Vec` clone.
- `rgbx_to_rgba`: isolated conversion equivalent to the production conversion loop.
- `byte_equality`: full byte equality comparison with equal inputs.
- `representative_write_lock`: uncontended `RwLock` write acquisition and `Arc` replacement. This is a representative lock micro-measurement, not a claim that it isolates every instruction inside `FramebufferStore`.
- `vec_to_arc_slice`: `Vec<u8> -> Arc<[u8]>` conversion on the pinned toolchain.
- `production_changed_frame`: the public `FramebufferStore::replace_native_rgbx` path for a first changed frame.
- `production_duplicate_frame`: the public duplicate-frame path, including conversion, lock acquisition, and equality detection while preserving the revision.

## Output schema

Every line begins with `framebuffer_measurement_v1` and contains:

```text
stage
width
height
frame_bytes
repetitions
elapsed_ns_min
elapsed_ns_median
elapsed_ns_max
allocations_min
allocations_median
allocations_max
allocated_bytes_min
allocated_bytes_median
allocated_bytes_max
```

Allocation values count allocation and reallocation calls and the requested bytes. They do not represent resident-set size, allocator metadata, retained capacity, deallocations, or third-party native allocations.

## Interpretation boundary

The measurements distinguish measured facts from source-reading hypotheses. They are evidence for deciding whether a separate performance project is justified; they are not permission to change framebuffer equality, revision, timestamp, ETag, stale-frame, or R13 `304` semantics in the correctness pass.

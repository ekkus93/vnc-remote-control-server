# VNC Remote Control Server Framebuffer Measurement Evidence

Date: 2026-08-06

Utility:

- `crates/controller-api/tests/framebuffer_measurement.rs`
- `crates/controller-api/tests/FRAMEBUFFER_MEASUREMENT.md`

## Exact command

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

## Environment

```text
rustc 1.97.1 (8bab26f4f 2026-07-14)
binary: rustc
commit-hash: 8bab26f4f68e0e26f0bb7960be334d5b520ea452
commit-date: 2026-07-14
host: x86_64-unknown-linux-gnu
release: 1.97.1
LLVM version: 22.1.6
cargo 1.97.1 (c980f4866 2026-06-30)
release: 1.97.1
commit-hash: c980f4866141969fab6254a680546a277789d6f0
commit-date: 2026-06-30
host: x86_64-unknown-linux-gnu
libgit2: 1.9.2 (sys:0.20.4 vendored)
libcurl: 8.20.0-DEV (sys:0.4.88+curl-8.20.0 vendored ssl:OpenSSL/3.6.2)
ssl: OpenSSL 3.6.2 7 Apr 2026
os: Ubuntu 24.4.0 (noble) [64-bit]
ldd (Ubuntu GLIBC 2.39-0ubuntu8.8) 2.39
Linux runnervmd93pd 6.17.0-1021-azure #21~24.04.1-Ubuntu SMP Wed Jul  1 21:45:31 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
```

Allocator: `std::alloc::System` wrapped by the utility's counting global allocator.

Resolution: 1920×1080.

Frame bytes: 8,294,400.

Repetitions: 12 per stage.

## Raw measurements

```text
test measure_representative_frame_pipeline ... framebuffer_measurement_v1 stage=native_copy width=1920 height=1080 frame_bytes=8294400 repetitions=12 elapsed_ns_min=240885 elapsed_ns_median=255768 elapsed_ns_max=1395489 allocations_min=1 allocations_median=1 allocations_max=1 allocated_bytes_min=8294400 allocated_bytes_median=8294400 allocated_bytes_max=8294400
framebuffer_measurement_v1 stage=rgbx_to_rgba width=1920 height=1080 frame_bytes=8294400 repetitions=12 elapsed_ns_min=154731429 elapsed_ns_median=154817146 elapsed_ns_max=154999645 allocations_min=1 allocations_median=1 allocations_max=1 allocated_bytes_min=8294400 allocated_bytes_median=8294400 allocated_bytes_max=8294400
framebuffer_measurement_v1 stage=byte_equality width=1920 height=1080 frame_bytes=8294400 repetitions=12 elapsed_ns_min=225332 elapsed_ns_median=244881 elapsed_ns_max=510633 allocations_min=0 allocations_median=0 allocations_max=0 allocated_bytes_min=0 allocated_bytes_median=0 allocated_bytes_max=0
framebuffer_measurement_v1 stage=representative_write_lock width=1920 height=1080 frame_bytes=8294400 repetitions=12 elapsed_ns_min=110 elapsed_ns_median=120 elapsed_ns_max=246003 allocations_min=0 allocations_median=0 allocations_max=0 allocated_bytes_min=0 allocated_bytes_median=0 allocated_bytes_max=0
framebuffer_measurement_v1 stage=vec_to_arc_slice width=1920 height=1080 frame_bytes=8294400 repetitions=12 elapsed_ns_min=265272 elapsed_ns_median=275897 elapsed_ns_max=1403712 allocations_min=1 allocations_median=1 allocations_max=1 allocated_bytes_min=8294416 allocated_bytes_median=8294416 allocated_bytes_max=8294416
framebuffer_measurement_v1 stage=production_changed_frame width=1920 height=1080 frame_bytes=8294400 repetitions=12 elapsed_ns_min=155050119 elapsed_ns_median=155230736 elapsed_ns_max=163480600 allocations_min=2 allocations_median=2 allocations_max=2 allocated_bytes_min=16588816 allocated_bytes_median=16588816 allocated_bytes_max=16588816
framebuffer_measurement_v1 stage=production_duplicate_frame width=1920 height=1080 frame_bytes=8294400 repetitions=12 elapsed_ns_min=154906729 elapsed_ns_median=155056302 elapsed_ns_max=155342581 allocations_min=1 allocations_median=1 allocations_max=1 allocated_bytes_min=8294400 allocated_bytes_median=8294400 allocated_bytes_max=8294400
```

## Interpretation

These are runner-specific measurements, not release thresholds. They distinguish allocation calls/requested bytes from resident memory and isolate representative stages where possible. `production_changed_frame` and `production_duplicate_frame` are the public `FramebufferStore::replace_native_rgbx` paths; the representative write-lock stage is an uncontended micro-measurement rather than a claim to isolate every instruction executed under the production lock.

No framebuffer hot-path optimization is part of the correctness pass. Equality, revision, timestamp, availability, ETag, stale-frame, and unchanged R13 `304` semantics remain authoritative. A separate performance specification should be created only if these measurements and a production workload justify one.

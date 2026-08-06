# Framebuffer Measurement Launcher

Run from the repository root:

```bash
python3 tests/measurement/framebuffer/run.py
```

The launcher executes the committed ignored integration measurement in
`crates/controller-api/tests/framebuffer_measurement.rs`. The measurement
contract, allocator semantics, output schema and direct Cargo command are
documented in `crates/controller-api/tests/FRAMEBUFFER_MEASUREMENT.md`.
Recorded 1920×1080 results are in
`docs/VNC_REMOTE_CONTROL_SERVER_FRAMEBUFFER_MEASUREMENT_EVIDENCE_2026-08-06.md`.

# R7 worker/framebuffer integration evidence

Date: 2026-08-03
Status: Candidate validation pending

## Verified prerequisites

Canonical framebuffer storage was exact-green on:

```text
Commit: 493a478b8ba3e1a5fb7086003f13c291478c8bbe
CI run: 30883374673
Quality job: 91909234102
Desktop/native job: 91909234131
```

Bounded PNG screenshot encoding was exact-green on:

```text
Commit: a70f0b56c844c4bf9b6ac4cb18ee49f1fcc0ca63
CI run: 30884462194
Quality job: 91912522738
Desktop/native job: 91912522833
```

## Integration candidate

The worker integration implementation was introduced by:

```text
cefbe49a8a52245bf4d9a77d40140298b0c72d46
```

Pinned Rust 1.97.1 `cargo fmt --all` produced worker blob:

```text
fd9c5340e4e620d6a056d9c8e7a4762c2c8e633d
```

That exact formatter output was applied to `master` by:

```text
8493e1d38388de2fea65eee5942f020da22f201d
```

## Implemented contract

- the native worker thread is the only framebuffer writer;
- a complete native frame is copied and validated before the public state reaches `Connected`;
- native display metadata and copied framebuffer dimensions/revision must agree;
- native RGBX bytes are converted into canonical RGBA8 bytes;
- public framebuffer revisions are process-local and monotonic across reconnects;
- disconnect, stall, manual reconnect, and shutdown invalidate the current framebuffer;
- stale pixels fail closed for snapshots and screenshots;
- `WorkerClient` exposes read-only metadata, immutable snapshots, and bounded screenshot-service construction;
- framebuffer memory is capped by validated worker configuration;
- tests cover coherent copy, opaque alpha conversion, stale shutdown state, reconnect revisions, authentication failure, and mismatched native metadata.

## Validation boundary

This integration is not considered complete until one exact `master` SHA passes:

```text
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo test --locked --workspace --all-features
RUSTDOCFLAGS=-Dwarnings cargo doc --locked --workspace --all-features --no-deps
python -m unittest discover -s tests -p 'test_*.py' -v
bash syntax checks
real Debian/TigerVNC desktop smoke
real LibVNCClient adapter smoke
```

The exact successful SHA, run, and job IDs will be appended only after authoritative CI completion.

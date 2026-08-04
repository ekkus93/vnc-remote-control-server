# R7 PNG dependency lock evidence

Date: 2026-08-03

## Dependency decision

The screenshot implementation uses the maintained Rust `png` crate at workspace requirement `0.18.1`.

## Lock generation procedure

The dependency declarations were prepared on temporary branch `r7-png-lock-prep`, based on exact green framebuffer commit `493a478b8ba3e1a5fb7086003f13c291478c8bbe`.

A temporary branch-only GitHub Actions workflow installed the pinned Rust 1.97.1 toolchain and native build dependencies, then ran:

```text
cargo check --workspace
```

Cargo generated and committed the updated lockfile on that isolated branch. The branch comparison against the base contained only:

- one `png` workspace dependency declaration;
- one controller crate dependency declaration;
- 64 added lockfile lines and no lockfile deletions;
- the temporary branch-only lock preparation workflow.

The exact Cargo-generated lockfile blob copied to `master` is:

```text
344730f1b6e2dd75745c6eb04e93d5b37850fc6b
```

No registry checksum was guessed or hand-authored. The temporary workflow was not copied to `master`.

## Master implementation commit

The dependency declarations, exact Cargo-generated lockfile, screenshot module, and module export were committed to `master` together as:

```text
804b6a06930cd6cbbd5ce805048cc737cf73e918
```

The implementation must still pass the authoritative `master` CI gate before R7.4 is considered complete.

# v0.1 Release Security and Native-Safety Policy

Date: 2026-08-05
Repository: `ekkus93/vnc-remote-control-server`
Scope: the v0.1 release candidate and every later release unless superseded by a stricter policy.

## Fail-closed release gates

Both the authoritative `CI` workflow and the `Release Gates` workflow must complete successfully on the exact release-candidate commit. `CI` proves functional and integration behavior; `Release Gates` proves static policy, native-safety, dependency, history, image-vulnerability, and SBOM requirements. Neither workflow substitutes for the other. A skipped, cancelled, neutral, timed-out, or failed required job is not acceptance evidence.

The following findings block release:

- any Rust advisory, prohibited license, wildcard dependency, or unapproved registry/source rejected by `cargo deny check`;
- any secret finding from Gitleaks across the complete reachable Git history;
- any CRITICAL vulnerability reported by Trivy in either release image;
- any ShellCheck, actionlint, BuildKit Dockerfile check, or Compose validation failure;
- any AddressSanitizer, ThreadSanitizer, or Miri failure;
- any ordinary formatting, Clippy, unit, documentation, desktop, native-adapter, Compose, integration, API, or end-to-end failure.

HIGH image vulnerabilities are retained in the JSON evidence and must be reviewed. They are not automatic v0.1 blockers unless they are exploitable in the shipped configuration, affect a security boundary, or are escalated by the release reviewer. CRITICAL findings are always blocking.

## Exceptions

There are no implicit or silent exceptions. An exception requires a repository issue that records the exact finding identifier, affected component and image digest, owner, rationale, compensating controls, approval, and an expiry no later than 30 days. The exception must be linked from this document and from the release evidence. Inline ignores without that record are prohibited.

No v0.1 exception is currently approved.

## Native-safety coverage and limitations

AddressSanitizer instruments the Rust LibVNCClient adapter and its boundary tests. ThreadSanitizer is limited to Rust-only shared-state tests because combining TSan with the distribution LibVNCClient shared library is not a reliable signal. Rust does not expose a general UBSan mode; Miri is the release gate for Rust undefined behavior and provenance checks. The Debian LibVNCClient shared library is not rebuilt with sanitizers, so upstream native-library defects remain outside this repository's instrumentation boundary.

These limitations must remain visible in the release evidence. A sanitizer command may not be changed to `continue-on-error`, wrapped in an unconditional success fallback, or replaced by a compile-only check without an explicit policy update.

## Image and artifact evidence

Release Gates builds the controller and desktop release images from the candidate commit, scans both images, and generates CycloneDX SBOMs. Static-policy, native-safety, and image-security artifacts are retained for 30 days. Failure artifacts must remain sanitized and must not contain bearer tokens, VNC passwords, typed text, clipboard payloads, or framebuffer screenshots.

## Tool pinning

The release gate pins the Rust stable and nightly toolchains, cargo-deny, actionlint, Gitleaks, Trivy, and GitHub Actions by immutable version or commit. Downloaded release archives are checked against the publisher-provided checksum manifest before installation.

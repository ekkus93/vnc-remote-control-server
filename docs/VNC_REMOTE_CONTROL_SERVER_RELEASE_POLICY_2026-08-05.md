# v0.1 Release Security and Native-Safety Policy

Date: 2026-08-05
Repository: `ekkus93/vnc-remote-control-server`
Scope: the v0.1 release candidate and every later release unless superseded by a stricter policy.

## Fail-closed release gates

Both the authoritative `CI` workflow and the `Release Gates` workflow must complete successfully on the exact release-candidate commit. `CI` proves functional and integration behavior; `Release Gates` proves static policy, native-safety, dependency, history, image-vulnerability, and SBOM requirements. Neither workflow substitutes for the other. A skipped, cancelled, neutral, timed-out, or failed required job is not acceptance evidence.

The following findings block release:

- any Rust advisory, prohibited license, wildcard dependency, or unapproved registry/source rejected by `cargo deny check`;
- any secret finding from Gitleaks across the complete reachable Git history;
- any CRITICAL image finding that is not matched by an exact, current reachability determination;
- any ShellCheck warning/error, actionlint error, BuildKit Dockerfile check, or Compose validation failure;
- any AddressSanitizer, ThreadSanitizer, or Miri failure;
- any ordinary formatting, Clippy, unit, documentation, desktop, native-adapter, Compose, integration, API, or end-to-end failure.

HIGH image vulnerabilities are retained in JSON evidence and must be reviewed. They are not automatic v0.1 blockers unless they are exploitable in the shipped configuration, affect a security boundary, or are escalated by the release reviewer.

## Exact CRITICAL VEX determinations

There are no implicit or silent exceptions. `--ignore-unfixed` is prohibited, wildcard ignores are prohibited, and scanner exit codes may not be discarded. The release gate parses the raw Trivy JSON and matches every CRITICAL finding by exact image, CVE, binary package, and installed version. Any unmatched CRITICAL tuple is release-blocking. A changed package version is unmatched and therefore blocking.

A permitted determination must be either `not_affected` or `not_exploitable`, include a substantive reachability rationale, cite the Debian Security Tracker, link a repository tracking issue, and expire no more than 30 days after review. Risk-acceptance entries are not permitted for v0.1. Stale determinations that no longer appear in the scan also fail the gate so they cannot accumulate silently.

Current determinations are stored in `security/trivy-critical-vex.json` and tracked by issue #7. They expire on 2026-09-04. Expiry, a new finding, a package-version change, a new application input path, or a mismatch between the report and the VEX file blocks release.

## Native-safety coverage and limitations

AddressSanitizer instruments the Rust LibVNCClient adapter and its boundary tests. ThreadSanitizer is limited to Rust-only shared-state tests because combining TSan with the distribution LibVNCClient shared library is not a reliable signal. Rust does not expose a general UBSan mode; Miri is the release gate for Rust undefined behavior and provenance checks. The Debian LibVNCClient shared library is not rebuilt with sanitizers, so upstream native-library defects remain outside this repository's instrumentation boundary.

These limitations must remain visible in the release evidence. A sanitizer command may not be changed to `continue-on-error`, wrapped in an unconditional success fallback, or replaced by a compile-only check without an explicit policy update.

Miri runs the pure-Rust core test target with `-Zmiri-disable-isolation` because Proptest resolves failure-persistence paths through the host current working directory. This permits host filesystem and environment access but does not disable Miri's undefined-behavior, validity, provenance, leak, or data-race checks. The Miri target contains no native FFI or network operations. Test generation, shrinking, assertions, and the complete pure-Rust core test target remain enabled.

## Image and artifact evidence

Release Gates builds the controller and desktop release images from the candidate commit, scans both images, and generates CycloneDX SBOMs. Static-policy, native-safety, raw vulnerability, exact VEX evaluation, and image-security artifacts are retained for 30 days. Failure artifacts must remain sanitized and must not contain bearer tokens, VNC passwords, typed text, clipboard payloads, or framebuffer screenshots.

## Tool pinning

The release gate pins the Rust stable and nightly toolchains, cargo-deny, actionlint, Gitleaks, Trivy, and GitHub Actions by immutable version or commit. Downloaded release archives are checked against the publisher-provided checksum manifest before installation.

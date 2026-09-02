# v0.1 Release Security and Native-Safety Policy

Date: 2026-08-05
Repository: `ekkus93/vnc-remote-control-server`
Scope: the v0.1 release candidate and every later release unless superseded by a stricter policy.

## Fail-closed release gates

Both the authoritative `CI` workflow and the `Release Gates` workflow must complete successfully on the exact release-candidate commit. `CI` proves functional and integration behavior; `Release Gates` proves static policy, native-safety, dependency, history, image-vulnerability, and SBOM requirements. Neither workflow substitutes for the other. A skipped, cancelled, neutral, timed-out, or failed required job is not acceptance evidence.

The following findings block release:

- any Rust advisory, prohibited license, wildcard dependency, or unapproved registry/source rejected by `cargo deny check`;
- any secret finding from Gitleaks across the complete reachable Git history that is not an explicitly reviewed exact false-positive fingerprint;
- any CRITICAL image finding that is not matched by an exact, current reachability determination;
- any ShellCheck warning/error, actionlint error, BuildKit Dockerfile check, or Compose validation failure;
- any AddressSanitizer, ThreadSanitizer, or Miri failure;
- any ordinary formatting, Clippy, unit, documentation, desktop, native-adapter, Compose, integration, API, or end-to-end failure.

HIGH image vulnerabilities are retained in JSON evidence and must be reviewed. They are not automatic v0.1 blockers unless they are exploitable in the shipped configuration, affect a security boundary, or are escalated by the release reviewer.

## Exact Gitleaks false-positive fingerprints

Gitleaks always scans the complete reachable Git history with its built-in rules. `.gitleaksignore` may contain only full finding fingerprints that have been individually reviewed and proven not to contain credentials or other secrets. Rule-wide, path-wide, wildcard, regular-expression, entropy, commit-range, baseline, or exit-code suppressions are prohibited.

The current ignore file contains three exact `generic-api-key` fingerprints. One is the previously reviewed rebase-TODO fixture. The other two are the same public RFC 6455 WebSocket handshake example nonce (`dGhlIHNhbXBsZSBub25jZQ==`) as it appeared in a historical controller test and a temporary recovery script. That nonce is protocol example data, not an API key or repository credential. The release-policy contract pins the complete ordered fingerprint set, forbids wildcard entries, and fails if an unreviewed fingerprint is added or one of the approved fingerprints changes.

Any future Gitleaks finding remains release-blocking until it is investigated. A finding may be added to `.gitleaksignore` only when its exact fingerprint and non-secret rationale are documented and the release-policy contract is updated in the same review. The full-history scan itself may not be narrowed or made non-blocking.

## Exact CRITICAL VEX determinations

There are no implicit or silent exceptions. `--ignore-unfixed` is prohibited, wildcard ignores are prohibited, and scanner exit codes may not be discarded. The release gate parses the raw Trivy JSON and matches every CRITICAL finding by exact image, CVE, binary package, and installed version. Any unmatched CRITICAL tuple is release-blocking. A changed package version is unmatched and therefore blocking.

A permitted determination must be either `not_affected` or `not_exploitable`, include a substantive reachability rationale, cite the Debian Security Tracker, link a repository tracking issue, and expire no more than 30 days after review. Risk-acceptance entries are not permitted for v0.1. Stale determinations that no longer appear in the scan also fail the gate so they cannot accumulate silently.

Current determinations are stored in `security/trivy-critical-vex.json` and tracked by issue #7. They expire on 2026-09-04. Expiry, a new finding, a package-version change, a new application input path, or a mismatch between the report and the VEX file blocks release.

## Native-safety coverage and limitations

AddressSanitizer instruments the Rust LibVNCClient adapter and its boundary tests. ThreadSanitizer executes the complete `controller-api --lib` target, including worker, shutdown, event-bridge, framebuffer, observability, and HTTP library tests, and separately executes `remote-desktop-core --lib`. No skip list, suppression file, `continue-on-error`, or native-adapter exclusion feature is used. The distribution Debian LibVNCClient shared library is not rebuilt with sanitizers, so upstream native-library defects remain outside this repository's instrumentation boundary. Rust does not expose a general UBSan mode; Miri is the pure-Rust undefined-behavior and provenance gate.

These limitations must remain visible in the release evidence. A sanitizer command may not be changed to `continue-on-error`, wrapped in an unconditional success fallback, or replaced by a compile-only check without an explicit policy update.

Miri runs only `remote-desktop-core --lib` with `-Zmiri-disable-isolation` because Proptest resolves failure-persistence paths through the host current working directory. This permits host filesystem and environment access but does not disable Miri's undefined-behavior, validity, provenance, leak, or data-race checks. `controller-api` is outside the Miri boundary because it depends on Tokio, OS threads, native FFI, and real I/O. Test generation, shrinking, assertions, and the complete pure-Rust core test target remain enabled.

## Image and artifact evidence

Release Gates builds the controller and desktop release images from the candidate commit, scans both images, and generates CycloneDX SBOMs. Static-policy, native-safety, raw vulnerability, exact VEX evaluation, and image-security artifacts are retained for 30 days. Failure artifacts must remain sanitized and must not contain bearer tokens, VNC passwords, typed text, clipboard payloads, or framebuffer screenshots.

## Tool pinning

The release gate pins the Rust stable and nightly toolchains, cargo-deny, actionlint, Gitleaks, Trivy, and GitHub Actions by immutable version or commit. Downloaded release archives are checked against the publisher-provided checksum manifest before installation.

Every permanent third-party GitHub Action reference under `.github/workflows/*.yml` or `.yaml` must use a full 40-hex commit SHA. Mutable tags, branches, aliases such as `@stable`, and major-version refs such as `@v4` are prohibited even when an action input separately pins the tool it installs. Repository-local actions referenced through `./...` are exempt because their implementation is already fixed by the candidate commit. The release-policy contract scans every permanent workflow file and fails closed on any non-local mutable `uses:` reference.

## Metric and API naming compatibility

Exported metric and API names must describe the represented value. A misleading pre-release name may be corrected without an alias only when a repository-wide search confirms that no shipped API schema, dashboard, alert, deployment example, operator contract, or permanent integration test consumes it. The evidence must record the search and the compatibility decision. Once an external consumer is identified, a rename requires a documented compatibility window or an explicit breaking-release decision.

For v0.1, `vrc_worker_command_queue_depth` was replaced by `vrc_worker_command_submissions_in_flight` without an alias. Accounting and permit acquisition did not change; the value can transiently exceed bounded channel capacity because it includes submissions between permit acquisition and queue admission.

# Security Policy

## Supported versions

The project is pre-release. Security fixes are applied only to the current `master` branch until the first tagged release. After v0.1, the newest supported minor release and `master` will receive security fixes.

## Reporting a vulnerability

Do not open a public issue containing exploit details, credentials, tokens, private hostnames, or sensitive screenshots. Use GitHub's private vulnerability reporting feature for this repository. Include:

- the affected commit or version;
- the attack preconditions;
- reproducible steps or a minimal proof of concept;
- the impact;
- suggested remediation, when known.

The maintainer will acknowledge a complete report, assess severity, coordinate a fix, and publish disclosure information after affected users have a reasonable update path.

## Security boundaries

- Production Compose must not publish raw VNC port `5901`.
- API and VNC credentials must come from secret files, never image layers or source control.
- The controller is designed for the project-owned desktop container, not arbitrary untrusted VNC servers.
- Typed text, clipboard contents, framebuffer pixels, bearer tokens, and VNC passwords must never be logged.
- The controller does not terminate TLS; exposure beyond localhost requires a trusted TLS reverse proxy and a reviewed network boundary.

## VNC password lifecycle

The shared `SecretString` abstraction is non-`Debug` and zeroizes its live byte buffer on drop. The controller uses it for the secret-file read result, validated configuration, worker settings and native-client configuration. The Rust adapter scrubs its temporary NUL-terminated connection buffer, and the C shim scrubs its persistent duplicated password before release using a C11-compatible volatile-byte loop. Tests instrument live buffers and drop behavior; no test reads freed memory.

The production controller image is based on Debian 13.6 and installs Debian's `libvncclient1`. The exact native package version is captured in every Release Gates image SBOM; the current validated image evidence records `0.9.15+dfsg-1+deb13u2`. The builder uses the corresponding Debian `libvncserver-dev` package rather than an Ubuntu package or an undeclared host library.

Classic VNC authentication uses at most the protocol-relevant first eight password bytes. Once the password callback returns a freshly allocated copy to LibVNCClient, that allocation is third-party-owned. The project therefore does **not** claim full-allocation zeroization for LibVNCClient-owned callback memory after handoff, including any bytes beyond the protocol-relevant prefix in a longer allocation. The project-owned shim does scrub the buffers it continues to own. This third-party residual must be re-reviewed whenever the native LibVNCClient package changes. Operators should still use the private VNC network and treat classic VNC authentication as access control, not transport confidentiality.

## API bearer-token lifecycle

The process-wide API token is held by an explicit `ApiToken` handle backed by `Arc<SecretString>`. Cloning controller or router state clones only the shared owner; it does not clone token bytes into an ordinary `String` or `Arc<str>`. The token type implements neither `Debug` nor `Display`, and the HTTP authentication boundary exposes only borrowed bytes for constant-time comparison. When the final owner is dropped, `SecretString` overwrites its live string bytes with volatile writes before releasing the allocation.

This is a project-owned live-buffer guarantee, not a claim that process crashes, core dumps, kernel memory, allocator metadata, reverse proxies, clients, or request-header storage contain no residual token bytes. Operators must still disable core dumps where appropriate, protect process memory, terminate TLS at a trusted boundary, and prevent authorization-header logging outside the controller.

## Secret-file rejection lifecycle

The filesystem reader checks metadata, regular-file status, size, and Unix permissions before reading. After reading, UTF-8 validation and CR/LF trimming operate on one owned byte vector. Invalid UTF-8, empty-after-trim, embedded NUL, and future parser rejection paths overwrite the complete live vector with volatile writes before returning a redaction-safe error. Successful parsing transfers the same allocation into `SecretString`; trailing CR/LF bytes are scrubbed before truncation.

## Clipboard buffer lifecycle

Project-owned native C clipboard allocations are scrubbed before replacement and destruction using the same volatile-byte primitive as the VNC password. The temporary outbound C copy passed to `SendClientCutText` is scrubbed before free on both success and failure. The stored payload length is retained so scrubbing covers the allocation through its terminating NUL.

This guarantee does not cover Rust clipboard request/response values, Axum response bodies, LibVNCClient-owned copies, the VNC server, desktop applications, toolkit or OS clipboard managers, client applications, allocator residuals, swap, or crash dumps. Clipboard contents remain sensitive product data and must never be logged.

## Release-security evidence

Release acceptance is governed by [`docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_POLICY_2026-08-05.md`](docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_POLICY_2026-08-05.md). Both permanent `CI` and `Release Gates` must pass on the exact candidate SHA. Release Gates records static/supply-chain evidence, native sanitizer/Miri evidence, image vulnerability reports, exact CRITICAL VEX evaluation, and CycloneDX SBOMs.

Current CRITICAL determinations are stored in [`security/trivy-critical-vex.json`](security/trivy-critical-vex.json). They expire on September 4, 2026; an expired determination, changed package version, or unmatched CRITICAL finding must fail closed.

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
- The MCP adapter authenticates to the controller with a file-backed bearer token; it does not accept a raw controller-token environment variable or command-line argument.
- MCP Streamable HTTP has no project-specific client-authentication layer and is restricted to SDK-protected loopback hosts. Never patch it to bind publicly as an authentication workaround.
- MCP mutation tools are absent by default and require explicit process-wide opt-in. Transport access to a mutation-enabled MCP process is equivalent to trusted desktop-control access.

The current MCP transport, secret, logging, and mutation-outcome security model is documented in [`docs/MCP_SERVER.md`](docs/MCP_SERVER.md).

## VNC password lifecycle

The shared `SecretString` abstraction is non-`Debug` and zeroizes its live byte buffer on drop. The controller uses it for the secret-file read result, validated configuration, worker settings and native-client configuration. The Rust adapter scrubs its temporary NUL-terminated connection buffer, and the C shim scrubs its persistent duplicated password before release using a C11-compatible volatile-byte loop. Tests instrument live buffers and drop behavior; no test reads freed memory.

The production controller image is based on Debian 13.6 and installs Debian's `libvncclient1`. The exact native package version is captured in every Release Gates image SBOM; the current validated image evidence records `0.9.15+dfsg-1+deb13u2`. The builder uses the corresponding Debian `libvncserver-dev` package rather than an Ubuntu package or an undeclared host library.

Classic VNC authentication uses at most the protocol-relevant first eight password bytes. Once the password callback returns a freshly allocated copy to LibVNCClient, that allocation is third-party-owned. The project therefore does **not** claim full-allocation zeroization for LibVNCClient-owned callback memory after handoff, including any bytes beyond the protocol-relevant prefix in a longer allocation. The project-owned shim does scrub the buffers it continues to own. This third-party residual must be re-reviewed whenever the native LibVNCClient package changes. Operators should still use the private VNC network and treat classic VNC authentication as access control, not transport confidentiality.

## API bearer-token lifecycle

The process-wide API token is held by an explicit `ApiToken` handle backed by `Arc<SecretString>`. Cloning controller or router state clones only the shared owner; it does not clone token bytes into an ordinary `String` or `Arc<str>`. The token type implements neither `Debug` nor `Display`, and the HTTP authentication boundary exposes only borrowed bytes for constant-time comparison. When the final owner is dropped, `SecretString` overwrites its live string bytes with volatile writes before releasing the allocation.

This is a project-owned live-buffer guarantee, not a claim that process crashes, core dumps, kernel memory, allocator metadata, reverse proxies, clients, or request-header storage contain no residual token bytes. Operators must still disable core dumps where appropriate, protect process memory, terminate TLS at a trusted boundary, and prevent authorization-header logging outside the controller.

## MCP controller-token lifecycle

`VRC_MCP_CONTROLLER_TOKEN_FILE` is the only supported controller-token ingress for the MCP adapter. The environment contains a file path, not the bearer-token value. The MCP secret reader validates metadata, regular-file status, a 1-byte through 4-KiB size bound, Unix permissions, strict UTF-8, trailing CR/LF handling, nonempty content, and NUL rejection before the typed Python controller client is constructed. Errors do not echo secret bytes.

The Python process cannot inherit the Rust `SecretString` volatile-zeroization guarantee. After decoding, the controller token exists in ordinary Python objects including a Python `str`; immutable Python string/bytes objects and copies made by the runtime or HTTP stack cannot be reliably scrubbed through a supported API. The MCP adapter therefore **does not guarantee zeroization** of controller-token bytes in Python process memory. Protect the MCP process as secret-bearing: restrict local process access, consider disabling core dumps, protect swap/process inspection where appropriate, and terminate the process when it no longer needs the token.

This limitation is not a reason to move the token to a raw environment variable, command line, URL, or source constant. File-only secret ingress still reduces disclosure through shell history, process argument lists, inherited environments, and configuration dumps.

## MCP transport and mutation boundary

stdio is the default MCP transport and is preferred when the MCP host can launch the child directly. Streamable HTTP is an explicit opt-in and accepts only `127.0.0.1`, `localhost`, or `::1`, the exact host spellings for which the pinned `mcp==2.1.1` SDK installs its DNS-rebinding Host/Origin protection. The adapter does not replace or disable that middleware. Remote access must use a trusted authenticated tunnel or a reviewed proxy boundary while the backend listener remains loopback-only.

The MCP HTTP listener itself does not authenticate clients. Any local process able to reach it must be treated as potentially able to invoke every registered tool. Because screenshots and clipboard reads return sensitive desktop data, read-only mode is still a trusted-client surface. When `VRC_MCP_ALLOW_MUTATIONS=true`, the same transport grants the exposed pointer, keyboard, text, clipboard-set, and reconnect capabilities process-wide.

A mutation transport/protocol failure is not proof that the controller received nothing. If a trustworthy command ID exists, MCP reports `command_outcome_unknown`, preserves the ID, sets `retry_safe=false`, and directs the caller to `vnc_get_command_status`. Without a trustworthy ID it reports conservative `mutation_outcome_unknown` with `retry_safe=false`. The adapter never fabricates an ID and never automatically retries or replays an ambiguous mutation.

## Secret-file rejection lifecycle

The filesystem reader checks metadata, regular-file status, size, and Unix permissions before reading. After reading, UTF-8 validation and CR/LF trimming operate on one owned byte vector. Invalid UTF-8, empty-after-trim, embedded NUL, and future parser rejection paths overwrite the complete live vector with volatile writes before returning a redaction-safe error. Successful parsing transfers the same allocation into `SecretString`; trailing CR/LF bytes are scrubbed before truncation.

## Clipboard buffer lifecycle

Project-owned native C clipboard allocations are scrubbed before replacement and destruction using the same volatile-byte primitive as the VNC password. The temporary outbound C copy passed to `SendClientCutText` is scrubbed before free on both success and failure. The stored payload length is retained so scrubbing covers the allocation through its terminating NUL.

This guarantee does not cover Rust clipboard request/response values, Axum response bodies, LibVNCClient-owned copies, the VNC server, desktop applications, toolkit or OS clipboard managers, client applications, allocator residuals, swap, or crash dumps. Clipboard contents remain sensitive product data and must never be logged.

## Release-security evidence

Release acceptance is governed by [`docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_POLICY_2026-08-05.md`](docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_POLICY_2026-08-05.md). Both permanent `CI` and `Release Gates` must pass on the exact candidate SHA. Release Gates records static/supply-chain evidence, native sanitizer/Miri evidence, image vulnerability reports, exact CRITICAL VEX evaluation, and CycloneDX SBOMs.

Current CRITICAL determinations are stored in [`security/trivy-critical-vex.json`](security/trivy-critical-vex.json). They were re-reviewed on August 31, 2026 and expire on September 30, 2026; an expired determination, changed package version, stale VEX tuple, or unmatched CRITICAL finding must fail closed.

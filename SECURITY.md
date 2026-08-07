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

## VNC password lifecycle

The shared `SecretString` abstraction is non-`Debug` and zeroizes its live byte buffer on drop. The controller uses it for the secret-file read result, validated configuration, worker settings and native-client configuration. The Rust adapter scrubs its temporary NUL-terminated connection buffer, and the C shim scrubs its persistent duplicated password before release using a C11-compatible volatile-byte loop. Tests instrument live buffers and drop behavior; no test reads freed memory.

The pinned Debian LibVNCClient package is `0.9.14+dfsg-1ubuntu0.2`. Its source location is `src/libvncclient/rfbclient.c`, function `HandleVncAuth`. That function receives the allocation returned by `GetPassword`, truncates the logical password to eight bytes for classic VNC DES authentication, encrypts the challenge, overwrites only the now-visible truncated string through its NUL terminator, and then frees the allocation. Consequently, bytes beyond offset eight in a longer callback allocation are not proven scrubbed before the library frees it. The shim has no post-authentication ownership hook for that allocation, so the unverified tail remains an explicit third-party residual rather than a project-owned-zeroization claim. Operators should still use a private network and treat VNC authentication as defense in depth, not transport confidentiality.

## API bearer-token lifecycle

The process-wide API token is held by an explicit `ApiToken` handle backed by `Arc<SecretString>`. Cloning controller or router state clones only the shared owner; it does not clone token bytes into an ordinary `String` or `Arc<str>`. The token type implements neither `Debug` nor `Display`, and the HTTP authentication boundary exposes only borrowed bytes for constant-time comparison. When the final owner is dropped, `SecretString` overwrites its live string bytes with volatile writes before releasing the allocation.

This is a project-owned live-buffer guarantee, not a claim that process crashes, core dumps, kernel memory, allocator metadata, reverse proxies, clients, or request-header storage contain no residual token bytes. Operators must still disable core dumps where appropriate, protect process memory, terminate TLS at a trusted boundary, and prevent authorization-header logging outside the controller.

## Secret-file rejection lifecycle

The filesystem reader checks metadata, regular-file status, size, and Unix permissions before reading. After reading, UTF-8 validation and CR/LF trimming operate on one owned byte vector. Invalid UTF-8, empty-after-trim, embedded NUL, and future parser rejection paths overwrite the complete live vector with volatile writes before returning a redaction-safe error. Successful parsing transfers the same allocation into `SecretString`; trailing CR/LF bytes are scrubbed before truncation.

## Clipboard buffer lifecycle

Project-owned native C clipboard allocations are scrubbed before replacement and destruction using the same volatile-byte primitive as the VNC password. The temporary outbound C copy passed to `SendClientCutText` is scrubbed before free on both success and failure. The stored payload length is retained so scrubbing covers the allocation through its terminating NUL.

This guarantee does not cover Rust clipboard request/response values, Axum response bodies, LibVNCClient-owned copies, the VNC server, the desktop test application, toolkit or OS clipboard managers, client applications, allocator residuals, swap, or crash dumps. Clipboard contents remain sensitive product data and must never be logged.

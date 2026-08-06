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

API bearer-token storage and constant-time comparison are unchanged in this pass. Moving the API token to the shared zeroizing abstraction is a deferred follow-up so that this correctness repair does not mix authentication behavior changes into the shutdown and worker-state work.

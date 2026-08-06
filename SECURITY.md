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

LibVNCClient 0.9.14+dfsg-1ubuntu0.2 owns the allocation returned by its `GetPassword` callback and frees it inside the library. The shim has no post-authentication hook that can scrub that library-owned copy, so this remains an explicit third-party residual rather than a project-owned-zeroization claim. Classic VNC authentication also uses only the first eight password bytes for the DES challenge response; operators should still use a private network and treat VNC authentication as defense in depth, not transport confidentiality.

API bearer-token storage and constant-time comparison are unchanged in this pass. Moving the API token to the shared zeroizing abstraction is a deferred follow-up so that this correctness repair does not mix authentication behavior changes into the shutdown and worker-state work.

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

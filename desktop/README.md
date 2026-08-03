# Desktop container

The desktop image runs one non-root XFCE session on TigerVNC display `:1` (`5901/tcp`). It requires a non-empty password secret at `/run/secrets/vnc_password` and never falls back to unauthenticated operation.

The secret path is a runtime entrypoint default rather than image ENV metadata. This keeps sensitive configuration out of Docker image configuration while still allowing an explicitly supplied `VNC_PASSWORD_FILE` at runtime. Compose-style secret files are mounted read-only and container-readable; the derived TigerVNC password file is then created as mode `0600` inside the non-root home directory.

The image installs Debian's `tigervnc-tools` package because it owns `/usr/bin/tigervncpasswd`, which creates the encoded authentication file before the server starts.

The image launches `desktop/test-app/test_app.py`, a deterministic Tk interface that records pointer, button, scroll, key, text, clipboard, and counter state in `/tmp/vnc-test-app-state.json`. Integration tests reset this file-backed state between cases.

The Debian 13.6 slim base is pinned to `sha256:020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd`, which was resolved and recorded by CI. Raw VNC remains private in production Compose; the M1 smoke test publishes it only to `127.0.0.1` for a bounded TigerVNC Viewer authentication probe.

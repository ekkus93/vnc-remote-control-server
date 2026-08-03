# Desktop container

The desktop image runs one non-root XFCE session on TigerVNC display `:1` (`5901/tcp`). It requires a non-empty password secret at `/run/secrets/vnc_password` and never falls back to unauthenticated operation.

The image launches `desktop/test-app/test_app.py`, a deterministic Tk interface that records pointer, button, scroll, key, text, clipboard, and counter state in `/tmp/vnc-test-app-state.json`. Integration tests reset this file-backed state between cases.

Release builds pin Debian 13.6 slim by digest. Raw VNC remains private in production Compose; the M1 smoke test publishes it only to `127.0.0.1` for a bounded TigerVNC Viewer authentication probe.

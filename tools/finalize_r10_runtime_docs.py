#!/usr/bin/env python3
"""Finalize R10 runtime evidence after the exact PR validation run passed."""

from pathlib import Path

EVIDENCE = Path("docs/VNC_REMOTE_CONTROL_SERVER_R10_MUTATING_HTTP_EVIDENCE_2026-08-04.md")
TODO = Path("docs/VNC_REMOTE_CONTROL_SERVER_REBASE_TODO_2026-08-03.md")


evidence = EVIDENCE.read_text(encoding="utf-8")
old_scope = (
    "This evidence record covers the authenticated mutating HTTP router slice of R10. "
    "It does not claim completion of the TCP listener, request-header/body deadlines, "
    "graceful process shutdown, or real public HTTP-to-TigerVNC end-to-end testing."
)
new_scope = (
    "This evidence record covers the authenticated HTTP router and the completed R10 "
    "runtime slice: the configured TCP listener, bounded header and body reads, "
    "signal-driven graceful shutdown, shutdown-time command rejection, and the real "
    "authenticated HTTP-to-worker-to-LibVNCClient-to-TigerVNC path."
)
if evidence.count(old_scope) != 1:
    raise SystemExit("R10 evidence scope text did not match exactly")
evidence = evidence.replace(old_scope, new_scope, 1)

marker = "## Remaining R10 work\n"
if evidence.count(marker) != 1:
    raise SystemExit("R10 evidence remaining-work marker did not match exactly")
evidence = evidence[: evidence.index(marker)] + """## Runtime completion implementation

The runtime completion branch adds:

- a real TCP listener bound to `ControllerConfig::listen_address`;
- bounded HTTP/1 header reads (`VRC_HTTP_HEADER_TIMEOUT_MS`);
- bounded, length-limited request-body collection (`VRC_HTTP_BODY_TIMEOUT_MS`);
- SIGINT/SIGTERM-driven shutdown that marks `HttpState` as shutting down before the listener stops accepting sockets;
- bounded active-connection draining (`VRC_SHUTDOWN_GRACE_MS`) followed by worker shutdown and join;
- slow-header, slow-body, and oversized-body runtime tests;
- a real authenticated HTTP -> WorkerClient -> LibVNCClient -> TigerVNC E2E test.

## Pull-request validation

```text
Pull request: #6
Validated head SHA: f0c7d8ee4a95a1cb154b83c87c3cbe8d84b9d494
CI run: 30945615936
Repository quality job: 92114729003
Desktop/native/E2E job: 92114729086
Result: success
```

The exact validated head passed:

- formatting;
- workspace Clippy for all targets and features with warnings denied;
- all Rust workspace tests, including the slow-header and slow-body runtime tests;
- warning-denied rustdoc;
- Python and shell contract gates;
- secured desktop image smoke;
- live native-adapter smoke;
- WorkerHandle input E2E;
- WorkerHandle failure-diagnostic redaction self-test;
- WorkerHandle text/clipboard E2E;
- authenticated HTTP -> worker -> LibVNCClient -> TigerVNC pointer mutation E2E;
- SIGTERM-driven bounded controller shutdown with secret-log checks.

## R10 boundary after this slice

The requested R10 runtime work is complete. Two checklist entries remain intentionally open because they belong to the later WebSocket/observability slice rather than this HTTP runtime slice:

- authenticate WebSocket upgrades;
- ensure future access logs redact the authorization header.
"""
EVIDENCE.write_text(evidence, encoding="utf-8")


todo = TODO.read_text(encoding="utf-8")
old_ci = "CI run: pending branch validation"
new_ci = """Validated head SHA: f0c7d8ee4a95a1cb154b83c87c3cbe8d84b9d494
Pull request: #6
CI run: 30945615936
Quality job: 92114729003 (success)
Desktop/native/HTTP E2E job: 92114729086 (success)"""
if todo.count(old_ci) != 1:
    raise SystemExit("authoritative R10 pending-CI marker did not match exactly")
todo = todo.replace(old_ci, new_ci, 1)
TODO.write_text(todo, encoding="utf-8")

Path(__file__).unlink()

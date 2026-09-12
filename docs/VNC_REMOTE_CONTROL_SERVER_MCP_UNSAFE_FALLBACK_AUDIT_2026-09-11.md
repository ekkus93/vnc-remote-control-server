# VNC Remote Control Server — MCP Unsafe-Fallback and Silent-Failure Audit

**Audit date:** 2026-09-11  
**Repository:** `ekkus93/vnc-remote-control-server`  
**Parent TODO:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_TODO_2026-09-02.md`

## Scope

MCP-013 reviewed the production MCP modules under `python/src/vnc_remote_control/mcp_*.py`, their configuration/execution/read/mutation/outcome/server paths, dependency-free contract tests, pinned-SDK tests, transport acceptance, and real controller/TigerVNC E2E.

The audit specifically searched for unsafe fallback behavior, quiet success after failure, broad exception suppression, hidden mutation replay, sensitive payload logging, weakened Streamable HTTP security, raw-token ingress, test doubles that accidentally bypass one-call semantics, and dependency-import compatibility fallbacks.

## Findings

### Broad exception handling and silent success

Production MCP code contains no bare `except`, no `except Exception`, no `except BaseException`, and no AST `pass` fallback. Typed exception handling remains explicit. No reviewed exception path returns empty/success data after failure.

### `.get(...)` and default behavior

The remaining mapping `.get(...)` uses are classified and guarded by `tests/test_mcp_unsafe_fallback_contract.py`:

- `environment.get(name)` implements documented defaults only when an optional environment variable is absent. A present malformed value fails closed.
- `registration.get("annotations")` and `registration.get("name")` are test/registration metadata validation paths and explicitly fail when required data is missing or invalid.

No controller protocol object is silently normalized with a `.get(..., default)` fallback.

### SDK/dependency fallback

The MCP SDK loader requires the reviewed API surface and exact dependency target. Missing or incompatible SDK APIs raise `McpDependencyError`. The `getattr(..., None)` compatibility probes in the loader are followed by explicit fail-closed checks; they do not downgrade functionality.

### Mutation retries and replay

No execution/mutation/outcome path contains retry, backoff, or sleep-based replay logic. Counting fakes prove each mutation invokes the typed client exactly once. Unknown outcome remains conservative and non-retry-safe.

### Logging and sensitive payloads

Production MCP code does not log tool arguments/results, Authorization headers, controller token values, typed keyboard text, clipboard text, screenshot bytes/base64, VNC credentials, or raw sensitive controller response bodies.

### Streamable HTTP security

Production server setup does not override `transport_security`. Official SDK Host/Origin/DNS-rebinding protections remain enabled. Legacy SSE is not exposed as a fallback.

### Secret ingress

The only controller token ingress is `VRC_MCP_CONTROLLER_TOKEN_FILE`. No raw controller token environment variable or CLI token option exists.

### Tests and one-call invariant

Dependency-free counting fakes, pinned-SDK tests, transport acceptance, and real-controller E2E all preserve the one-call/no-retry invariant. Test doubles do not authorize a hidden production retry path.

## Intentional ignored/alternate behavior

The reviewed intentional ignored/alternate-result behavior is limited to:

- `ExitStack.pop_all()` transferring cleanup ownership only after successful MCP construction;
- repeated executor `close()` waiting for the first shutdown rather than initiating another shutdown;
- unsafe controller identifiers being intentionally omitted from error metadata rather than echoed;
- documented configuration defaults applying only when optional variables are absent;
- test/E2E diagnostic-capture failures remaining secondary evidence that cannot convert the primary failure into success.

None is a silent-success fallback.

## Permanent regression contract

`tests/test_mcp_unsafe_fallback_contract.py` permanently rejects broad production exception/pass fallbacks, unclassified mapping `.get(...)` growth, raw token ingress, transport-security overrides/legacy SSE, and retry/backoff/sleep APIs in mutation execution/outcome handling.

Existing behavioral tests remain authoritative for exact one-call mappings, payload-free errors, mutation ambiguity, SDK integration, transport security, and real-controller behavior.

## Result

MCP-013 is satisfied on the reviewed source subject to the new closeout candidate passing permanent CI and Release Gates. No unsafe fallback or quiet failure remains unclassified in the reviewed MCP production surface.

## 2026-09-12 cancellation/bounding remediation addendum

A later code review of exact `master` `7b69ad82a6939c9619d8b8a0b9146c005bf6889e` found two classes of behavior that the original MCP-013 audit did not cover:

1. post-admission task cancellation could abandon the asyncio wrapper while the synchronous controller call continued, allowing a later worker exception to become `Future exception was never retrieved`; and
2. the typed Python HTTP client used unrestricted response-body reads before MCP screenshot-size validation.

The original 2026-09-11 audit conclusions remain historical evidence for the scope reviewed then, but its statement that no production behavior defect existed is superseded for current `master` by `docs/VNC_REMOTE_CONTROL_SERVER_MCP_CANCELLATION_AND_BOUNDING_REMEDIATION_TODO_2026-09-12.md`.

The remediation extends the audit to `asyncio.shield`, `asyncio.wrap_future`, cancellation propagation, done callbacks, executor-owned future lifetimes, shutdown races, default event-loop exception diagnostics, and controller response ingestion. The fixed executor transfers terminal-observation ownership to a non-logging done callback before post-admission cancellation escapes; mutation cancellation is conservatively classified as unknown/non-retry-safe; read cancellation remains cancellation while its worker result is drained. The typed client now bounds JSON, screenshot, metrics, and error bodies while reading them.

Permanent regression coverage is provided by `tests/test_mcp_cancellation_contract.py`, `tests/test_python_response_bounds.py`, the extended `tests/test_mcp_execution.py`, and the extended `tests/test_mcp_unsafe_fallback_contract.py`. These tests also prove sensitive payloads are absent from cancellation cleanup diagnostics and that no retry/replay path was introduced.

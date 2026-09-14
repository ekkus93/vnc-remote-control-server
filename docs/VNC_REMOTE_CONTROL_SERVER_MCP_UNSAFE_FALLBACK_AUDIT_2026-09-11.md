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

## 2026-09-14 fail-closed boundary reconciliation addendum

A fresh Ralph Bridge re-audit of exact `master` `4371f1f30c11c7bc72237bc9cf842ebaf04de354` compared current source directly against stale PR #41 and found three additional production boundary defects that the historical MCP-013 audit and the 2026-09-12 cancellation/bounding remediation had not closed:

1. `_run_configured_transport()` revalidated neither the injected transport nor HTTP bind values immediately before SDK dispatch and implicitly treated every non-`stdio` transport as Streamable HTTP;
2. unknown `VRC_MCP_*` environment variables were silently ignored, allowing typos or raw-token-shaped aliases to create a quiet configuration mismatch; and
3. `McpOutcomeToolRegistrar` accepted caller-supplied mutation validation exception classes without preventing broad built-in classes from widening handled-failure classification.

These defects were fixed through PR #50 rather than by merging stale PR #41 wholesale. Current production code now revalidates transport/host/port at final dispatch, rejects unknown MCP-prefixed environment names using a closed vocabulary, and accepts only application-specific `ValueError` subclasses for dynamic mutation validation classification. Permanent behavioral coverage is in `tests/test_mcp_fail_closed_boundaries.py`.

The exact final PR candidate `4d0689405f34d068fced58cd8af793007a433599` passed CI `34872815462` and Release Gates `34872815475`. PR #50 was squash-merged to exact `master` `c3748230acc6f375ba274e999f85a17ee0be3cda`, which passed fresh CI `34873573103`, Release Gates `34873573179`, and Publish CI Status `34873575943`, including production MCP/TigerVNC E2E and R13 Compose integration/E2E.

The authoritative detailed reconciliation is `docs/VNC_REMOTE_CONTROL_SERVER_MCP_FAIL_CLOSED_RECONCILIATION_2026-09-14.md`. Historical statements above that no production behavior defect remained are preserved as evidence of the conclusions reached on their exact reviewed generations, but are superseded for current `master` by the 2026-09-12 and 2026-09-14 addenda.

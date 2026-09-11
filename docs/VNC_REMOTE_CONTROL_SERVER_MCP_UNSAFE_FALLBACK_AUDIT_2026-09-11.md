# VNC Remote Control Server — MCP unsafe-fallback and silent-failure audit

Date: 2026-09-11

Tracked task: `MCP-013` in `docs/VNC_REMOTE_CONTROL_SERVER_MCP_TODO_2026-09-02.md`

Reviewed baseline: `master` at `0da2324f89fa72933486fcb6e59e26d7c4bf8880`

## Scope

The audit reviewed the production MCP modules under `python/src/vnc_remote_control/mcp_*.py`, the MCP configuration/execution/read/mutation/outcome/server paths, their dependency-free contract tests, pinned-SDK tests, transport acceptance tests, and the real controller/TigerVNC MCP E2E. The existing permanent CI evidence on the reviewed baseline is CI `34147921952` and Release Gates `34147921940`, both successful on the same exact SHA.

No production behavior defect was found during MCP-013. The audit therefore adds a permanent static regression contract rather than inventing a compatibility fallback or changing already validated runtime semantics.

## MCP-013 conclusions

### Broad exception handling and false success

Production MCP code has no bare `except`, no `except Exception`, no `except BaseException`, and no `pass` fallback. Exception handling is typed and purpose-specific. The outcome registrar converts only the enumerated typed controller/adapter errors into native MCP error results (`is_error=true`); it does not convert failures into empty or successful output.

`BoundedControllerExecutor` obtains worker exceptions from the completed future and preserves typed `VncRemoteControlError` failures. Untyped worker failures become `McpUnexpectedControllerError` with fixed payload-free text. `aclose()` catches only `asyncio.CancelledError` so adapter-owned worker shutdown completes before cancellation is re-raised.

### Mapping defaults and compatibility probes

The only production `Mapping.get` calls are intentional and fail closed:

- `environment.get(name)` distinguishes an absent optional environment variable from a present value. Present malformed or empty values are validated explicitly rather than replaced with defaults.
- `registration.get("annotations")` and `registration.get("name")` inspect MCP tool registration metadata. Missing/invalid values immediately raise `McpOutcomeRegistrationError`; there is no guessed annotation or name.

The SDK loader uses `getattr(..., None)` only to verify the exact pinned `mcp==2.1.1` callable surface. A missing/incompatible symbol raises `McpDependencyError`; it does not probe alternate SDK APIs, downgrade transports, fabricate image output, or continue with reduced behavior. The screenshot image helper is similarly required to expose `to_image_content`; absence is an explicit protocol/dependency failure.

### Mutation replay and retry

No production MCP retry, backoff, or sleep mechanism exists around controller mutations. Every mutation handler performs complete local preflight and then calls the shared executor exactly once. Existing mutation tests count both executor and typed-client invocations for every mutation and prove controller failures are not automatically replayed. Outcome-classification tests prove known-command ambiguity instructs caller-driven `vnc_get_command_status` inspection and no-command-ID ambiguity is `retry_safe=false`.

The real MCP/TigerVNC E2E also issues each mutation once. Its polling loops are read-only observation after a single mutation; they never replay a mutation.

### Sensitive logging

Production MCP logging is limited to fixed diagnostic text plus reviewed non-payload tool names. Existing tests inject sensitive sentinels into worker errors, API messages, typed text, clipboard values, and screenshot data and prove they do not appear in MCP diagnostic text. The real E2E audits MCP/controller logs for the bearer token, VNC password, typed text, and clipboard fixtures and fails if any appear.

No production MCP logger records tool arguments, tool results, Authorization headers, bearer-token bytes, typed text, clipboard text, or screenshot bytes/base64.

### Transport security

Streamable HTTP accepts only `127.0.0.1`, `localhost`, or `::1`, the exact loopback spellings for which the pinned SDK enables its DNS-rebinding protection. The adapter deliberately does not supply `transport_security`, so the SDK Host/Origin policy remains authoritative. Legacy SSE is not exposed as a fallback.

Pinned-SDK transport acceptance proves stdio and Streamable HTTP catalog/schema/annotation equivalence, read invocation, explicit mutation opt-in, exactly-one mutation mapping, bad Host/Origin rejection, EOF shutdown for stdio, and bounded SIGTERM shutdown for HTTP.

### Secret ingress

The controller token has one MCP ingress: `VRC_MCP_CONTROLLER_TOKEN_FILE`. No raw token environment variable, CLI argument, URL credential, source constant, or fallback token source exists. Configuration tests explicitly prove `VRC_MCP_CONTROLLER_TOKEN` is not accepted as a source and secret values do not appear in errors or repr output.

### Test-double review

The dependency-free read and mutation test executors call the supplied synchronous operation exactly once while recording the boundary. Mutation tests separately record every fake typed-client call and verify the complete ten-tool catalog maps one handler invocation to one controller-client invocation. The pinned-SDK outcome tests and official-client transport acceptance tests independently cover the real SDK wrapper layer, so the one-call/no-retry invariant is not dependent on a permissive mock alone.

### Intentional ignored/alternate-result behavior

No correctness-sensitive production result is silently ignored. The reviewed exceptions are:

- construction uses `ExitStack.pop_all()` only after successful server/tool registration to transfer executor cleanup ownership to the MCP lifespan;
- repeated executor `close()` waits for the first shutdown rather than starting another shutdown;
- sanitized unsafe controller identifiers are intentionally omitted from error metadata instead of echoed;
- missing optional config values use documented defaults, while present invalid values fail closed;
- test/E2E diagnostic-capture failure is secondary evidence only: the primary test failure remains authoritative and teardown failure independently forces nonzero exit.

These are not silent-success fallbacks.

## Permanent regression contract

`tests/test_mcp_unsafe_fallback_contract.py` makes the audit mechanically persistent. It fails CI if production MCP code introduces:

- a bare or generic `Exception`/`BaseException` handler;
- an AST `pass` fallback;
- a new unclassified `.get(...)` use;
- raw `VRC_MCP_CONTROLLER_TOKEN` ingress;
- a `transport_security=` override or legacy SSE transport;
- a retry/backoff/sleep call in execution, mutation, or outcome handling.

Existing behavioral tests remain authoritative for exact one-call mappings, payload-safe logging, pinned-SDK compatibility failure, transport security, and real-controller E2E semantics.

## Result

MCP-013 is satisfied on the reviewed source subject to the new closeout candidate passing permanent CI and Release Gates. No unsafe fallback or quiet failure remains unclassified in the reviewed MCP production surface.

# VNC Remote Control Server — MCP-013 Unsafe-Fallback and Silent-Failure Audit

**Date:** 2026-09-07  
**Audit base:** exact `master` SHA `0da2324f89fa72933486fcb6e59e26d7c4bf8880`  
**Working branch:** `ralph/mcp-013-unsafe-fallback-audit-20260907`  
**Authoritative MCP specification:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_SPEC_2026-09-02.md`  
**Authoritative MCP TODO:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_TODO_2026-09-02.md`

This audit is deliberately fail-closed. A pattern is not accepted merely because current tests happen to pass. Broad exception handling, compatibility fallbacks, ignored failures, mutation replay, sensitive logging, permissive transport security, and raw-secret ingress are treated as defects unless the behavior is both bounded and explicitly justified.

## Scope

The source audit covers every MCP adapter module:

- `python/src/vnc_remote_control/mcp_config.py`
- `python/src/vnc_remote_control/mcp_execution.py`
- `python/src/vnc_remote_control/mcp_mutation_tools.py`
- `python/src/vnc_remote_control/mcp_outcomes.py`
- `python/src/vnc_remote_control/mcp_server.py`
- `python/src/vnc_remote_control/mcp_tools.py`

The test audit covers every `tests/test_mcp*.py` contract, including the official-SDK stdio/Streamable HTTP acceptance suite, plus the real `tests/mcp_e2e.py` / `tests/mcp-e2e/run.sh` harness and its permanent CI invocation. The typed controller client is inspected where MCP outcome semantics depend on its error contract, but unrelated optional client features are not reclassified as MCP adapter behavior.

## Findings corrected by MCP-013

### F1 — Invalid transport objects could fall through to Streamable HTTP

Before this audit, `_run_configured_transport()` used `if transport == "stdio": ... return` followed by the Streamable HTTP call. The production `McpConfig.load()` path accepts only `stdio|streamable-http`, but a bypassed/injected `McpConfig` object with any other transport value reached the HTTP branch. This was an implicit network-transport fallback and was not acceptable as a defense-in-depth boundary.

Correction:

- centralize runtime transport/host/port validation in `validate_mcp_transport_configuration()`;
- invoke that validation both during environment loading and immediately before `server.run()`;
- retain an explicit `streamable-http` vocabulary check instead of an implicit `else`;
- add regressions proving invalid transport, non-loopback host, and invalid port never call the SDK runner.

### F2 — Unknown `VRC_MCP_*` variables were silently ignored

Before this audit, supported variables were read individually. An unknown MCP-prefixed key—including `VRC_MCP_CONTROLLER_TOKEN`—was ignored if the required token-file variable was also valid. The raw token was not used, so this was not a secret-ingress bypass, but it was a silent configuration failure that could mislead an operator about which security-sensitive setting was active.

Correction:

- define the complete current `VRC_MCP_*` environment vocabulary;
- reject any unknown MCP-prefixed variable before reading configuration values;
- keep unrelated process environment variables allowed;
- add a regression proving `VRC_MCP_CONTROLLER_TOKEN` fails even when a valid token file exists, without echoing the raw secret value;
- record the closed environment vocabulary in this audit and enforce it with a permanent regression contract.

### F3 — Dynamic validation exception registration could theoretically widen a catch

`McpOutcomeToolRegistrar` catches `self._handled_errors`, which is intentionally a tuple of typed controller/adapter errors plus the supplied mutation preflight error classes. Production construction supplies only `McpMutationValidationError`, but the constructor previously did not reject a future caller supplying the literal base `Exception` class.

Correction:

- reject `Exception`, `BaseException`-like/non-`Exception` types, and non-type values from the mutation-validation class tuple;
- keep the dynamic handler narrow by construction;
- add a regression proving `mutation_validation_errors=(Exception,)` is rejected.


## Exception-handler census

There are no bare `except:` blocks and no literal `except Exception`/`except BaseException` blocks in the MCP modules. `tests/test_mcp_safety_audit_contract.py` preserves that invariant structurally.

| Module | Handler | Classification / rationale |
|---|---|---|
| `mcp_config.py` | `ValueError` around typed-client URL/timeout and token validation | Converts only the typed client's local validation failure into payload-free `McpConfigError`; no request is issued. |
| `mcp_config.py` | `UnicodeEncodeError` | Detects non-UTF-8-representable environment values and fails configuration. |
| `mcp_config.py` | `ValueError` around float parsing | Rejects malformed timeout input; invalid input is never defaulted. |
| `mcp_config.py` | `OSError` around secret metadata/open/read | Converts filesystem failures into secret-byte-free config errors. |
| `mcp_config.py` | `UnicodeDecodeError` | Rejects non-UTF-8 secret bytes. |
| `mcp_execution.py` | `RuntimeError` around thread-pool submission | Handles only executor-shutdown submission failure, releases the already-reserved slot, and reports pre-request closure. |
| `mcp_execution.py` | `asyncio.CancelledError` during shutdown | Waits for authoritative cleanup to complete and then re-raises cancellation; cancellation is not swallowed. |
| `mcp_mutation_tools.py` | `UnicodeEncodeError` | Rejects invalid clipboard Unicode before controller issuance. |
| `mcp_outcomes.py` | `UnicodeEncodeError` | Omits unsafe untrusted identifier metadata rather than echoing it. It does not convert an operation failure to success. |
| `mcp_outcomes.py` | `self._handled_errors` | Dynamic but narrow: typed controller/adapter failures plus validated narrow preflight exception classes. Literal `Exception` widening is now rejected at construction. Every caught path returns native MCP `is_error=true`. |
| `mcp_server.py` | `ImportError` | Makes missing/broken optional MCP SDK imports an explicit startup failure with the exact install requirement; there is no alternative SDK/version fallback. |
| `mcp_server.py` | `TypeError` around reviewed Pydantic Field calls | Treats SDK schema API incompatibility as explicit dependency failure; no degraded schema is registered. |
| `mcp_server.py` | `(McpConfigError, McpDependencyError)` in `main()` | Prints sanitized startup diagnostics to stderr and exits status 2; it never starts a fallback server. |
| `mcp_tools.py` | `zlib.error` | Converts malformed screenshot compression to payload-free `ProtocolError`; no placeholder image is returned. |
| `mcp_tools.py` | `UnicodeEncodeError` | Rejects unsafe screenshot identifier metadata; malformed metadata never becomes accepted output. |

## `pass`, `.get`, fallback, and ignored-result census

### `pass`

No `pass` statement exists in the production MCP modules. Test protocol fakes contain resource-free `close`/`aclose` methods whose bodies are documentation-only and implicitly return `None`; they do not hide operational cleanup failures because those fakes own no resources.

### `.get`

Only three production MCP `.get` uses survive:

1. `environment.get(name)` in `mcp_config.py`: absence is semantically distinct from an explicitly malformed value; documented defaults apply only when absent. Unknown `VRC_MCP_*` names are now rejected before lookup.
2. `registration.get("annotations")` in `mcp_outcomes.py`: `None` is not accepted; the registrar immediately requires an explicit boolean `read_only_hint`.
3. `registration.get("name")` in `mcp_outcomes.py`: missing/non-string/empty names immediately raise `McpOutcomeRegistrationError`.

None uses `.get(..., permissive_default)` to hide invalid MCP configuration or controller protocol state.

### Attribute/import compatibility probes

`load_mcp_sdk_components()` uses `getattr(..., None)` only to probe the exact pinned SDK API and then requires every probed item to be callable. Missing API surface raises `McpDependencyError`; no legacy class name, import path, transport, schema, or SSE fallback is attempted.

The screenshot helper similarly probes `to_image_content` and raises `ProtocolError` if it is absent; it does not emit base64 JSON or placeholder content as a compatibility path.

### Intentional ignored return values

Every surviving ignored-call result is side-effect/validation oriented and does not discard an operational success/failure signal:

- `mcp_config.py`: `_reject_unknown_mcp_environment`, transport validation, secret-stat validation, UTF-8 encode preflight, and temporary `VncRemoteControlClient(...)` construction are validation-only calls that signal failure by exception.
- `mcp_execution.py`: slot acquire/release, `Event.wait/set`, `ExitStack.close`, shield/wait synchronization, and the cancellation cleanup await are synchronization/cleanup operations; completion is verified by control flow and exceptions are not suppressed.
- `mcp_mutation_tools.py`: annotation updates and catalog registration helpers are side-effect-only. They live inside the `_register` helper whose name/docstring make registration itself the intended effect; validator calls fail by exception before issuance.
- `mcp_outcomes.py`: `dict.update` and fixed-message logger calls are explicit side effects; logger calls never receive exception objects or payload values.
- `mcp_server.py`: runtime validation, cleanup callback registration, tool registration, `ExitStack.pop_all()`, transport `server.run()`, and `main()` are lifecycle side effects. The `pop_all()` site already documents that successful construction transfers executor ownership to the MCP lifespan.
- `mcp_tools.py`: PNG validation/finalization are exception-signaled validation calls. Tool decorator results are used only inside `register_read_only_tools`, whose registration purpose is explicit in the containing function.

No ignored result is used to turn failed cleanup, failed mutation issuance, malformed protocol data, or dependency incompatibility into apparent success.

## Mutation retry/replay audit

All ten mutation controller helpers contain exactly one `runtime.executor.call(...)` and no `for`, `while`, retry, or backoff loop:

- pointer move;
- pointer button transition;
- click;
- double-click;
- vertical scroll;
- keyboard key transition;
- keyboard chord;
- keyboard text;
- clipboard set;
- reconnect request.

The new static audit contract mechanically preserves the one-executor-call/no-loop shape. Existing mutation/outcome tests continue to count client and executor calls, so test doubles do not become evidence for replay behavior they bypass.

## Logging and sensitive-data audit

Production MCP logging exists only in `mcp_outcomes.py`. Every log message is a fixed string; the only interpolated value is the statically registered tool name. Exception objects, exception strings, tool arguments, tool results, Authorization headers, bearer tokens, keyboard text, clipboard text, and screenshot bytes are not passed to logging.

`main()` writes only sanitized `McpConfigError`/`McpDependencyError` text to stderr. Secret-file errors contain path/reason metadata but not secret bytes. The static audit contract rejects MCP logger calls that add arbitrary interpolated objects or keyword options such as `exc_info`.

The real MCP/TigerVNC E2E harness is part of the logging audit. Its MCP child environment carries the controller token **file path** but not the raw token; its forbidden-log fixture set covers the controller token, VNC password, typed-text payload, and outbound clipboard payload; runtime logs and retained failure diagnostics are checked against those values; diagnostic files are sanitized before write; screenshot data is decoded and inspected in memory only; and the shell wrapper uses `set -euo pipefail` without shell tracing. Mutation calls remain single-shot while only read-only state observation is polled.

## Transport-security audit

The Streamable HTTP path:

- accepts only `127.0.0.1`, `localhost`, or `::1`;
- revalidates transport/host/port immediately before calling the SDK runner;
- passes only `transport`, `host`, `port`, and `stateless_http=True`;
- does not pass or construct `transport_security`;
- therefore leaves the pinned SDK's Host/Origin/DNS-rebinding policy authoritative.

The official-SDK acceptance test continues to require HTTP 421 for a hostile Host and HTTP 403 for a hostile Origin. No legacy SSE transport exists.

## Secret-ingress audit

The MCP adapter has no CLI token option and no raw-token environment source. `VRC_MCP_CONTROLLER_TOKEN_FILE` is the only controller-token ingress. MCP-prefixed environment names are now closed-vocabulary, so a raw-token-shaped alias or typo fails startup instead of being ignored.

The token value is never included in `repr`, startup errors, MCP tool results, or logs. Python's inability to guarantee volatile zeroization remains documented separately and is not treated as permission to weaken file-only ingress.

## Test-double audit

The existing `RecordingExecutor`/`ImmediateExecutor` fakes invoke the supplied operation exactly once and record that boundary. Existing tests assert exact executor/client call counts for all mutation handlers and ambiguous outcomes. Independently, `test_mcp_execution.py` exercises the real `BoundedControllerExecutor` and its unexpected-exception normalization. The new structural audit contract inspects the production mutation helpers themselves and requires exactly one `runtime.executor.call(...)` with no loop in every helper, so the one-call/no-retry conclusion does not depend on a permissive fake.

Mocks that bypass filesystem or SDK startup are retained only where the test is specifically about construction metadata or error translation. No mock-based success is treated as proof of a replay path that the production source contract contradicts.

## Optional dependency audit

The core Python package still imports without MCP installed. MCP construction dynamically imports the exact reviewed SDK surface and fails explicitly with `McpDependencyError` if import or required API probing fails. There is no silent feature downgrade, alternate MCP version, alternate import path, or legacy transport fallback.

The core client's separate optional WebSocket dependency behavior is outside the MCP adapter call path: none of the MCP tools call the event-subscription API. It is therefore not used as an MCP dependency fallback.

## Regression enforcement added by this audit

`tests/test_mcp_safety_audit_contract.py` now mechanically guards:

- no production MCP `pass`, bare `except`, literal `except Exception`, or `except BaseException`;
- exactly one executor call and no loops in every mutation helper;
- fixed-message MCP logging with no exception/payload interpolation;
- no Streamable HTTP `transport_security` override;
- no MCP retry/backoff calls;
- the real MCP E2E child uses file-backed token ingress, keeps the sensitive fixture set under redaction audit, and runs without shell tracing.

Behavioral tests additionally guard strict MCP environment vocabulary, runtime transport/bind revalidation, and narrow dynamic outcome-handler configuration.

## Closure status

This document records the implementation audit, not final task closure. MCP-013 should remain unchecked in the authoritative TODO until the exact branch candidate passes permanent CI and Release Gates, is merged deliberately, and the resulting `master` generation is revalidated according to the repository workflow.

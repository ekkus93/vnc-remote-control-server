# VNC Remote Control Server — MCP Cancellation and Bounding Remediation Specification

**Date:** 2026-09-12  
**Repository:** `ekkus93/vnc-remote-control-server`  
**Reviewed master:** `7b69ad82a6939c9619d8b8a0b9146c005bf6889e`  
**Parent MCP specification:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_SPEC_2026-09-02.md`  
**Parent MCP TODO:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_TODO_2026-09-02.md`  
**Parent MCP evidence:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_EVIDENCE_2026-09-02.md`

## 1. Purpose

This specification defines the remediation required for issues discovered during the 2026-09-12 code review of the completed MCP phase.

The MCP architecture, security defaults, supply-chain controls, no-retry design, and most existing checklist items remain valid. This remediation is deliberately narrow. It addresses correctness gaps at asynchronous cancellation boundaries and response-size enforcement without redesigning the MCP architecture or weakening existing gates.

The remediation has four objectives:

1. make cancellation semantics truthful for admitted controller mutations;
2. ensure every admitted executor future has its terminal result or exception observed;
3. enforce response-size bounds while bytes are being ingested from the controller, not only after full materialization;
4. reconcile the original MCP audit/evidence after the defects are fixed and permanently regression-tested.

## 2. Findings being remediated

### 2.1 Post-admission cancellation can hide an uncertain mutation outcome

`BoundedControllerExecutor.call()` currently shields a submitted synchronous worker from cancellation so executor capacity remains reserved until the underlying call exits. That capacity behavior is correct.

However, when the awaiting MCP task is cancelled after the controller call has been admitted/submitted, the caller receives cancellation while the underlying mutation may still complete successfully or fail later.

That creates an outcome ambiguity:

```text
MCP caller
    -> mutation admitted
    -> controller request starts
    -> MCP task cancelled
    -> caller sees cancellation
    -> controller mutation may still succeed
```

A caller may incorrectly infer that the mutation did not execute and retry it. That can duplicate non-idempotent actions such as pointer clicks, keyboard input, clipboard writes, or reconnect requests.

The adapter MUST NOT imply that a post-admission cancellation proves non-execution.

### 2.2 Cancelled worker failures can become unobserved future exceptions

When the awaiting MCP task is cancelled and the underlying worker later raises, the wrapped future may never have its terminal exception consumed.

The observable symptom can be:

```text
Future exception was never retrieved
```

This is incorrect because:

- executor-owned work must have a defined cleanup/observation owner;
- error normalization must not be bypassed accidentally;
- generic asyncio diagnostics must not become a secondary uncontrolled error-reporting channel;
- sensitive controller details must not leak through unobserved-future diagnostics.

### 2.3 Controller HTTP response ingestion is not bounded during read

The typed Python controller client currently performs unrestricted reads such as:

```python
response_body = response.read()
```

and reads error bodies similarly.

For screenshots, the MCP layer later enforces a PNG byte ceiling, but that occurs only after the entire HTTP response has already been allocated in memory.

Therefore a broken, compromised, or misconfigured controller can cause the MCP process to consume an arbitrarily large response before the later size check rejects it.

The transport/client layer MUST enforce bounds while reading bytes.

### 2.4 Final MCP audit/completion evidence must be reconciled

The original MCP phase recorded MCP-003, MCP-005, MCP-007, MCP-013, and MCP-015 as complete based on the behavior and tests known at the time. Those historical validation runs remain factual and MUST NOT be rewritten.

However, the newly discovered defects mean the present-day completion conclusion must be updated after remediation.

The project MUST preserve historical evidence while adding a new remediation evidence trail.

## 3. Non-goals

This remediation MUST NOT:

- add automatic mutation retries;
- add polling-and-replay behavior;
- replace the typed Python controller client;
- bypass the authenticated Rust controller;
- add a second MCP command authority;
- weaken controller-side command semantics;
- weaken CI, Release Gates, VEX, SBOM, Gitleaks, cargo-deny, sanitizer, Miri, or license gates;
- introduce public MCP HTTP binding;
- disable SDK Host/Origin/DNS-rebinding protections;
- add legacy SSE compatibility;
- change mutation capability to enabled-by-default;
- expand the MCP tool catalog except where diagnostic metadata is required to preserve truthful outcome semantics.

## 4. Required invariants

### 4.1 Admission invariant

Before a controller call has been admitted/submitted, cancellation MAY abort it without side effects if the implementation can prove the controller request was never issued.

After admission/submission, cancellation MUST NOT be represented as proof that the side effect did not occur.

### 4.2 Exactly-once adapter invocation invariant

The MCP adapter MUST invoke the typed controller client at most once for each admitted mutation request.

Cancellation MUST NOT cause the adapter to replay or resubmit a mutation.

### 4.3 Capacity ownership invariant

Cancellation MUST NOT release executor capacity before the underlying synchronous controller call actually reaches a terminal state.

The existing bounded-admission behavior MUST be preserved.

### 4.4 Terminal future observation invariant

Every admitted executor future MUST have exactly one owner responsible for observing its terminal result or exception.

No supported cancellation path may leave a future that can produce:

```text
Future exception was never retrieved
```

### 4.5 Unknown-outcome invariant

If the adapter cannot prove whether a post-admission mutation executed, the externally visible result MUST remain conservative:

```text
outcome = "unknown"
retry_safe = false
```

If a trustworthy controller command ID exists, it MUST be preserved and the caller MUST be directed to inspect command status.

If no trustworthy command ID exists, the adapter MUST NOT fabricate one.

### 4.6 Sensitive-data invariant

Cancellation cleanup, background callbacks, logging, exception-draining code, and oversized-response handling MUST NOT log or expose:

- Authorization headers;
- bearer-token contents;
- controller token file contents;
- typed keyboard text;
- clipboard payloads;
- screenshot bytes/base64;
- raw sensitive controller response bodies;
- VNC credentials.

### 4.7 Bounded-ingestion invariant

All controller response-body reads used by the MCP path MUST have explicit byte ceilings enforced while reading.

A declared `Content-Length` MAY be used for early rejection but MUST NOT be trusted as the sole bound.

The client MUST detect bodies that exceed the configured/constant bound even when:

- `Content-Length` is absent;
- `Content-Length` is incorrect;
- transfer encoding is chunked;
- the server sends one extra byte beyond the allowed maximum.

## 5. Cancellation semantics

### 5.1 Required state distinction

The implementation MUST distinguish at least these states:

1. **not admitted / not submitted**
2. **admitted and running**
3. **terminal success**
4. **terminal typed failure**
5. **terminal unexpected failure**

A cancellation request may occur in any state.

### 5.2 Cancellation before admission

If cancellation occurs before controller work is submitted, the operation may terminate as cancellation because the adapter can prove the controller request was never issued.

Tests MUST prove zero underlying client calls occurred.

### 5.3 Cancellation after admission

Once work is admitted, the adapter MUST preserve truthful outcome semantics.

Acceptable implementation strategies include, but are not limited to:

- continuing to await the underlying call in a cancellation-safe scope until a terminal controller outcome is available;
- converting cancellation into a structured conservative unknown-outcome result once admission is known;
- using a dedicated lifecycle object that retains responsibility for the submitted future and safely maps its terminal result.

The implementation MUST choose one explicit strategy and document it.

It MUST NOT simply abandon the future and propagate raw `CancelledError` while the controller mutation continues invisibly.

### 5.4 Read-only calls

Read-only calls do not carry mutation replay risk, but their futures still MUST be terminally observed and capacity-safe.

The implementation MAY use simpler cancellation semantics for reads if:

- no unobserved future exception is possible;
- capacity ownership remains correct;
- no sensitive diagnostics leak;
- read errors remain correctly classified.

## 6. Executor remediation requirements

`BoundedControllerExecutor` or its replacement MUST:

- reserve capacity before submission;
- reject or fail fast when saturated according to existing policy;
- run synchronous controller calls outside the MCP event loop;
- retain capacity until the worker exits;
- observe every worker terminal result/exception;
- avoid duplicate callbacks/cleanup;
- be safe if cancellation races with completion;
- be safe if `close()` races with completion;
- preserve bounded shutdown;
- preserve no-retry/no-replay semantics.

A helper callback that drains a future is acceptable only if it does not create a second semantic consumer and does not bypass structured mutation classification.

## 7. Controller response-size limits

### 7.1 General approach

The typed Python client MUST replace unrestricted response-body reads on MCP-reachable paths with bounded reads.

A recommended primitive is:

```text
read at most MAX_BYTES + 1
if bytes_read > MAX_BYTES:
    fail closed
```

The exact implementation may use another mechanism if equivalent behavior is proven by tests.

### 7.2 Screenshot response

The screenshot response-body ceiling MUST be enforced before the full PNG is materialized beyond the allowed size.

The existing PNG structural/decompression validation MUST remain in place after transport-level bounding.

The transport-level limit and MCP screenshot PNG limit MUST be intentionally related and documented.

### 7.3 JSON/controller responses

JSON response bodies MUST have an explicit maximum size suitable for the controller's documented response schemas.

The limit MUST be high enough for valid status, display, clipboard metadata, command status, and other normal API payloads, but finite.

### 7.4 Metrics/text responses

Metrics/text endpoints MUST have finite explicit limits.

Existing controller-side bounds do not eliminate the client-side requirement because the MCP adapter must fail safely against a malfunctioning or compromised peer.

### 7.5 Error bodies

HTTP error response bodies MUST also be bounded.

An oversized error response MUST result in a sanitized local error classification without retaining or echoing the complete body.

## 8. Error taxonomy

The remediation MUST preserve existing error taxonomy wherever possible.

New/changed errors MUST be classified deliberately.

Expected categories include:

- pre-admission cancellation;
- post-admission mutation unknown outcome;
- controller transport error;
- controller protocol error;
- command outcome unknown;
- response body too large;
- malformed screenshot/PNG;
- unexpected adapter failure.

No newly added category may imply replay safety unless it can prove the request was not issued.

## 9. Regression test requirements

### 9.1 Executor cancellation matrix

Permanent tests MUST cover:

- cancel before admission -> zero controller calls;
- cancel after admission -> worker succeeds;
- cancel after admission -> worker raises typed transport error;
- cancel after admission -> worker raises protocol error;
- cancel after admission -> worker raises unexpected exception;
- cancellation races with worker completion;
- cancellation races with executor shutdown;
- capacity remains occupied until worker termination;
- capacity returns exactly once after termination;
- no `Future exception was never retrieved`;
- no duplicate underlying call.

### 9.2 Mutation cancellation matrix

At least one real mutation wrapper MUST be exercised through the actual MCP mutation handler path.

The suite MUST prove:

- exactly one typed-client mutation call;
- post-admission cancellation never implies safe replay;
- known command IDs remain usable when available;
- no fabricated command ID;
- unknown outcome is explicit when required;
- typed text/clipboard payloads are absent from diagnostics.

Representative mutation coverage SHOULD include at least one pointer/click action and one payload-bearing mutation such as keyboard text or clipboard.

### 9.3 Read cancellation matrix

Tests MUST prove read-only cancellation does not:

- leak capacity;
- create unobserved future errors;
- convert read errors into mutation-unknown errors.

### 9.4 Bounded HTTP-body tests

Tests MUST cover:

- body exactly at limit;
- body one byte over limit;
- absent `Content-Length`;
- dishonest small `Content-Length`;
- oversized chunked/streamed response where practical;
- oversized error response;
- screenshot body over limit;
- valid screenshot at limit-compatible size;
- bounded JSON response;
- bounded metrics/text response.

Tests SHOULD use deterministic local fakes and MUST NOT require internet access.

## 10. Unsafe-fallback and silent-failure audit extension

The MCP unsafe-fallback audit MUST be reopened with explicit attention to asynchronous ownership.

The new audit MUST search/review:

- `asyncio.shield`;
- `asyncio.wrap_future`;
- executor-submitted futures;
- cancellation handlers;
- done callbacks;
- abandoned task/future paths;
- `CancelledError`;
- background cleanup;
- exception-draining logic;
- shutdown races;
- logging from asyncio default exception handlers;
- any callback that catches/ignores exceptions.

Every intentional ignored terminal result MUST have a nearby rationale and a regression proving it cannot hide a controller failure or leak sensitive data.

## 11. Documentation requirements

`docs/MCP_SERVER.md` MUST document:

- pre-admission versus post-admission cancellation semantics;
- why an admitted mutation cannot be assumed not to have executed;
- the continued no-retry/no-replay rule;
- command-status recovery when a trustworthy command ID exists;
- response-body limits at the client boundary;
- behavior for oversized controller responses.

The root README/operator/security docs need updates only if their existing text becomes materially inaccurate.

## 12. Original MCP TODO/evidence reconciliation

The original MCP records MUST remain historically truthful.

Do NOT delete prior green CI run IDs or rewrite them as failures.

Instead:

- append a remediation note to affected MCP sections;
- mark present-day affected conclusions as reopened or superseded where appropriate;
- identify the new remediation TODO as the authority for the newly discovered issues;
- preserve old candidate/master evidence as historical validation of those exact generations;
- update the final completion declaration only after remediation is validated.

Affected original sections are at least:

- MCP-003
- MCP-005
- MCP-007
- MCP-013
- MCP-015

MCP-014 historical exact-generation evidence remains valid as historical evidence.

## 13. CI and Release Gates

Before merge, one exact candidate SHA MUST pass:

- regular CI;
- Release Gates.

The exact candidate validation MUST include:

- Python compile/lint/type checks;
- dependency-free core-client test path;
- MCP unit/contract tests;
- new cancellation regressions;
- bounded response regressions;
- stdio transport acceptance;
- Streamable HTTP acceptance;
- production MCP -> controller -> TigerVNC E2E;
- R13 integration;
- supply-chain/license inventory;
- Gitleaks;
- cargo-deny;
- sanitizer/Miri gates;
- Trivy/SBOM/VEX enforcement.

If any fix changes the candidate SHA, both workflows MUST run again on the new exact SHA.

## 14. Merge and post-merge validation

Merge only through the repository's policy-approved guarded merge path.

After merge:

1. record exact merged `master` SHA;
2. require fresh regular CI on that SHA;
3. require fresh Release Gates on that SHA;
4. investigate every failure;
5. do not rerun a deterministic code/test failure without root-cause analysis;
6. update final evidence only after exact merged-master validation is green.

## 15. Acceptance criteria

The remediation is complete only when all of the following are true:

- no admitted executor future can become unobserved;
- no supported cancellation path emits `Future exception was never retrieved`;
- post-admission mutation cancellation never falsely implies non-execution;
- no mutation is automatically retried or replayed;
- exactly-one underlying mutation call is preserved;
- capacity remains reserved until the worker actually exits;
- screenshot/controller response ingestion is bounded during read;
- oversized success and error bodies fail closed;
- no sensitive data leaks through cleanup or cancellation diagnostics;
- permanent regression tests cover the new failure modes;
- the extended unsafe-fallback audit is complete;
- living documentation reflects the final behavior;
- original MCP evidence is reconciled without rewriting history;
- exact candidate CI and Release Gates pass;
- guarded merge succeeds;
- exact merged-master CI and Release Gates pass;
- final remediation evidence is recorded.

## 16. Stop conditions

The Ralph loop MUST stop and require explicit user input if any of these occur:

- the required cancellation semantics cannot be expressed without changing public MCP protocol/tool behavior in a materially incompatible way;
- a fix would require weakening an existing security/release gate;
- a fix would require automatic replay of an uncertain mutation;
- the controller API lacks enough information to preserve truthful mutation outcome semantics and a protocol-level change is required;
- a new secret ingress path would be necessary;
- external infrastructure credentials or operator action are required.

Otherwise the Ralph loop should continue until all remediation tasks are implemented, validated, merged, and reconciled.

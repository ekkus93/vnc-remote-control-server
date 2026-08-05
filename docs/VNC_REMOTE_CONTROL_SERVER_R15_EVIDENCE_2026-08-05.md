# VNC Remote Control Server — R15 Evidence

Date: 2026-08-05
Milestone: R15 — README, operator docs, and API docs
Repository: `ekkus93/vnc-remote-control-server`
Branch: `master`

## Result

R15 is implemented and validated. The repository now contains an accurate top-level README, a complete operator guide, an OpenAPI 3.1 HTTP contract, a separate WebSocket event contract, permanent documentation parity tests, and real-controller validation of the published curl examples.

No branch or pull request was created.

## Product commits and clean head

- Operator guide commit: `8eb2b2eb832359e30be2b8072eca220ac13d3903`
- Validated README/OpenAPI/curl-test product commit: `d913218f12bf91477f2306c15dbd281fb3f0ca54`
- Clean head after temporary R15 payload and executor removal: `e55bf28d4dd90259b1c43f90135577393545b150`

## Permanent deliverables

- `README.md`
  - current product boundary and status;
  - Mermaid architecture diagram;
  - prerequisites and quick start;
  - documentation index and security boundaries.
- `docs/OPERATOR_GUIDE.md`
  - product/trust boundary;
  - deployment architecture and prerequisites;
  - secret generation and file-permission rationale;
  - disposable, persistent, and loopback-debug modes;
  - API binding and TLS/reverse-proxy expectations;
  - health/readiness, authenticated API, screenshot, input, clipboard, reconnect, metrics, and WebSocket examples;
  - asynchronous `202` semantics;
  - shutdown and reconnect behavior;
  - resource limits and tuning;
  - desktop, authentication, controller, readiness, screenshot, and overload troubleshooting.
- `docs/openapi.json`
  - OpenAPI 3.1.0;
  - every HTTP route and method in the Rust router;
  - public health routes and bearer-secured `/v1/*` routes;
  - request and response schemas;
  - stable error/status mappings;
  - screenshot headers, ETag, conditional `304`, and PNG responses;
  - bounded input and clipboard constraints;
  - explicit v0.1 horizontal-scroll rejection;
  - asynchronous accepted-command semantics.
- `docs/WEBSOCKET_EVENTS.md`
  - authentication and upgrade behavior;
  - snapshot and event envelopes;
  - all serialized event types;
  - process-local sequence semantics;
  - bounded buffering, heartbeat, reconnect, and close behavior;
  - payload-redaction guarantees.
- `deploy/README.md`
  - links to the complete operator and machine-readable API documentation.
- `tests/test_documentation_contract.py`
  - exact OpenAPI/router path and method parity;
  - bearer-security coverage;
  - required response and example coverage;
  - operator-topic coverage;
  - WebSocket serialization/documentation parity.
- `tests/http-e2e/run.sh`
  - permanent `R15_DOCUMENTED_CURL_EXAMPLES` scenario against the production controller and real TigerVNC desktop;
  - liveness, status, display, PNG screenshot, pointer, text, clipboard, and rate-limit-aware reconnect examples;
  - accepted-command response validation and payload-redaction checks.

## Fail-closed findings during validation

### Payload transport whitespace

GitHub's contents API introduced line endings between base64 chunks. The executor initially rejected the concatenated payload hash. Reconstruction was corrected to remove only ASCII whitespace before checking the immutable normalized payload hash and the decompressed script hash.

### WebSocket snapshot label

The documentation contract required every serialized event type to appear explicitly. The initial WebSocket guide described the snapshot but did not label the heading with backticked `snapshot`. The guide was corrected; no serializer or test was weakened.

### Manual reconnect rate limit

The HTTP E2E already performs a manual reconnect during WebSocket lifecycle validation. The later documented reconnect curl initially received the correct `429 reconnect_rate_limited` response because it ran inside the configured two-second admission interval. The test now waits 2.1 seconds before validating the standalone curl example. The controller's rate limit remained unchanged.

## Focused R15 validation

Workflow: `Complete R15 Documentation`
Run: `31009207323`
Job: `92316720636`
URL: https://github.com/ekkus93/vnc-remote-control-server/actions/runs/31009207323
Conclusion: `success`

Validated before the product commit:

- both immutable payload hashes;
- OpenAPI JSON syntax;
- focused R15 documentation contracts;
- the full Python/workflow contract suite;
- first-party shell syntax;
- whitespace correctness;
- all documented curl examples against the production controller binary and real TigerVNC desktop.

## Ordinary clean-head CI

Workflow: `CI`
Run: `31009513801`
URL: https://github.com/ekkus93/vnc-remote-control-server/actions/runs/31009513801
Head SHA: `e55bf28d4dd90259b1c43f90135577393545b150`
Conclusion: `success`

Jobs:

- Repository quality gates: `92317766142` — `success`
- Secured Debian desktop and native adapter: `92317766230` — `success`

The clean-head run passed:

- Rust formatting;
- Clippy for all targets/features with warnings denied;
- all Rust tests;
- rustdoc with warnings denied;
- Python compilation;
- all Python/workflow contracts, including R15 documentation parity;
- shell syntax;
- desktop image smoke;
- native adapter smoke;
- WorkerHandle input E2E;
- text and clipboard E2E;
- authenticated HTTP/WebSocket E2E, including the published R15 curls;
- controller image, Compose, and persistence smoke;
- R13 lifecycle/integration E2E.

CI evidence artifact:

- Name: `ci-evidence-31009513801`
- Artifact ID: `8931824284`
- Digest: `sha256:956622a8c89a3c15ac36c525adcb200cd02b1539fcfc34b60a1b30d3291d0138`
- Head SHA: `e55bf28d4dd90259b1c43f90135577393545b150`

## Acceptance conclusion

Every R15.1 and R15.2 checklist item has a permanent implementation and executable evidence. Documentation is checked against the Rust router and event serialization, and the principal curl examples execute against the real controller/TigerVNC stack. R15 is ready to be marked complete in the authoritative rebased TODO.

# VNC Remote Control Server — MCP Server Evidence

**Specification date:** 2026-09-02  
**Closeout date:** 2026-09-11  
**Specification:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_SPEC_2026-09-02.md`  
**TODO:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_TODO_2026-09-02.md`  
**Unsafe-fallback audit:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_UNSAFE_FALLBACK_AUDIT_2026-09-11.md`

This file is the final evidence record for MCP-001 through MCP-015. Checkboxes are closed from source, tests, workflow configuration, documentation, and exact-generation CI evidence; commit messages alone are not acceptance evidence.

## 1. Baseline and prerequisite

The MCP phase started from repository `master` SHA `e3a719600b03b5622ceec9e013dfc9ef94c12702`; the dated MCP specification was committed at `b454c754291a950a6d21ede9dd9594e5e45530`.

The prerequisite Code Review Remediation V2 phase is complete. Its authoritative validated implementation generation is `4956a624be10ddb4b23aa23bcea23560b9c13a24`, with CI `33666006266` and Release Gates `33666005936` both successful. V2 explicitly released the prior MCP deferral only after all V2-R0 through V2-R10 requirements were reconciled.

## 2. Final architecture and authority boundary

The implemented path is:

```text
MCP host/client
    -> stdio or loopback Streamable HTTP
vnc-remote-control-mcp
    -> typed VncRemoteControlClient
authenticated Rust controller HTTP API
    -> bounded controller worker
LibVNCClient adapter
    -> isolated/project-owned TigerVNC desktop
```

The MCP adapter is deliberately thin. It does not speak RFB directly, bypass bearer authentication, reach into Rust worker state, or create a second command authority. Existing controller validation, queueing, command-outcome, reconnect, framebuffer, clipboard, and input-safety semantics remain authoritative.

## 3. SDK and protocol target

The reviewed optional dependency is exactly `mcp==2.1.1`, declared in `python/pyproject.toml` and enforced by source/runtime contracts. The implementation target from the dated specification is MCP protocol generation `2026-07-28` through the official Python MCP SDK v2.

Missing or incompatible SDK APIs fail explicitly with `McpDependencyError`; there is no alternate-SDK compatibility probe that silently degrades functionality.

## 4. Tool catalog and annotations

Read-only tools are always present:

- `vnc_get_status`
- `vnc_get_display`
- `vnc_get_screenshot`
- `vnc_get_clipboard`
- `vnc_get_command_status`
- `vnc_get_metrics`

The mutation catalog is absent by default and appears only with explicit `VRC_MCP_ALLOW_MUTATIONS=true`:

- `vnc_move_pointer`
- `vnc_set_pointer_button`
- `vnc_click_pointer`
- `vnc_double_click_pointer`
- `vnc_scroll_pointer`
- `vnc_set_keyboard_key`
- `vnc_send_keyboard_chord`
- `vnc_type_keyboard_text`
- `vnc_set_clipboard`
- `vnc_request_reconnect`

Read tools carry `readOnlyHint=true`, `destructiveHint=false`, and `idempotentHint=true`; open-world is true only for desktop-derived screenshot/clipboard content and false for the remaining read tools. Mutation tools conservatively use `readOnlyHint=false`, `destructiveHint=true`, `idempotentHint=false`, and `openWorldHint=true`.

Contract tests prove every mutation maps to exactly one typed-client call. Screenshot output is native MCP image content rather than JSON/base64 text.

## 5. Configuration, bounds, and capability default

The final configuration contract is:

| Variable | Default | Accepted value / bound |
|---|---|---|
| `VRC_MCP_CONTROLLER_URL` | `http://127.0.0.1:8080` | validated controller base URL; credentials/query/fragment rejected |
| `VRC_MCP_CONTROLLER_TOKEN_FILE` | required | validated regular secret file |
| `VRC_MCP_CONTROLLER_TIMEOUT_SECONDS` | `5.0` | finite `0.1..=60.0` seconds |
| `VRC_MCP_ALLOW_MUTATIONS` | `false` | exactly `0`, `1`, `false`, or `true` |
| `VRC_MCP_MAX_CONCURRENT_CALLS` | `8` | integer `1..=64` |
| `VRC_MCP_TRANSPORT` | `stdio` | exactly `stdio` or `streamable-http` |
| `VRC_MCP_HTTP_HOST` | `127.0.0.1` | exactly `127.0.0.1`, `localhost`, or `::1` |
| `VRC_MCP_HTTP_PORT` | `8765` | integer `1..=65535` |

Mutation capability is disabled by default. Invalid present values fail closed rather than falling back to defaults.

All controller calls share one adapter-owned bounded executor/admission limit. Admission happens before worker submission so work cannot accumulate in an unbounded executor queue. Cancellation does not free capacity before an already-running synchronous controller call exits.

## 6. Controller-token secret policy and Python memory limitation

The sole MCP controller-token ingress is `VRC_MCP_CONTROLLER_TOKEN_FILE`; no raw token env var, CLI argument, URL credential, source constant, or alternate fallback exists.

The secret reader requires readable metadata and a regular file, size `1..4096` bytes, strict UTF-8, no embedded NUL, and nonempty content after trimming trailing CR/LF only. On POSIX, group/other write bits and all execute bits are rejected. Error text identifies path/reason without echoing token bytes.

Python cannot provide the Rust `SecretString` volatile-zeroization guarantee. The decoded token necessarily exists in ordinary Python objects and may have runtime/HTTP-stack copies. Documentation states this limitation explicitly rather than overstating memory erasure guarantees.

## 7. Mutation outcome and no-retry policy

The adapter contains no automatic mutation retry, replay, or backoff loop.

- terminal success preserves the real controller `command_id` and `status="succeeded"`;
- controller-known ambiguous outcome is `kind="command_outcome_unknown"`, preserves the real command ID, sets `outcome="unknown"` and `retry_safe=false`, and instructs the caller to inspect `vnc_get_command_status(command_id)`;
- ambiguity without a trustworthy command ID is `kind="mutation_outcome_unknown"`, `command_id=null`, `outcome="unknown"`, and `retry_safe=false`;
- authoritative accepted-command failure remains failed and is not retried;
- read-only transport/protocol failures remain read errors rather than mutation ambiguity.

Counting fakes, pinned-SDK tests, transport acceptance, and real-controller E2E independently prove exactly-one mutation invocation and no automatic replay.

## 8. Transport validation

### stdio

The default executable transport is stdio. Official-SDK client acceptance proves tool discovery, read invocation, mutation-disabled default, explicit mutation opt-in, exactly-one mutation mapping, protocol-only stdout, and clean EOF-driven shutdown.

### Streamable HTTP

The HTTP transport is explicit, loopback-only, and stateless. Production configuration accepts only `127.0.0.1`, `localhost`, and `::1`. The adapter does not provide a `transport_security` override, so the official SDK Host/Origin/DNS-rebinding protections remain authoritative. Acceptance tests prove bad Host and Origin requests are rejected. Legacy SSE is not exposed as a compatibility fallback.

Cross-transport acceptance compares tool names, schemas, and annotations for semantic equivalence.

## 9. Real controller/TigerVNC MCP E2E

Permanent CI runs `tests/mcp-e2e/run.sh` against the production controller and isolated TigerVNC desktop using the official MCP client and file-backed controller token. The E2E proves:

- read-only catalog and mutation absence by default;
- real status/display reads;
- native MCP screenshot content;
- explicit mutation-enabled process;
- pointer/click effects;
- keyboard text effects without payload logging;
- clipboard set/read without payload logging;
- command-status inspection;
- bounded reconnect recovery;
- no raw VNC publication;
- negative controller/tool failure does not become MCP success;
- bounded teardown without leaked test containers/processes.

The final implementation candidate and final validated merged master both passed this permanent E2E.

## 10. Dependency, license, and supply-chain review

The core Python client remains third-party-runtime-dependency-free when installed without the MCP extra.

Release Gates maintain an explicit reviewed CPython 3.12/Linux MCP runtime closure in `security/python-mcp-runtime-policy.json` and `security/python-mcp-runtime-constraints.txt`. The policy freezes 28 exact third-party distributions, including direct `mcp==2.1.1`, and accepts only the reviewed license families MIT, MIT-0, BSD-3-Clause, Apache-2.0, Apache-2.0 OR BSD-3-Clause, and PSF-2.0.

Permanent Release Gates install the closure in an isolated environment, run `pip check`, verify exact package/version/license metadata, and upload the inventory. Existing immutable-action, Gitleaks, cargo-deny, auditable-binary, sanitizer, Miri, Trivy, VEX, and CycloneDX SBOM gates remain enabled; no MCP gate uses `continue-on-error`.

## 11. Unsafe-fallback and silent-failure audit

MCP-013 reviewed all production `mcp_*.py` configuration, execution, read, mutation, outcome, and server paths together with unit/contract, pinned-SDK, transport, and real-controller tests.

No production behavior defect was found. The permanent `tests/test_mcp_unsafe_fallback_contract.py` rejects broad `Exception`/`BaseException` handlers, AST `pass` fallbacks, new unclassified `.get(...)` uses, raw controller-token ingress, transport-security overrides/legacy SSE, and retry/backoff/sleep calls in execution/mutation/outcome handling.

Intentional alternate/ignored-result behavior is limited and documented:

- `ExitStack.pop_all()` transfers executor cleanup ownership only after successful MCP construction;
- repeated executor `close()` waits for the first shutdown rather than starting another;
- unsafe controller identifiers are intentionally omitted from error metadata;
- absent optional configuration uses documented defaults while present invalid values fail closed;
- test/E2E diagnostic-capture failure is secondary evidence only and cannot turn the primary failure into success.

None is a silent-success fallback.

MCP-013 audit checkpoint `5f70bd064c663a00843369f791a2cdf460734737` passed CI `34642850866` and Release Gates `34642850991`.

## 12. Exact-generation validation history

The first reconciled MCP-013/MCP-014 candidate `a20d0522dfb3b8d18d3b7b9fb512132e5fc94f90` passed CI `34643586810` and Release Gates `34643586639` and was merged as `bb4178455a727f7baaebac46a31157f1c3713baa`.

Fresh merged-master validation then exposed a real race-sensitive R13 lifecycle-test defect in CI `34644165866`: during the deliberate desktop restart, the harness could briefly observe the intentionally SIGTERM-stopped old desktop generation (`exit_code=143`) and incorrectly classify it as an unexpected terminal startup failure. Release Gates `34644166258` passed, and the MCP production controller/TigerVNC E2E itself had passed before the R13 failure.

The defect was fixed without weakening ordinary startup health checks. The restart path tolerates only the exact clean intentional stop snapshot (`Status=exited`, `ExitCode=143`, `OOMKilled=false`, empty Docker error) and then delegates to the existing strict health waiter. Unexpected terminal states and unhealthy running states remain fail-closed. Regression tests cover the intended handoff and negative states.

### Final frozen candidate

PR #43 final head:

`446bfcf09a4a69b523b0352ff573f34b5a62dd61`

- CI `34647222799`: **success**
- Release Gates `34647222812`: **success**

The exact CI run passed repository quality gates, core-without-MCP validation, desktop/native/WorkerHandle/HTTP/Compose paths, production MCP controller/TigerVNC E2E, and the previously failing R13 integration/restart/resource validation.

### Final validated merged implementation master

PR #43 was merged through the repository's policy-approved squash path. Exact merged implementation `master`:

`a31e2f3fdf77085292fe65648d8741613f91cb38`

- CI `34658956284`: **success**
- Release Gates `34658956281`: **success**

Both workflows are fresh push runs on that exact SHA. The final master CI again passed the production MCP E2E and R13 restart scenario.

## 13. Final VEX review

`security/trivy-critical-vex.json` currently records:

- `reviewed_at`: `2026-08-31`
- `expires_at`: `2026-09-30`
- tracking issue: `7`

The metadata is unexpired at the 2026-09-11 final validation. Exact final candidate Release Gates `34647222812` and exact merged-master Release Gates `34658956281` both passed `Enforce exact CRITICAL VEX determinations`, so the current image vulnerability inventories match the reviewed determinations. Any expiry, package/version change, unmatched CRITICAL finding, or determination drift remains release-blocking.

## 14. Final documentation-closed master validation

PR #44 added the MCP-015 evidence record and closed the MCP TODO on top of the already validated runtime implementation generation. That documentation-only closeout merged to `master` as:

`3a04e0854468ed036affdf07674e095da7c806a6`

Fresh post-closeout workflows on that exact `master` SHA completed successfully:

- CI `34660215099`: **success**
- Release Gates `34660215186`: **success**

Those workflow IDs are external validation observed after the documentation-closed commit existed and after it merged. They are recorded here as evidence about that generation, not as a claim that the commit could contain future workflow results before the workflows ran.

The distinction is intentional:

- authoritative runtime implementation generation: `a31e2f3fdf77085292fe65648d8741613f91cb38`, validated by CI `34658956284` and Release Gates `34658956281`;
- documentation-closed generation from PR #44: `3a04e0854468ed036affdf07674e095da7c806a6`, validated by CI `34660215099` and Release Gates `34660215186`.

## 15. Final reconciliation and declaration

MCP-001 through MCP-013 were reconciled against current source, permanent tests, living documentation, and workflow configuration before candidate freeze. MCP-014 was then satisfied with exact candidate and exact merged-master CI/Release Gates evidence, including investigation and correction of the R13 failure without weakening a gate. MCP-015 was satisfied by the evidence record added in PR #44, and that documentation-closed generation was subsequently validated by fresh permanent workflows.

No TODO checkbox is closed solely because a commit message claims completion. The acceptance basis is executable source/tests, workflow configuration, documentation contracts, exact GitHub Actions run results, and the explicit audit/evidence records cited above.

The MCP implementation phase is complete. All applicable MCP-001 through MCP-015 requirements are satisfied; the later MCP closeout evidence-correction task changes evidence wording only and does not reopen or change runtime MCP behavior.

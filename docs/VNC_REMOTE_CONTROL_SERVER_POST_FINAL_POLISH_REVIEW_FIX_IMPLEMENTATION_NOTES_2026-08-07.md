# VNC Remote Control Server Post-Final-Polish Review Fix Implementation Notes

Date: 2026-08-07 (implementation resumed and completed 2026-08-08)

Spec: `docs/VNC_REMOTE_CONTROL_SERVER_POST_FINAL_POLISH_REVIEW_FIX_SPEC_2026-08-07.md`

TODO: `docs/VNC_REMOTE_CONTROL_SERVER_POST_FINAL_POLISH_REVIEW_FIX_TODO_2026-08-07.md`

Reviewed code baseline SHA: `b1ce8addc846ef8f55f1ffeab5ecd82bfb9b235b`

Spec planning commit: `9095ecc1d96a010061ca463e05848c11f9e92eaa`

Implementation starting SHA: `c0fa89ebc4e32e64e5a4ed0d701f139b905e12f8`

Status: **complete**. Final implementation/documentation SHA and permanent workflow evidence recorded below.

## Baseline and scope

Immediately before source changes, `master` was `c0fa89ebc4e32e64e5a4ed0d701f139b905e12f8`. The only commit after the spec planning commit at that time was `c0fa89ebc4e32e64e5a4ed0d701f139b905e12f8`, which added the companion TODO. No production code had changed between spec planning and implementation start.

The prior final-polish pass remains closed. Its accepted request-ID exhaustion, EventHub exhaustion wake-up, native scrub source-contract strategy, privacy, CI, and release-gate behavior are invariants for this pass and were re-confirmed still in force (full test suite green; no assertion in that area was weakened).

## How this pass actually proceeded

The bulk of P1-P11's substantive implementation (input ownership preflight, strict Python decoding, worker event terminalization, HTTP task observability, mutex poison policy, non-Unicode configuration, request-ID invariant handling, command-ID exhaustion, structured native classification, tracing/timestamp fail-closed behavior) was implemented across 39 commits between the spec-planning commit and the point this session resumed work, ending at `fc25309` ("ci: acquire pinned hosted-doc assets read-only"). That prior work was done without local Rust/Python/Docker execution available (see the original note below, superseded once a working checkout with network access became available this session).

> Original validation-environment note from the prior work (superseded): "Direct outbound DNS/network access from the local execution container cannot resolve `github.com`, so a normal local clone is unavailable. Source changes are being made through the connected GitHub repository interface. Local Rust/Python/Docker commands will not be represented as passed unless a usable checkout becomes available; permanent exact-SHA CI and Release Gates remain authoritative execution evidence."

This session resumed with a full local checkout, working `cargo`/`pylint`/`mypy`/`ruff`/`shellcheck` toolchain, and outbound network access (confirmed via `curl` to `github.com` and authenticated `gh` CLI access). Because the TODO/implementation-notes files still showed "not started"/"in progress" and no checkboxes were marked, this session began by auditing the actual `master` tip against the spec, rather than assuming the prior commits were complete or correct. That audit found real, unresolved gaps — see "Baseline-confirmed defects" and "Gaps found and fixed" below — which is why the implementation starting SHA above still shows the original pre-work SHA: the audit found genuine unfinished/broken work, not a false "not started" status.

## Baseline-confirmed defects (the two primary spec-required regressions)

### TypeText pre-held-key ownership

Confirmed fixed and regression-tested. `crates/controller-api/src/input.rs` preflights the full synthesized-key set against `pressed_keys` before any native event; `type_text_rejects_preheld_printable_key_without_side_effects`, `type_text_rejects_preheld_enter_without_side_effects`, and `type_text_rejects_preheld_tab_without_side_effects` all pass and prove atomic rejection before any side effect.

### Python typed-response coercion

Confirmed fixed and regression-tested. `python/src/vnc_remote_control/client.py` now runs every typed HTTP response through narrow runtime validators (`_require_object`, `_require_bool`, `_require_exact_int`, `_require_string_enum`, etc.) before constructing a model; `test_typed_http_responses_reject_malformed_primitives_and_enums` and `test_nonempty_malformed_api_error_is_protocol_error` in `tests/test_python_client.py` cover the required malformed-field matrix from spec 5.6.

## Gaps found and fixed this session

Auditing the `master` tip (`fc25309`) against the spec surfaced real, unresolved problems, despite the TODO/spec/implementation-notes trio implying prior completion:

1. **Both permanent `CI` and `Release Gates` were red on the tip this session started from** (runs `31248340699`/`31248340685`, both `failure`). Root causes, all fixed and reverified:
   - `cargo fmt --all --check` failed: several files (`worker/tests/reconnect.rs` and others) had drifted from rustfmt's canonical formatting.
   - `cargo test --workspace --all-features` failed to compile: the command-ID exhaustion pass (P9) added `WorkerClient::command_id_exhausted: Arc<AtomicBool>` but left three hand-constructed `WorkerClient { ... }` test literals (`metric_semantics.rs`, `shutdown.rs` ×2) without the new field, and `worker/tests/lifecycle.rs` referenced `DesktopError::CommandIdExhausted` without importing `DesktopError`. This also broke the ThreadSanitizer test-compile step in Release Gates.
   - `tests/integration/run.sh`'s R13 suite failed: `tests/integration/r13_checks_auth.py`'s wrong-password check waited up to 20s for `state == "authentication_failed"`, a state the current (correct, spec-required) classification no longer produces — a wrong VNC password is now truthfully classified `WorkerFailureKind::Protocol` per spec 13.1/13.4, since LibVNCClient's generic `InitialiseRFBConnection()` failure carries no trustworthy authentication-rejection evidence. The test timed out after 40 reconnect attempts.
   - Fixed in commits `fed5886` (compile errors + rustfmt), `0838581` (R13 test expectation + `docs/OPERATOR_GUIDE.md`, which had the same stale `authentication_failed` claim in three places), and `d55fe45` (two Python lint findings the same regressions had left behind: three over-length test-payload lines in `tests/test_python_client.py`, and a missing-docstring finding in `tests/test_post_final_polish_native_contract.py`). CI/Release Gates confirmed green on `d55fe45` (runs `31255809209`/`31255809228`).

2. **P7 (self-hosted Swagger UI/ReDoc assets) was entirely unimplemented.** The one prior commit toward it (`fc25309`) only fetched the assets into a scratch CI workflow artifact (`.github/workflows/post-final-polish-asset-fetch.yml`); `crates/controller-api/src/http/docs_ui.rs` still hard-coded `https://cdn.jsdelivr.net/...` and `https://cdn.redoc.ly/...` in the served HTML and CSP, and the TODO's P7 checkboxes were (correctly) still unchecked. Implemented fully in commit `34938a5`:
   - Vendored the exact pinned files (`swagger-ui-dist@5.32.11`: `swagger-ui.css`, `swagger-ui-bundle.js`, `swagger-ui-standalone-preset.js`; `redoc@2.5.3`: `redoc.standalone.js`) unmodified under `crates/controller-api/third_party/{swagger-ui/5.32.11,redoc/2.5.3}/`, each with its upstream `LICENSE` (Apache-2.0, MIT) and a `MANIFEST.md` recording source URL, version, license, and SHA-256 digest.
   - Embedded them via `include_str!` (same pattern as `docs/openapi.json`) and served them from new local routes (`/docs/assets/swagger-ui.css`, `/docs/assets/swagger-ui-bundle.js`, `/docs/assets/swagger-ui-standalone-preset.js`, `/redoc/assets/redoc.standalone.js`) — no controller startup or request-time network fetch.
   - Pointed `/docs`/`/redoc` HTML at the local routes and tightened both CSPs to `script-src 'self'` (`style-src 'self'` for Swagger; ReDoc keeps `style-src 'unsafe-inline'` because it injects component styles as inline `<style>` tags, documented in-line in `docs_ui.rs`).
   - Rewrote the Rust `docs_ui` integration test and the Python `tests/test_hosted_docs_contract.py` contract test to assert the local routes serve the exact vendored bytes/digests and that neither the CSP nor the controller-authored HTML references an external URL.
   - Updated `README.md` and `docs/OPERATOR_GUIDE.md`, which both still told readers the UI assets loaded from a CDN.
   - Removed the now-superseded `post-final-polish-asset-fetch.yml` workflow — the assets it fetched are vendored with pinned digests instead of re-fetched from a CDN on every push.
   - **Known accepted gap**: the vendored, unmodified `redoc.standalone.js` still contains a reference to `https://cdn.redoc.ly/redoc/logo-mini.svg` for an optional "powered by Redocly" branding badge. The tightened `img-src data:` CSP blocks that request; ReDoc's own `onError` handler hides the badge when it fails to load. This is a silent, cosmetic-only gap, not a script/style trust dependency, and does not affect the security property P7 exists to establish (entering a bearer token into hosted Swagger no longer requires trusting third-party runtime JavaScript delivery).

3. **P12.1's OpenAPI error-code contract was missing `command_id_exhausted`.** The Rust implementation (P9) correctly returns `error.code = "command_id_exhausted"` with HTTP 503, but `docs/openapi.json`'s `ErrorEnvelope.code` enum never listed it, and `tests/test_documentation_contract.py`'s cross-check didn't catch this because its own hardcoded `EXPECTED_ERROR_CODES` set was equally out of date — both sides silently agreed on the same incomplete list. Fixed in commit `ced436c`, along with documenting the new code in `docs/OPERATOR_GUIDE.md`'s 503/504 troubleshooting section and tightening `python/README.md`'s client-error description (which only mentioned `ProtocolError` for malformed success responses, omitting the malformed non-empty error-envelope behavior P11.3 added).

No other gaps were found across a full re-audit of P1-P6 and P8-P11 (source inspection plus the full local test/lint suite below all pass and specifically exercise every named scenario in the spec).

## Design decisions

- **Command-ID exhaustion readiness**: verified (not a gap) that `WorkerClient::mark_command_id_exhausted()` sets the shared `WorkerSnapshot.fatal_exit` flag, which `http::support::ready()` already consults — so exhaustion correctly makes the controller not-ready for new command service via the existing mechanism, without needing a second dedicated flag.
- **`AuthenticationFailed` retained but currently unreachable**: `classify_native_error()` never produces `WorkerFailureKind::Authentication` (only `Protocol`, `Configuration`, `Transport`, or `Native`), so `ConnectionState::AuthenticationFailed` is presently unreachable in production. This matches spec 13.1/13.4 exactly: the state remains for a future trustworthy authentication-rejection signal and must not be fabricated from message text or generic initialization failure.
- **R13 wrong-password fix**: rather than asserting a new terminal state, the corrected test waits for `last_failure == "protocol"` while `state` cycles through `connecting`/`reconnecting`, matching the worker's actual (correct) bounded-retry behavior for an unproven-cause connection failure.
- **Vendoring over CDN**: chose to vendor the exact upstream distribution bytes rather than any alternative (self-built bundle, different UI library) to keep the change minimal and preserve the already-accepted pinned versions (5.32.11 / 2.5.3) — consistent with spec 10.1's "preserve the currently selected versions unless an explicit separate upgrade is justified."

## Justified retained ignored-result sites

Spot-checked every remaining `let _ =` in production Rust (`worker/run.rs`, `events.rs`, `runtime.rs`, `screenshot.rs`, `observability.rs`, `main.rs`, `worker/desktop_worker.rs`); each falls into one of the explicitly preserved categories from spec 3.4 / TODO P11.4: a completion/result send after the caller already timed out and dropped its receiver, a screenshot result send after request timeout while the encode permit remains held, event broadcast with no replay listeners, best-effort input cleanup with unresolved state still tracked and observable, or a normal shutdown-queue send when the out-of-band shutdown signal is authoritative. None hide an unexpected subsystem failure or invariant violation. The remaining `unwrap_or(u64::MAX)` sites (`loop_state.rs`, `middleware.rs`, `desktop_worker.rs`) are internal tracing/log duration fields, not public response timestamp semantics, so they are out of P11.2's scope (which targets `http::support::unix_milliseconds`, the function actually used for public `*_unix_ms` response fields — that one is checked and fails closed).

## Local validation actually performed

Run directly against this checkout (all green):

```text
cargo fetch --locked
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo test --locked --workspace --all-features        # 152 controller-api tests + all other crates, 0 failed
RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps
python -m compileall -q tools/ci_status tests desktop/test-app
ruff check .
pylint --rcfile=.pylintrc python/src/vnc_remote_control tests scripts tools/ci_status desktop/test-app   # 10.00/10
mypy --config-file mypy.ini python/src/vnc_remote_control tests scripts tools/ci_status desktop/test-app  # no issues
python3 -m unittest discover -s tests -p 'test_*.py'   # 109 tests, 0 failed
bash -n <all listed shell scripts>
shellcheck <all listed shell scripts>                  # clean
```

## Unavailable local validation

This execution environment has no Docker/TigerVNC available, so the P14.4 Docker/VNC suites (`tests/desktop/run.sh`, `tests/native/run.sh`, `tests/worker-e2e/run.sh`, `tests/worker-text-clipboard-e2e/run.sh`, `tests/http-e2e/run.sh`, `tests/compose/run.sh`, `tests/integration/run.sh`) and `actionlint` were not run locally. Per policy, these are not claimed as locally passed; they were validated via the permanent `CI`/`Release Gates` workflows on the exact final SHA (below).

## Deferred follow-ups

- ReDoc's optional branding-badge image reference to `cdn.redoc.ly` (see P7 above) — cosmetic-only, safe to defer indefinitely; revisit only if ReDoc is upgraded and a self-hostable/removable badge option becomes available.
- No other deferred items. Every checklist item in the companion TODO was either verified true or fixed.

## Final evidence

```text
Reviewed code baseline SHA:
b1ce8addc846ef8f55f1ffeab5ecd82bfb9b235b

Spec planning commit:
9095ecc1d96a010061ca463e05848c11f9e92eaa

Implementation starting SHA:
c0fa89ebc4e32e64e5a4ed0d701f139b905e12f8

Final implementation SHA:
ced436c64462ea8909e458469892a8ae0b4327fb

Implementation CI run:
31256296608 — success

Implementation Release Gates run:
31256296590 — success

Final documentation/evidence SHA:
<fill after this commit — see this file's own commit for the exact value>

Intermediate failed candidate SHA:
fc25309922 (CI run 31248340699 — failure: rustfmt drift, worker test compile
errors from the command-ID exhaustion field, R13 wrong-password timeout;
Release Gates run 31248340685 — failure: same worker test compile error
broke the ThreadSanitizer test-compile step)

Confirmed baseline-failing regressions:
- TypeText pre-held-key ownership: fixed and regression-tested before this
  session (type_text_rejects_preheld_{printable_key,enter,tab}_without_side_effects,
  all passing)
- Python response type coercion: fixed and regression-tested before this
  session (test_typed_http_responses_reject_malformed_primitives_and_enums,
  test_nonempty_malformed_api_error_is_protocol_error, both passing)

P3 worker event receiver/sequence terminalization:
Implemented and verified correct; unexpected TrySendError::Disconnected
becomes a terminal, once-logged, fail-closed worker state distinct from
orderly-shutdown disconnection; event sequence exhaustion is terminal with
no wraparound. All named regression tests pass.

P4 HTTP task/runtime observability:
Implemented and verified correct; JoinSet results are inspected and
classified (panic/error/expected-cancellation/clean), graceful shutdown
remains bounded, no raw request data appears in diagnostics.

P5 poison policy:
Implemented and verified correct; authoritative worker/framebuffer/
screenshot-permit mutex poison fails closed with a payload-free diagnostic
rather than silently resuming with into_inner().

P6 non-Unicode configuration:
Implemented and verified correct; every VRC_* variable read through the
controller config loader fails closed on VarError::NotUnicode rather than
collapsing it into the absent/default case.

P7 self-hosted API docs assets:
Was entirely unimplemented on resume (CDN URLs still hard-coded); fully
implemented this session. swagger-ui-dist 5.32.11 (Apache-2.0) and redoc
2.5.3 (MIT) vendored unmodified under crates/controller-api/third_party/,
digests and license/source metadata recorded in third_party/MANIFEST.md
and pinned in tests/test_hosted_docs_contract.py; served from new local
/docs/assets/* and /redoc/assets/* routes; CSP tightened to script-src
'self' (style-src 'self' for Swagger, 'unsafe-inline' retained for ReDoc's
inline component styles only). One accepted cosmetic gap: ReDoc's optional
branding-badge image reference to cdn.redoc.ly fails closed silently under
the tightened img-src.

P8 request-ID invariant handling:
Implemented and verified correct; missing-extension state is an explicit
500 internal_error invariant, not a fabricated normal ID; invalid caller
IDs are replaced without raw-value logging; final-polish exhaustion
behavior (503 request_id_exhausted, reserved sentinel, once-only
diagnostic) is unchanged.

P9 command-ID exhaustion:
Implemented and verified correct; a shared Arc<AtomicBool> terminal flag
across all WorkerClient clones prevents any further enqueue after the
first exhausted allocation, sets WorkerSnapshot.fatal_exit (making
readiness reflect the terminal state), and maps to error.code =
"command_id_exhausted" / HTTP 503. The OpenAPI error-code contract was
missing this code on resume; fixed this session.

P10 structured native initialization classification:
Implemented and verified correct; a distinct VRC_STATUS_PROTOCOL_
INITIALIZATION_FAILED shim status maps to NativeError::ProtocolInitialization
Failed and WorkerFailureKind::Protocol, with no message.contains(...)
classification remaining. The R13 integration test and three
docs/OPERATOR_GUIDE.md passages still asserted/documented the old unproven
authentication_failed label for a wrong password on resume; corrected this
session to match the truthful classification.

P11 retained intentional ignored-result sites:
Tracing initialization and public HTTP timestamp conversion both fail
closed (process exit 1 / HTTP 500 internal_error) rather than silently
defaulting; Python non-empty malformed error envelopes raise ProtocolError;
spot-checked ignored-result sites all carry an ownership/lifecycle
justification matching one of the explicitly preserved spec 3.4 categories.

Local validation:
cargo fetch/fmt/clippy/test/doc (152 controller-api tests + all other
crates, 0 failed), Python compileall/ruff/pylint(10.00/10)/mypy(clean)/
unittest (109 tests, 0 failed), bash -n, shellcheck — all green, commands
listed in full above.

Unavailable local validation:
No Docker/TigerVNC in this execution environment, so the seven P14.4
Docker/VNC E2E suites and actionlint were not run locally; validated via
the permanent CI/Release Gates workflows on the exact final SHA instead.

Deferred follow-ups:
ReDoc's optional cdn.redoc.ly branding-badge image reference (cosmetic-
only, fails closed silently under the tightened CSP; safe to defer
indefinitely).
```

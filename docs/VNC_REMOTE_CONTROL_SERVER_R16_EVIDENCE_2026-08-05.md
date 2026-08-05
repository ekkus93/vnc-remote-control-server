# VNC Remote Control Server — R16 Final v0.1 Acceptance Evidence

Date: 2026-08-05  
Milestone: R16 — Final v0.1 acceptance gate  
Repository: `ekkus93/vnc-remote-control-server`  
Branch: `master`  
Release-candidate commit: `dd3b14917ad5e239573d584238ff67ded8138203`

## Release decision

**Accepted for v0.1.**

The permanent `CI` and `Release Gates` workflows both completed successfully on the exact same release-candidate SHA. No skipped, cancelled, neutral, timed-out, or failed required job is used as acceptance evidence.

The release candidate contains only the permanent workflows:

- `.github/workflows/ci.yml`
- `.github/workflows/publish-ci-status.yml`
- `.github/workflows/release-gates.yml`

The temporary R16 repair and commit executors were removed before the acceptance runs.

## Exact same-SHA GitHub Actions evidence

### Functional and integration CI

- Workflow: `CI`
- Run: `31029834071`
- Head SHA: `dd3b14917ad5e239573d584238ff67ded8138203`
- Conclusion: `success`
- Repository quality gates job: `92387470896` — `success`
- Secured Debian desktop and native adapter job: `92387470858` — `success`

The run passed:

- Rust formatting;
- Clippy on all targets and features with warnings denied;
- all Rust unit and documentation tests;
- Python compilation and all permanent repository/workflow contracts;
- first-party shell syntax;
- desktop image smoke;
- native adapter smoke;
- real WorkerHandle pointer/keyboard E2E;
- real WorkerHandle text/clipboard E2E;
- authenticated HTTP and WebSocket E2E against TigerVNC;
- controller image, Compose, secret, and persistence smoke;
- the complete R13 real-Compose lifecycle and integration suite.

### Release security and native-safety gates

- Workflow: `Release Gates`
- Run: `31029833868`
- Head SHA: `dd3b14917ad5e239573d584238ff67ded8138203`
- Conclusion: `success`
- Static and supply-chain policy job: `92387653372` — `success`
- Release image vulnerability and SBOM job: `92387653399` — `success`
- Native sanitizer and Miri job: `92387653418` — `success`

The run passed:

- ShellCheck at warning severity;
- actionlint;
- BuildKit Dockerfile checks;
- all Compose configuration checks;
- `cargo deny check`;
- complete reachable Git-history scanning with Gitleaks;
- AddressSanitizer;
- ThreadSanitizer on the Rust-only core;
- Miri on the complete pure-Rust core test target;
- controller and desktop image builds from the exact candidate;
- Trivy HIGH/CRITICAL inventories;
- CycloneDX SBOM generation;
- exact CRITICAL VEX enforcement.

## Toolchain and release-image identity

- Rust stable: `rustc 1.97.1 (8bab26f4f 2026-07-14)`
- Rust nightly for sanitizers/Miri: `rustc 1.99.0-nightly (ad3d0bc14 2026-07-31)`
- Stable LLVM: `22.1.6`
- Nightly LLVM: `22.1.8`
- Debian runtime/desktop base: `debian:13.6-slim@sha256:020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd`
- TigerVNC release-image packages: `1.15.0+dfsg-2.1~deb13u1`
- LibVNCClient in the release controller image: `0.9.15+dfsg-1+deb13u2`
- LibVNCClient on the Ubuntu native-safety runner: `0.9.14`
- Docker client/server: `28.0.4`
- Docker Buildx: `0.35.0`
- Docker Compose: `2.38.2`
- cargo-deny: `0.19.7`
- actionlint: `1.7.12`
- ShellCheck: `0.9.0`
- Gitleaks: `8.30.1`
- Trivy: `0.70.0`

## R16 acceptance matrix

### R16.1 Architecture and isolation

Accepted through the production Dockerfiles, Compose topology, native binding decision, deployment contracts, native contracts, and real Compose tests:

- exactly one project-owned desktop session;
- separate non-root desktop and controller containers;
- production raw VNC exposed only inside the `internal: true` Docker network;
- the optional debug override binds raw VNC only to `127.0.0.1`;
- all Linux capabilities dropped and `no-new-privileges` applied;
- bounded PID counts and a read-only controller root filesystem;
- raw LibVNCClient state confined to the reviewed adapter and its single owner worker thread.

### R16.2 Observation

Accepted through unit, HTTP E2E, WorkerHandle E2E, and R13 integration evidence:

- complete framebuffer acquisition before readiness;
- exact `1280x800` display metadata;
- coherent PNG screenshots;
- process/revision ETags and conditional `304`;
- stale framebuffer invalidation during reconnect;
- authenticated payload-free WebSocket snapshots and revision events.

### R16.3 Control

Accepted through the real public API → worker → LibVNCClient → TigerVNC → deterministic desktop path:

- pointer movement;
- button down/up;
- left, middle, and right click;
- atomic double-click;
- vertical scroll in both directions;
- explicit, tested rejection of nonzero horizontal scroll in v0.1;
- key down/up;
- ordered chord press and reverse release;
- exact supported text;
- atomic rejection of unsupported text;
- outbound and inbound clipboard behavior.

No unsupported input is silently clamped, discarded, retried into apparent success, or partially applied.

### R16.4 Reliability

Accepted through bounded unit and real lifecycle tests:

- automatic reconnect after desktop restart;
- visible authentication failure without rapid retry;
- explicit command-queue saturation;
- bounded headers, bodies, worker acknowledgements, screenshot encodes, reconnects, WebSocket clients, and shutdown;
- stale-frame invalidation and readiness failure on worker/transport failure;
- bounded slow-client event buffers;
- queue admission and worker acknowledgement semantics that prevent silent command loss.

### R16.5 Security

Accepted through configuration contracts, real E2E redaction probes, full-history scanning, dependency policy, image scanning, and SBOM evidence:

- bearer authentication on all `/v1/*` HTTP routes and the WebSocket handshake;
- mandatory VNC authentication;
- file-mounted API and VNC secrets;
- no secrets in image layers;
- no bearer token, VNC password, typed text, clipboard payload, or framebuffer payload in logs/evidence;
- no public raw VNC binding in production;
- dropped capabilities, non-root users, resource limits, read-only controller root, and bounded tmpfs;
- successful Rust advisory/license/source policy;
- successful image vulnerability policy.

### R16.6 Quality evidence

Every required quality class passed on the exact release-candidate SHA:

- formatting;
- warning-denied Clippy;
- Rust unit and documentation tests;
- adapter/native smoke and ASan;
- desktop smoke;
- Compose and persistence smoke;
- integration and end-to-end tests;
- TSan and Miri;
- complete-history secret scanning;
- dependency policy;
- image scans and SBOMs;
- README/operator/OpenAPI/WebSocket documentation parity.

## Image vulnerability evidence

The release-image job retained HIGH and CRITICAL results rather than hiding them:

- controller: 24 HIGH, 4 CRITICAL findings;
- desktop: 55 HIGH, 18 CRITICAL findings;
- total observed CRITICAL package tuples: 22;
- unreviewed CRITICAL tuples: 0;
- stale VEX entries: 0.

The six unique CRITICAL CVEs are matched by exact image, CVE, binary package, and installed version. There is no `--ignore-unfixed`, wildcard exception, ignored scanner exit code, or open-ended risk acceptance.

The determinations were reviewed on 2026-08-05, expire on 2026-09-04, and are tracked by issue #7. Expiry, a package-version change, a new finding, a changed reachability path, or any tuple mismatch blocks the gate.

## Retained artifacts

### CI evidence

- Name: `ci-evidence-31029834071`
- Artifact ID: `8940222454`
- Digest: `sha256:fecbfcb8174f7d05082c6b10c3b2bd350a4c1e2b7d78d0f066d2b122f28cfeb4`
- Recorded head SHA: `dd3b14917ad5e239573d584238ff67ded8138203`

### Static-policy evidence

- Name: `static-policy-31029833868`
- Artifact ID: `8940276185`
- Digest: `sha256:0aeffa870f979afea65d845f28e44e6e292e620b84eccf27f013ca5b4cde1f2e`

### Native-safety evidence

- Name: `native-safety-31029833868`
- Artifact ID: `8940266325`
- Digest: `sha256:bd82223c5149d11f0d89a1dd78c58fb7d060c8ad6fb072f087dffe355e0598bc`

### Image-security and SBOM evidence

- Name: `image-security-31029833868`
- Artifact ID: `8940252403`
- Digest: `sha256:7ba56fd8c6331a84b0c54de85ea37ab88f229e22edc18a481320bb46f496863e`

## Known v0.1 limitations

- Exactly one project-owned Debian desktop is supported.
- Arbitrary external VNC servers, multiple sessions, multi-user authorization, browser/noVNC viewing, OCR, accessibility-tree automation, Playwright, and AI planning are outside scope.
- The controller does not terminate TLS; exposure beyond localhost requires a trusted reverse proxy.
- Horizontal scrolling is deliberately unsupported and nonzero horizontal requests fail explicitly.
- Typed text is limited to tab, carriage return, line feed, and printable ASCII `U+0020`–`U+007E`.
- Clipboard API strings are UTF-8 and bounded to 1 MiB, but the legacy RFB clipboard channel is byte-oriented; invalid inbound UTF-8 is rejected.
- ASan covers the Rust adapter boundary, TSan covers the Rust-only core, and Miri covers the pure-Rust core. The distribution LibVNCClient shared library is not rebuilt with sanitizers.
- Current exact CRITICAL reachability determinations require revalidation by 2026-09-04.

## Final conclusion

R16 is complete. The exact release-candidate SHA passed functional, integration, security, supply-chain, image, sanitizer, and Miri gates without a silent fallback or waived required failure. The repository is accepted as v0.1 within the documented product and security boundary.

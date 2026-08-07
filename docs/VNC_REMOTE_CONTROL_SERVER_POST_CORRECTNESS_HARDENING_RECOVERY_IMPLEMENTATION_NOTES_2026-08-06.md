# VNC Remote Control Server Post-Correctness Hardening Recovery Implementation Notes

Date: 2026-08-06

Starting partial SHA: `100e4454634a577bf5ffd7b0dbc8913cf5a60cea`

Reviewed correctness baseline: `96836f7ff964813fb727a1f7407fb0b1f448b738`

Recovered implementation SHA: `ea97616ff659856f2d3f41a220e7fa1b37c272eb`

Rust integration fixup SHA: `9adefcb980d43ac89a7e71b410c03f63cb65d330`

This recovery audited the eight partial Rust commits rather than accepting them as completion evidence.

Implemented repairs:

- removed broad ordinary-string conversion and exposure helpers from `ApiToken`;
- made router construction accept the explicit token type directly;
- changed secret parsing to validate borrowed bytes, preserve the full rejection buffer, scrub with volatile writes, and transfer the successful allocation without an extra plaintext copy;
- made EventHub exhaustion logging one-shot and kept allocation fail-closed;
- factored WebSocket event-session preparation at the existing pre-`on_upgrade` boundary so sequence-exhaustion mapping and client-permit cleanup are directly testable without Hyper runtime upgrade state;
- retained the CR12 mismatched-frame negative proof and matching-frame positive control, with nonblocking causal progress reporting so the fixture cannot deadlock shutdown;
- retained required `HttpBackend` command metric methods and corrected the HTTP metric test to require the backend-provided queue capacity rather than a silent zero;
- scrubbed project-owned native clipboard storage before replacement/destruction and outbound send copies before free;
- moved clipboard revision-overflow rejection before allocation and replacement;
- documented and tested the exact project-owned clipboard and secret boundaries;
- added `event_sequence_exhausted` to OpenAPI and WebSocket documentation.

The clipboard guarantee is deliberately narrow. It does not cover Rust HTTP values, LibVNCClient, VNC servers, desktop applications, toolkits, OS clipboard managers, clients, allocators, swap, or crash dumps.

## Focused recovery validation

- Recovery patch/application run `31140212303`: success. Exact-anchor preparation, preflight, Rust formatting, native contract tests, and documentation contract tests passed before the recovery implementation was committed.
- Controller Rust integration run `31140862333`: success. `cargo test --locked -p controller-api --lib` passed all 125 controller-api library tests after the final integration fixes.
- Temporary recovery/fixup scripts and workflows are absent from the resulting implementation tree.

The workflow-generated fixup SHA did not recursively trigger permanent workflows because GitHub suppresses workflow runs caused by pushes authenticated with the workflow `GITHUB_TOKEN`. This documentation/evidence commit is therefore the first normal `master` push after the recovered implementation and is the permanent-validation candidate.

Exact permanent CI and Release Gates run IDs are recorded only after this validation candidate, or a later repair/documentation tip, completes both workflows successfully on the same exact SHA.

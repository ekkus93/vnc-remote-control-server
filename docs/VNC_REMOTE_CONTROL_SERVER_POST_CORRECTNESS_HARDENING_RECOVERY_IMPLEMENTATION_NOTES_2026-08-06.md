# VNC Remote Control Server Post-Correctness Hardening Recovery Implementation Notes

Date: 2026-08-06

Starting partial SHA: `100e4454634a577bf5ffd7b0dbc8913cf5a60cea`

This recovery audited the eight partial Rust commits rather than accepting them as completion evidence.

Implemented repairs:

- removed broad ordinary-string conversion and exposure helpers from `ApiToken`;
- made router construction accept the explicit token type directly;
- changed secret parsing to validate borrowed bytes, preserve the full rejection buffer, scrub with volatile writes, and transfer the successful allocation without an extra plaintext copy;
- made EventHub exhaustion logging one-shot and kept allocation fail-closed;
- proved the failed initial WebSocket snapshot releases its client permit;
- retained the CR12 mismatched-frame negative proof and matching-frame positive control;
- retained required `HttpBackend` command metric methods;
- scrubbed project-owned native clipboard storage before replacement/destruction and outbound send copies before free;
- moved clipboard revision-overflow rejection before allocation and replacement;
- documented and tested the exact project-owned clipboard and secret boundaries;
- added `event_sequence_exhausted` to OpenAPI and WebSocket documentation.

The clipboard guarantee is deliberately narrow. It does not cover Rust HTTP values, LibVNCClient, VNC servers, desktop applications, toolkits, OS clipboard managers, clients, allocators, swap, or crash dumps.

Exact permanent workflow run IDs are recorded only after the final repository tip completes CI and Release Gates.

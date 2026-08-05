# Responses: Worker Shutdown Refactor Spec + TODO Review

Covers: `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_REFACTOR_SPEC_2026-08-05.md` +
`docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_REFACTOR_TODO_2026-08-05.md`

## 1

Q: Spec §7 / TODO F9's local validation commands don't exactly match `Makefile`/CI (missing
`--all-features` on clippy and test, `pytest` vs. the authoritative `unittest discover`, a
narrower `compileall` target set, and a `bash -n` glob that misses `desktop/xstartup` and 6 of 7
`tests/*/run.sh` scripts). Should the actual Makefile/CI commands be run instead when validating
locally (recommended, since it's a strict superset and this repo treats CI as authoritative
anyway), or should the spec's commands be followed literally as written?

A:

## 2

Q: TODO F9–F12 call for pushing the final commit straight to `master` and polling exact-SHA
CI/Release Gates to completion before marking this done. Should that push-and-monitor sequence
happen automatically once local validation is green, or should implementation stop after local
validation so the diff can be reviewed before it goes to `master`?

A:

## 3

Q: (Minor, optional) Spec §5.5/TODO F5 leave `WorkerCommand::Shutdown` retention as implementer's
discretion ("keep if useful"). The default plan is to keep it for the two e2e binaries'
compatibility unless there's a preference for removing it now that the atomic flag is
authoritative. Any preference, or is discretion fine?

A:

---

Fill in the `A:` lines above and share this file (or paste the answers) back to continue.

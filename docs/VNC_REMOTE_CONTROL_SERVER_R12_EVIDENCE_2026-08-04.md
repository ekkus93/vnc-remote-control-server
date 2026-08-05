# R12 Controller Image, Compose, and Persistence Evidence — 2026-08-04

## Scope

R12 packages the production controller, defines the production and development Compose topologies, and proves disposable and persistent desktop-home behavior without retaining credential material.

## Controller image

- `controller/Dockerfile` is a multi-stage build.
- Rust compilation and native development packages exist only in the builder stage.
- The runtime stage contains the stripped `controller-api` binary, LibVNCClient runtime libraries, CA certificates, `curl`, and `tini`.
- The runtime image excludes Cargo, rustc, the C compiler, Cargo registries, source code, and build secrets.
- The process runs as the dedicated `controller` user with UID/GID `10002`.
- The image-level healthcheck targets `/health/live`; Compose uses `/health/ready`.

## Production Compose

- `deploy/compose.yaml` defines separate desktop and controller services.
- Desktop-controller traffic uses an internal desktop-control network.
- Only the controller also joins a separate API-ingress bridge, allowing Docker to publish the API without exposing the desktop network.
- Desktop VNC is internal-only through `expose: 5901`.
- Only the controller API is published, loopback-only by default.
- Both services enable `no-new-privileges` and drop all Linux capabilities.
- The controller root filesystem is read-only with a bounded, no-exec `/tmp` tmpfs.
- No service mounts the Docker socket.
- API and VNC credentials are mounted as file-backed Compose secrets.

## Debug VNC

`deploy/compose.debug-vnc.yaml` is an explicit development-only override. It adds exactly one raw VNC binding at `127.0.0.1:5901` by default. The production Compose file has no desktop host port.

## Persistence

- Disposable desktop state remains the default.
- `deploy/compose.persistence.yaml` explicitly mounts a named volume at `/home/desktop`.
- User files and desktop settings under `/home/desktop` persist only in that mode.
- `/tmp`, controller state, source secret mounts, and generated VNC credentials do not persist.
- The desktop entrypoint now generates `/tmp/vnc-runtime/passwd`, outside `/home/desktop`, and removes the runtime directory during cleanup.

## Validation

`tests/compose/run.sh` proves:

- production and debug rendered Compose contracts;
- successful controller and desktop image builds;
- non-root controller runtime and required dynamic LibVNCClient linkage;
- absence of build tools and secrets from the runtime image;
- read-only controller root filesystem and `no-new-privileges`;
- healthy desktop and controller startup;
- authenticated status, display, and PNG screenshot requests;
- no production host VNC binding;
- loopback-only debug VNC connectivity;
- disposable recreation clears desktop-home state;
- persistent recreation retains the expected marker;
- raw and generated VNC credential material is absent from persistent home.

Executor run: 30967019129.
Implementation SHA and ordinary exact-head CI evidence are appended after validation completes.

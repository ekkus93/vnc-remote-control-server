# Deployment

For the complete operator lifecycle, API examples, tuning, recovery, and troubleshooting, see [`../docs/OPERATOR_GUIDE.md`](../docs/OPERATOR_GUIDE.md). The machine-readable HTTP contract is [`../docs/openapi.json`](../docs/openapi.json). For replacing the stock desktop with a project-owned customized VNC desktop, see [`../docs/CUSTOM_DESKTOP_IMAGES.md`](../docs/CUSTOM_DESKTOP_IMAGES.md).

`compose.yaml` is the production topology. It builds a non-root controller image and the Debian/TigerVNC desktop image. Both services share an internal desktop-control network; only the controller also joins a separate API-ingress bridge so Docker can publish the controller API. The default API binding is loopback-only at `127.0.0.1:8080`.

The stock controller targets the `desktop` Compose service through:

```text
VRC_VNC_HOST=desktop
VRC_VNC_PORT=5901
VRC_VNC_PASSWORD_FILE=/run/secrets/vnc_password
```

The name `desktop` is resolved by Docker service discovery because both services share `desktop_control`. A custom image can replace the `desktop` image without changing the Rust controller or Python client as long as it preserves the supported VNC contract.

## Secrets

Create local secret files before starting the stack:

```bash
install -d -m 0700 deploy/secrets
printf '%s' 'replace-with-a-long-api-token' > deploy/secrets/api_token.txt
printf '%s' 'replace-with-a-vnc-password' > deploy/secrets/vnc_password.txt
chmod 0700 deploy/secrets
chmod 0444 deploy/secrets/api_token.txt deploy/secrets/vnc_password.txt
```

The secret directory ignores all credential files. Keep the directory at mode `0700`; the files use mode `0444` because local Docker Compose mounts file-backed secrets read-only while preserving their host ownership, and both services run as dedicated non-root UIDs. The private parent directory prevents other host users from traversing to the files. The controller reads both credentials from `/run/secrets`; the desktop reads the VNC password from `/run/secrets`. The generated TigerVNC credential file is stored only in `/tmp/vnc-runtime/passwd`, never under the persistent home directory.

## Disposable production mode

The default desktop home lives in the container writable layer. Recreating the desktop container clears user-created desktop state:

```bash
docker compose -f deploy/compose.yaml up --build -d
docker compose -f deploy/compose.yaml down
```

## Persistent desktop-home mode

Use the persistence override to mount a named volume at `/home/desktop`:

```bash
docker compose -f deploy/compose.yaml -f deploy/compose.persistence.yaml up --build -d
```

This preserves files and settings under `/home/desktop`. It does not preserve `/tmp`, controller process state, API tokens, VNC password source files, or the generated TigerVNC password file. Remove the named volume deliberately with `docker compose -f deploy/compose.yaml -f deploy/compose.persistence.yaml down --volumes`.

## Custom desktop image

The preferred custom-image workflow keeps the service name `desktop` and overrides only its image/build source. For example:

```yaml
services:
  desktop:
    image: my-firefox-discord-desktop:local
    build: !reset null
```

The explicit `!reset null` clears the stock `build` section in the merged Compose model, so Compose uses the prebuilt custom image rather than rebuilding the stock desktop under the new image tag.

Start it with:

```bash
docker compose \
  -f deploy/compose.yaml \
  -f compose.custom-desktop.yaml \
  up --detach --wait
```

Because the service remains named `desktop`, the controller can keep `VRC_VNC_HOST=desktop`. The custom target must still preserve VNC authentication, framebuffer, input, clipboard if required, lifecycle, private networking, and healthcheck behavior. Do not expose raw VNC or weaken readiness to accommodate an incompatible image. See [`../docs/CUSTOM_DESKTOP_IMAGES.md`](../docs/CUSTOM_DESKTOP_IMAGES.md) for the complete contract and examples.

## Development-only raw VNC

Raw VNC is absent from production Compose. For local diagnostics only, opt into the debug override:

```bash
docker compose -f deploy/compose.yaml -f deploy/compose.debug-vnc.yaml up --build -d
```

The override binds VNC only to `127.0.0.1:5901`. Never use the debug override on a production host and never change the binding to `0.0.0.0`.

## Health

The controller image has an image-level liveness check against `/health/live`. Production Compose overrides it with the readiness check at `/health/ready`, which becomes healthy only after the controller has a current complete desktop frame.

## Controller timing budgets

`VRC_STARTUP_TIMEOUT_MS` is the complete native-worker startup budget, including timeout cleanup; its default is 10000 ms. `VRC_SHUTDOWN_TIMEOUT_MS` is one total process-cleanup budget shared by worker shutdown and event-bridge cleanup; its default is 5000 ms and values below the derived 500 ms minimum are rejected. These are distinct from `VRC_COMMAND_ACK_TIMEOUT_MS`, which applies only to individual HTTP command acknowledgements, and `VRC_SHUTDOWN_GRACE_MS`, which applies to HTTP server draining.

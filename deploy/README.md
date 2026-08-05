# Deployment

For the complete operator lifecycle, API examples, tuning, recovery, and troubleshooting, see [`../docs/OPERATOR_GUIDE.md`](../docs/OPERATOR_GUIDE.md). The machine-readable HTTP contract is [`../docs/openapi.json`](../docs/openapi.json).

`compose.yaml` is the production topology. It builds a non-root controller image and the Debian/TigerVNC desktop image. Both services share an internal desktop-control network; only the controller also joins a separate API-ingress bridge so Docker can publish the controller API. The default API binding is loopback-only at `127.0.0.1:8080`.

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

## Development-only raw VNC

Raw VNC is absent from production Compose. For local diagnostics only, opt into the debug override:

```bash
docker compose -f deploy/compose.yaml -f deploy/compose.debug-vnc.yaml up --build -d
```

The override binds VNC only to `127.0.0.1:5901`. Never use the debug override on a production host and never change the binding to `0.0.0.0`.

## Health

The controller image has an image-level liveness check against `/health/live`. Production Compose overrides it with the readiness check at `/health/ready`, which becomes healthy only after the controller has a current complete desktop frame.

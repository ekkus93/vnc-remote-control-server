# Custom Desktop Images

This guide explains how to replace the stock desktop image with a project-owned customized desktop while keeping the Rust controller and Python client unchanged.

The central architecture is:

```text
Python application
    |
    | HTTP / WebSocket
    | VncClient(base_url, api_token)
    v
Rust controller
    |
    | RFB / VNC
    | VRC_VNC_HOST
    | VRC_VNC_PORT
    | VRC_VNC_PASSWORD_FILE
    v
Project-owned VNC desktop container
    |
    +-- XFCE or another compatible desktop environment
    +-- Firefox
    +-- Discord
    +-- other applications
```

The Python client talks only to the Rust controller. The Rust controller talks only to the configured VNC server. The Python application does not need to know which desktop image is behind the controller.

## 1. Supported customization boundary

The supported v0.1 customization model is **one project-owned desktop target that preserves the tested VNC contract**.

The easiest and preferred path is to derive a new image from the repository's known-good desktop image and install additional applications into it. Doing this preserves the TigerVNC, XFCE, user, startup, healthcheck, display, and secret-handling behavior that the repository already tests.

The controller is not fundamentally coupled to the Debian package set or to Firefox, Discord, or any other application. It is coupled to the VNC behavior exposed by the target.

This guide does **not** expand the v0.1 support claim to arbitrary external VNC servers. A different VNC implementation, a Wayland-only desktop, another operating system, or a remotely managed third-party VNC host may work, but it is not considered supported until the repository's framebuffer, input, authentication, clipboard, reconnect, shutdown, and integration contracts pass against that target.

## 2. The three configuration boundaries

There are three independent boundaries. Keeping them separate avoids most configuration mistakes.

### Boundary A: Python client to Rust controller

The Python library is initialized with the Rust controller's HTTP base URL and API bearer token:

```python
from pathlib import Path

from vnc_remote_control import VncClient

api_token = Path("deploy/secrets/api_token.txt").read_text(encoding="utf-8").strip()

client = VncClient(
    "http://127.0.0.1:8080",
    api_token,
)
```

If the Python application and controller are in the same Docker Compose network, the URL can instead use the controller service name, for example:

```python
client = VncClient("http://controller:8080", api_token)
```

The Python client does not receive `VRC_VNC_HOST`, the VNC port, the VNC password, or the desktop image name.

### Boundary B: Rust controller to VNC desktop

The controller selects its VNC target with:

```text
VRC_VNC_HOST
VRC_VNC_PORT
VRC_VNC_PASSWORD_FILE
```

The stock Compose topology uses:

```yaml
environment:
  VRC_VNC_HOST: desktop
  VRC_VNC_PORT: "5901"
  VRC_VNC_PASSWORD_FILE: /run/secrets/vnc_password
```

`VRC_VNC_HOST=desktop` means "connect to the host named `desktop`". In the stock Compose topology, `desktop` is the Docker Compose service name.

The VNC password file mounted into the controller must contain the password accepted by the target VNC server. Do not put the VNC password directly in an environment variable.

### Boundary C: Docker service discovery

The controller and desktop must be able to reach one another over a Docker network. The production topology uses the private `desktop_control` network:

```yaml
services:
  desktop:
    networks:
      - desktop_control

  controller:
    networks:
      - desktop_control
      - api_ingress

networks:
  desktop_control:
    internal: true
```

Docker Compose service names are DNS names on shared Compose networks. Therefore:

```text
VRC_VNC_HOST=desktop
```

resolves to the `desktop` service when both services share `desktop_control`.

If you rename the service to `firefox_desktop`, either change `VRC_VNC_HOST` to `firefox_desktop` or give the service an appropriate network alias. Do not depend on ephemeral container IP addresses.

## 3. What the stock desktop image provides

The repository's `desktop/Dockerfile` is the known-good reference implementation. It currently provides, among other things:

- Debian as the operating-system base;
- TigerVNC server and tools;
- XFCE desktop components;
- X11 support and keyboard data;
- D-Bus support;
- fonts and basic desktop utilities;
- `tini` as the container init process;
- the non-root `desktop` user;
- `DISPLAY=:1`;
- default geometry `1280x800`;
- default depth `24`;
- the project desktop entrypoint;
- the project desktop healthcheck;
- the project X startup script;
- VNC password-file handling;
- TCP port `5901` for VNC.

A custom image derived from this image inherits this plumbing automatically unless it deliberately replaces it.

## 4. Recommended workflow: derive from the stock desktop

First build the repository desktop as a reusable local base image:

```bash
docker build \
  --tag vnc-remote-control-desktop:base \
  desktop
```

Then create a custom Dockerfile such as `desktop/custom/firefox-discord.Dockerfile`:

```dockerfile
FROM vnc-remote-control-desktop:base

USER root

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        firefox-esr \
    && rm -rf /var/lib/apt/lists/*

# Install Discord or other applications here using a deliberately pinned,
# reviewed package source. Application-specific packaging is intentionally
# separate from the VNC/controller contract.

USER desktop:desktop
```

Build it:

```bash
docker build \
  --file desktop/custom/firefox-discord.Dockerfile \
  --tag my-firefox-discord-desktop:local \
  .
```

The important part is not the application list. The important part is that the derived image still starts the project desktop entrypoint and exposes the same working VNC environment.

Do not accidentally leave the final runtime user as `root`. The stock image intentionally runs the desktop as `desktop:desktop`.

## 5. Point Compose at the custom image

The simplest approach is a small Compose override. For example, create a local `compose.custom-desktop.yaml`:

```yaml
services:
  desktop:
    image: my-firefox-discord-desktop:local
    build: null
```

Then start the stack with the stock production topology plus the override:

```bash
docker compose \
  -f deploy/compose.yaml \
  -f compose.custom-desktop.yaml \
  up --detach --wait
```

Because the service is still named `desktop`, the stock controller configuration remains valid:

```text
VRC_VNC_HOST=desktop
VRC_VNC_PORT=5901
```

No Rust code and no Python code need to change.

If you intentionally use a different desktop service name, update the controller target explicitly:

```yaml
services:
  firefox_desktop:
    image: my-firefox-discord-desktop:local
    expose:
      - "5901"
    networks:
      - desktop_control

  controller:
    environment:
      VRC_VNC_HOST: firefox_desktop
      VRC_VNC_PORT: "5901"
```

The custom desktop must still receive the same VNC secret and preserve the required security and health configuration. In practice, retaining the service name `desktop` is simpler because it lets the existing Compose contract remain unchanged.

## 6. Minimum VNC desktop contract

A custom desktop target must satisfy all behavior that the controller depends on.

### Required connectivity

- The target is reachable from the controller container by `VRC_VNC_HOST:VRC_VNC_PORT`.
- The stock port is `5901`.
- The target and controller share a network that permits the connection.
- Production does not expose raw VNC publicly.

### Required authentication

- The VNC server accepts the configured password authentication used by the controller's LibVNCClient adapter.
- The controller reads its password from `VRC_VNC_PASSWORD_FILE`.
- The desktop receives the corresponding secret without embedding it in the image, URL, logs, or ordinary environment variables.

### Required framebuffer behavior

- The VNC server provides a coherent framebuffer.
- The desktop produces a complete frame before the controller is considered ready.
- The configured framebuffer fits within the controller's bounded framebuffer limit.
- The current tested format is the stock TigerVNC/XFCE configuration at 24-bit depth.

### Required input behavior

The target must correctly accept the RFB operations used by the API:

- pointer movement;
- mouse button press/release;
- click and double-click sequences;
- vertical scrolling;
- key press/release;
- key chords;
- text expressed through the supported keyboard contract.

### Clipboard behavior

If the `/v1/clipboard` API is expected to work, the VNC server and desktop environment must provide compatible RFB clipboard behavior in both directions.

A custom desktop without compatible clipboard support may still display pixels and accept input, but it does not satisfy the complete supported controller contract.

### Lifecycle behavior

- The container must stay alive while the desktop/VNC service is healthy.
- Startup failures must be visible rather than silently ignored.
- A meaningful healthcheck should fail when the usable VNC desktop is not ready.
- SIGTERM should permit orderly desktop and VNC shutdown.

## 7. Do not copy only the application layer and discard the contract

A Docker image that merely contains Firefox or Discord is not automatically a valid controller target.

For example, this is insufficient by itself:

```dockerfile
FROM debian:stable-slim
RUN apt-get update && apt-get install -y firefox-esr
```

It does not provide the required VNC server, graphical session, VNC authentication, startup behavior, healthcheck, non-root desktop user, or private-network contract.

Starting from `vnc-remote-control-desktop:base` avoids having to rebuild those pieces for every application variant.

## 8. Complete configuration example

A normal local deployment has this chain:

```text
Python process
    VncClient(
        base_url="http://127.0.0.1:8080",
        api_token=<API token>
    )
        |
        | HTTP / WebSocket
        v
controller service
    VRC_LISTEN_ADDR=0.0.0.0:8080
    VRC_VNC_HOST=desktop
    VRC_VNC_PORT=5901
    VRC_VNC_PASSWORD_FILE=/run/secrets/vnc_password
        |
        | private desktop_control network
        | RFB / VNC
        v
desktop service
    image=my-firefox-discord-desktop:local
    VNC password=<same VNC secret>
    TigerVNC=:1 / TCP 5901
    XFCE
    Firefox
    Discord
```

There are two different credentials:

- **API token:** authenticates the Python/HTTP client to the Rust controller.
- **VNC password:** authenticates the Rust controller to the VNC desktop.

They are not interchangeable and should remain separate secret files.

## 9. Python does not change when the desktop changes

Once the controller remains at the same HTTP address, swapping the desktop image does not require changing Python application code:

```python
client = VncClient("http://127.0.0.1:8080", api_token)
```

The same client can call status, screenshots, pointer, keyboard, clipboard, reconnect, metrics, and WebSocket event APIs regardless of which supported custom desktop image is behind the controller.

That separation is intentional:

```text
Python knows the controller API.
Controller knows the VNC target.
Desktop image knows its applications.
```

## 10. Validation after changing the desktop image

Do not treat a successful Docker build as proof that the target satisfies the VNC contract.

At minimum:

1. Start the stack and require Compose health to succeed.
2. Confirm `/health/live` returns `200`.
3. Confirm `/health/ready` returns `200` only after a current framebuffer exists.
4. Query `/v1/status` and `/v1/display`.
5. Fetch `/v1/screenshot.png` and inspect the image.
6. Exercise pointer movement and click.
7. Exercise keyboard key/chord/text input.
8. Exercise clipboard get/set if clipboard support is required.
9. Exercise reconnect and verify readiness drops and recovers correctly.
10. Stop the stack normally and verify clean shutdown.

For a desktop image intended to become repository-supported rather than merely local, run the repository's permanent quality and real integration suites and add target-specific tests where application or VNC behavior differs.

Do not weaken healthchecks, readiness, authentication, timeouts, or failure reporting to make an incompatible custom image appear healthy.

## 11. Security rules for custom images

Custom application images expand the software and network attack surface. Preserve the production security boundary:

- do not publish VNC port `5901` publicly;
- keep VNC on the private `desktop_control` network;
- keep the controller API on loopback or behind a trusted TLS reverse proxy;
- keep API and VNC credentials in secret files;
- do not bake credentials into an image;
- do not log credentials, clipboard contents, typed text, or screenshots;
- retain non-root runtime where practical;
- retain `no-new-privileges` and dropped capabilities unless a reviewed application requirement proves otherwise;
- review any extra package repositories or downloaded application packages;
- rebuild and rescan custom images when base images or installed applications change.

If an application requires a weaker container security setting, treat that as an explicit security change. Do not silently add privileges, host networking, broad device access, or capability restoration as a compatibility fallback.

## 12. Troubleshooting custom targets

### Controller cannot resolve the desktop

Render the final Compose configuration:

```bash
docker compose \
  -f deploy/compose.yaml \
  -f compose.custom-desktop.yaml \
  config
```

Verify that `VRC_VNC_HOST` matches the desktop service name or network alias and that both services share `desktop_control`.

### Controller reports authentication failure

Verify that the custom desktop and controller use the same VNC secret source. Do not print the secret value while troubleshooting.

### Liveness works but readiness does not

The HTTP process can be alive while the VNC target is unavailable or while no complete framebuffer exists. Check `/v1/status`, the desktop healthcheck, controller logs, desktop logs, VNC authentication, and framebuffer startup.

Do not replace readiness with liveness.

### Screenshot works but input does not

The target may not satisfy the same RFB input semantics as the tested TigerVNC desktop. Test pointer, key transitions, chords, and text independently. Do not silently emulate success in the controller or Python library.

### Clipboard does not work

Confirm that the custom VNC server and desktop environment support compatible RFB clipboard exchange. Clipboard compatibility is part of the full supported contract, not an automatic consequence of framebuffer support.

## 13. Related documentation

- [`../README.md`](../README.md): project overview and quick start.
- [`OPERATOR_GUIDE.md`](OPERATOR_GUIDE.md): supported deployment, lifecycle, recovery, resource limits, and troubleshooting.
- [`../deploy/README.md`](../deploy/README.md): production Compose topology and deployment modes.
- [`../python/README.md`](../python/README.md): Python client installation and usage.
- [`openapi.json`](openapi.json): machine-readable HTTP API contract.
- [`WEBSOCKET_EVENTS.md`](WEBSOCKET_EVENTS.md): WebSocket event contract.

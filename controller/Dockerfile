# syntax=docker/dockerfile:1.7

FROM rust:1.97.1-slim-trixie@sha256:fc0648ac2962539be80bd424729a20fd80f7b64bfba7e90bbd642aed6c697c5a AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        build-essential \
        libvncserver-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY Cargo.toml Cargo.lock rust-toolchain.toml ./
COPY crates ./crates
COPY docs/openapi.json ./docs/openapi.json

RUN cargo build --locked --release --package controller-api --bin controller-api \
    && strip /workspace/target/release/controller-api

FROM debian:13.6-slim@sha256:3a39a0592364683e6bab97937b72cad5a8fa6dcbbee90edb3bb48c7f8e94f258 AS runtime

ARG CONTROLLER_UID=10002
ARG CONTROLLER_GID=10002

ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/nonexistent \
    VRC_LISTEN_ADDR=0.0.0.0:8080 \
    VRC_API_TOKEN_FILE=/run/secrets/api_token \
    VRC_VNC_HOST=desktop \
    VRC_VNC_PORT=5901 \
    VRC_VNC_PASSWORD_FILE=/run/secrets/vnc_password

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        curl \
        libvncclient1 \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid "${CONTROLLER_GID}" controller \
    && useradd --system \
        --uid "${CONTROLLER_UID}" \
        --gid "${CONTROLLER_GID}" \
        --home-dir /nonexistent \
        --no-create-home \
        --shell /usr/sbin/nologin \
        controller

COPY --from=builder --chown=root:root /workspace/target/release/controller-api /usr/local/bin/controller-api
COPY --chown=root:root controller/healthcheck.sh /usr/local/bin/controller-healthcheck

RUN chmod 0755 /usr/local/bin/controller-api /usr/local/bin/controller-healthcheck

USER controller:controller
WORKDIR /nonexistent

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=6 \
    CMD ["/usr/local/bin/controller-healthcheck", "live"]

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/controller-api"]

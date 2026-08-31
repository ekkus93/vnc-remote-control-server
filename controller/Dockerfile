# syntax=docker/dockerfile:1.7

FROM rust:1.98.0-slim-trixie@sha256:cc0448b41c3b7b7fea44f5dc50eacba729a56db365b65b7bd5e8a82d5b3db078 AS builder

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

FROM debian:13.6-slim@sha256:020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd AS runtime

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

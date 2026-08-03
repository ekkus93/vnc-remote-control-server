FROM debian:13.6-slim

ARG DESKTOP_UID=10001
ARG DESKTOP_GID=10001

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:1 \
    VNC_GEOMETRY=1280x800 \
    VNC_DEPTH=24 \
    VNC_PASSWORD_FILE=/run/secrets/vnc_password \
    TEST_APP_STATE_FILE=/tmp/vnc-test-app-state.json

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        adwaita-icon-theme \
        dbus-x11 \
        fonts-dejavu-core \
        netcat-openbsd \
        procps \
        python3 \
        python3-tk \
        thunar \
        tigervnc-common \
        tigervnc-standalone-server \
        tini \
        x11-utils \
        x11-xkb-utils \
        xauth \
        xfonts-base \
        xfce4-panel \
        xfce4-session \
        xfce4-settings \
        xfce4-terminal \
        xfconf \
        xfdesktop4 \
        xfwm4 \
        xkb-data \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${DESKTOP_GID}" desktop \
    && useradd --create-home --home-dir /home/desktop --uid "${DESKTOP_UID}" --gid "${DESKTOP_GID}" --shell /bin/bash desktop \
    && install -d -o desktop -g desktop -m 0700 /home/desktop/.vnc

COPY --chown=root:root entrypoint.sh /usr/local/bin/desktop-entrypoint
COPY --chown=root:root healthcheck.sh /usr/local/bin/desktop-healthcheck
COPY --chown=root:root xstartup /usr/local/bin/xstartup
COPY --chown=desktop:desktop test-app/test_app.py /opt/vnc-test-app/test_app.py

RUN chmod 0755 \
        /usr/local/bin/desktop-entrypoint \
        /usr/local/bin/desktop-healthcheck \
        /usr/local/bin/xstartup \
        /opt/vnc-test-app/test_app.py

USER desktop:desktop
WORKDIR /home/desktop

EXPOSE 5901

HEALTHCHECK --interval=5s --timeout=3s --start-period=30s --retries=6 \
    CMD ["/usr/local/bin/desktop-healthcheck", "ready"]

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/desktop-entrypoint"]

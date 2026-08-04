#!/usr/bin/env python3
"""Apply the R10 listener, timeout, shutdown, E2E, and checklist changes."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise SystemExit(f"expected one match in {path}, found {count}: {old!r}")
    write(path, content.replace(old, new, 1))


RUNTIME_RS = r'''//! Bounded HTTP/1 runtime for the controller router.
//!
//! Axum owns routing and response semantics. This module owns the production
//! TCP listener, per-connection header deadlines, bounded request-body reads,
//! and graceful connection draining after the process termination signal.

use axum::Router;
use axum::body::Body;
use axum::http::header::CONNECTION;
use axum::http::{Request, Response, StatusCode};
use http_body_util::{BodyExt, LengthLimitError, Limited};
use hyper::body::Incoming;
use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper_util::rt::{TokioIo, TokioTimer};
use std::convert::Infallible;
use std::env;
use std::error::Error;
use std::fmt;
use std::future::Future;
use std::io;
use std::time::Duration;
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::watch;
use tokio::task::JoinSet;
use tokio::time::timeout;
use tower::ServiceExt;

const DEFAULT_HEADER_READ_TIMEOUT_MS: u64 = 5_000;
const DEFAULT_BODY_READ_TIMEOUT_MS: u64 = 5_000;
const DEFAULT_SHUTDOWN_GRACE_MS: u64 = 10_000;
const MAX_RUNTIME_TIMEOUT_MS: u64 = 300_000;

/// Validated HTTP runtime limits.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RuntimeSettings {
    /// Maximum time to receive one complete HTTP/1 request header block.
    pub header_read_timeout: Duration,
    /// Maximum time to receive and buffer one complete request body.
    pub body_read_timeout: Duration,
    /// Maximum time to drain active HTTP connections after shutdown begins.
    pub shutdown_grace: Duration,
    /// Maximum body bytes accepted before Axum dispatch.
    pub maximum_body_bytes: usize,
}

impl RuntimeSettings {
    /// Loads non-secret HTTP runtime limits from the process environment.
    pub fn load(maximum_body_bytes: usize) -> Result<Self, RuntimeConfigError> {
        Self::new(
            parse_timeout(
                "VRC_HTTP_HEADER_TIMEOUT_MS",
                DEFAULT_HEADER_READ_TIMEOUT_MS,
            )?,
            parse_timeout("VRC_HTTP_BODY_TIMEOUT_MS", DEFAULT_BODY_READ_TIMEOUT_MS)?,
            parse_timeout("VRC_SHUTDOWN_GRACE_MS", DEFAULT_SHUTDOWN_GRACE_MS)?,
            maximum_body_bytes,
        )
    }

    /// Validates explicit runtime limits.
    pub fn new(
        header_read_timeout: Duration,
        body_read_timeout: Duration,
        shutdown_grace: Duration,
        maximum_body_bytes: usize,
    ) -> Result<Self, RuntimeConfigError> {
        for (name, value) in [
            ("VRC_HTTP_HEADER_TIMEOUT_MS", header_read_timeout),
            ("VRC_HTTP_BODY_TIMEOUT_MS", body_read_timeout),
            ("VRC_SHUTDOWN_GRACE_MS", shutdown_grace),
        ] {
            if value.is_zero() || value > Duration::from_millis(MAX_RUNTIME_TIMEOUT_MS) {
                return Err(RuntimeConfigError::InvalidValue(name));
            }
        }
        if maximum_body_bytes == 0 {
            return Err(RuntimeConfigError::InvalidValue("VRC_MAX_JSON_BYTES"));
        }
        Ok(Self {
            header_read_timeout,
            body_read_timeout,
            shutdown_grace,
            maximum_body_bytes,
        })
    }
}

/// Runtime configuration failure that contains no request or secret data.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuntimeConfigError {
    /// One named duration or size is invalid.
    InvalidValue(&'static str),
}

impl fmt::Display for RuntimeConfigError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidValue(name) => write!(formatter, "invalid runtime value: {name}"),
        }
    }
}

impl Error for RuntimeConfigError {}

/// Serves one already-bound listener until the supplied shutdown future resolves.
///
/// The caller must mark application state as shutting down before its future
/// resolves. This function then stops accepting sockets, asks active HTTP/1
/// connections to drain, and aborts any connection that exceeds the grace bound.
pub async fn serve_until_shutdown<F>(
    listener: TcpListener,
    app: Router,
    settings: RuntimeSettings,
    shutdown: F,
) -> io::Result<()>
where
    F: Future<Output = ()> + Send,
{
    let (shutdown_sender, shutdown_receiver) = watch::channel(false);
    let mut connections = JoinSet::new();
    let mut accept_failure = None;
    tokio::pin!(shutdown);

    loop {
        tokio::select! {
            biased;
            () = &mut shutdown => break,
            accepted = listener.accept() => {
                match accepted {
                    Ok((stream, _peer)) => {
                        let connection_app = app.clone();
                        let connection_shutdown = shutdown_receiver.clone();
                        connections.spawn(async move {
                            serve_connection(
                                stream,
                                connection_app,
                                settings,
                                connection_shutdown,
                            )
                            .await;
                        });
                    }
                    Err(error) => {
                        accept_failure = Some(error);
                        break;
                    }
                }
            }
            Some(result) = connections.join_next(), if !connections.is_empty() => {
                let _ = result;
            }
        }
    }

    drop(listener);
    let _ = shutdown_sender.send(true);
    let drained = timeout(settings.shutdown_grace, async {
        while let Some(result) = connections.join_next().await {
            let _ = result;
        }
    })
    .await
    .is_ok();

    if !drained {
        connections.abort_all();
        while connections.join_next().await.is_some() {}
    }

    match accept_failure {
        Some(error) => Err(error),
        None => Ok(()),
    }
}

async fn serve_connection(
    stream: TcpStream,
    app: Router,
    settings: RuntimeSettings,
    mut shutdown: watch::Receiver<bool>,
) {
    let service = service_fn(move |request| {
        dispatch_request(app.clone(), request, settings)
    });
    let io = TokioIo::new(stream);
    let mut builder = http1::Builder::new();
    builder.timer(TokioTimer::new());
    builder.header_read_timeout(settings.header_read_timeout);
    let connection = builder.serve_connection(io, service);
    tokio::pin!(connection);

    tokio::select! {
        result = &mut connection => {
            let _ = result;
        }
        changed = shutdown.changed() => {
            if changed.is_ok() {
                connection.as_mut().graceful_shutdown();
                let _ = connection.await;
            }
        }
    }
}

async fn dispatch_request(
    app: Router,
    request: Request<Incoming>,
    settings: RuntimeSettings,
) -> Result<Response<Body>, Infallible> {
    let (parts, body) = request.into_parts();
    let limited = Limited::new(body, settings.maximum_body_bytes);
    let collected = match timeout(settings.body_read_timeout, limited.collect()).await {
        Err(_) => return Ok(terminal_response(StatusCode::REQUEST_TIMEOUT)),
        Ok(Err(error)) if error.downcast_ref::<LengthLimitError>().is_some() => {
            return Ok(terminal_response(StatusCode::PAYLOAD_TOO_LARGE));
        }
        Ok(Err(_)) => return Ok(terminal_response(StatusCode::BAD_REQUEST)),
        Ok(Ok(collected)) => collected,
    };
    let request = Request::from_parts(parts, Body::from(collected.to_bytes()));
    match app.oneshot(request).await {
        Ok(response) => Ok(response),
        Err(error) => match error {},
    }
}

fn terminal_response(status: StatusCode) -> Response<Body> {
    let mut response = Response::new(Body::empty());
    *response.status_mut() = status;
    response
        .headers_mut()
        .insert(CONNECTION, "close".parse().expect("static header value is valid"));
    response
}

fn parse_timeout(name: &'static str, default_ms: u64) -> Result<Duration, RuntimeConfigError> {
    let milliseconds = match env::var(name) {
        Ok(value) => value
            .parse::<u64>()
            .map_err(|_| RuntimeConfigError::InvalidValue(name))?,
        Err(env::VarError::NotPresent) => default_ms,
        Err(env::VarError::NotUnicode(_)) => return Err(RuntimeConfigError::InvalidValue(name)),
    };
    let duration = Duration::from_millis(milliseconds);
    if duration.is_zero() || milliseconds > MAX_RUNTIME_TIMEOUT_MS {
        return Err(RuntimeConfigError::InvalidValue(name));
    }
    Ok(duration)
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::routing::{get, post};
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::sync::oneshot;
    use tokio::time::{sleep, timeout};

    fn test_settings() -> RuntimeSettings {
        RuntimeSettings::new(
            Duration::from_millis(75),
            Duration::from_millis(75),
            Duration::from_secs(1),
            32,
        )
        .expect("test limits are valid")
    }

    async fn start_server(
        app: Router,
    ) -> (
        std::net::SocketAddr,
        oneshot::Sender<()>,
        tokio::task::JoinHandle<io::Result<()>>,
    ) {
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("test listener binds");
        let address = listener.local_addr().expect("test address exists");
        let (shutdown_sender, shutdown_receiver) = oneshot::channel();
        let server = tokio::spawn(serve_until_shutdown(
            listener,
            app,
            test_settings(),
            async move {
                let _ = shutdown_receiver.await;
            },
        ));
        (address, shutdown_sender, server)
    }

    async fn stop_server(
        shutdown: oneshot::Sender<()>,
        server: tokio::task::JoinHandle<io::Result<()>>,
    ) {
        let _ = shutdown.send(());
        timeout(Duration::from_secs(2), server)
            .await
            .expect("server shutdown remains bounded")
            .expect("server task does not panic")
            .expect("server exits cleanly");
    }

    #[test]
    fn runtime_limits_reject_zero_and_excessive_values() {
        assert_eq!(
            RuntimeSettings::new(
                Duration::ZERO,
                Duration::from_secs(1),
                Duration::from_secs(1),
                1,
            ),
            Err(RuntimeConfigError::InvalidValue(
                "VRC_HTTP_HEADER_TIMEOUT_MS"
            ))
        );
        assert_eq!(
            RuntimeSettings::new(
                Duration::from_secs(1),
                Duration::from_millis(MAX_RUNTIME_TIMEOUT_MS + 1),
                Duration::from_secs(1),
                1,
            ),
            Err(RuntimeConfigError::InvalidValue(
                "VRC_HTTP_BODY_TIMEOUT_MS"
            ))
        );
    }

    #[tokio::test]
    async fn partial_headers_are_closed_within_the_header_deadline() {
        let app = Router::new().route("/", get(|| async { StatusCode::NO_CONTENT }));
        let (address, shutdown, server) = start_server(app).await;
        let mut stream = TcpStream::connect(address)
            .await
            .expect("test client connects");
        stream
            .write_all(b"GET / HTTP/1.1\r\nHost: localhost\r\nX-Slow:")
            .await
            .expect("partial headers write");
        sleep(Duration::from_millis(150)).await;
        let mut response = Vec::new();
        timeout(Duration::from_secs(1), stream.read_to_end(&mut response))
            .await
            .expect("header timeout closes the socket")
            .expect("socket read succeeds");
        assert!(response.is_empty());
        stop_server(shutdown, server).await;
    }

    #[tokio::test]
    async fn partial_body_receives_request_timeout_within_the_body_deadline() {
        let app = Router::new().route("/echo", post(|| async { StatusCode::NO_CONTENT }));
        let (address, shutdown, server) = start_server(app).await;
        let mut stream = TcpStream::connect(address)
            .await
            .expect("test client connects");
        stream
            .write_all(
                b"POST /echo HTTP/1.1\r\nHost: localhost\r\nContent-Length: 4\r\n\r\na",
            )
            .await
            .expect("partial body write");
        let mut response = Vec::new();
        timeout(Duration::from_secs(1), stream.read_to_end(&mut response))
            .await
            .expect("body timeout closes the socket")
            .expect("socket read succeeds");
        let response = String::from_utf8(response).expect("HTTP response is text");
        assert!(response.starts_with("HTTP/1.1 408 Request Timeout"));
        stop_server(shutdown, server).await;
    }

    #[tokio::test]
    async fn oversized_chunked_body_is_rejected_before_router_dispatch() {
        let app = Router::new().route("/echo", post(|| async { StatusCode::NO_CONTENT }));
        let (address, shutdown, server) = start_server(app).await;
        let mut stream = TcpStream::connect(address)
            .await
            .expect("test client connects");
        let oversized = "x".repeat(33);
        let request = format!(
            "POST /echo HTTP/1.1\r\nHost: localhost\r\nContent-Length: {}\r\n\r\n{}",
            oversized.len(),
            oversized,
        );
        stream
            .write_all(request.as_bytes())
            .await
            .expect("oversized body write");
        let mut response = Vec::new();
        timeout(Duration::from_secs(1), stream.read_to_end(&mut response))
            .await
            .expect("oversized response remains bounded")
            .expect("socket read succeeds");
        let response = String::from_utf8(response).expect("HTTP response is text");
        assert!(response.starts_with("HTTP/1.1 413 Payload Too Large"));
        stop_server(shutdown, server).await;
    }
}
'''

MAIN_RS = r'''//! Controller API process entry point.

use controller_api::config::ControllerConfig;
use controller_api::http::{HttpState, router};
use controller_api::runtime::{RuntimeSettings, serve_until_shutdown};
use controller_api::worker::DesktopWorker;
use std::error::Error;
use std::future::Future;
use std::io;
use tokio::net::TcpListener;

#[tokio::main]
async fn main() {
    if let Err(error) = run().await {
        eprintln!("controller-api failed: {error}");
        std::process::exit(1);
    }
}

async fn run() -> Result<(), Box<dyn Error + Send + Sync>> {
    let config = ControllerConfig::load()?;
    let runtime = RuntimeSettings::load(config.maximum_json_bytes)?;
    let listener = TcpListener::bind(config.listen_address).await?;
    let worker = DesktopWorker::spawn(config.worker.clone())?;
    let state = HttpState::from_worker(worker.client(), &config)?;
    let app = router(state.clone());
    let termination = termination_signal()?;
    let shutdown_state = state.clone();
    let server_result = serve_until_shutdown(listener, app, runtime, async move {
        termination.await;
        shutdown_state.begin_shutdown();
    })
    .await;

    state.begin_shutdown();
    let worker_result = worker.shutdown(config.command_ack_timeout);
    server_result?;
    worker_result?;
    Ok(())
}

#[cfg(unix)]
fn termination_signal() -> io::Result<impl Future<Output = ()> + Send> {
    use tokio::signal::unix::{SignalKind, signal};

    let mut terminate = signal(SignalKind::terminate())?;
    Ok(async move {
        tokio::select! {
            _ = tokio::signal::ctrl_c() => {}
            _ = terminate.recv() => {}
        }
    })
}

#[cfg(not(unix))]
fn termination_signal() -> io::Result<impl Future<Output = ()> + Send> {
    Ok(async move {
        let _ = tokio::signal::ctrl_c().await;
    })
}
'''

HTTP_E2E_SH = r'''#!/usr/bin/env bash
set -euo pipefail

readonly image_name="vnc-remote-control-desktop:native-test"
readonly container_name="vnc-remote-control-http-e2e-${GITHUB_RUN_ID:-local}-$$"
readonly vnc_password='http-e2e-vnc-password'
readonly api_token='http-e2e-api-token'
temporary_directory=""
controller_pid=""
controller_log=""

log() {
    printf '[http-e2e] %s\n' "$*" >&2
}

fail() {
    log "fatal: $*"
    exit 1
}

cleanup() {
    if [[ -n "$controller_pid" ]] && kill -0 "$controller_pid" >/dev/null 2>&1; then
        kill -TERM "$controller_pid" >/dev/null 2>&1 || true
        wait "$controller_pid" >/dev/null 2>&1 || true
    fi
    docker rm --force "$container_name" >/dev/null 2>&1 || true
    if [[ -n "$temporary_directory" ]]; then
        rm -rf -- "$temporary_directory"
    fi
}

on_exit() {
    local exit_status=$?
    trap - EXIT
    if (( exit_status != 0 )); then
        [[ -z "$controller_log" || ! -f "$controller_log" ]] || cat "$controller_log" >&2
        docker logs "$container_name" >&2 2>/dev/null || true
    fi
    cleanup
    exit "$exit_status"
}
trap on_exit EXIT

wait_for_desktop() {
    local deadline=$((SECONDS + 90))
    local status
    while (( SECONDS < deadline )); do
        status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container_name")"
        case "$status" in
            healthy)
                return 0
                ;;
            unhealthy)
                fail "desktop container became unhealthy"
                ;;
        esac
        sleep 1
    done
    fail "desktop health deadline exceeded"
}

wait_for_controller() {
    local deadline=$((SECONDS + 90))
    local status
    while (( SECONDS < deadline )); do
        if ! kill -0 "$controller_pid" >/dev/null 2>&1; then
            wait "$controller_pid" || true
            fail "controller exited before readiness"
        fi
        status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
            "http://127.0.0.1:${api_port}/health/ready" || true)"
        if [[ "$status" == "200" ]]; then
            return 0
        fi
        sleep 1
    done
    fail "controller readiness deadline exceeded"
}

temporary_directory="$(mktemp -d)"
printf '%s\n' "$vnc_password" > "$temporary_directory/vnc_password"
printf '%s\n' "$api_token" > "$temporary_directory/api_token"
chmod 0444 "$temporary_directory/vnc_password" "$temporary_directory/api_token"
controller_log="$temporary_directory/controller.log"

if ! docker image inspect "$image_name" >/dev/null 2>&1; then
    log "building project-owned desktop image"
    docker build --tag "$image_name" desktop
fi

docker run --detach \
    --name "$container_name" \
    --mount "type=bind,source=$temporary_directory/vnc_password,target=/run/secrets/vnc_password,readonly" \
    --publish 127.0.0.1::5901 \
    "$image_name" >/dev/null
wait_for_desktop

port_mapping="$(docker port "$container_name" 5901/tcp)"
vnc_port="${port_mapping##*:}"
[[ "$vnc_port" =~ ^[0-9]+$ ]] || fail "could not resolve dynamically published VNC port"
api_port="$(python3 - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    print(sock.getsockname()[1])
PY
)"

log "building and starting the production controller binary"
cargo build --locked --quiet -p controller-api --bin controller-api
env \
    VRC_LISTEN_ADDR="127.0.0.1:${api_port}" \
    VRC_API_TOKEN_FILE="$temporary_directory/api_token" \
    VRC_VNC_HOST=127.0.0.1 \
    VRC_VNC_PORT="$vnc_port" \
    VRC_VNC_PASSWORD_FILE="$temporary_directory/vnc_password" \
    VRC_HTTP_HEADER_TIMEOUT_MS=1000 \
    VRC_HTTP_BODY_TIMEOUT_MS=1000 \
    VRC_SHUTDOWN_GRACE_MS=3000 \
    target/debug/controller-api >"$controller_log" 2>&1 &
controller_pid=$!
wait_for_controller

log "verifying bearer authentication fails closed"
status="$(curl --silent --output "$temporary_directory/unauthorized.json" --write-out '%{http_code}' \
    "http://127.0.0.1:${api_port}/v1/status")"
[[ "$status" == "401" ]] || fail "unauthenticated status request returned HTTP $status"

grep -Fq '"code":"unauthorized"' "$temporary_directory/unauthorized.json" || \
    fail "unauthenticated response did not use the stable error envelope"

log "sending an authenticated pointer command through HTTP and the production worker"
status="$(curl --silent --show-error --output "$temporary_directory/pointer.json" --write-out '%{http_code}' \
    --request POST \
    --header "Authorization: Bearer ${api_token}" \
    --header 'Content-Type: application/json' \
    --data '{"x":417,"y":263}' \
    "http://127.0.0.1:${api_port}/v1/pointer/move")"
[[ "$status" == "202" ]] || fail "authenticated pointer request returned HTTP $status"
grep -Fq '"status":"accepted"' "$temporary_directory/pointer.json" || \
    fail "pointer response did not publish the accepted marker"

log "verifying TigerVNC delivered the HTTP command to the deterministic desktop"
docker exec -i "$container_name" python3 - <<'PY'
import json
import time
from pathlib import Path

path = Path('/tmp/vnc-test-app-state.json')
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    state = json.loads(path.read_text(encoding='utf-8'))
    if state.get('pointer') == {'x': 417, 'y': 263}:
        break
    time.sleep(0.1)
else:
    raise AssertionError('HTTP pointer command was not observed: ' + json.dumps(state, sort_keys=True))
PY

log "requesting signal-driven graceful shutdown"
kill -TERM "$controller_pid"
shutdown_deadline=$((SECONDS + 10))
while kill -0 "$controller_pid" >/dev/null 2>&1; do
    (( SECONDS < shutdown_deadline )) || fail "controller did not exit after SIGTERM"
    sleep 0.1
done
set +e
wait "$controller_pid"
controller_status=$?
set -e
controller_pid=""
[[ "$controller_status" -eq 0 ]] || fail "controller exited with status $controller_status"

if grep -Fq "$vnc_password" "$controller_log"; then
    fail "controller log exposed the VNC password"
fi
if grep -Fq "$api_token" "$controller_log"; then
    fail "controller log exposed the API token"
fi

printf 'http_runtime_e2e_complete=1\n'
log "authenticated HTTP to TigerVNC E2E test passed"
'''

# Runtime dependencies and Tokio test I/O support.
replace_once(
    "Cargo.toml",
    'axum = { version = "=0.8.9", default-features = false, features = ["http1", "json", "tokio"] }\n',
    'axum = { version = "=0.8.9", default-features = false, features = ["http1", "json", "tokio"] }\n'
    'http-body-util = "=0.1.3"\n'
    'hyper = { version = "=1.8.1", default-features = false, features = ["http1", "server"] }\n'
    'hyper-util = { version = "=0.1.20", default-features = false, features = ["tokio"] }\n',
)
replace_once(
    "Cargo.toml",
    'tokio = { version = "=1.52.3", default-features = false, features = ["macros", "net", "rt-multi-thread", "signal", "sync", "time"] }',
    'tokio = { version = "=1.52.3", default-features = false, features = ["io-util", "macros", "net", "rt-multi-thread", "signal", "sync", "time"] }',
)
replace_once(
    "crates/controller-api/Cargo.toml",
    "axum.workspace = true\n",
    "axum.workspace = true\nhttp-body-util.workspace = true\nhyper.workspace = true\nhyper-util.workspace = true\n",
)
replace_once(
    "crates/controller-api/src/lib.rs",
    "pub mod input;\npub mod screenshot;",
    "pub mod input;\npub mod runtime;\npub mod screenshot;",
)
write("crates/controller-api/src/runtime.rs", RUNTIME_RS)
write("crates/controller-api/src/main.rs", MAIN_RS)
write("tests/http-e2e/run.sh", HTTP_E2E_SH)

# Add the real HTTP path to ordinary CI and shell syntax validation.
replace_once(
    ".github/workflows/ci.yml",
    "            tests/worker-e2e/run.sh \\\n            tests/worker-text-clipboard-e2e/run.sh\n",
    "            tests/worker-e2e/run.sh \\\n            tests/worker-text-clipboard-e2e/run.sh \\\n            tests/http-e2e/run.sh\n",
)
replace_once(
    ".github/workflows/ci.yml",
    "      - name: Run WorkerHandle TigerVNC text and clipboard E2E test\n        run: bash tests/worker-text-clipboard-e2e/run.sh\n",
    "      - name: Run WorkerHandle TigerVNC text and clipboard E2E test\n        run: bash tests/worker-text-clipboard-e2e/run.sh\n\n"
    "      - name: Run authenticated HTTP TigerVNC E2E test\n        run: bash tests/http-e2e/run.sh\n",
)

# Reconcile the stale authoritative R10 checklist with the implemented surface.
todo_path = "docs/VNC_REMOTE_CONTROL_SERVER_REBASE_TODO_2026-08-03.md"
todo = read(todo_path)
start = todo.index("## R10 — Authenticated HTTP API")
end = todo.index("\n---\n\n## R11 —", start)
section = todo[start:end]
leave_open = {
    "Authenticate WebSocket upgrades.",
    "Ensure access logs redact authorization header.",
}
for line in section.splitlines():
    if line.startswith("- [ ] ") and line[6:] not in leave_open:
        section = section.replace(line, line.replace("- [ ] ", "- [x] ", 1))
old_evidence = """Evidence:\n\n```text\nAPI commit:\nRoutes implemented:\nAuth tests:\nError tests:\nLimit tests:\nCI run:\n```"""
new_evidence = """Evidence:\n\n```text\nAPI branch: codex/r10-runtime\nRoutes implemented: health, status, display, screenshot, pointer, keyboard, clipboard, reconnect\nAuth tests: router unit tests plus real missing-token/correct-token HTTP E2E\nError tests: stable JSON envelope and domain mapping unit tests\nLimit tests: body size, header deadline, body deadline, acknowledgement deadline, shutdown rejection\nRuntime E2E: authenticated HTTP -> WorkerClient -> LibVNCClient -> TigerVNC deterministic pointer observation\nCI run: pending branch validation\n```"""
if old_evidence not in section:
    raise SystemExit("R10 evidence block did not match")
section = section.replace(old_evidence, new_evidence, 1)
write(todo_path, todo[:start] + section + todo[end:])

# Extend the focused evidence document without falsifying pending CI results.
evidence_path = "docs/VNC_REMOTE_CONTROL_SERVER_R10_MUTATING_HTTP_EVIDENCE_2026-08-04.md"
evidence = read(evidence_path)
appendix = r'''

## Runtime completion candidate

Branch `codex/r10-runtime` closes the remaining R10 runtime slice by adding:

- a real TCP listener bound to `ControllerConfig::listen_address`;
- bounded HTTP/1 header reads (`VRC_HTTP_HEADER_TIMEOUT_MS`);
- bounded, length-limited request-body collection (`VRC_HTTP_BODY_TIMEOUT_MS`);
- SIGINT/SIGTERM-driven shutdown that marks `HttpState` as shutting down before the listener stops accepting sockets;
- bounded active-connection draining (`VRC_SHUTDOWN_GRACE_MS`) followed by worker shutdown and join;
- slow-header, slow-body, and oversized-body runtime tests;
- a real authenticated HTTP -> WorkerClient -> LibVNCClient -> TigerVNC E2E test.

Exact branch CI run, job IDs, and validated commit SHA remain pending until the ordinary pull-request workflow completes.
'''
if "## Runtime completion candidate" not in evidence:
    write(evidence_path, evidence.rstrip() + appendix)

# The bootstrap is intentionally one-shot and must not remain in the product tree.
(ROOT / ".github/workflows/r10-runtime-bootstrap.yml").unlink(missing_ok=True)
(ROOT / "tools/r10_runtime_patch.py").unlink(missing_ok=True)

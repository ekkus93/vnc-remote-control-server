//! Bounded HTTP/1 runtime for the controller router.
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
use tower::util::ServiceExt;

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
            parse_timeout("VRC_HTTP_HEADER_TIMEOUT_MS", DEFAULT_HEADER_READ_TIMEOUT_MS)?,
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
    let service = service_fn(move |request| dispatch_request(app.clone(), request, settings));
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
    response.headers_mut().insert(
        CONNECTION,
        "close".parse().expect("static header value is valid"),
    );
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
            Err(RuntimeConfigError::InvalidValue("VRC_HTTP_BODY_TIMEOUT_MS"))
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
            .write_all(b"POST /echo HTTP/1.1\r\nHost: localhost\r\nContent-Length: 4\r\n\r\na")
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

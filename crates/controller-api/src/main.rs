//! Controller API process entry point.

use controller_api::config::ControllerConfig;
use controller_api::duration_policy::validate_startup_durations;
use controller_api::events::EventHub;
use controller_api::http::{HttpState, HttpWorkerSettings, router};
use controller_api::observability::{Metrics, init_tracing};
use controller_api::runtime::{RuntimeSettings, serve_until_shutdown};
use controller_api::shutdown::finalize_runtime;
use controller_api::worker::DesktopWorker;
use std::error::Error;
use std::future::Future;
use std::io;
use tokio::net::TcpListener;

#[tokio::main]
async fn main() {
    if let Err(error) = init_tracing() {
        eprintln!("controller tracing initialization failed: {error}");
        std::process::exit(1);
    }
    if let Err(error) = run().await {
        tracing::error!(error = %error, "controller_api_failed");
        std::process::exit(1);
    }
}

async fn run() -> Result<(), Box<dyn Error + Send + Sync>> {
    let config = ControllerConfig::load()?;
    validate_startup_durations(&config)?;
    let ControllerConfig {
        listen_address,
        api_token,
        process_instance,
        maximum_json_bytes,
        command_ack_timeout,
        shutdown_timeout,
        screenshot_concurrency,
        screenshot_timeout,
        websocket_event_capacity,
        websocket_max_clients,
        websocket_ping_interval,
        websocket_idle_timeout,
        worker: worker_settings,
    } = config;

    let runtime = RuntimeSettings::load(maximum_json_bytes)?;
    let listener = TcpListener::bind(listen_address).await?;
    let mut worker = DesktopWorker::spawn(worker_settings)?;
    let metrics = Metrics::default();
    let (event_hub, event_bridge) = EventHub::start(
        worker.take_events()?,
        websocket_event_capacity,
        websocket_max_clients,
        websocket_ping_interval,
        websocket_idle_timeout,
        metrics.clone(),
    )?;
    let state = HttpState::from_worker(
        worker.client(),
        event_hub,
        metrics,
        HttpWorkerSettings {
            api_token,
            process_instance,
            maximum_json_bytes,
            command_ack_timeout,
            screenshot_concurrency,
            screenshot_timeout,
        },
    )?;
    let app = router(state.clone());
    let termination = termination_signal()?;
    let shutdown_state = state.clone();
    let server_result = serve_until_shutdown(listener, app, runtime, async move {
        termination.await;
        shutdown_state.begin_shutdown();
    })
    .await;

    state.begin_shutdown();
    finalize_runtime(server_result, worker, event_bridge, shutdown_timeout)?;
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

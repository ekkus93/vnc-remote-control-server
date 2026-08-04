//! Controller API process entry point.

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

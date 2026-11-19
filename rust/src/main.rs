//! nfl-webd binary: fantasy-page front door + reverse proxy to the Python
//! compute backend (the jra-van-re jv-webd method).

use nfl_webd::{router, Config};

/// ctrl-c + SIGTERM (matches jv-webd's graceful-shutdown pattern).
async fn shutdown_signal() {
    let ctrl_c = tokio::signal::ctrl_c();
    #[cfg(unix)]
    {
        let mut term = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
            .expect("SIGTERM handler");
        tokio::select! {
            _ = ctrl_c => {}
            _ = term.recv() => {}
        }
    }
    #[cfg(not(unix))]
    ctrl_c.await.expect("ctrl-c handler");
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();

    let cfg = Config::from_env();
    let listener = match tokio::net::TcpListener::bind(&cfg.bind).await {
        Ok(l) => l,
        Err(e) => {
            tracing::error!("bind {}: {e}", cfg.bind);
            std::process::exit(1);
        }
    };
    tracing::info!(
        "nfl-webd on {} — backend={} root={}",
        cfg.bind,
        cfg.backend,
        cfg.root.display()
    );
    // ConnectInfo so the proxy can set X-Forwarded-For from the real peer.
    axum::serve(
        listener,
        router(cfg).into_make_service_with_connect_info::<std::net::SocketAddr>(),
    )
    .with_graceful_shutdown(shutdown_signal())
    .await
    .expect("serve");
}

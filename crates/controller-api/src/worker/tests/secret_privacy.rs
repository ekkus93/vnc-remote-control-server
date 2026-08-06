use super::*;

const PASSWORD_SENTINEL: &str = "vnc-password-private-e74a91c3";

#[test]
fn native_failure_json_logs_exclude_vnc_password_sentinel() {
    let mut config = settings();
    config.native.password = SecretString::from(PASSWORD_SENTINEL);

    let ((), records) = crate::test_support::capture_json_logs(|| {
        let worker = DesktopWorker::spawn_with_factory(config, || {
            Err::<MockSession, _>(NativeError::NativeFailure {
                message: format!(
                    "VNC protocol initialization failed: {PASSWORD_SENTINEL}"
                ),
            })
        })
        .expect("worker spawns");
        let client = worker.client();
        wait_for_state(&client, ConnectionState::AuthenticationFailed);
        worker
            .shutdown(Duration::from_secs(1))
            .expect("worker joins after authentication failure");
    });

    assert!(crate::test_support::json_logs_contain(
        &records,
        "worker_failure_recorded"
    ));
    assert!(
        !crate::test_support::json_logs_contain(&records, PASSWORD_SENTINEL),
        "structured worker log leaked VNC password sentinel"
    );
}

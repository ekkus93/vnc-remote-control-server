use controller_api::runtime::RuntimeSettings;
use std::time::Duration;

#[test]
fn http_connection_limit_accepts_exact_documented_maximum() {
    let settings = RuntimeSettings::new(
        Duration::from_secs(1),
        Duration::from_secs(1),
        Duration::from_secs(1),
        65_536,
        1,
    )
    .expect("documented exact HTTP connection maximum must be accepted");

    assert_eq!(settings.maximum_connections, 65_536);
}

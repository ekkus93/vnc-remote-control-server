use super::*;

#[tokio::test]
async fn command_status_reports_pending_running_failed_and_rejected_states() {
    let (state, backend) = test_state_with_backend(true, MockScreenshot::Png);
    {
        let mut outcomes = backend
            .command_outcomes
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        outcomes.insert(2, (CommandOutcomeState::Queued, None));
        outcomes.insert(3, (CommandOutcomeState::Running, None));
        outcomes.insert(4, (CommandOutcomeState::Failed, Some("transport")));
        outcomes.insert(
            5,
            (CommandOutcomeState::Rejected, Some("command_queue_full")),
        );
    }
    let app = router(state);

    for (command_id, expected_status, expected_failure, retry_safe) in [
        (2, "queued", None, false),
        (3, "running", None, false),
        (4, "failed", Some("transport"), false),
        (5, "rejected", Some("command_queue_full"), true),
    ] {
        let response = app
            .clone()
            .oneshot(
                request(&format!("/v1/commands/{command_id}"))
                    .header(AUTHORIZATION, "Bearer test-token")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("status response");
        assert_eq!(response.status(), StatusCode::OK);
        let body = json_body(response).await;
        assert_eq!(body["command_id"], command_id);
        assert_eq!(body["status"], expected_status);
        match expected_failure {
            Some(failure) => assert_eq!(body["failure"], failure),
            None => assert!(body["failure"].is_null()),
        }
        assert_eq!(body["retry_safe"], retry_safe);
    }
}

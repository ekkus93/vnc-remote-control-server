#define VRC_TESTING 1
#define WaitForMessage vrc_test_wait_for_message
#define HandleRFBServerMessage vrc_test_handle_server_message
#include "../../crates/libvnc-adapter/native/vnc_shim.c"
#undef HandleRFBServerMessage
#undef WaitForMessage

#include <assert.h>
#include <stdint.h>

typedef enum vrc_test_poll_mode {
    VRC_TEST_POLL_VALID,
    VRC_TEST_POLL_OVERSIZE
} vrc_test_poll_mode;

static vrc_client *vrc_test_poll_client;
static vrc_test_poll_mode vrc_test_poll_behavior;

int vrc_test_wait_for_message(rfbClient *native, unsigned int timeout_microseconds) {
    (void)native;
    (void)timeout_microseconds;
    return 1;
}

rfbBool vrc_test_handle_server_message(rfbClient *native) {
    const char valid[] = "poll-valid";

    (void)native;
    assert(vrc_test_poll_client != NULL);
    if (vrc_test_poll_behavior == VRC_TEST_POLL_OVERSIZE) {
        (void)vrc_store_clipboard(
            vrc_test_poll_client,
            "x",
            (int)VRC_MAX_CLIPBOARD_BYTES + 1);
    } else {
        assert(vrc_store_clipboard(vrc_test_poll_client, valid, 10) == VRC_STATUS_OK);
    }
    return TRUE;
}

static void reset_client(vrc_client *client) {
    vrc_release_clipboard(&client->clipboard, &client->clipboard_length);
    client->clipboard_revision = 0U;
    client->connected = 0;
    client->native = NULL;
    vrc_clear_callback_failure(client);
    vrc_set_error(client, NULL);
    vrc_test_fail_clipboard_allocation = 0;
}

static void test_store_failure_classes(void) {
    vrc_client client = {0};
    const char valid[] = "valid";

    assert(vrc_store_clipboard(&client, valid, 5) == VRC_STATUS_OK);
    assert(client.clipboard != NULL);
    assert(client.clipboard_revision == 1U);

    vrc_clear_callback_failure(&client);
    assert(vrc_store_clipboard(&client, "x", (int)VRC_MAX_CLIPBOARD_BYTES + 1)
           == VRC_STATUS_CLIPBOARD_TOO_LARGE);
    assert(client.clipboard == NULL);
    assert(client.callback_status == VRC_STATUS_CLIPBOARD_TOO_LARGE);
    assert(client.callback_clipboard_bytes == VRC_MAX_CLIPBOARD_BYTES + 1U);

    reset_client(&client);
    assert(vrc_store_clipboard(&client, valid, 5) == VRC_STATUS_OK);
    vrc_clear_callback_failure(&client);
    vrc_test_fail_clipboard_allocation = 1;
    assert(vrc_store_clipboard(&client, valid, 5)
           == VRC_STATUS_CLIPBOARD_ALLOCATION_FAILED);
    assert(client.clipboard == NULL);
    assert(client.callback_status == VRC_STATUS_CLIPBOARD_ALLOCATION_FAILED);

    reset_client(&client);
    assert(vrc_store_clipboard(&client, valid, 5) == VRC_STATUS_OK);
    vrc_clear_callback_failure(&client);
    assert(vrc_store_clipboard(&client, NULL, 1) == VRC_STATUS_CLIPBOARD_STATE_INVALID);
    assert(client.clipboard == NULL);
    assert(client.callback_status == VRC_STATUS_CLIPBOARD_STATE_INVALID);

    reset_client(&client);
    client.clipboard_revision = UINT64_MAX;
    assert(vrc_store_clipboard(&client, valid, 5)
           == VRC_STATUS_CLIPBOARD_REVISION_EXHAUSTED);
    assert(client.clipboard == NULL);
    assert(client.callback_status == VRC_STATUS_CLIPBOARD_REVISION_EXHAUSTED);

    reset_client(&client);
    assert(vrc_store_clipboard(&client, valid, 5) == VRC_STATUS_OK);
    assert(client.clipboard != NULL);
    assert(strcmp(client.clipboard, valid) == 0);

    reset_client(&client);
}

static void test_poll_propagates_callback_failure_and_clears_stale_state(void) {
    vrc_client client = {0};

    client.native = (rfbClient *)(uintptr_t)1U;
    client.connected = 1;
    vrc_test_poll_client = &client;
    vrc_test_poll_behavior = VRC_TEST_POLL_OVERSIZE;

    assert(vrc_client_poll(&client, 1U) == VRC_STATUS_CLIPBOARD_TOO_LARGE);
    assert(client.connected == 0);
    assert(client.clipboard == NULL);
    assert(client.callback_status == VRC_STATUS_CLIPBOARD_TOO_LARGE);

    client.connected = 1;
    vrc_test_poll_behavior = VRC_TEST_POLL_VALID;
    assert(vrc_client_poll(&client, 1U) == VRC_STATUS_OK);
    assert(client.connected == 1);
    assert(client.callback_status == VRC_STATUS_OK);
    assert(client.clipboard != NULL);
    assert(strcmp(client.clipboard, "poll-valid") == 0);

    reset_client(&client);
    vrc_test_poll_client = NULL;
}

int main(void) {
    test_store_failure_classes();
    test_poll_propagates_callback_failure_and_clears_stale_state();
    return 0;
}

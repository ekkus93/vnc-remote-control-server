#define VRC_TESTING 1
#include "../../crates/libvnc-adapter/native/vnc_shim.c"

#include <assert.h>

static void reset_client(vrc_client *client) {
    vrc_release_clipboard(&client->clipboard, &client->clipboard_length);
    client->clipboard_revision = 0U;
    vrc_clear_callback_failure(client);
    vrc_set_error(client, NULL);
    vrc_test_fail_clipboard_allocation = 0;
}

int main(void) {
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
    return 0;
}

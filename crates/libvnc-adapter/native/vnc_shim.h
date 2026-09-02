#ifndef VRC_VNC_SHIM_H
#define VRC_VNC_SHIM_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct vrc_client vrc_client;

typedef enum vrc_status {
    VRC_STATUS_OK = 0,
    VRC_STATUS_INVALID_ARGUMENT = 1,
    VRC_STATUS_ALLOCATION_FAILED = 2,
    VRC_STATUS_NATIVE_FAILURE = 3,
    VRC_STATUS_TIMEOUT = 4,
    VRC_STATUS_DISCONNECTED = 5,
    VRC_STATUS_FRAMEBUFFER_UNAVAILABLE = 6,
    VRC_STATUS_BUFFER_TOO_SMALL = 7,
    VRC_STATUS_CLIPBOARD_UNAVAILABLE = 8,
    VRC_STATUS_PROTOCOL_INITIALIZATION_FAILED = 9,
    VRC_STATUS_CLIPBOARD_TOO_LARGE = 10,
    VRC_STATUS_CLIPBOARD_ALLOCATION_FAILED = 11,
    VRC_STATUS_CLIPBOARD_STATE_INVALID = 12,
    VRC_STATUS_CLIPBOARD_REVISION_EXHAUSTED = 13,
    VRC_STATUS_FRAMEBUFFER_REVISION_EXHAUSTED = 14
} vrc_status;

vrc_client *vrc_client_create(
    const char *host,
    int port,
    const char *password,
    unsigned int connect_timeout_seconds,
    unsigned int read_timeout_seconds
);

vrc_status vrc_client_connect(vrc_client *client);
vrc_status vrc_client_poll(vrc_client *client, unsigned int timeout_microseconds);
vrc_status vrc_client_request_full_refresh(vrc_client *client);
vrc_status vrc_client_send_pointer(vrc_client *client, int x, int y, int button_mask);
vrc_status vrc_client_send_key(vrc_client *client, uint32_t keysym, int pressed);
vrc_status vrc_client_send_clipboard(vrc_client *client, const char *text, size_t text_length);

vrc_status vrc_client_dimensions(
    const vrc_client *client,
    uint32_t *width,
    uint32_t *height,
    uint64_t *revision,
    int *complete
);

vrc_status vrc_client_framebuffer_length(const vrc_client *client, size_t *length);
vrc_status vrc_client_copy_framebuffer(
    const vrc_client *client,
    uint8_t *destination,
    size_t destination_length,
    uint64_t *revision
);

vrc_status vrc_client_clipboard_length(
    const vrc_client *client,
    size_t *length,
    uint64_t *revision
);
vrc_status vrc_client_copy_clipboard(
    const vrc_client *client,
    char *destination,
    size_t destination_length,
    uint64_t *revision
);

int vrc_client_protocol_major(const vrc_client *client);
const char *vrc_client_last_error(const vrc_client *client);
size_t vrc_client_last_callback_clipboard_bytes(const vrc_client *client);
void vrc_client_destroy(vrc_client *client);

#ifdef __cplusplus
}
#endif

#endif

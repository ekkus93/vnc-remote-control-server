#define _POSIX_C_SOURCE 200809L

#include "vnc_shim.h"

#include <limits.h>
#include <rfb/rfbclient.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define VRC_MAX_FRAMEBUFFER_BYTES ((size_t)64U * 1024U * 1024U)
#define VRC_MAX_CLIPBOARD_BYTES ((size_t)1024U * 1024U)
#define VRC_ERROR_CAPACITY ((size_t)128U)

struct vrc_client {
    rfbClient *native;
    char *host;
    int port;
    char *password;
    uint8_t *framebuffer;
    size_t framebuffer_length;
    uint32_t width;
    uint32_t height;
    uint64_t revision;
    int complete;
    char *clipboard;
    size_t clipboard_length;
    uint64_t clipboard_revision;
    unsigned int connect_timeout_seconds;
    unsigned int read_timeout_seconds;
    int connected;
    char last_error[VRC_ERROR_CAPACITY];
};

static int vrc_context_tag;

static void vrc_set_error(vrc_client *client, const char *message) {
    if (client == NULL) {
        return;
    }
    if (message == NULL) {
        client->last_error[0] = '\0';
        return;
    }
    (void)snprintf(client->last_error, VRC_ERROR_CAPACITY, "%s", message);
}

static void vrc_secure_scrub(void *buffer, size_t length) {
    volatile unsigned char *bytes = buffer;

    if (buffer == NULL) {
        return;
    }
    while (length > 0U) {
        *bytes = 0U;
        bytes += 1;
        length -= 1U;
    }
}

static void vrc_release_clipboard(char **clipboard, size_t *length) {
    if (clipboard == NULL || length == NULL) {
        return;
    }
    if (*clipboard != NULL) {
        vrc_secure_scrub(*clipboard, *length + 1U);
        free(*clipboard);
    }
    *clipboard = NULL;
    *length = 0U;
}

static char *vrc_duplicate(const char *value) {
    size_t length;
    char *copy;

    if (value == NULL) {
        return NULL;
    }
    length = strlen(value);
    copy = malloc(length + 1U);
    if (copy == NULL) {
        return NULL;
    }
    memcpy(copy, value, length + 1U);
    return copy;
}

static vrc_client *vrc_context(rfbClient *native) {
    if (native == NULL) {
        return NULL;
    }
    return rfbClientGetClientData(native, &vrc_context_tag);
}

static char *vrc_get_password(rfbClient *native) {
    vrc_client *client = vrc_context(native);

    if (client == NULL || client->password == NULL) {
        return NULL;
    }
    /* LibVNCClient owns and frees this callback result. The shim has no
     * post-authentication hook through which it can scrub that library-owned
     * copy. The persistent shim-owned source is scrubbed during destruction. */
    return vrc_duplicate(client->password);
}

static rfbBool vrc_allocate_framebuffer(rfbClient *native) {
    vrc_client *client = vrc_context(native);
    size_t width;
    size_t height;
    size_t pixels;
    size_t length;
    uint8_t *framebuffer;

    if (client == NULL || native == NULL || native->width <= 0 || native->height <= 0) {
        vrc_set_error(client, "invalid framebuffer dimensions");
        return FALSE;
    }

    width = (size_t)native->width;
    height = (size_t)native->height;
    if (width > SIZE_MAX / height) {
        vrc_set_error(client, "framebuffer size overflow");
        return FALSE;
    }
    pixels = width * height;
    if (pixels > SIZE_MAX / 4U) {
        vrc_set_error(client, "framebuffer byte size overflow");
        return FALSE;
    }
    length = pixels * 4U;
    if (length > VRC_MAX_FRAMEBUFFER_BYTES) {
        vrc_set_error(client, "framebuffer exceeds configured maximum");
        return FALSE;
    }

    framebuffer = calloc(length, 1U);
    if (framebuffer == NULL) {
        vrc_set_error(client, "framebuffer allocation failed");
        return FALSE;
    }

    if (native->frameBuffer == client->framebuffer) {
        native->frameBuffer = NULL;
    }
    free(client->framebuffer);
    client->framebuffer = framebuffer;
    client->framebuffer_length = length;
    client->width = (uint32_t)native->width;
    client->height = (uint32_t)native->height;
    client->complete = 0;
    native->frameBuffer = framebuffer;
    return TRUE;
}

static void vrc_finished_framebuffer_update(rfbClient *native) {
    vrc_client *client = vrc_context(native);

    if (client == NULL || client->framebuffer == NULL) {
        return;
    }
    if (client->revision == UINT64_MAX) {
        vrc_set_error(client, "framebuffer revision overflow");
        client->complete = 0;
        return;
    }
    client->revision += 1U;
    client->complete = 1;
}

static void vrc_store_clipboard(vrc_client *client, const char *text, int text_length) {
    size_t length;
    char *copy;

    if (client == NULL || text_length < 0) {
        vrc_set_error(client, "invalid clipboard update");
        return;
    }
    length = (size_t)text_length;
    if (length > VRC_MAX_CLIPBOARD_BYTES) {
        vrc_set_error(client, "clipboard update exceeds configured maximum");
        return;
    }
    if (length > 0U && text == NULL) {
        vrc_set_error(client, "invalid clipboard update");
        return;
    }
    if (client->clipboard_revision == UINT64_MAX) {
        vrc_set_error(client, "clipboard revision overflow");
        return;
    }

    copy = malloc(length + 1U);
    if (copy == NULL) {
        vrc_set_error(client, "clipboard allocation failed");
        return;
    }
    if (length > 0U) {
        memcpy(copy, text, length);
    }
    copy[length] = '\0';

    vrc_release_clipboard(&client->clipboard, &client->clipboard_length);
    client->clipboard = copy;
    client->clipboard_length = length;
    client->clipboard_revision += 1U;
}

static void vrc_got_clipboard(rfbClient *native, const char *text, int text_length) {
    vrc_store_clipboard(vrc_context(native), text, text_length);
}

vrc_client *vrc_client_create(
    const char *host,
    int port,
    const char *password,
    unsigned int connect_timeout_seconds,
    unsigned int read_timeout_seconds
) {
    vrc_client *client;

    if (host == NULL || host[0] == '\0' || password == NULL || password[0] == '\0'
        || port <= 0 || port > 65535 || connect_timeout_seconds == 0U
        || read_timeout_seconds == 0U) {
        return NULL;
    }

    client = calloc(1U, sizeof(*client));
    if (client == NULL) {
        return NULL;
    }
    client->host = vrc_duplicate(host);
    client->password = vrc_duplicate(password);
    if (client->host == NULL || client->password == NULL) {
        vrc_client_destroy(client);
        return NULL;
    }
    client->port = port;
    client->connect_timeout_seconds = connect_timeout_seconds;
    client->read_timeout_seconds = read_timeout_seconds;
    client->last_error[0] = '\0';
    return client;
}

vrc_status vrc_client_connect(vrc_client *client) {
    if (client == NULL || client->native != NULL) {
        return VRC_STATUS_INVALID_ARGUMENT;
    }

    client->native = rfbGetClient(8, 3, 4);
    if (client->native == NULL) {
        vrc_set_error(client, "rfbGetClient failed");
        return VRC_STATUS_ALLOCATION_FAILED;
    }

    client->native->GetPassword = vrc_get_password;
    client->native->MallocFrameBuffer = vrc_allocate_framebuffer;
    client->native->FinishedFrameBufferUpdate = vrc_finished_framebuffer_update;
    client->native->GotXCutText = vrc_got_clipboard;
    client->native->connectTimeout = client->connect_timeout_seconds;
    client->native->readTimeout = client->read_timeout_seconds;
    client->native->appData.shareDesktop = TRUE;
    rfbClientSetClientData(client->native, &vrc_context_tag, client);

    if (!ConnectToRFBServer(client->native, client->host, client->port)) {
        vrc_set_error(client, "VNC transport connection failed");
        return VRC_STATUS_NATIVE_FAILURE;
    }
    if (!InitialiseRFBConnection(client->native)) {
        vrc_set_error(client, "VNC protocol initialization failed");
        return VRC_STATUS_NATIVE_FAILURE;
    }

    /* Request a host-independent 32-bit true-colour format whose in-memory
     * bytes are exactly [R, G, B, X]. The canonical Rust layer replaces X with
     * opaque alpha. SetFormatAndEncodings sends this contract to the server. */
    client->native->format.bitsPerPixel = 32;
    client->native->format.depth = 24;
    client->native->format.trueColour = TRUE;
    client->native->format.bigEndian = FALSE;
    client->native->format.redMax = 255;
    client->native->format.greenMax = 255;
    client->native->format.blueMax = 255;
    client->native->format.redShift = 0;
    client->native->format.greenShift = 8;
    client->native->format.blueShift = 16;
    client->native->appData.requestedDepth = 24;

    client->native->width = client->native->si.framebufferWidth;
    client->native->height = client->native->si.framebufferHeight;
    /* HandleRFBServerMessage automatically sends an incremental framebuffer
     * request before FinishedFrameBufferUpdate. rfbGetClient initializes
     * updateRect.x to -1, which serializes as 65535 if left untouched. Keep
     * LibVNCClient's automatic rearm path, but make its rectangle explicit. */
    client->native->updateRect.x = 0;
    client->native->updateRect.y = 0;
    client->native->updateRect.w = client->native->width;
    client->native->updateRect.h = client->native->height;
    if (!client->native->MallocFrameBuffer(client->native)) {
        vrc_set_error(client, "VNC framebuffer initialization failed");
        return VRC_STATUS_NATIVE_FAILURE;
    }
    if (!SetFormatAndEncodings(client->native)) {
        vrc_set_error(client, "VNC format negotiation failed");
        return VRC_STATUS_NATIVE_FAILURE;
    }
    if (!SendFramebufferUpdateRequest(
            client->native,
            0,
            0,
            client->native->width,
            client->native->height,
            FALSE)) {
        vrc_set_error(client, "initial framebuffer request failed");
        return VRC_STATUS_NATIVE_FAILURE;
    }

    client->connected = 1;
    vrc_set_error(client, NULL);
    return VRC_STATUS_OK;
}

vrc_status vrc_client_poll(vrc_client *client, unsigned int timeout_microseconds) {
    int wait_result;

    if (client == NULL || client->native == NULL || client->connected == 0) {
        return VRC_STATUS_DISCONNECTED;
    }
    wait_result = WaitForMessage(client->native, timeout_microseconds);
    if (wait_result == 0) {
        return VRC_STATUS_TIMEOUT;
    }
    if (wait_result < 0) {
        client->connected = 0;
        client->complete = 0;
        vrc_set_error(client, "VNC transport wait failed");
        return VRC_STATUS_DISCONNECTED;
    }
    if (!HandleRFBServerMessage(client->native)) {
        client->connected = 0;
        client->complete = 0;
        vrc_set_error(client, "VNC server message handling failed");
        return VRC_STATUS_DISCONNECTED;
    }
    return VRC_STATUS_OK;
}

vrc_status vrc_client_request_full_refresh(vrc_client *client) {
    if (client == NULL || client->native == NULL || client->connected == 0) {
        return VRC_STATUS_DISCONNECTED;
    }
    if (client->native->width <= 0 || client->native->height <= 0) {
        return VRC_STATUS_FRAMEBUFFER_UNAVAILABLE;
    }
    client->complete = 0;
    if (!SendFramebufferUpdateRequest(
            client->native,
            0,
            0,
            client->native->width,
            client->native->height,
            FALSE)) {
        vrc_set_error(client, "full framebuffer request failed");
        return VRC_STATUS_NATIVE_FAILURE;
    }
    return VRC_STATUS_OK;
}

vrc_status vrc_client_send_pointer(vrc_client *client, int x, int y, int button_mask) {
    if (client == NULL || client->native == NULL || client->connected == 0) {
        return VRC_STATUS_DISCONNECTED;
    }
    if (x < 0 || y < 0 || x >= client->native->width || y >= client->native->height
        || button_mask < 0 || button_mask > 255) {
        return VRC_STATUS_INVALID_ARGUMENT;
    }
    if (!SendPointerEvent(client->native, x, y, button_mask)) {
        vrc_set_error(client, "pointer event failed");
        return VRC_STATUS_NATIVE_FAILURE;
    }
    return VRC_STATUS_OK;
}

vrc_status vrc_client_send_key(vrc_client *client, uint32_t keysym, int pressed) {
    if (client == NULL || client->native == NULL || client->connected == 0) {
        return VRC_STATUS_DISCONNECTED;
    }
    if (pressed != 0 && pressed != 1) {
        return VRC_STATUS_INVALID_ARGUMENT;
    }
    if (!SendKeyEvent(client->native, keysym, pressed != 0 ? TRUE : FALSE)) {
        vrc_set_error(client, "key event failed");
        return VRC_STATUS_NATIVE_FAILURE;
    }
    return VRC_STATUS_OK;
}

vrc_status vrc_client_send_clipboard(vrc_client *client, const char *text, size_t text_length) {
    char *copy;
    rfbBool sent;

    if (client == NULL || client->native == NULL || client->connected == 0) {
        return VRC_STATUS_DISCONNECTED;
    }
    if ((text == NULL && text_length > 0U) || text_length > VRC_MAX_CLIPBOARD_BYTES
        || text_length > (size_t)INT_MAX) {
        return VRC_STATUS_INVALID_ARGUMENT;
    }
    if (text_length > 0U && memchr(text, '\0', text_length) != NULL) {
        return VRC_STATUS_INVALID_ARGUMENT;
    }

    copy = malloc(text_length + 1U);
    if (copy == NULL) {
        vrc_set_error(client, "clipboard send allocation failed");
        return VRC_STATUS_ALLOCATION_FAILED;
    }
    if (text_length > 0U) {
        memcpy(copy, text, text_length);
    }
    copy[text_length] = '\0';
    sent = SendClientCutText(client->native, copy, (int)text_length);
    vrc_secure_scrub(copy, text_length + 1U);
    free(copy);
    if (!sent) {
        vrc_set_error(client, "clipboard send failed");
        return VRC_STATUS_NATIVE_FAILURE;
    }
    return VRC_STATUS_OK;
}

vrc_status vrc_client_dimensions(
    const vrc_client *client,
    uint32_t *width,
    uint32_t *height,
    uint64_t *revision,
    int *complete
) {
    if (client == NULL || width == NULL || height == NULL || revision == NULL || complete == NULL) {
        return VRC_STATUS_INVALID_ARGUMENT;
    }
    if (client->width == 0U || client->height == 0U) {
        return VRC_STATUS_FRAMEBUFFER_UNAVAILABLE;
    }
    *width = client->width;
    *height = client->height;
    *revision = client->revision;
    *complete = client->complete;
    return VRC_STATUS_OK;
}

vrc_status vrc_client_framebuffer_length(const vrc_client *client, size_t *length) {
    if (client == NULL || length == NULL) {
        return VRC_STATUS_INVALID_ARGUMENT;
    }
    if (client->framebuffer == NULL || client->complete == 0) {
        return VRC_STATUS_FRAMEBUFFER_UNAVAILABLE;
    }
    *length = client->framebuffer_length;
    return VRC_STATUS_OK;
}

vrc_status vrc_client_copy_framebuffer(
    const vrc_client *client,
    uint8_t *destination,
    size_t destination_length,
    uint64_t *revision
) {
    if (client == NULL || destination == NULL || revision == NULL) {
        return VRC_STATUS_INVALID_ARGUMENT;
    }
    if (client->framebuffer == NULL || client->complete == 0) {
        return VRC_STATUS_FRAMEBUFFER_UNAVAILABLE;
    }
    if (destination_length < client->framebuffer_length) {
        return VRC_STATUS_BUFFER_TOO_SMALL;
    }
    memcpy(destination, client->framebuffer, client->framebuffer_length);
    *revision = client->revision;
    return VRC_STATUS_OK;
}

vrc_status vrc_client_clipboard_length(
    const vrc_client *client,
    size_t *length,
    uint64_t *revision
) {
    if (client == NULL || length == NULL || revision == NULL) {
        return VRC_STATUS_INVALID_ARGUMENT;
    }
    if (client->clipboard == NULL) {
        return VRC_STATUS_CLIPBOARD_UNAVAILABLE;
    }
    *length = client->clipboard_length;
    *revision = client->clipboard_revision;
    return VRC_STATUS_OK;
}

vrc_status vrc_client_copy_clipboard(
    const vrc_client *client,
    char *destination,
    size_t destination_length,
    uint64_t *revision
) {
    if (client == NULL || destination == NULL || revision == NULL) {
        return VRC_STATUS_INVALID_ARGUMENT;
    }
    if (client->clipboard == NULL) {
        return VRC_STATUS_CLIPBOARD_UNAVAILABLE;
    }
    if (destination_length < client->clipboard_length + 1U) {
        return VRC_STATUS_BUFFER_TOO_SMALL;
    }
    memcpy(destination, client->clipboard, client->clipboard_length + 1U);
    *revision = client->clipboard_revision;
    return VRC_STATUS_OK;
}

int vrc_client_protocol_major(const vrc_client *client) {
    if (client == NULL || client->native == NULL) {
        return 0;
    }
    return client->native->major;
}

const char *vrc_client_last_error(const vrc_client *client) {
    if (client == NULL) {
        return "invalid client";
    }
    return client->last_error;
}

void vrc_client_destroy(vrc_client *client) {
    if (client == NULL) {
        return;
    }
    if (client->native != NULL) {
        if (client->native->frameBuffer == client->framebuffer) {
            client->native->frameBuffer = NULL;
        }
        free(client->framebuffer);
        client->framebuffer = NULL;
        client->framebuffer_length = 0U;
        rfbClientCleanup(client->native);
        client->native = NULL;
    } else {
        free(client->framebuffer);
    }
    vrc_release_clipboard(&client->clipboard, &client->clipboard_length);
    if (client->password != NULL) {
        vrc_secure_scrub(client->password, strlen(client->password));
        free(client->password);
        client->password = NULL;
    }
    free(client->host);
    free(client);
}

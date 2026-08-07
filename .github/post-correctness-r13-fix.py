from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# LibVNCClient automatically sends its configured incremental request before
# invoking FinishedFrameBufferUpdate. rfbGetClient starts updateRect.x at -1,
# so initialize the full-screen rectangle explicitly and do not send a second
# request from the callback.
shim = ROOT / "crates/libvnc-adapter/native/vnc_shim.c"
text = shim.read_text(encoding="utf-8")
old_callback = '''static void vrc_finished_framebuffer_update(rfbClient *native) {
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
    if (!SendFramebufferUpdateRequest(
            native,
            0,
            0,
            native->width,
            native->height,
            TRUE)) {
        vrc_set_error(client, "incremental framebuffer request failed");
        client->complete = 0;
        client->connected = 0;
    }
}
'''
new_callback = '''static void vrc_finished_framebuffer_update(rfbClient *native) {
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
'''
if text.count(old_callback) != 1:
    raise SystemExit(f"vnc_shim.c: expected one old framebuffer callback, found {text.count(old_callback)}")
text = text.replace(old_callback, new_callback, 1)
old_setup = '''    client->native->width = client->native->si.framebufferWidth;
    client->native->height = client->native->si.framebufferHeight;
    if (!client->native->MallocFrameBuffer(client->native)) {
'''
new_setup = '''    client->native->width = client->native->si.framebufferWidth;
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
'''
if text.count(old_setup) != 1:
    raise SystemExit(f"vnc_shim.c: expected one framebuffer setup anchor, found {text.count(old_setup)}")
shim.write_text(text.replace(old_setup, new_setup, 1), encoding="utf-8")

contract = ROOT / "tests/test_native_contract.py"
text = contract.read_text(encoding="utf-8")
old_test = '''    def test_native_framebuffer_updates_rearm_incremental_delivery(self):
        source = SHIM_SOURCE.read_text(encoding="utf-8")
        callback_start = source.index("static void vrc_finished_framebuffer_update")
        callback_end = source.index("static void vrc_store_clipboard", callback_start)
        callback = source[callback_start:callback_end]
        self.assertIn("SendFramebufferUpdateRequest(", callback)
        self.assertIn("native->width", callback)
        self.assertIn("native->height", callback)
        self.assertIn("TRUE", callback)
        self.assertIn("incremental framebuffer request failed", callback)
        self.assertIn("client->complete = 0;", callback)
        self.assertIn("client->connected = 0;", callback)
'''
new_test = '''    def test_native_framebuffer_updates_use_library_incremental_rearm(self):
        source = SHIM_SOURCE.read_text(encoding="utf-8")
        callback_start = source.index("static void vrc_finished_framebuffer_update")
        callback_end = source.index("static void vrc_store_clipboard", callback_start)
        callback = source[callback_start:callback_end]
        self.assertNotIn("SendFramebufferUpdateRequest(", callback)
        self.assertIn("client->revision += 1U;", callback)
        self.assertIn("client->complete = 1;", callback)

        connect_start = source.index("vrc_status vrc_client_connect")
        connect_end = source.index("vrc_status vrc_client_poll", connect_start)
        connect = source[connect_start:connect_end]
        for assignment in (
            "client->native->updateRect.x = 0;",
            "client->native->updateRect.y = 0;",
            "client->native->updateRect.w = client->native->width;",
            "client->native->updateRect.h = client->native->height;",
        ):
            self.assertIn(assignment, connect)
        self.assertIn("HandleRFBServerMessage automatically sends", connect)
        self.assertLess(connect.index("updateRect.x = 0"), connect.index("SendFramebufferUpdateRequest("))
'''
if text.count(old_test) != 1:
    raise SystemExit(f"native contract: expected one old incremental rearm test, found {text.count(old_test)}")
contract.write_text(text.replace(old_test, new_test, 1), encoding="utf-8")

state_checks = ROOT / "tests/integration/r13_checks_state.py"
text = state_checks.read_text(encoding="utf-8")
old_screenshot = '''    screenshot = harness.request("GET", "/v1/screenshot.png")
    require(screenshot.status == 200, f"screenshot failed: {screenshot.status}")
    require(parse_png_dimensions(screenshot.body) == (1280, 800), "PNG dimensions were not 1280x800")
    etag = screenshot.headers.get("etag")
    require(bool(etag), "screenshot omitted ETag")
    conditional = harness.request("GET", "/v1/screenshot.png", headers={"If-None-Match": etag})
    require(conditional.status == 304 and not conditional.body, "conditional screenshot did not return empty 304")
    return str(etag)
'''
new_screenshot = '''    deadline = time.monotonic() + 12
    last_status: int | None = None
    while time.monotonic() < deadline:
        screenshot = harness.request("GET", "/v1/screenshot.png")
        require(screenshot.status == 200, f"screenshot failed: {screenshot.status}")
        require(parse_png_dimensions(screenshot.body) == (1280, 800), "PNG dimensions were not 1280x800")
        etag = screenshot.headers.get("etag")
        require(bool(etag), "screenshot omitted ETag")
        conditional = harness.request("GET", "/v1/screenshot.png", headers={"If-None-Match": etag})
        last_status = conditional.status
        if conditional.status == 304:
            require(not conditional.body, "conditional screenshot 304 contained a response body")
            return str(etag)
        require(
            conditional.status == 200,
            f"conditional screenshot returned unexpected status {conditional.status}",
        )
        time.sleep(0.05)
    raise AssertionError(
        f"framebuffer did not stabilize for conditional screenshot revalidation; last status={last_status}"
    )
'''
if text.count(old_screenshot) != 1:
    raise SystemExit(f"R13 state checks: expected one immediate screenshot 304 block, found {text.count(old_screenshot)}")
state_checks.write_text(text.replace(old_screenshot, new_screenshot, 1), encoding="utf-8")

for temporary in (
    ROOT / ".github/post-correctness-r13-fix.py",
    ROOT / ".github/workflows/post-correctness-r13-fix.yml",
):
    temporary.unlink()

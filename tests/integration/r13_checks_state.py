"""Initial-state, screenshot, input, and clipboard checks."""

from __future__ import annotations

import time
from typing import Any

from r13_config import INBOUND_CLIPBOARD, MAX_CLIPBOARD_BYTES, OUTBOUND_CLIPBOARD, SUPPORTED_TEXT, UNSUPPORTED_TEXT
from r13_harness import Harness
from r13_helpers import error_code, parse_png_dimensions, post_json, require, wait_until


def assert_initial_state_and_screenshots(harness: Harness) -> str:
    harness.log("verifying connected state, display metadata, PNG dimensions, ETag, and 304")
    status = harness.request("GET", "/v1/status")
    require(status.status == 200 and status.json().get("state") == "connected", f"not connected: {status.body!r}")
    display = harness.request("GET", "/v1/display")
    require(display.status == 200, f"display failed: {display.status}")
    display_json = display.json()
    require(display_json.get("width") == 1280 and display_json.get("height") == 800, f"bad display: {display_json}")
    require(display_json.get("complete") is True, "display was not complete")
    screenshot = harness.request("GET", "/v1/screenshot.png")
    require(screenshot.status == 200, f"screenshot failed: {screenshot.status}")
    require(parse_png_dimensions(screenshot.body) == (1280, 800), "PNG dimensions were not 1280x800")
    etag = screenshot.headers.get("etag")
    require(bool(etag), "screenshot omitted ETag")
    conditional = harness.request("GET", "/v1/screenshot.png", headers={"If-None-Match": etag})
    require(conditional.status == 304 and not conditional.body, "conditional screenshot did not return empty 304")
    return str(etag)


def assert_input_and_clipboard(harness: Harness, initial_etag: str) -> None:
    harness.log("verifying clipboard_unavailable before first inbound update")
    initial_clipboard = harness.request("GET", "/v1/clipboard")
    require(initial_clipboard.status == 503, f"initial clipboard unexpectedly available: {initial_clipboard.status}")
    require(error_code(initial_clipboard) == "clipboard_unavailable", "initial clipboard used wrong error code")

    harness.log("verifying text preflight, key ordering, and public clipboard flow")
    response = post_json(harness, "/v1/keyboard/text", {"text": SUPPORTED_TEXT})
    require(response.status == 202, f"supported text returned {response.status}")
    state = harness.wait_desktop_state(lambda value: value.get("text") == SUPPORTED_TEXT)
    baseline_text = state["text"]
    unsupported = post_json(harness, "/v1/keyboard/text", {"text": UNSUPPORTED_TEXT})
    require(unsupported.status == 422 and error_code(unsupported) == "unsupported_text", "unsupported text was not rejected atomically")
    time.sleep(0.25)
    require(harness.desktop_state().get("text") == baseline_text, "unsupported text partially mutated the entry")

    for payload in (
        {"key": "F5", "action": "down"},
        {"key": "F5", "action": "up"},
    ):
        response = post_json(harness, "/v1/keyboard/key", payload)
        require(response.status == 202, f"key transition failed: {response.status}")
    response = post_json(harness, "/v1/keyboard/chord", {"keys": ["CTRL_LEFT", "SHIFT_LEFT", "F6"]})
    require(response.status == 202, f"chord failed: {response.status}")

    expected_keys = [
        ("key_down", "F5"),
        ("key_up", "F5"),
        ("key_down", "Control_L"),
        ("key_down", "Shift_L"),
        ("key_down", "F6"),
        ("key_up", "F6"),
        ("key_up", "Shift_L"),
        ("key_up", "Control_L"),
    ]
    key_state = harness.wait_desktop_state(
        lambda value: any(
            event.get("type") == "key_up" and event.get("key") == "Control_L"
            for event in value.get("events", [])
        )
    )
    key_index = 0
    for event in key_state["events"]:
        if key_index < len(expected_keys) and (event.get("type"), event.get("key")) == expected_keys[key_index]:
            key_index += 1
    require(key_index == len(expected_keys), "key/chord event order was not observed")

    response = harness.request("PUT", "/v1/clipboard", {"text": OUTBOUND_CLIPBOARD})
    require(response.status == 202, f"outbound clipboard failed: {response.status}")
    clipboard_reader = r'''
import sys, time, tkinter as tk
expected = sys.argv[1]
root = tk.Tk(); root.withdraw()
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    root.update()
    try: value = root.clipboard_get()
    except tk.TclError: value = None
    if value == expected: break
    time.sleep(0.05)
else:
    root.destroy(); raise SystemExit("desktop clipboard did not receive API value")
root.destroy()
'''
    harness.compose(
        "exec",
        "-T",
        "-e",
        "DISPLAY=:1",
        "desktop",
        "python3",
        "-c",
        clipboard_reader,
        OUTBOUND_CLIPBOARD,
    )
    controls = harness.desktop_state().get("controls", {})
    require(set(controls) >= {"copy", "paste", "reset"}, f"missing deterministic controls: {controls!r}")

    def click_control(name: str) -> None:
        point = controls[name]
        click = post_json(
            harness,
            "/v1/pointer/click",
            {"x": int(point["x"]), "y": int(point["y"]), "button": "left"},
        )
        require(click.status == 202, f"{name} control click failed: {click.status}")

    click_control("paste")
    harness.wait_desktop_state(
        lambda value: value.get("text") == OUTBOUND_CLIPBOARD
        and any(event.get("type") == "paste" for event in value.get("events", []))
    )

    reset_point = controls["reset"]
    click_control("reset")
    harness.wait_desktop_state(
        lambda value: value.get("text") == ""
        and value.get("counter") == 0
        and value.get("clipboard_revision") == 0
        and value.get("keys_down") == []
        and all(
            event.get("type") == "button_up"
            and event.get("button") == "left"
            and event.get("x") == int(reset_point["x"])
            and event.get("y") == int(reset_point["y"])
            for event in value.get("events", [])
        )
    )
    response = post_json(harness, "/v1/keyboard/text", {"text": INBOUND_CLIPBOARD})
    require(response.status == 202, "copy fixture typing failed")
    harness.wait_desktop_state(lambda value: value.get("text") == INBOUND_CLIPBOARD)
    click_control("copy")
    harness.wait_desktop_state(
        lambda value: any(event.get("type") == "copy" for event in value.get("events", []))
    )

    inbound: dict[str, Any] | None = None
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        snapshot = harness.request("GET", "/v1/clipboard")
        if snapshot.status == 200 and snapshot.json().get("text") == INBOUND_CLIPBOARD:
            inbound = snapshot.json()
            break
        time.sleep(0.1)
    require(inbound is not None, "API did not receive desktop clipboard")
    require(int(inbound["revision"]) > 0, "clipboard revision was not positive")
    require(int(inbound["updated_at_unix_ms"]) > 0, "clipboard timestamp was not positive")

    oversized = harness.request("PUT", "/v1/clipboard", {"text": "x" * (MAX_CLIPBOARD_BYTES + 1)}, timeout=20)
    require(oversized.status == 413 and error_code(oversized) == "clipboard_too_large", "oversized clipboard used wrong response")

    harness.log("verifying pointer, buttons, clicks, double-click, and vertical scrolling")
    baseline_events = list(harness.desktop_state().get("events", []))
    baseline_sequence = max((int(event.get("sequence", 0)) for event in baseline_events), default=0)
    requests = [
        ("/v1/pointer/move", {"x": 320, "y": 240}),
        ("/v1/pointer/button", {"x": 330, "y": 250, "button": "left", "pressed": True}),
        ("/v1/pointer/button", {"x": 330, "y": 250, "button": "left", "pressed": False}),
        (
            "/v1/pointer/click",
            {
                "x": int(controls["increment"]["x"]),
                "y": int(controls["increment"]["y"]),
                "button": "left",
            },
        ),
        ("/v1/pointer/click", {"x": 440, "y": 430, "button": "middle"}),
        ("/v1/pointer/click", {"x": 460, "y": 430, "button": "right"}),
        ("/v1/pointer/double-click", {"x": 480, "y": 430, "button": "left", "interval_ms": 20}),
        ("/v1/pointer/scroll", {"x": 500, "y": 430, "delta_y": 2}),
        ("/v1/pointer/scroll", {"x": 500, "y": 430, "delta_y": -1}),
    ]
    for path, payload in requests:
        response = post_json(harness, path, payload)
        require(response.status == 202, f"{path} returned {response.status}: {response.body!r}")

    def input_complete(value: dict[str, Any]) -> bool:
        events = [event for event in value.get("events", []) if int(event.get("sequence", 0)) > baseline_sequence]
        left_down = sum(event.get("type") == "button_down" and event.get("button") == "left" for event in events)
        left_up = sum(event.get("type") == "button_up" and event.get("button") == "left" for event in events)
        middle_down = sum(event.get("type") == "button_down" and event.get("button") == "middle" for event in events)
        right_down = sum(event.get("type") == "button_down" and event.get("button") == "right" for event in events)
        scroll_up = sum(event.get("type") == "scroll" and event.get("delta_y") == 1 for event in events)
        scroll_down = sum(event.get("type") == "scroll" and event.get("delta_y") == -1 for event in events)
        return (
            value.get("pointer") == {"x": 500, "y": 430}
            and value.get("counter") == 1
            and value.get("buttons") == {"left": False, "middle": False, "right": False}
            and left_down == 4
            and left_up == 4
            and middle_down == 1
            and right_down == 1
            and scroll_up == 2
            and scroll_down == 1
        )

    final_state = harness.wait_desktop_state(input_complete)

    def etag_changed() -> bool:
        response = harness.request("GET", "/v1/screenshot.png")
        return response.status == 200 and response.headers.get("etag") not in {None, initial_etag}

    wait_until(etag_changed, "screenshot ETag change after visible input", 12)

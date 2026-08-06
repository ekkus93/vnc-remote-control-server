"""Abuse/concurrency bounds and reconnect/resource-bound checks."""

from __future__ import annotations

import concurrent.futures
import threading
import time

from r13_config import MAX_JSON_BYTES
from r13_harness import Harness
from r13_helpers import error_code, post_json, require
from r13_types import HttpResult


def assert_abuse_and_concurrency(harness: Harness) -> None:
    harness.log("verifying body, coordinate, scroll, queue, reconnect, and screenshot bounds")
    oversized_json = b"{" + b"x" * MAX_JSON_BYTES + b"}"
    response = harness.request(
        "POST",
        "/v1/pointer/move",
        oversized_json,
        headers={"Content-Type": "application/json"},
        timeout=20,
    )
    require(response.status == 413, f"oversized JSON returned {response.status}")

    invalid_coordinate = post_json(harness, "/v1/pointer/move", {"x": 1280, "y": 800})
    require(invalid_coordinate.status == 422 and error_code(invalid_coordinate) == "invalid_coordinate", "coordinate limit was not explicit")
    scroll = post_json(harness, "/v1/pointer/scroll", {"x": 1, "y": 1, "delta_y": 101})
    require(scroll.status == 422 and error_code(scroll) == "scroll_too_large", "scroll limit was not explicit")
    horizontal = post_json(
        harness,
        "/v1/pointer/scroll",
        {"x": 1, "y": 1, "delta_x": 1, "delta_y": 0},
    )
    require(
        horizontal.status == 422 and error_code(horizontal) == "invalid_request",
        "unsupported horizontal scrolling was not rejected explicitly",
    )

    barrier = threading.Barrier(12)

    def long_click(index: int) -> HttpResult:
        barrier.wait(timeout=5)
        return post_json(
            harness,
            "/v1/pointer/double-click",
            {"x": 600 + (index % 10), "y": 450, "button": "left", "interval_ms": 1000},
            timeout=15,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(long_click, range(12)))
    require(any(result.status == 202 for result in results), "queue saturation produced no accepted command")
    require(
        any(result.status == 503 and error_code(result) == "command_queue_full" for result in results),
        f"queue saturation was not explicit: {[result.status for result in results]}",
    )

    first = post_json(harness, "/v1/connection/reconnect", {})
    second = post_json(harness, "/v1/connection/reconnect", {})
    require(first.status == 202, f"first reconnect failed: {first.status}")
    require(second.status == 429 and error_code(second) == "reconnect_rate_limited", "reconnect rate limit was not explicit")
    harness.wait_ready()

    screenshot_barrier = threading.Barrier(12)

    def screenshot(_: int) -> HttpResult:
        screenshot_barrier.wait(timeout=5)
        return harness.request("GET", "/v1/screenshot.png", timeout=15)

    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        screenshots = list(executor.map(screenshot, range(12)))
    elapsed = time.monotonic() - started
    require(elapsed < 15, f"concurrent screenshots exceeded bounded deadline: {elapsed:.2f}s")
    require(all(result.status in {200, 503} for result in screenshots), "concurrent screenshots returned unexpected status")
    require(any(result.status == 200 for result in screenshots), "no concurrent screenshot succeeded")
    for result in screenshots:
        if result.status == 503:
            require(error_code(result) == "screenshot_busy", "screenshot overload used wrong error")


def assert_reconnect_and_resource_bounds(harness: Harness) -> None:
    harness.log("verifying desktop restart detection, framebuffer invalidation, reconnect, and resource bounds")
    baseline_threads, baseline_rss = harness.controller_metrics()
    previous_etag = harness.request("GET", "/v1/screenshot.png").headers["etag"]
    saw_unready = False
    saw_unavailable = False
    for cycle in range(3):
        harness.compose("stop", "desktop")
        status = harness.wait_status(lambda value: value.get("state") != "connected", 15)
        require(status.get("state") in {"degraded", "disconnected", "reconnecting", "connecting"}, f"unexpected disconnect state: {status}")
        ready = harness.request("GET", "/health/ready", token=None)
        require(ready.status == 503, "readiness remained true after desktop stop")
        saw_unready = True
        display = harness.request("GET", "/v1/display")
        screenshot = harness.request("GET", "/v1/screenshot.png")
        require(display.status == 503 and error_code(display) == "framebuffer_unavailable", "old display remained available")
        require(screenshot.status == 503 and error_code(screenshot) == "framebuffer_unavailable", "old screenshot remained available")
        saw_unavailable = True
        harness.compose("start", "desktop")
        harness.wait_service_health("desktop")
        harness.wait_ready()
        connected = harness.request("GET", "/v1/status").json()
        require(connected.get("state") == "connected", f"cycle {cycle} did not reconnect")
        new_screenshot = harness.request("GET", "/v1/screenshot.png")
        require(new_screenshot.status == 200, "screenshot did not return after reconnect")
        new_etag = new_screenshot.headers.get("etag")
        require(new_etag and new_etag != previous_etag, "ETag did not change after framebuffer invalidation")
        previous_etag = new_etag
    require(saw_unready and saw_unavailable, "reconnect scenario did not observe invalidation")
    threads, rss = harness.controller_metrics()
    require(threads <= baseline_threads + 4, f"worker thread count grew materially: {baseline_threads} -> {threads}")
    rss_allowance = max(32768, baseline_rss // 2)
    require(rss <= baseline_rss + rss_allowance, f"controller RSS grew materially: {baseline_rss} -> {rss} KiB")

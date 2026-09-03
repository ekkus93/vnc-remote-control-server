"""Concurrency and lifecycle tests for bounded MCP controller-call execution."""

from __future__ import annotations

import asyncio
import threading
import time
import unittest
from collections.abc import Callable

from vnc_remote_control.errors import TransportError
from vnc_remote_control.mcp_execution import (
    BoundedControllerExecutor,
    McpCallCapacityError,
    McpExecutorClosedError,
    McpUnexpectedControllerError,
)


async def _wait_until(predicate: Callable[[], bool], *, timeout: float = 1.0) -> None:
    """Wait for a deterministic test condition without blocking the event loop."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition was not reached before timeout")
        await asyncio.sleep(0.001)


class BoundedControllerExecutorTests(unittest.IsolatedAsyncioTestCase):
    """Verify bounded admission, cancellation, failure, and shutdown semantics."""

    async def test_call_runs_off_event_loop_and_returns_result(self) -> None:
        """Verify controller work executes on a worker thread exactly once."""
        executor = BoundedControllerExecutor(1)
        self.addAsyncCleanup(executor.aclose)
        loop_thread = threading.get_ident()
        calls = 0

        def operation(value: int) -> tuple[int, int]:
            nonlocal calls
            calls += 1
            return threading.get_ident(), value * 2

        worker_thread, result = await executor.call(operation, 21)
        self.assertNotEqual(worker_thread, loop_thread)
        self.assertEqual(result, 42)
        self.assertEqual(calls, 1)

    async def test_saturation_fails_before_unbounded_submission(self) -> None:
        """Verify excess calls are rejected while all fixed slots are occupied."""
        executor = BoundedControllerExecutor(2)
        self.addAsyncCleanup(executor.aclose)
        release = threading.Event()
        started = 0
        peak = 0
        active = 0
        lock = threading.Lock()

        def blocking_call() -> str:
            nonlocal active, peak, started
            with lock:
                started += 1
                active += 1
                peak = max(peak, active)
            release.wait(timeout=1.0)
            with lock:
                active -= 1
            return "done"

        first = asyncio.create_task(executor.call(blocking_call))
        second = asyncio.create_task(executor.call(blocking_call))
        await _wait_until(lambda: started == 2)

        with self.assertRaises(McpCallCapacityError):
            await executor.call(blocking_call)
        self.assertEqual(started, 2)
        self.assertEqual(peak, 2)

        release.set()
        self.assertEqual(await first, "done")
        self.assertEqual(await second, "done")

    async def test_typed_client_failure_passes_through_without_retry(self) -> None:
        """Verify typed client failures remain classified and release capacity."""
        executor = BoundedControllerExecutor(1)
        self.addAsyncCleanup(executor.aclose)
        calls = 0

        def failing_call() -> None:
            nonlocal calls
            calls += 1
            raise TransportError("typed transport failure")

        with self.assertRaisesRegex(TransportError, "typed transport failure"):
            await executor.call(failing_call)
        self.assertEqual(calls, 1)
        self.assertEqual(await executor.call(lambda: "recovered"), "recovered")

    async def test_unexpected_worker_failure_is_normalized_once_without_payload(self) -> None:
        """An untyped controller exception becomes one explicit adapter error."""
        executor = BoundedControllerExecutor(1)
        self.addAsyncCleanup(executor.aclose)
        calls = 0

        def failing_call() -> None:
            nonlocal calls
            calls += 1
            raise RuntimeError("SENSITIVE_UNEXPECTED_WORKER_DETAIL")

        with self.assertRaises(McpUnexpectedControllerError) as captured:
            await executor.call(failing_call)
        self.assertEqual(calls, 1)
        self.assertNotIn("SENSITIVE_UNEXPECTED_WORKER_DETAIL", str(captured.exception))
        self.assertIsInstance(captured.exception.__cause__, RuntimeError)
        self.assertEqual(await executor.call(lambda: "recovered"), "recovered")

    async def test_cancelled_waiter_does_not_release_active_worker_capacity(self) -> None:
        """Verify cancellation cannot free a slot before the worker actually exits."""
        executor = BoundedControllerExecutor(1)
        self.addAsyncCleanup(executor.aclose)
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def blocking_call() -> None:
            started.set()
            release.wait(timeout=1.0)
            finished.set()

        task = asyncio.create_task(executor.call(blocking_call))
        await _wait_until(started.is_set)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        with self.assertRaises(McpCallCapacityError):
            await executor.call(lambda: None)
        self.assertFalse(finished.is_set())

        release.set()
        await _wait_until(finished.is_set)
        self.assertIsNone(await executor.call(lambda: None))

    async def test_close_rejects_new_calls_and_waits_for_admitted_work(self) -> None:
        """Verify shutdown closes admission and joins active adapter-owned work."""
        executor = BoundedControllerExecutor(1)
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def blocking_call() -> None:
            started.set()
            release.wait(timeout=1.0)
            finished.set()

        task = asyncio.create_task(executor.call(blocking_call))
        await _wait_until(started.is_set)
        close_task = asyncio.create_task(executor.aclose())
        await _wait_until(lambda: executor.closed)

        with self.assertRaises(McpExecutorClosedError):
            await executor.call(lambda: None)
        self.assertFalse(close_task.done())

        release.set()
        await task
        await close_task
        self.assertTrue(finished.is_set())

    async def test_aclose_finishes_shutdown_before_propagating_cancellation(self) -> None:
        """Verify cleanup cancellation cannot orphan an admitted controller call."""
        executor = BoundedControllerExecutor(1)
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def blocking_call() -> None:
            started.set()
            release.wait(timeout=1.0)
            finished.set()

        call_task = asyncio.create_task(executor.call(blocking_call))
        await _wait_until(started.is_set)
        close_task = asyncio.create_task(executor.aclose())
        await _wait_until(lambda: executor.closed)
        close_task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(close_task.done())

        release.set()
        await call_task
        with self.assertRaises(asyncio.CancelledError):
            await close_task
        self.assertTrue(finished.is_set())

    async def test_invalid_capacity_and_idempotent_close_are_explicit(self) -> None:
        """Verify invalid bounds fail and repeated close does not resume service."""
        with self.assertRaises(ValueError):
            BoundedControllerExecutor(0)

        executor = BoundedControllerExecutor(1)
        await executor.aclose()
        await executor.aclose()
        with self.assertRaises(McpExecutorClosedError):
            await executor.call(lambda: None)

    async def test_event_loop_remains_responsive_during_synchronous_call(self) -> None:
        """Verify a blocking controller operation does not block the MCP event loop."""
        executor = BoundedControllerExecutor(1)
        self.addAsyncCleanup(executor.aclose)
        started = threading.Event()
        release = threading.Event()

        def blocking_call() -> None:
            started.set()
            release.wait(timeout=1.0)

        task = asyncio.create_task(executor.call(blocking_call))
        await _wait_until(started.is_set)
        before = time.monotonic()
        await asyncio.sleep(0.01)
        self.assertLess(time.monotonic() - before, 0.2)
        release.set()
        await task


if __name__ == "__main__":
    unittest.main()

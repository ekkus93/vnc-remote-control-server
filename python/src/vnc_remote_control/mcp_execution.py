"""Bounded asynchronous execution for synchronous controller-client calls."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from functools import partial
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


class McpCallCapacityError(RuntimeError):
    """Raised when all bounded controller-call execution slots are occupied."""


class McpExecutorClosedError(RuntimeError):
    """Raised when a controller call is submitted after executor shutdown starts."""


@contextmanager
def _managed_thread_pool(max_workers: int) -> Iterator[ThreadPoolExecutor]:
    """Yield the adapter-owned pool and guarantee blocking shutdown on close."""
    with ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="vrc-mcp-controller",
    ) as executor:
        yield executor


class BoundedControllerExecutor:
    """Run synchronous controller calls off-loop with fail-fast bounded admission.

    The executor owns exactly ``max_concurrent_calls`` worker threads and the
    same number of admission slots. A slot is reserved before submission, so no
    controller call can accumulate in ``ThreadPoolExecutor``'s otherwise
    unbounded internal queue. The worker wrapper, rather than the awaiting
    coroutine, releases the slot; therefore caller cancellation cannot make
    capacity appear free while the underlying synchronous call is still active.
    """

    def __init__(self, max_concurrent_calls: int) -> None:
        if max_concurrent_calls < 1:
            raise ValueError("max_concurrent_calls must be at least one")
        self._max_concurrent_calls = max_concurrent_calls
        self._available_slots = max_concurrent_calls
        self._state_lock = threading.Lock()
        self._closed = False
        self._shutdown_complete = threading.Event()
        self._resources = ExitStack()
        self._executor = self._resources.enter_context(
            _managed_thread_pool(max_concurrent_calls)
        )

    @property
    def max_concurrent_calls(self) -> int:
        """Return the fixed controller-call concurrency bound."""
        return self._max_concurrent_calls

    @property
    def closed(self) -> bool:
        """Return whether shutdown admission has begun."""
        with self._state_lock:
            return self._closed

    def _acquire_slot(self) -> None:
        with self._state_lock:
            if self._closed:
                raise McpExecutorClosedError("controller executor is closed")
            if self._available_slots == 0:
                raise McpCallCapacityError("controller call capacity is exhausted")
            self._available_slots -= 1

    def _release_slot(self) -> None:
        with self._state_lock:
            if self._available_slots >= self._max_concurrent_calls:
                raise RuntimeError("controller call capacity accounting overflow")
            self._available_slots += 1

    def _run_with_slot(self, operation: Callable[[], R]) -> R:
        try:
            return operation()
        finally:
            self._release_slot()

    async def call(
        self,
        operation: Callable[P, R],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> R:
        """Execute one synchronous controller call exactly once off the event loop."""
        self._acquire_slot()
        job = partial(operation, *args, **kwargs)
        try:
            concurrent_future = self._executor.submit(self._run_with_slot, job)
        except RuntimeError as exc:
            self._release_slot()
            raise McpExecutorClosedError(
                "controller executor closed before call submission"
            ) from exc

        # Shield prevents coroutine cancellation from cancelling a queued
        # concurrent Future before its worker wrapper runs and releases the
        # already-reserved slot. The caller still receives CancelledError.
        return await asyncio.shield(asyncio.wrap_future(concurrent_future))

    def close(self) -> None:
        """Stop new admission and wait for all already-admitted calls to finish."""
        with self._state_lock:
            if self._closed:
                wait_for_existing_shutdown = True
            else:
                self._closed = True
                wait_for_existing_shutdown = False

        if wait_for_existing_shutdown:
            self._shutdown_complete.wait()
            return

        try:
            self._resources.close()
        finally:
            self._shutdown_complete.set()

    async def aclose(self) -> None:
        """Close without blocking the event loop, even if the closer is cancelled."""
        close_task = asyncio.create_task(asyncio.to_thread(self.close))
        try:
            await asyncio.shield(close_task)
        except asyncio.CancelledError:
            # Shutdown remains authoritative: do not leave adapter-owned worker
            # threads running merely because the task performing cleanup was
            # cancelled. Re-propagate cancellation only after cleanup completes.
            await close_task
            raise

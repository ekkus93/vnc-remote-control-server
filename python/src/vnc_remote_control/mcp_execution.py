"""Bounded asynchronous execution for synchronous controller-client calls."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from functools import partial
from typing import Any, ParamSpec, TypeVar

from .errors import VncRemoteControlError

P = ParamSpec("P")
R = TypeVar("R")


class McpCallCapacityError(RuntimeError):
    """Raised when all bounded controller-call execution slots are occupied."""


class McpExecutorClosedError(RuntimeError):
    """Raised when a controller call is submitted after executor shutdown starts."""


class McpUnexpectedControllerError(RuntimeError):
    """Raised when one admitted controller operation fails outside the typed client API."""


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

    @staticmethod
    def _completed_result(future: asyncio.Future[R]) -> R:
        """Return one completed result while normalizing only untyped worker failures."""
        if future.cancelled():
            raise McpUnexpectedControllerError(
                "controller call future was unexpectedly cancelled"
            )
        error = future.exception()
        if error is not None:
            if isinstance(error, VncRemoteControlError):
                raise error
            raise McpUnexpectedControllerError(
                "controller call failed with an unexpected exception"
            ) from error
        return future.result()

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

        # Wait for completion without awaiting the wrapped Future directly. This
        # lets us inspect worker exceptions without a broad exception handler.
        # Shield preserves the capacity guarantee: cancelling the caller never
        # cancels the admitted worker or releases its slot early. Once submission
        # succeeds, cancellation can only arrive at this await, so a propagated
        # CancelledError means the controller call was already admitted.
        wrapped_future = asyncio.wrap_future(concurrent_future)
        try:
            await asyncio.shield(asyncio.wait((wrapped_future,)))
        except asyncio.CancelledError:
            if wrapped_future.done():
                # Prefer a terminal controller result that won the cancellation
                # race; this preserves any real command ID/outcome metadata.
                return self._completed_result(wrapped_future)
            # The original waiter is disappearing while the synchronous worker
            # remains authoritative. Transfer terminal-observation ownership to
            # a fixed callback so a later failure cannot become an unobserved
            # Future exception or leak exception payload text through asyncio's
            # default exception handler. Mutation outcome classification happens
            # one layer above, where read-vs-mutation intent is known.
            wrapped_future.add_done_callback(self._observe_abandoned_future)
            raise
        return self._completed_result(wrapped_future)

    @staticmethod
    def _observe_abandoned_future(future: asyncio.Future[Any]) -> None:
        """Consume one abandoned admitted future's terminal state without logging it."""
        if not future.cancelled():
            future.exception()

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

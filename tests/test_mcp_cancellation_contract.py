"""End-to-end dependency-free contracts for MCP cancellation ownership."""

# Intentional overlap with lower-level outcome/executor tests proves the same
# safety invariants through the actual registered mutation surface.
# pylint: disable=duplicate-code

from __future__ import annotations

import asyncio
import threading
import unittest
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

from mcp_test_support import RecordingToolRegistrar, RegisteredTool, fake_annotations_factory
from vnc_remote_control.errors import TransportError
from vnc_remote_control.mcp_execution import BoundedControllerExecutor, McpCallCapacityError
from vnc_remote_control.mcp_mutation_tools import (
    McpMutationClient,
    McpMutationRuntime,
    McpMutationValidationError,
    build_mutation_schema_metadata,
    register_mutation_tools,
)
from vnc_remote_control.mcp_outcomes import McpOutcomeToolRegistrar
from vnc_remote_control.models import CommandResponse


@dataclass(frozen=True, slots=True)
class FakeTextContent:
    """Minimal native text-content stand-in."""

    type: str
    text: str


@dataclass(frozen=True, slots=True)
class FakeCallToolResult:
    """Minimal native call-tool result stand-in."""

    content: list[FakeTextContent]
    structured_content: dict[str, object] | None = None
    is_error: bool = False


def _text_content_factory(**kwargs: Any) -> FakeTextContent:
    """Build one inspectable SDK-like text content value."""
    return FakeTextContent(type=kwargs["type"], text=kwargs["text"])


def _call_tool_result_factory(**kwargs: Any) -> FakeCallToolResult:
    """Build one inspectable SDK-like tool result value."""
    return FakeCallToolResult(
        content=kwargs["content"],
        structured_content=kwargs.get("structured_content"),
        is_error=kwargs.get("is_error", False),
    )


async def _wait_until(predicate: Callable[[], bool], *, timeout: float = 1.0) -> None:
    """Wait for one deterministic threaded-test condition."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition was not reached before timeout")
        await asyncio.sleep(0.001)


class BlockingMutationClient:
    """Fake client whose selected mutations stay active across caller cancellation."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.text_failure: BaseException | None = None

    def click_pointer(self, x: int, y: int, button: str) -> CommandResponse:
        """Record and block one pointer click until released by the test."""
        self.calls.append(("click_pointer", (x, y, button)))
        self.started.set()
        self.release.wait(timeout=2.0)
        self.finished.set()
        return CommandResponse(command_id=501, status="succeeded")

    def type_keyboard_text(self, text: str) -> CommandResponse:
        """Record and block one text mutation, optionally failing after release."""
        self.calls.append(("type_keyboard_text", (text,)))
        self.started.set()
        self.release.wait(timeout=2.0)
        self.finished.set()
        if self.text_failure is not None:
            raise self.text_failure
        return CommandResponse(command_id=502, status="succeeded")


def _registered_tools(
    client: BlockingMutationClient,
    executor: BoundedControllerExecutor,
) -> dict[str, RegisteredTool]:
    tools: dict[str, RegisteredTool] = {}
    registrar = McpOutcomeToolRegistrar(
        RecordingToolRegistrar(tools),
        call_tool_result_factory=_call_tool_result_factory,
        text_content_factory=_text_content_factory,
        mutation_validation_errors=(McpMutationValidationError,),
    )
    schema = build_mutation_schema_metadata(SimpleNamespace)
    register_mutation_tools(
        registrar,
        McpMutationRuntime(client=cast(McpMutationClient, client), executor=executor),
        annotations_factory=fake_annotations_factory,
        schema=schema,
    )
    return tools


class McpCancellationContractTests(unittest.IsolatedAsyncioTestCase):
    """Prove cancellation never turns an admitted mutation into replay-safe silence."""

    async def test_post_admission_read_cancellation_propagates_and_drains_worker(self) -> None:
        """Read cancellation propagates while terminal worker failure is still drained."""
        executor = BoundedControllerExecutor(1)
        self.addAsyncCleanup(executor.aclose)
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        diagnostics: list[dict[str, Any]] = []
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: diagnostics.append(context))
        self.addCleanup(loop.set_exception_handler, previous_handler)

        def read_operation() -> str:
            started.set()
            release.wait(timeout=2.0)
            finished.set()
            raise TransportError("SENSITIVE_READ_CANCEL_DETAIL")

        tools: dict[str, RegisteredTool] = {}
        registrar = McpOutcomeToolRegistrar(
            RecordingToolRegistrar(tools),
            call_tool_result_factory=_call_tool_result_factory,
            text_content_factory=_text_content_factory,
            mutation_validation_errors=(McpMutationValidationError,),
        )

        @registrar(
            name="test_read",
            description="test read",
            annotations=SimpleNamespace(read_only_hint=True),
            structured_output=True,
        )
        async def test_read() -> str:
            return await executor.call(read_operation)

        task = asyncio.create_task(tools["test_read"][0]())
        await _wait_until(started.is_set)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        with self.assertRaises(McpCallCapacityError):
            await executor.call(lambda: None)

        release.set()
        await _wait_until(finished.is_set)
        await asyncio.sleep(0)
        self.assertEqual(diagnostics, [])
        self.assertIsNone(await executor.call(lambda: None))

    async def test_cancel_before_handler_runs_issues_no_controller_call(self) -> None:
        """Cancellation before scheduling proves that no controller mutation is issued."""
        executor = BoundedControllerExecutor(1)
        self.addAsyncCleanup(executor.aclose)
        client = BlockingMutationClient()
        tools = _registered_tools(client, executor)

        task = asyncio.create_task(tools["vnc_click_pointer"][0](1, 2, "left"))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(client.calls, [])
        self.assertFalse(client.started.is_set())

    async def test_post_admission_click_cancellation_is_unknown_and_exactly_once(self) -> None:
        """An admitted click becomes unknown/non-retry-safe and runs exactly once."""
        executor = BoundedControllerExecutor(1)
        self.addAsyncCleanup(executor.aclose)
        client = BlockingMutationClient()
        tools = _registered_tools(client, executor)

        task = asyncio.create_task(tools["vnc_click_pointer"][0](11, 12, "left"))
        await _wait_until(client.started.is_set)
        task.cancel()
        result = await task

        self.assertIsInstance(result, FakeCallToolResult)
        self.assertTrue(result.is_error)
        self.assertEqual(
            result.structured_content,
            {
                "kind": "mutation_outcome_unknown",
                "command_id": None,
                "outcome": "unknown",
                "retry_safe": False,
                "instruction": (
                    "Automatic replay is unsafe because the controller may already have "
                    "received the mutation."
                ),
            },
        )
        self.assertIn("cancelled after controller-call admission", result.content[0].text)
        self.assertEqual(client.calls, [("click_pointer", (11, 12, "left"))])

        with self.assertRaises(McpCallCapacityError):
            await executor.call(lambda: None)
        client.release.set()
        await _wait_until(client.finished.is_set)
        self.assertIsNone(await executor.call(lambda: None))
        self.assertEqual(len(client.calls), 1)

    async def test_cancelled_sensitive_mutation_failure_is_drained_without_payload_log(
        self,
    ) -> None:
        """A cancelled payload mutation drains later failure without leaking its payload."""
        executor = BoundedControllerExecutor(1)
        self.addAsyncCleanup(executor.aclose)
        client = BlockingMutationClient()
        secret = "TYPE_SECRET_CANCEL_SENTINEL"
        client.text_failure = TransportError(f"transport failed around {secret}")
        tools = _registered_tools(client, executor)
        loop = asyncio.get_running_loop()
        diagnostics: list[dict[str, Any]] = []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: diagnostics.append(context))
        self.addCleanup(loop.set_exception_handler, previous_handler)

        task = asyncio.create_task(tools["vnc_type_keyboard_text"][0](secret))
        await _wait_until(client.started.is_set)
        task.cancel()
        result = await task
        self.assertEqual(result.structured_content["kind"], "mutation_outcome_unknown")
        self.assertFalse(result.structured_content["retry_safe"])
        self.assertNotIn(secret, result.content[0].text)

        client.release.set()
        await _wait_until(client.finished.is_set)
        await asyncio.sleep(0)
        self.assertEqual(diagnostics, [])
        self.assertEqual(client.calls, [("type_keyboard_text", (secret,))])


if __name__ == "__main__":
    unittest.main()

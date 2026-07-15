from __future__ import annotations

import io
import unittest
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console

from agent.tui import DisplayManager, _run_react_turn
from tools.base import Tool, ToolRegistry


ROOT = Path(__file__).resolve().parents[1]


class _MockDisplay(DisplayManager):
    """DisplayManager that records what would be rendered instead of printing."""

    def __init__(self, console: Console) -> None:
        super().__init__(console)
        self.calls: list[tuple[str, Any, ...]] = []

    def render_user(self, text: str):
        self.calls.append(("user", text))
        return super().render_user(text)

    def render_assistant(self, text: str):
        self.calls.append(("assistant", text))
        return super().render_assistant(text)

    def render_tool_call(self, name: str, args: dict[str, Any], verdict: str = "?"):
        self.calls.append(("tool_call", name, args, verdict))
        return super().render_tool_call(name, args, verdict)

    def render_tool_result(self, name: str, result: str):
        self.calls.append(("tool_result", name, result))
        return super().render_tool_result(name, result)

    def render_system(self, text: str):
        self.calls.append(("system", text))
        return super().render_system(text)


class _StreamingBackend:
    """Backend with chat_stream that emits one tool call then a final answer."""

    def __init__(self, tool_name: str = "echo", arguments: dict | None = None) -> None:
        self.model = "test-stream"
        self._tool_name = tool_name
        self._arguments = arguments or {}

    def chat_stream(self, messages, tools=None):
        if messages and messages[-1].get("role") == "tool":
            yield {"type": "content", "content": "final answer"}
            yield {"type": "done", "content": "final answer", "tool_calls": []}
            return

        yield {"type": "content", "content": "thinking..."}
        yield {"type": "tool_call_start", "name": self._tool_name, "index": 0}
        yield {
            "type": "done",
            "content": "thinking...",
            "tool_calls": [
                {"id": "tc1", "name": self._tool_name, "arguments": self._arguments}
            ],
        }


class _FailingStreamBackend:
    model = "test-fallback"

    def chat_stream(self, messages, tools=None):
        raise httpx.ConnectError("stream dropped")
        yield  # pragma: no cover - make this function a generator

    def chat(self, messages, tools=None):
        return {
            "content": "fallback answer",
            "tool_calls": [],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        }


class TuiWrapperTests(unittest.TestCase):
    def _run(self, backend, registry, messages, auto_approve=False, confirmer=None):
        output = io.StringIO()
        console = Console(file=output, force_terminal=False)
        display = _MockDisplay(console)
        _run_react_turn(
            backend, registry, messages, display, console,
            auto_approve=auto_approve, confirmer=confirmer, workdir=ROOT,
        )
        return display, messages

    def test_streaming_tool_call_and_final_answer(self):
        registry = ToolRegistry()
        registry.register(Tool("echo", "test", {"type": "object"}, lambda **kw: "ok"))

        backend = _StreamingBackend(tool_name="echo", arguments={"x": 1})
        messages = [{"role": "system", "content": "sys"}]
        display, messages = self._run(backend, registry, messages, auto_approve=True)

        # assistant + tool result + final assistant = 3 new messages
        self.assertEqual(len(messages), 4)
        self.assertEqual(messages[-1]["role"], "assistant")
        self.assertEqual(messages[-1]["content"], "final answer")

        rendered = [(c[0], c[1]) for c in display.calls]
        self.assertIn(("tool_call", "echo"), rendered)
        self.assertIn(("tool_result", "echo"), rendered)
        # final assistant panel rendered
        self.assertTrue(any(c[0] == "assistant" and c[1] == "final answer" for c in display.calls))

    def test_confirmer_refuses_tool(self):
        registry = ToolRegistry()
        registry.register(Tool("echo", "test", {"type": "object"}, lambda **kw: "ok"))

        backend = _StreamingBackend(tool_name="echo", arguments={"x": 1})
        messages = [{"role": "system", "content": "sys"}]

        def confirmer(name, args, reason):
            return False

        display, messages = self._run(backend, registry, messages, confirmer=confirmer)

        # Tool result should be a refusal observation, not "ok".
        tool_msg = next(m for m in messages if m["role"] == "tool")
        self.assertIn("需确认", tool_msg["content"])

        rendered = [(c[0], c[1]) for c in display.calls]
        self.assertIn(("tool_call", "echo"), rendered)
        self.assertIn(("tool_result", "echo"), rendered)

    def test_unknown_tool_renders_error(self):
        registry = ToolRegistry()
        backend = _StreamingBackend(tool_name="missing", arguments={})
        messages = [{"role": "system", "content": "sys"}]
        display, messages = self._run(backend, registry, messages)

        tool_msg = next(m for m in messages if m["role"] == "tool")
        self.assertIn("未知工具", tool_msg["content"])

    def test_retryable_stream_error_falls_back_to_non_streaming_chat(self):
        messages = [{"role": "system", "content": "sys"}]
        display, messages = self._run(_FailingStreamBackend(), ToolRegistry(), messages)

        self.assertEqual(messages[-1]["content"], "fallback answer")
        self.assertTrue(any(
            call[0] == "assistant" and call[1] == "fallback answer"
            for call in display.calls
        ))


if __name__ == "__main__":
    unittest.main()

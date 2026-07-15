from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from agent.strategy import ReactCallbacks, run_react_turns
from tools.base import Tool, ToolRegistry


ROOT = Path(__file__).resolve().parents[1]


class StrategyTests(unittest.TestCase):
    def _make_registry(self, name: str = "echo", run=None):
        registry = ToolRegistry()
        run = run or (lambda **kw: f"ran: {kw}")
        registry.register(Tool(name, "test", {"type": "object"}, run))
        return registry

    def test_returns_final_answer_when_no_tool_calls(self):
        def backend_call(messages, tools):
            return {"content": "final answer", "tool_calls": []}

        registry = self._make_registry()
        messages = [{"role": "system", "content": "sys"}]
        result = run_react_turns(backend_call, registry, messages)

        self.assertEqual(result, "final answer")
        self.assertEqual(messages[-1]["role"], "assistant")
        self.assertEqual(messages[-1]["content"], "final answer")

    def test_dispatches_tool_and_injects_observation(self):
        calls = []

        def backend_call(messages, tools):
            if messages[-1]["role"] == "tool":
                return {"content": "done", "tool_calls": []}
            return {
                "content": "",
                "tool_calls": [{"id": "t1", "name": "echo", "arguments": {"x": 1}}],
            }

        registry = self._make_registry(run=lambda **kw: calls.append(kw) or "ok")
        messages = [{"role": "system", "content": "sys"}]
        result = run_react_turns(
            backend_call, registry, messages, auto_approve=True, workdir=ROOT
        )

        self.assertEqual(result, "done")
        self.assertEqual(calls, [{"x": 1}])
        self.assertEqual(messages[-2]["role"], "tool")
        self.assertEqual(messages[-2]["content"], "ok")

    def test_unknown_tool_produces_error_observation(self):
        def backend_call(messages, tools):
            if messages[-1]["role"] == "tool":
                return {"content": "done", "tool_calls": []}
            return {
                "content": "",
                "tool_calls": [{"id": "t1", "name": "missing", "arguments": {}}],
            }

        registry = self._make_registry()
        messages = [{"role": "system", "content": "sys"}]
        result = run_react_turns(backend_call, registry, messages)

        self.assertEqual(result, "done")
        self.assertEqual(messages[-2]["role"], "tool")
        self.assertIn("未知工具", messages[-2]["content"])

    def test_max_turns_reached(self):
        def backend_call(messages, tools):
            return {
                "content": "",
                "tool_calls": [{"id": "t1", "name": "echo", "arguments": {}}],
            }

        registry = self._make_registry()
        messages = [{"role": "system", "content": "sys"}]

        reached = []
        callbacks = ReactCallbacks(
            on_max_turns_reached=lambda: reached.append(True)
        )
        result = run_react_turns(
            backend_call, registry, messages, max_turns=2, callbacks=callbacks, workdir=ROOT
        )

        self.assertIn("最大轮数", result)
        self.assertEqual(reached, [True])
        # 2 assistant + 2 tool results = 4 messages appended to initial system
        self.assertEqual(len(messages), 5)

    def test_confirmer_is_consulted(self):
        confirmed = []

        def backend_call(messages, tools):
            if messages[-1]["role"] == "tool":
                return {"content": "done", "tool_calls": []}
            return {
                "content": "",
                "tool_calls": [{"id": "t1", "name": "echo", "arguments": {"x": 1}}],
            }

        def confirmer(name, args, reason):
            confirmed.append((name, args, reason))
            return False

        registry = self._make_registry()
        messages = [{"role": "system", "content": "sys"}]
        result = run_react_turns(
            backend_call, registry, messages, confirmer=confirmer, workdir=ROOT
        )

        self.assertEqual(result, "done")
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(confirmed[0][0], "echo")
        # Confirmer refused, so the observation should say "需确认".
        tool_msg = next(m for m in messages if m["role"] == "tool")
        self.assertIn("需确认", tool_msg["content"])

    def test_callbacks_fire(self):
        events = []

        def backend_call(messages, tools):
            if messages[-1]["role"] == "tool":
                return {"content": "final", "tool_calls": []}
            return {
                "content": "thinking",
                "tool_calls": [{"id": "t1", "name": "echo", "arguments": {"x": 1}}],
            }

        callbacks = ReactCallbacks(
            on_assistant_message=lambda c, t: events.append(("assistant", c)),
            on_tool_call=lambda n, a, v: events.append(("tool_call", n)),
            on_tool_result=lambda n, r: events.append(("tool_result", n, r)),
        )

        registry = self._make_registry(run=lambda **kw: "ok")
        messages = [{"role": "system", "content": "sys"}]
        run_react_turns(
            backend_call, registry, messages,
            auto_approve=True, callbacks=callbacks, workdir=ROOT
        )

        self.assertEqual(events, [
            ("assistant", "thinking"),
            ("tool_call", "echo"),
            ("tool_result", "echo", "ok"),
            ("assistant", "final"),
        ])

    def test_actual_prompt_usage_triggers_context_compaction(self):
        calls = 0
        compacted_inputs = []

        def backend_call(messages, tools):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {
                    "content": "",
                    "tool_calls": [{"id": "t1", "name": "echo", "arguments": {}}],
                    "usage": {"prompt_tokens": 1_000, "completion_tokens": 10, "total_tokens": 1_010},
                }
            compacted_inputs.extend(messages)
            return {"content": "done", "tool_calls": []}

        events = []
        callbacks = ReactCallbacks(on_context_compacted=lambda: events.append("compacted"))
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "old user"},
            {"role": "assistant", "content": "old assistant"},
            {"role": "tool", "content": "old observation"},
        ]

        result = run_react_turns(
            backend_call,
            self._make_registry(),
            messages,
            token_budget=100,
            auto_approve=True,
            callbacks=callbacks,
            workdir=ROOT,
        )

        self.assertEqual(result, "done")
        self.assertEqual(events, ["compacted"])
        self.assertTrue(any("[上下文压缩" in str(item.get("content", "")) for item in compacted_inputs))


if __name__ == "__main__":
    unittest.main()

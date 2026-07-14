from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.loop import AgentLoop
from agent.strategy import run_react_turns
from agent.tracer import Tracer, cost_report, replay
from tools.base import Tool, ToolRegistry


class TracerTests(unittest.TestCase):
    def test_agent_loop_persists_trace_and_exposes_latest_tracer(self):
        class FinalBackend:
            def chat(self, messages, tools=None):
                return {
                    "content": "done", "tool_calls": [],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
                }

        with tempfile.TemporaryDirectory() as directory:
            agent = AgentLoop(FinalBackend(), ToolRegistry(), "sys", workdir=Path(directory))
            self.assertEqual(agent.run("task"), "done")
            self.assertIsNotNone(agent.last_tracer)
            self.assertEqual(agent.last_tracer.spans[0]["tokens"], 10)
            self.assertTrue(agent.last_tracer.path.is_file())
            self.assertIn("agent-runs", agent.last_tracer.path.parts)

    def test_span_records_usage_timing_and_safe_llm_summary(self):
        tracer = Tracer()
        response = {
            "content": "private model prose",
            "tool_calls": [{"name": "read", "arguments": {"path": "a.txt"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        }

        self.assertIs(tracer.span("llm", "decide", lambda: response, turn=0), response)
        span = tracer.spans[0]
        self.assertTrue(span["ok"])
        self.assertGreaterEqual(span["duration_ms"], 0)
        self.assertEqual(span["tokens"], 13)
        self.assertEqual(span["usage"]["prompt_tokens"], 10)
        self.assertIn("read", span["out"])
        self.assertNotIn("private model prose", span["out"])

    def test_exception_is_recorded_redacted_and_reraised(self):
        tracer = Tracer()

        def fail():
            raise RuntimeError("TOKEN=do-not-store")

        with self.assertRaises(RuntimeError):
            tracer.span("tool", "broken", fail)

        self.assertFalse(tracer.spans[0]["ok"])
        self.assertNotIn("do-not-store", tracer.spans[0]["out"])
        self.assertIn("[REDACTED]", tracer.spans[0]["out"])

    def test_replay_and_cost_report_accept_persisted_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            tracer = Tracer(path)
            tracer.span("llm", "decide", lambda: {
                "content": "first",
                "tool_calls": [],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            })
            tracer.span("llm", "decide", lambda: {
                "content": "second",
                "tool_calls": [],
                "usage": {"prompt_tokens": 250, "completion_tokens": 30, "total_tokens": 280},
            })

            rendered = replay(path, emit=False)
            report = cost_report(
                path, prompt_price_per_1k=0.001,
                completion_price_per_1k=0.002, emit=False,
            )

            self.assertIn("120tok", rendered)
            self.assertEqual(report["prompt_tokens"], 350)
            self.assertEqual(report["completion_tokens"], 50)
            self.assertEqual(report["total_tokens"], 400)
            self.assertEqual(report["priciest"]["seq"], 2)
            self.assertAlmostEqual(report["estimated_cost"], 0.00045)

    def test_react_integration_orders_llm_tool_llm_and_keeps_observation(self):
        tracer = Tracer()
        registry = ToolRegistry()
        registry.register(Tool(
            "echo", "test", {"type": "object"},
            lambda **kwargs: f"result={kwargs['value']}",
        ))

        def backend(messages, tools):
            if messages[-1]["role"] == "tool":
                self.assertEqual(messages[-1]["content"], "result=7")
                return {
                    "content": "done", "tool_calls": [],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 2, "total_tokens": 22},
                }
            return {
                "content": "", "tool_calls": [
                    {"id": "c1", "name": "echo", "arguments": {"value": 7}}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
            }

        messages = [{"role": "system", "content": "sys"}]
        result = run_react_turns(
            backend, registry, messages, auto_approve=True,
            workdir=Path.cwd(), tracer=tracer,
        )

        self.assertEqual(result, "done")
        self.assertEqual([span["kind"] for span in tracer.spans], ["llm", "tool", "llm"])
        self.assertEqual([span.get("tokens") for span in tracer.spans], [11, None, 22])
        self.assertEqual(messages[-2]["role"], "tool")

    def test_jsonl_contains_no_raw_model_prose_or_secret_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            tracer = Tracer(path)
            tracer.span("llm", "decide", lambda: {
                "content": "raw model prose", "tool_calls": [],
                "usage": {"total_tokens": 1},
            }, api_key="secret-value")
            stored = path.read_text(encoding="utf-8")
            event = json.loads(stored)
            self.assertNotIn("raw model prose", stored)
            self.assertNotIn("secret-value", stored)
            self.assertEqual(event["api_key"], "[REDACTED]")


if __name__ == "__main__":
    unittest.main()

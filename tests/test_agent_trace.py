import json
import tempfile
import unittest
from pathlib import Path

from agent.loop import AgentLoop
from backend.fake_backend import FakeBackend
from tools.base import Tool, ToolRegistry


class _ToolBackend:
    def chat(self, messages, tools=None):
        if messages[-1]["role"] == "tool":
            return {"content": "done", "tool_calls": []}
        return {"content": "", "tool_calls": [{"id": "1", "name": "probe", "arguments": {}}]}


class AgentTraceTests(unittest.TestCase):
    def test_trace_records_agent_and_tool_events(self):
        registry = ToolRegistry()
        registry.register(Tool("probe", "probe", {"type": "object", "properties": {}}, lambda: "ok"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            result = AgentLoop(_ToolBackend(), registry, "system", auto_approve=True, trace_path=path).run("go")
            events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(result, "done")
        self.assertEqual([event["type"] for event in events], ["assistant", "tool", "assistant"])
        self.assertEqual(events[1]["name"], "probe")


if __name__ == "__main__":
    unittest.main()

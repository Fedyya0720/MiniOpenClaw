from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from agent.context import spill_observation
from agent.loop import AgentLoop
from agent.strategy import run_react_turns
from agent.trace import ToolRunTrace, redact_text
from envpool.install import InstallSpec, serial_install
from envpool.manager import EnvironmentPool
from envpool.sandbox import SandboxDescriptor
from tools.base import Tool, ToolRegistry


def _direct_sandbox(command, env_path, workdir):
    return SandboxDescriptor(list(command), "test-direct", False, True, [], [], "test mode")


class _OneToolBackend:
    def __init__(self, name: str, arguments: dict[str, object]) -> None:
        self.name = name
        self.arguments = arguments

    def chat(self, messages, tools=None):
        if messages[-1]["role"] == "tool":
            return {"content": "final model prose must not be traced", "tool_calls": []}
        return {
            "content": "model prose must not be traced",
            "tool_calls": [{"id": "call-evidence", "name": self.name, "arguments": self.arguments}],
        }


class ToolTraceTests(unittest.TestCase):
    def _registry(self, result: str = "normal output") -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(Tool("echo", "test", {"type": "object"}, lambda **_args: result))
        return registry

    def _events(self, directory: Path) -> tuple[Path, list[dict]]:
        runs = list((directory / ".mini-openclaw" / "tool-runs").iterdir())
        self.assertEqual(len(runs), 1)
        trace_file = runs[0] / "trace.jsonl"
        return runs[0], [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]

    def test_clean_output_is_exact_with_metadata_and_tool_only_events(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent = AgentLoop(
                _OneToolBackend("echo", {"value": "safe"}), self._registry("hello\nworld"),
                "system prose must not be traced", auto_approve=True, workdir=root,
            )
            self.assertEqual(agent.run("user prose must not be traced"), "final model prose must not be traced")
            run, events = self._events(root)
            self.assertEqual([event["event"] for event in events], ["tool_call", "tool_result"])
            call, result = events
            self.assertEqual(call["tool_id"], "call-evidence")
            self.assertEqual(call["arguments"], {"value": "safe"})
            self.assertEqual(result["status"], "ok")
            self.assertFalse(result["redacted"])
            self.assertEqual(result["original_sha256"], hashlib.sha256(b"hello\nworld").hexdigest())
            artifact = run / result["artifact_path"]
            self.assertEqual(artifact.read_text(encoding="utf-8"), "hello\nworld")
            serialized = (run / "trace.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("user prose", serialized)
            self.assertNotIn("model prose", serialized)
            self.assertNotIn("system prose", serialized)

    def test_default_redacts_arguments_and_results(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MINIOPENCLAW_TRACE_SENSITIVE", None)
            root = Path(directory)
            agent = AgentLoop(
                _OneToolBackend("echo", {"api_key": "arg-secret"}),
                self._registry("TOKEN=result-secret\nAuthorization: Bearer abc123\nerror ordinary"),
                "sys", auto_approve=True, workdir=root,
            )
            agent.run("task")
            run, events = self._events(root)
            self.assertEqual(events[0]["arguments"]["api_key"], "[REDACTED]")
            result = events[1]
            self.assertTrue(result["redacted"])
            self.assertFalse(result["sensitive_retention"])
            stored = (run / result["artifact_path"]).read_text(encoding="utf-8")
            self.assertNotIn("result-secret", stored)
            self.assertNotIn("abc123", stored)
            self.assertIn("error ordinary", stored)

    def test_forensic_opt_in_retains_exact_sensitive_content(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ, {"MINIOPENCLAW_TRACE_SENSITIVE": "1"}, clear=False
        ):
            root = Path(directory)
            agent = AgentLoop(
                _OneToolBackend("echo", {"token": "argument-token"}),
                self._registry("PASSWORD=result-password"), "sys", auto_approve=True, workdir=root,
            )
            agent.run("task")
            run, events = self._events(root)
            self.assertEqual(events[0]["arguments"]["token"], "argument-token")
            self.assertTrue(events[0]["sensitive_retention"])
            result = events[1]
            self.assertTrue(result["sensitive_retention"])
            self.assertFalse(result["redacted"])
            self.assertEqual((run / result["artifact_path"]).read_text(encoding="utf-8"), "PASSWORD=result-password")

    def test_large_result_is_complete_and_permission_status_is_traced(self):
        large = "x" * 1_100_123
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = ToolRunTrace(root)
            registry = self._registry(large)

            def backend(messages, tools):
                if messages[-1]["role"] == "tool":
                    return {"content": "done", "tool_calls": []}
                return {"content": "", "tool_calls": [{"id": "large", "name": "echo", "arguments": {}}]}

            run_react_turns(backend, registry, [{"role": "system", "content": "sys"}],
                            auto_approve=True, workdir=root, spill_threshold=1, trace=trace)
            artifact = next((trace.artifact_root).iterdir())
            self.assertEqual(artifact.stat().st_size, len(large.encode("utf-8")))

            denied_trace = ToolRunTrace(root)
            denied = ToolRegistry()
            denied.register(Tool("bash", "test", {"type": "object"}, lambda **_args: "not run"))
            run_react_turns(backend_call=lambda *_args, **_kwargs: {
                "content": "", "tool_calls": [{"id": "deny", "name": "bash", "arguments": {"command": "echo x"}}]
            }, registry=denied, messages=[{"role": "system", "content": "sys"}],
                            max_turns=1, workdir=root, trace=denied_trace)
            denied_events = [json.loads(line) for line in denied_trace.trace_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(denied_events[-1]["status"], "permission_denied")


class RedactionTests(unittest.TestCase):
    def test_redacts_json_shell_bearer_and_url_credentials(self):
        original = (
            '{"api_key":"json-secret","normal":"ordinary words"}\n'
            'PASSWORD="shell-secret"\n'
            'Authorization: Bearer bearer-secret\n'
            'https://user:url-secret@example.test/path'
        )
        redacted, sensitive = redact_text(original)
        self.assertTrue(sensitive)
        for secret in ("json-secret", "shell-secret", "bearer-secret", "url-secret"):
            self.assertNotIn(secret, redacted)
        self.assertIn('"api_key":"[REDACTED]"', redacted)
        self.assertIn('PASSWORD="[REDACTED]"', redacted)
        self.assertIn("ordinary words", redacted)

    def test_large_ordinary_text_stays_exact_and_fast(self):
        original = "ordinary diagnostics without credential syntax\n" * 30_000
        started = time.monotonic()
        redacted, sensitive = redact_text(original)
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertFalse(sensitive)
        self.assertEqual(redacted, original)


    def test_large_sensitive_spill_redacts_by_default_with_secure_modes(self):
        payload = '{"api_key":"spill-secret"}\n' + ("x" * 20_000)
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MINIOPENCLAW_TRACE_SENSITIVE", None)
            root = Path(directory)
            summary = spill_observation(payload, "echo", root, threshold=1)
            artifact = next((root / ".mini-openclaw" / "spill").iterdir())
            stored = artifact.read_text(encoding="utf-8")
            self.assertNotIn("spill-secret", stored)
            self.assertIn('"api_key":"[REDACTED]"', stored)
            self.assertNotIn("spill-secret", summary)
            self.assertIn("原始内容", summary)
            self.assertIn("存储内容", summary)
            self.assertIn("已脱敏：是", summary)
            self.assertEqual((artifact.stat().st_mode & 0o777), 0o600)
            self.assertEqual(((root / ".mini-openclaw" / "spill").stat().st_mode & 0o777), 0o700)

    def test_sensitive_spill_forensic_opt_in_retains_exact_artifact(self):
        payload = "TOKEN=forensic-secret\n" + ("x" * 20_000)
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ, {"MINIOPENCLAW_TRACE_SENSITIVE": "1"}, clear=False
        ):
            root = Path(directory)
            summary = spill_observation(payload, "echo", root, threshold=1)
            artifact = next((root / ".mini-openclaw" / "spill").iterdir())
            self.assertEqual(artifact.read_text(encoding="utf-8"), payload)
            self.assertNotIn("forensic-secret", summary)
            self.assertIn("敏感内容保留：是", summary)
            self.assertIn("已脱敏：否", summary)

    def test_large_spill_is_complete_and_external_custom_directory_is_safe(self):
        payload = "z" * 1_050_000
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ, {"MINIOPENCLAW_SPILL_DIR": "/tmp/unsafe-spill"}, clear=False
        ):
            root = Path(directory)
            summary = spill_observation(payload, "echo", root, threshold=1)
            self.assertIn("SHA-256", summary)
            spills = list((root / ".mini-openclaw" / "spill").iterdir())
            self.assertEqual(len(spills), 1)
            self.assertEqual(spills[0].read_text(encoding="utf-8"), payload)


class PacsEvidenceTests(unittest.TestCase):
    def test_durable_log_survives_cleanup_with_correct_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pool = EnvironmentPool(root)
            info = pool.create("evidence", env_id="evidence")
            spec = InstallSpec(
                env_id="evidence", label="evidence",
                argv=[info.python, "-c", "print('durable-output')"],
            )
            with mock.patch("envpool.install.build_sandbox", side_effect=_direct_sandbox):
                batch = serial_install(pool, [spec], timeout=5, allow_test_commands=True)
            result = batch.results[0]
            log = Path(result.log_path)
            stored = log.read_text(encoding="utf-8")
            self.assertEqual(result.batch_id, batch.batch_id)
            self.assertTrue(log.is_file())
            self.assertEqual(result.stored_sha256, hashlib.sha256(stored.encode("utf-8")).hexdigest())
            pool.cleanup("evidence")
            self.assertTrue(log.is_file())
            self.assertIn("durable-output", log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

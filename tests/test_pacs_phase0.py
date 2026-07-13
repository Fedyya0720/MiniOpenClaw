"""Phase 0 scaffolding tests: package imports, autonomous mode, PACS permission classification.

Run: python -m unittest tests.test_pacs_phase0
"""
import os
import unittest
from unittest import mock

from agent.permissions import (
    PACS_READONLY,
    PACS_EXEC,
    evaluate,
)
from pathlib import Path


class PackageImportTest(unittest.TestCase):
    def test_envpool_and_resolver_importable(self):
        import envpool  # noqa: F401
        import resolver  # noqa: F401

    def test_selfcheck_still_passes_registry(self):
        from tools.base import build_default_registry
        reg = build_default_registry()
        # Phase 1 registers five PACS tools on top of the 9 baseline tools.
        self.assertEqual(len(reg), 14)


class PacsPermissionClassificationTest(unittest.TestCase):
    def setUp(self):
        self.workdir = Path.cwd()

    def test_resolver_tools_auto_allow(self):
        # Pure-compute resolver tools should auto-allow (no prompt) even without
        # --auto-approve, so the agent isn't blocked mid-search.
        for tool in PACS_READONLY:
            verdict = evaluate(tool, {}, self.workdir).verdict
            self.assertEqual(verdict, "allow", f"{tool} should auto-allow, got {verdict}")

    def test_envpool_tools_confirm_without_flag(self):
        # envpool tools spawn pip → confirm by default (not auto-allow without the flag).
        for tool in PACS_EXEC:
            verdict = evaluate(tool, {}, self.workdir).verdict
            self.assertEqual(verdict, "confirm", f"{tool} should confirm, got {verdict}")

    def test_envpool_tools_auto_approved_via_permission_observation(self):
        # Under auto_approve=True the confirm verdict is authorized (None returned).
        from agent.permissions import permission_observation
        for tool in PACS_EXEC:
            obs = permission_observation(tool, {}, self.workdir, auto_approve=True)
            self.assertIsNone(obs, f"{tool} should be authorized under auto_approve")

    def test_resolver_tools_authorized_even_without_auto_approve(self):
        from agent.permissions import permission_observation
        for tool in PACS_READONLY:
            obs = permission_observation(tool, {}, self.workdir, auto_approve=False)
            self.assertIsNone(obs, f"{tool} should be authorized without auto_approve")


class AutonomousModeTest(unittest.TestCase):
    def _run_cli(self, argv, env=None):
        import agent.cli as cli

        captured = {}

        class FakeLoop:
            def __init__(self, backend, registry, system_prompt, **kwargs):
                captured.update(kwargs)

            def run(self, task, images=None):
                captured["task"] = task
                return "done"

        with mock.patch.object(cli, "_build_agent_deps", return_value=(object(), object(), "system")), \
             mock.patch("agent.loop.AgentLoop", FakeLoop), \
             mock.patch("builtins.print"), \
             mock.patch.dict(os.environ, env or {}, clear=False):
            cli.main(argv)
            captured["serial_env"] = os.environ.get("MINIOPENCLAW_PACS_SERIAL")
        return captured

    def test_env_var_enables_auto_approve(self):
        captured = self._run_cli(
            ["configure project"],
            {"MINIOPENCLAW_AUTO_APPROVE": "1"},
        )
        self.assertTrue(captured["auto_approve"])
        self.assertEqual(captured["task"], "configure project")

    def test_explicit_flag_enables_auto_approve(self):
        captured = self._run_cli(
            ["--auto-approve", "configure project"],
            {"MINIOPENCLAW_AUTO_APPROVE": "0"},
        )
        self.assertTrue(captured["auto_approve"])

    def test_serial_flag_sets_env_var(self):
        captured = self._run_cli(["--serial", "configure project"])
        self.assertEqual(captured["serial_env"], "1")


if __name__ == "__main__":
    unittest.main()

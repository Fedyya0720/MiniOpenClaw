from __future__ import annotations

import unittest
from pathlib import Path

from agent.permissions import check
from tools.base import build_default_registry


ROOT = Path(__file__).resolve().parents[1]


class SkillToolTests(unittest.TestCase):
    def test_default_registry_loads_full_skill_body(self):
        tool = build_default_registry().get("skill")
        self.assertIsNotNone(tool)
        body = tool.run(name="python-debug")
        self.assertIn("# Skill: python-debug", body)
        self.assertIn("复现错误", body)
        self.assertIn("最小修复", body)

    def test_skill_loading_is_read_only(self):
        self.assertEqual(check("skill", {"name": "python-debug"}, ROOT), "allow")

    def test_unknown_skill_lists_available_names(self):
        tool = build_default_registry().get("skill")
        result = tool.run(name="missing-skill")
        self.assertIn("未找到 Skill", result)
        self.assertIn("python-debug", result)


if __name__ == "__main__":
    unittest.main()

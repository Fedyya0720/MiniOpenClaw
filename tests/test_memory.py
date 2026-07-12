import tempfile
import unittest
from pathlib import Path

from agent.memory import KVMemory, Memory, inject_memory
from tools.base import build_default_registry
from tools.memory import remember


class MemoryTest(unittest.TestCase):
    def test_memory_survives_new_instance_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "MEMORY.md"
            Memory(path).write("时间戳使用 UTC")
            Memory(path).write("时间戳使用 UTC")
            self.assertEqual(Memory(path).recall(), "- 时间戳使用 UTC\n")

    def test_recall_can_filter_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "MEMORY.md"
            memory = Memory(path)
            memory.write("包管理器使用 pnpm")
            memory.write("时间戳使用 UTC")
            self.assertEqual(memory.recall("PNPM"), "- 包管理器使用 pnpm")

    def test_inject_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "MEMORY.md"
            Memory(path).write("测试使用 unittest")
            prompt = inject_memory("system", Memory(path))
            self.assertIn("已知记忆", prompt)
            self.assertIn("测试使用 unittest", prompt)

    def test_remember_tool_writes_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "MEMORY.md"
            result = remember("API 时间使用 ISO-8601", path)
            self.assertEqual(result, "已记住：API 时间使用 ISO-8601")
            self.assertIn("ISO-8601", path.read_text(encoding="utf-8"))

    def test_remember_tool_is_in_default_registry(self):
        self.assertIsNotNone(build_default_registry().get("remember"))


class KVMemoryTest(unittest.TestCase):
    def test_update_and_forget_are_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            memory = KVMemory(path)
            memory.remember("pm", "npm")
            memory.remember("pm", "pnpm")
            self.assertEqual(KVMemory(path).recall("pm"), "pnpm")
            self.assertTrue(memory.forget("pm"))
            self.assertIsNone(KVMemory(path).recall("pm"))


if __name__ == "__main__":
    unittest.main()

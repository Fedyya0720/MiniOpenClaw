"""跨会话记忆：文本项目记忆与结构化键值记忆。

Memory 面向会影响未来行为的稳定约定；它与仅在一次运行中生效的
``agent.context`` 不同。默认路径相对当前工作目录解析，确保 CLI 在项目
目录启动时始终读写同一份项目记忆。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class Memory:
    """以 Markdown 列表持久化项目级长期记忆。"""

    def __init__(self, path: str | Path = "MEMORY.md"):
        self.path = Path(path)

    def write(self, note: str) -> None:
        """追加一条非空记忆；重复内容不会再次写入。"""
        normalized = " ".join(note.strip().splitlines()).strip()
        if not normalized:
            raise ValueError("记忆内容不能为空")

        existing = self.recall()
        entry = f"- {normalized}"
        if entry in existing.splitlines():
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        needs_newline = self.path.exists() and self.path.stat().st_size > 0
        with self.path.open("a", encoding="utf-8") as file:
            if needs_newline and not existing.endswith("\n"):
                file.write("\n")
            file.write(entry + "\n")

    def recall(self, query: str = "") -> str:
        """读回记忆；提供 query 时只返回包含该文本的行。"""
        if not self.path.is_file():
            return ""
        content = self.path.read_text(encoding="utf-8")
        query = query.strip().casefold()
        if not query:
            return content
        return "\n".join(
            line for line in content.splitlines() if query in line.casefold()
        )


class KVMemory:
    """支持按 key 更新与遗忘的 JSON 结构化记忆。"""

    def __init__(self, path: str | Path = "memory.json"):
        self.path = Path(path)
        self.data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"无法读取结构化记忆 {self.path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"结构化记忆必须是 JSON 对象：{self.path}")
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def remember(self, key: str, value: Any) -> None:
        key = key.strip()
        if not key:
            raise ValueError("记忆 key 不能为空")
        self.data[key] = value
        self._save()

    def forget(self, key: str) -> bool:
        """删除 key 并持久化；返回该 key 是否原本存在。"""
        existed = key in self.data
        self.data.pop(key, None)
        self._save()
        return existed

    def recall(self, key: str | None = None) -> Any:
        return self.data.get(key) if key is not None else dict(self.data)


def inject_memory(system_prompt: str, memory: Memory) -> str:
    """把会话开始时召回的项目记忆追加到 system prompt。"""
    recalled = memory.recall().strip()
    if not recalled:
        return system_prompt
    return (
        system_prompt
        + "\n\n## 关于本项目 / 用户的已知记忆（相关时遵循）\n"
        + recalled
    )

"""供模型写入跨会话项目记忆的工具。"""
from __future__ import annotations

from pathlib import Path

from agent.memory import Memory
from tools.base import Tool


def remember(note: str, path: str | Path = "MEMORY.md") -> str:
    Memory(path).write(note)
    return "已记住：" + note.strip()


remember_tool = Tool(
    name="remember",
    description=(
        "当用户明确要求记住，或告诉你一条跨会话仍成立的项目约定、偏好、"
        "关键决策时，调用此工具写入持久记忆。不要记录闲聊、密钥、密码或隐私信息。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "note": {
                "type": "string",
                "description": "具体、脱敏且在未来会影响行为的长期记忆",
            }
        },
        "required": ["note"],
        "additionalProperties": False,
    },
    run=remember,
)

"""Read skill instructions on demand without bloating the base prompt."""
from __future__ import annotations

from pathlib import Path

from skills.loader import load_skills
from tools.base import Tool


def skill_read(name: str, root: str = "skills") -> str:
    skills = {skill.name: skill for skill in load_skills(root)}
    skill = skills.get(name)
    if skill is None:
        return f"错误：未知 Skill {name}。可用：{', '.join(sorted(skills))}"
    return f"# Skill: {skill.name}\n\n{skill.body}"


skill_read_tool = Tool(
    "skill_read",
    "加载一个已发现 Skill 的完整操作说明。任务匹配 Skills 目录时应先调用，再执行领域工具。",
    {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Skills 清单中的准确名称"}},
        "required": ["name"],
        "additionalProperties": False,
    },
    skill_read,
)

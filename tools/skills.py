"""Read-only tool for loading a selected Skill body on demand."""
from __future__ import annotations

from skills.loader import load_skills
from tools.base import Tool


def load_skill(name: str) -> str:
    requested = name.strip()
    for skill in load_skills():
        if skill.name == requested:
            return f"# Skill: {skill.name}\n\n{skill.body}"
    available = ", ".join(skill.name for skill in load_skills())
    return f"未找到 Skill: {requested}。可用 Skill: {available}"


skill_tool = Tool(
    name="skill",
    description="按名称加载某个 Skill 的完整步骤指引；领域任务开始时先加载匹配的 Skill。",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skills catalog 中的精确名称"},
        },
        "required": ["name"],
        "additionalProperties": False,
    },
    run=load_skill,
)

"""Skills 加载器（Day9）。

Skill 与 Tool 的区别：
  - Tool 是一次函数调用（read 一个文件）。
  - Skill 是一包"领域知识 + 操作流程 + 可选脚本/资源"，用一个 SKILL.md 描述，
    在合适的时候被加载进上下文，告诉模型"面对这类任务该怎么一步步做"。

SKILL.md 结构（约定）：
  ---
  name: pdf-report
  description: 一句话说明何时该用这个 skill（用于召回判断）
  ---
  正文：步骤、注意事项、可调用的脚本路径、示例。

加载器要做：扫描 skills/ 下每个含 SKILL.md 的目录，解析 frontmatter，
按需把正文注入系统提示词 / 作为可发现的能力清单。
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path


def parse_skill_md(text: str, path: Path) -> Skill:
    """Parse YAML frontmatter (name/description) + markdown body from SKILL.md."""
    lines = text.split("\n")
    name = path.parent.name  # fallback: directory name
    description = ""
    body = ""

    if lines and lines[0].strip() == "---":
        # Find closing ---
        end = 1
        while end < len(lines) and lines[end].strip() != "---":
            end += 1
        # Parse frontmatter lines
        for line in lines[1:end]:
            stripped = line.strip()
            if stripped.startswith("name:"):
                name = stripped[5:].strip()
            elif stripped.startswith("description:"):
                description = stripped[12:].strip()
        # Body is everything after closing ---
        body = "\n".join(lines[end + 1:]).strip()
    else:
        # No frontmatter — entire file is body
        body = text.strip()

    return Skill(name=name, description=description, body=body, path=path)


def load_skills(root: str = "skills") -> list[Skill]:
    """扫描 root 下所有 SKILL.md。"""
    skills: list[Skill] = []
    for md in Path(root).glob("*/SKILL.md"):
        skills.append(parse_skill_md(md.read_text(encoding="utf-8"), md))
    return skills


def skills_catalog(skills: list[Skill]) -> str:
    """生成给模型看的可用 skill 清单（name + description），用于按需召回。

    The returned string is injected into the system prompt via {skills_catalog}
    placeholder, so the model can recognize when a skill should be activated.
    """
    return "\n".join(f"- {s.name}: {s.description}" for s in skills)

"""PACS Phase 1 dependency parser tool."""
from __future__ import annotations

import json
from pathlib import Path

from resolver.dep_parser import parse_project
from tools.base import Tool


def _parse(project_path: str | None = None) -> str:
    try:
        result = parse_project(Path(project_path or Path.cwd()))
        return json.dumps({"ok": True, **result}, ensure_ascii=False, sort_keys=True)
    except Exception as exc:
        return json.dumps(
            {"ok": False, "error": str(exc), "type": type(exc).__name__},
            ensure_ascii=False, sort_keys=True,
        )


parse_deps_tool = Tool(
    name="parse_deps",
    description="解析 requirements.txt、pyproject.toml 或 environment.yml，返回 JSON 依赖约束。",
    parameters={"type": "object", "properties": {
        "project_path": {"type": "string", "description": "项目目录或依赖文件；默认当前目录"},
    }},
    run=_parse,
)

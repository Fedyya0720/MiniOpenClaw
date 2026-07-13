"""High-level PACS build tool for Agent use."""
from __future__ import annotations

import json
from typing import Any

from pacs import PACSBuilder
from tools.base import Tool


def pacs_build(
    project_path: str,
    python_version: str = "",
    max_parallel: int = 2,
    max_attempts: int = 8,
    timeout: float = 180,
    refresh_versions: bool = False,
    validation_modules: list[str] | str | None = None,
    install_project: bool = True,
) -> str:
    try:
        if isinstance(validation_modules, str):
            validation_modules = json.loads(validation_modules)
        result = PACSBuilder(project_path).build(
            python_version=python_version,
            max_parallel=max_parallel,
            max_attempts=max_attempts,
            timeout=timeout,
            refresh_versions=refresh_versions,
            validation_modules=validation_modules or [],
            install_project=install_project,
        )
        return json.dumps(result.as_dict(), ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)


pacs_build_tool = Tool(
    "pacs_build",
    "端到端构建 Python 环境：发现真实版本、并行搜索、验证、生成锁文件和 PACS 报告。",
    {
        "type": "object",
        "properties": {
            "project_path": {"type": "string"},
            "python_version": {"type": "string"},
            "max_parallel": {"type": "integer", "default": 2},
            "max_attempts": {"type": "integer", "default": 8},
            "timeout": {"type": "number", "default": 180},
            "refresh_versions": {"type": "boolean", "default": False},
            "validation_modules": {"type": "array", "items": {"type": "string"}},
            "install_project": {"type": "boolean", "default": True},
        },
        "required": ["project_path"],
        "additionalProperties": False,
    },
    pacs_build,
)

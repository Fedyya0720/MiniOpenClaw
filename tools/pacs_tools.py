"""Single high-level PACS tool for fast Agent execution."""
from __future__ import annotations

import json
from typing import Any

from pacs import PACSBuilder
from tools.base import Tool


def _pacs_build(
    project_path: str,
    python: str | None = None,
    max_parallel: int = 2,
    max_attempts: int = 8,
    timeout: float = 120.0,
    version_catalog: dict[str, list[str]] | None = None,
    validation_modules: list[str] | None = None,
    pip_args: list[str] | None = None,
    refresh_versions: bool = False,
    backend: str = "venv",
    version_batch_size: int = 5,
    max_versions_per_package: int = 20,
    install_project: bool = True,
) -> str:
    try:
        result = PACSBuilder(project_path).build(
            python=python,
            max_parallel=max_parallel,
            max_attempts=max_attempts,
            timeout=timeout,
            version_catalog=version_catalog,
            validation_modules=validation_modules or [],
            pip_args=pip_args or [],
            refresh_versions=refresh_versions,
            backend=backend,
            version_batch_size=version_batch_size,
            max_versions_per_package=max_versions_per_package,
            install_project=install_project,
        )
        return json.dumps(result, ensure_ascii=False, sort_keys=True)
    except Exception as exc:
        return json.dumps(
            {"success": False, "error": str(exc), "type": type(exc).__name__},
            ensure_ascii=False, sort_keys=True,
        )


pacs_build_tool = Tool(
    name="pacs_build",
    description=(
        "用一次调用完成 Python 环境的版本发现、有限域求解、评分、pip 预求解、"
        "并行安装、失败约束学习、验证、锁定和清理。配置项目环境时优先使用此工具。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "project_path": {"type": "string"},
            "python": {"type": "string"},
            "max_parallel": {"type": "integer"},
            "max_attempts": {"type": "integer"},
            "timeout": {"type": "number"},
            "version_catalog": {"type": "object"},
            "validation_modules": {"type": "array", "items": {"type": "string"}},
            "pip_args": {"type": "array", "items": {"type": "string"}},
            "refresh_versions": {"type": "boolean"},
            "backend": {"type": "string", "enum": ["venv", "conda"]},
            "version_batch_size": {"type": "integer"},
            "max_versions_per_package": {"type": "integer"},
            "install_project": {"type": "boolean"},
        },
        "required": ["project_path"],
    },
    run=_pacs_build,
)

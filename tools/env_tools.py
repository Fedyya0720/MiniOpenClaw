"""PACS 环境池工具：创建、并行安装、状态查询与清理。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from envpool.install import InstallSpec, install_for_environment
from envpool.manager import EnvironmentPool
from tools.base import Tool


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _pool(workdir: str | None) -> EnvironmentPool:
    return EnvironmentPool(Path(workdir or Path.cwd()))


def _create(label: str, env_id: str | None = None, python: str | None = None,
            backend: str = "venv", workdir: str | None = None) -> str:
    try:
        info = _pool(workdir).create(
            label, env_id=env_id, python_executable=python, backend=backend,
        )
        return _json({"ok": True, "environment": info.to_dict()})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc), "type": type(exc).__name__})


def _run(specs: list[dict[str, Any]], workdir: str | None = None,
         timeout: float = 300.0, max_workers: int | None = None) -> str:
    """用 ThreadPoolExecutor 并行执行一个批次；串行模式由环境变量控制。"""
    try:
        parsed = [InstallSpec(**item) for item in specs]
        result = install_for_environment(
            _pool(workdir), parsed, timeout=timeout, max_workers=max_workers
        )
        return _json({"ok": True, **result.to_dict()})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc), "type": type(exc).__name__})


def _status(env_id: str | None = None, workdir: str | None = None) -> str:
    try:
        result = _pool(workdir).status(env_id)
        if isinstance(result, list):
            data: Any = [item.to_dict() for item in result]
        else:
            data = result.to_dict() if result else None
        return _json({"ok": True, "environments": data})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc), "type": type(exc).__name__})


def _cleanup(env_id: str | None = None, workdir: str | None = None) -> str:
    try:
        return _json({"ok": True, "removed": _pool(workdir).cleanup(env_id)})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc), "type": type(exc).__name__})


_WORKDIR = {
    "type": "string",
    "description": "仅允许 AgentLoop 当前工作目录的规范化绝对/相对等价路径；省略时使用该目录。",
}

env_create_tool = Tool(
    name="env_create",
    description="创建隔离 Python 环境（venv 或 conda）并写入可重启恢复的 manifest。",
    parameters={"type": "object", "properties": {
        "label": {"type": "string"}, "env_id": {"type": "string"},
        "python": {"type": "string"},
        "backend": {"type": "string", "description": "venv（默认）或 conda；conda 需事先安装"},
        "workdir": _WORKDIR,
    }, "required": ["label"]},
    run=_create,
)

env_run_tool = Tool(
    name="env_run",
    description="在一次调用中用 ThreadPoolExecutor 并行/并行安装整批候选；首项是 naive 候选。",
    parameters={"type": "object", "properties": {
        "specs": {"type": "array", "items": {"type": "object", "properties": {
            "env_id": {"type": "string"}, "label": {"type": "string"},
            "packages": {"type": "array", "items": {"type": "string"}},
            "argv": {"type": "array", "items": {"type": "string"}},
        }, "required": ["env_id", "label"]}},
        "workdir": _WORKDIR, "timeout": {"type": "number"},
        "max_workers": {"type": "integer"},
    }, "required": ["specs"]},
    run=_run,
)

env_status_tool = Tool(
    name="env_status",
    description="扫描 manifest 查询一个或全部环境状态。",
    parameters={"type": "object", "properties": {
        "env_id": {"type": "string"}, "workdir": _WORKDIR,
    }}, run=_status,
)

env_cleanup_tool = Tool(
    name="env_cleanup",
    description="严格限制在环境池根目录内清理一个或全部环境。",
    parameters={"type": "object", "properties": {
        "env_id": {"type": "string"}, "workdir": _WORKDIR,
    }}, run=_cleanup,
)

"""Agent tools exposing the PACS environment pool."""
from __future__ import annotations

import json
from typing import Any

from envpool import EnvironmentPool, parallel_install
from tools.base import Tool


_POOL = EnvironmentPool()


def env_create(python_version: str = "", label: str = "") -> str:
    try:
        return json.dumps(_POOL.create(python_version or None, label).as_dict(), ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def env_status(env_id: str = "") -> str:
    envs = [_POOL.get(env_id)] if env_id else _POOL.list()
    data = [env.as_dict() for env in envs if env is not None]
    if env_id and not data:
        return json.dumps({"error": f"未知环境：{env_id}"}, ensure_ascii=False)
    return json.dumps(data, ensure_ascii=False)


def env_cleanup(env_id: str = "") -> str:
    try:
        return json.dumps({"removed": _POOL.cleanup(env_id or None)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def env_run(
    jobs: list[dict[str, Any]] | str | None = None,
    env_id: str = "",
    packages: list[str] | str | None = None,
    timeout: float = 120,
) -> str:
    try:
        if isinstance(jobs, str):
            jobs = json.loads(jobs)
        if jobs is None:
            package_list = json.loads(packages) if isinstance(packages, str) else (packages or [])
            jobs = [{"env_id": env_id, "packages": package_list}]
        envs, package_sets = [], []
        for job in jobs:
            env = _POOL.get(str(job.get("env_id", "")))
            if env is None:
                raise ValueError(f"未知环境：{job.get('env_id', '')}")
            envs.append(env)
            package_sets.append([str(item) for item in job.get("packages", [])])
        results = parallel_install(envs, package_sets, float(timeout))
        return json.dumps([result.as_dict() for result in results], ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


env_create_tool = Tool(
    "env_create", "创建一个 PACS 隔离 Python 虚拟环境。",
    {"type": "object", "properties": {"python_version": {"type": "string"}, "label": {"type": "string"}}, "additionalProperties": False},
    env_create,
)
env_run_tool = Tool(
    "env_run", "在一个或多个隔离环境中并行执行 pip install。",
    {"type": "object", "properties": {
        "jobs": {"type": "array", "items": {"type": "object", "properties": {"env_id": {"type": "string"}, "packages": {"type": "array", "items": {"type": "string"}}}, "required": ["env_id", "packages"]}},
        "env_id": {"type": "string"}, "packages": {"type": "array", "items": {"type": "string"}}, "timeout": {"type": "number", "default": 120}}, "additionalProperties": False},
    env_run,
)
env_status_tool = Tool(
    "env_status", "查询 PACS 环境池状态。",
    {"type": "object", "properties": {"env_id": {"type": "string"}}, "additionalProperties": False}, env_status,
)
env_cleanup_tool = Tool(
    "env_cleanup", "删除指定 PACS 环境；省略 env_id 时删除全部。",
    {"type": "object", "properties": {"env_id": {"type": "string"}}, "additionalProperties": False}, env_cleanup,
)

ENV_TOOLS = (env_create_tool, env_run_tool, env_status_tool, env_cleanup_tool)

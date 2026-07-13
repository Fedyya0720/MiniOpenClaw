"""Agent tools exposing PACS dependency resolution primitives."""
from __future__ import annotations

import json
from typing import Any

from resolver import ConstraintGraph, generate_combinations, parse_dependencies, parse_failure as parse_failure_log
from tools.base import Tool


def _value(value: Any, expected: type) -> Any:
    if isinstance(value, str) and expected in {list, dict}:
        return json.loads(value)
    return value


def parse_deps(project_path: str) -> str:
    try:
        return json.dumps([dep.as_dict() for dep in parse_dependencies(project_path)], ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def generate_candidates(
    deps: list[dict[str, Any]] | str,
    constraints: list[dict[str, Any]] | str | None = None,
    max_candidates: int = 4,
    version_catalog: dict[str, list[str]] | str | None = None,
    newest_first: bool = False,
) -> str:
    try:
        result = generate_combinations(
            _value(deps, list), _value(constraints or [], list), int(max_candidates),
            _value(version_catalog or {}, dict), bool(newest_first),
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def parse_failure(log_text: str, attempted_combo: dict[str, Any] | str | None = None) -> str:
    try:
        return json.dumps(parse_failure_log(log_text, _value(attempted_combo or {}, dict)), ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def infer_constraints(constraints: list[dict[str, Any]] | str, db_path: str = "") -> str:
    try:
        graph = ConstraintGraph(db_path or None)
        supplied = _value(constraints, list)
        added = graph.add(supplied)
        inferred = graph.infer()
        return json.dumps({"added": added, "inferred": inferred, "constraints": graph.all()}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


parse_deps_tool = Tool("parse_deps", "解析项目 requirements.txt 或 pyproject.toml 依赖。", {"type": "object", "properties": {"project_path": {"type": "string"}}, "required": ["project_path"], "additionalProperties": False}, parse_deps)
generate_combinations_tool = Tool("generate_combinations", "根据依赖、真实版本目录与冲突约束生成候选组合。", {"type": "object", "properties": {"deps": {"type": "array"}, "constraints": {"type": "array"}, "max_candidates": {"type": "integer", "default": 4}, "version_catalog": {"type": "object"}, "newest_first": {"type": "boolean", "default": False}}, "required": ["deps"], "additionalProperties": False}, generate_candidates)
parse_failure_tool = Tool("parse_failure", "把 pip 失败日志解析为结构化冲突约束。", {"type": "object", "properties": {"log_text": {"type": "string"}, "attempted_combo": {"type": "object"}}, "required": ["log_text"], "additionalProperties": False}, parse_failure)
infer_constraints_tool = Tool("infer_constraints", "持久化新约束并执行传递推导。", {"type": "object", "properties": {"constraints": {"type": "array"}, "db_path": {"type": "string"}}, "required": ["constraints"], "additionalProperties": False}, infer_constraints)

RESOLVER_TOOLS = (parse_deps_tool, generate_combinations_tool, parse_failure_tool, infer_constraints_tool)

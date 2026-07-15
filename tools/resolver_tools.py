"""PACS resolver tools — dependency parsing, combination generation, failure analysis,
constraint-graph inference."""
from __future__ import annotations

import json
from pathlib import Path

from resolver.combinations import generate_combinations as _gen_combos
from resolver.constraint_graph import ConstraintGraph
from resolver.dep_parser import parse_project
from resolver.failure_parser import parse_failure_file
from tools.base import Tool

# Module-level singleton — loaded once, shared across tool invocations.
_constraint_graph: ConstraintGraph | None = None


def _get_graph() -> ConstraintGraph:
    global _constraint_graph
    if _constraint_graph is None:
        _constraint_graph = ConstraintGraph()
    return _constraint_graph


def _parse(project_path: str | None = None) -> str:
    try:
        result = parse_project(Path(project_path or Path.cwd()))
        return json.dumps({"ok": True, **result}, ensure_ascii=False, sort_keys=True)
    except Exception as exc:
        return json.dumps(
            {"ok": False, "error": str(exc), "type": type(exc).__name__},
            ensure_ascii=False, sort_keys=True,
        )


def _combinations(
    dependencies: list[dict[str, object]],
    constraints: list[dict[str, object]] | None = None,
    max_candidates: int = 20,
) -> str:
    """Generate version combinations with constraint pruning."""
    try:
        result = _gen_combos(
            [dict(d) for d in dependencies],
            [dict(c) for c in (constraints or [])],
            max_candidates,
        )
        return json.dumps({"ok": True, **result}, ensure_ascii=False, sort_keys=True,
                          default=str)
    except Exception as exc:
        return json.dumps(
            {"ok": False, "error": str(exc), "type": type(exc).__name__},
            ensure_ascii=False, sort_keys=True,
        )


def _parse_failure(log_path: str = "") -> str:
    """Read an install log and emit structured failure entries."""
    try:
        entries = parse_failure_file(log_path)
        return json.dumps(
            {"ok": True, "entries": entries, "count": len(entries)},
            ensure_ascii=False, sort_keys=True,
        )
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


generate_combinations_tool = Tool(
    name="generate_combinations",
    description=(
        "根据 parse_deps 返回的依赖规格和已知冲突（约束剪枝）生成版本组合列表。"
        "pip index versions 获取可用版本，specifier 匹配合法区间，"
        "约束对 (pkg_a,ver_a,pkg_b,ver_b) 排除已知不兼容组合。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "dependencies": {
                "type": "array",
                "description": "parse_deps 返回的 dependencies 列表",
            },
            "constraints": {
                "type": "array",
                "description": (
                    "已知冲突对，每项含 pkg_a, ver_a, pkg_b, ver_b，"
                    "可选 error_type, confidence, kind"
                ),
            },
            "max_candidates": {
                "type": "integer",
                "description": "最多返回多少个组合（默认 20）",
            },
        },
        "required": ["dependencies"],
    },
    run=_combinations,
)


parse_failure_tool = Tool(
    name="parse_failure",
    description=(
        "读取安装日志并返回结构化失败分析。"
        "分类 15+ 种 pip 失败模式（版本冲突、平台不匹配、缺少系统库/头文件、"
        "wheel 不可用、SSL/网络错误、编译器缺失、超时等），"
        "每项带 error_type、confidence、constraints 和可选的修复 hint。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "log_path": {
                "type": "string",
                "description": "env_run 返回的安装日志的绝对或相对路径",
            },
        },
        "required": ["log_path"],
    },
    run=_parse_failure,
)


def _infer_constraints(
    constraints: list[dict[str, object]],
    run_transitive: bool = True,
) -> str:
    """Insert observed constraints into the global constraint graph and optionally
    run transitive inference to derive new edges."""
    try:
        graph = _get_graph()
        edges = [
            {
                "pkg_a": str(c["pkg_a"]), "ver_a": str(c["ver_a"]),
                "pkg_b": str(c["pkg_b"]), "ver_b": str(c["ver_b"]),
                "confidence": float(c.get("confidence", 0.5)),
                "kind": str(c.get("kind", "observed")),
                "source": str(c.get("source", "infer_constraints_tool")),
                "error_type": str(c.get("error_type", "")),
            }
            for c in constraints
        ]
        inserted = graph.insert(edges)
        derived = 0
        if run_transitive:
            touched = set()
            for e in edges:
                touched.add(e["pkg_a"])
                touched.add(e["pkg_b"])
            derived = graph.infer_transitive(touched) if touched else 0
        total = len(graph.load_all())
        return json.dumps(
            {
                "ok": True,
                "inserted": inserted,
                "derived": derived,
                "total_edges": total,
            },
            ensure_ascii=False, sort_keys=True,
        )
    except Exception as exc:
        return json.dumps(
            {"ok": False, "error": str(exc), "type": type(exc).__name__},
            ensure_ascii=False, sort_keys=True,
        )


infer_constraints_tool = Tool(
    name="infer_constraints",
    description=(
        "将 parse_failure 返回的约束条目插入全局约束图，"
        "可选运行传递推导以发现间接冲突。"
        "约束图持久化于 ~/.cache/miniopenclaw/constraint_graph.db，跨会话复用。"
        "返回插入数量、推导数量及图中总边数。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "constraints": {
                "type": "array",
                "description": (
                    "parse_failure 返回的 constraints 列表，"
                    "每项含 pkg_a, ver_a, pkg_b, ver_b，"
                    "可选 confidence, kind, source, error_type"
                ),
            },
            "run_transitive": {
                "type": "boolean",
                "description": "是否运行传递推导以生成 derived 边（默认 true）",
            },
        },
        "required": ["constraints"],
    },
    run=_infer_constraints,
)

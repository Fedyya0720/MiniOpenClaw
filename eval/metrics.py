"""工具调用三项指标（Day6 Lab3 验收用）。

  - JSON 合法率：模型输出的 tool_call 能否被 json.loads 成功解析。
  - 工具选择正确率：选对工具名的比例。
  - 参数正确率：关键参数与期望一致的比例。
"""
from __future__ import annotations
import json
from typing import Any


def json_valid_rate(raw_outputs: list[str]) -> float:
    """raw_outputs：模型为每条用例生成的 <tool_call>{...}</tool_call> 原文。

    Extracts the JSON portion via _extract_json() and validates with json.loads.
    For more robust extraction from <tool_call> tags, consider reusing
    prompt.render.parse_tool_calls().
    """
    ok = 0
    for out in raw_outputs:
        try:
            json.loads(_extract_json(out)); ok += 1
        except Exception:  # noqa
            pass
    return ok / max(len(raw_outputs), 1)


def tool_choice_accuracy(preds: list[dict], expected_tools: list[str]) -> float:
    correct = sum(1 for p, e in zip(preds, expected_tools) if p.get("name") == e)
    return correct / max(len(expected_tools), 1)


def arg_accuracy(preds: list[dict], expected_args: list[dict]) -> float:
    """关键参数匹配率：期望 args 的每个键值都在预测里对上。"""
    correct = 0
    for p, e in zip(preds, expected_args):
        pa = p.get("arguments", {})
        if all(str(pa.get(k)) == str(v) for k, v in e.items()):
            correct += 1
    return correct / max(len(expected_args), 1)


def _extract_json(text: str) -> str:
    """Extract the outermost {...} JSON block from tool_call text.

    For production use, prefer prompt.render.parse_tool_calls() which handles
    <tool_call> tag boundaries and provides additional validation.
    """
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start >= 0 else "{}"


# ========== Day3 下午 · 评估 harness ==========

import re
TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)

SAMPLE_RECORDS: list[dict[str, Any]] = [
    {"task": "read-config",
     "steps": [
         {"tool_calls": [{"name": "read", "arguments": {"path": "config.json"}}],
          "raw": '<tool_call>{"name":"read","arguments":{"path":"config.json"}}</tool_call>',
          "prompt_tokens": 310, "completion_tokens": 22},
     ],
     "final": "config.json 里 timeout = 30 秒。"},
    {"task": "list-dir",
     "steps": [
         {"tool_calls": [{"name": "bash", "arguments": {"command": "ls"}}],
          "raw": '<tool_call>{"name":"bash","arguments":{"command":"ls"}}</tool_call>',
          "prompt_tokens": 290, "completion_tokens": 18},
     ],
     "final": "当前目录有：main.py config.json README.md"},
    {"task": "read-config",
     "steps": [
         {"tool_calls": [],
          "raw": '<tool_call>{"name":"read","arguments":{"path":',
          "prompt_tokens": 305, "completion_tokens": 12},
         {"tool_calls": [], "raw": "我不确定 timeout 的值。",
          "prompt_tokens": 340, "completion_tokens": 15},
     ],
     "final": "我不确定 timeout 的值。"},
]

def success_rate(tasks: list, records: list[dict]) -> float:
    by_name = {t.name: t for t in tasks}
    ok = 0
    for r in records:
        task = by_name.get(r["task"])
        if task and task.check(r):
            ok += 1
    return ok / max(len(records), 1)

def step_count(record: dict) -> int:
    return len(record["steps"])

def token_count(record: dict) -> int:
    return sum(s.get("prompt_tokens", 0) + s.get("completion_tokens", 0)
               for s in record["steps"])

def json_valid_rate(records: list[dict]) -> float:
    total, ok = 0, 0
    for r in records:
        for s in r["steps"]:
            m = TOOL_CALL_RE.search(s.get("raw", ""))
            if not m:
                continue
            total += 1
            try:
                json.loads(m.group(1)); ok += 1
            except json.JSONDecodeError:
                pass
    return ok / max(total, 1)

# -- PACS metrics (Phase 5) --------------------------------------------------


def pacs_attempt_count(run: dict[str, Any]) -> int:
    """Number of install attempts to reach first success (the load-bearing B3 metric)."""
    return int(run.get("n_attempts", 0) or 0)


def pacs_t_success(run: dict[str, Any]) -> float | None:
    """Wall-clock seconds from task submission to first working environment."""
    t = run.get("t_success")
    return float(t) if t is not None else None


def pacs_coverage(runs: list[dict[str, Any]]) -> float:
    """Fraction of projects for which a working environment was produced."""
    ok = sum(1 for r in runs if r.get("success"))
    return ok / max(len(runs), 1)


def pacs_reuse_rate(runs: list[dict[str, Any]]) -> float:
    """Fraction of known constraints reused vs freshly probed (ideally > 0 on second run)."""
    total = sum(int(r.get("n_attempts", 0) or 0) for r in runs)
    reused = sum(int(r.get("constraints_reused", 0) or 0) for r in runs)
    return reused / max(total, 1)


# Demo data — a PACS run on the torch + numpy conflict fixture.
_PACS_CONFLICT_RUN: dict[str, Any] = {
    "task": "pacs-conflict",
    "project": "tests/fixtures/torch-numpy-conflict",
    "success": True,
    "n_attempts": 3,
    "t_success": 48.2,
    "constraints_reused": 0,
    "lock_file": "lock-requirements.txt",
    "steps": [
        {"tool_calls": [{"name": "parse_deps", "arguments": {"project_path": "tests/fixtures/torch-numpy-conflict"}}]},
        {"tool_calls": [{"name": "env_create", "arguments": {"label": "naive", "env_id": "v0"}}]},
        {"tool_calls": [{"name": "env_run", "arguments": {"specs": [{"env_id": "v0", "label": "naive", "packages": ["torch==2.0.1", "numpy==2.0.0"]}]}}]},
        {"tool_calls": [{"name": "parse_failure", "arguments": {"log_path": "..."}}]},
        {"tool_calls": [{"name": "infer_constraints", "arguments": {"constraints": [{"pkg_a": "torch", "ver_a": "2.0.1", "pkg_b": "numpy", "ver_b": "2.0.0", "kind": "observed"}]}}]},
        {"tool_calls": [{"name": "generate_combinations", "arguments": {"dependencies": [{"name": "torch", "specifier": ">=2.0"}, {"name": "numpy", "specifier": ">=1.24"}], "constraints": [{"pkg_a": "torch", "ver_a": "2.0.1", "pkg_b": "numpy", "ver_b": "2.0.0"}]}}]},
        {"tool_calls": [{"name": "env_create", "arguments": {"label": "candidate-1", "env_id": "v1"}}]},
        {"tool_calls": [{"name": "env_create", "arguments": {"label": "candidate-2", "env_id": "v2"}}]},
        {"tool_calls": [{"name": "env_run", "arguments": {"specs": [{"env_id": "v1", "label": "c1", "packages": ["torch==2.1.0", "numpy==1.26.0"]}, {"env_id": "v2", "label": "c2", "packages": ["torch==2.0.1", "numpy==1.24.0"]}], "max_workers": 2}}]},
        {"tool_calls": [{"name": "env_cleanup", "arguments": {}}]},
    ],
}

# Second run on the same project — constraints are known, fewer attempts.
_PACS_CONFLICT_RUN2: dict[str, Any] = {
    "task": "pacs-conflict",
    "project": "tests/fixtures/torch-numpy-conflict",
    "success": True,
    "n_attempts": 1,
    "t_success": 12.1,
    "constraints_reused": 2,
    "lock_file": "lock-requirements.txt",
}
PACS_DEMO_RUNS: list[dict[str, Any]] = [_PACS_CONFLICT_RUN, _PACS_CONFLICT_RUN2]


# -- serial baseline sample (B3 ablation) -------------------------------------

_SERIAL_CONFLICT_RUN: dict[str, Any] = {
    "task": "pacs-conflict-serial",
    "project": "tests/fixtures/torch-numpy-conflict",
    "success": True,
    "n_attempts": 7,
    "t_success": 173.5,
    "mode": "serial",
}
_PACS_PARALLEL_RUN: dict[str, Any] = {
    "task": "pacs-conflict-parallel",
    "project": "tests/fixtures/torch-numpy-conflict",
    "success": True,
    "n_attempts": 3,
    "t_success": 48.2,
    "mode": "parallel",
}
PACS_ABLATION_RUNS: list[dict[str, Any]] = [_SERIAL_CONFLICT_RUN, _PACS_PARALLEL_RUN]


if __name__ == "__main__":
    from eval.tasks import SAMPLE_TASKS
    recs = SAMPLE_RECORDS
    print("成功率        :", success_rate(SAMPLE_TASKS, recs))
    print("平均步数      :", sum(step_count(r) for r in recs) / len(recs))
    print("平均 token    :", sum(token_count(r) for r in recs) / len(recs))
    print("JSON 合法率   :", json_valid_rate(recs))

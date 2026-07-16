"""End-to-end Agent ablation: ordinary tools versus the PACS tool."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import signal
import statistics
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from agent.cli import _load_dotenv
from agent.loop import AgentLoop
from agent.memory import Memory, inject_memory
from agent.prompts import build_system_prompt
from backend.client import DeepSeekBackend
from envpool.manager import EnvironmentPool
from eval.fixtures.pacs_projects import (
    create_clean_project,
    create_conflict_project,
    create_real_package_conflict_project,
)
from resolver.constraint_graph import ConstraintGraph
import tools.resolver_tools as resolver_tools
from skills.loader import load_skills, skills_catalog
from tools.base import ToolRegistry, build_default_registry


VARIANTS = ("traditional-agent", "pacs-agent")
_MAX_TURNS_RESPONSE = "[达到最大轮数上限，未完成任务]"
_FAILED_FINAL_MARKERS = ("未完成任务", "无法完成任务", "任务失败")
_PACS_TOOL_LINE = "- **pacs_build**: 一次调用完成 Python 环境的依赖发现、求解、并行安装、验证、锁定和清理。\n"
_PACS_RULE = (
    "- 用户要求配置、装配或安装当前 Python 项目的环境时，第一次工具调用必须是 "
    "`pacs_build(project_path=\".\")`；它会自行读取依赖，不要先调用 read、glob、bash "
    "或低层 PACS 工具。只有项目路径未知、用户只要分析且不允许安装、用户明确要求不用 "
    "`pacs_build` 做消融对照，或 `pacs_build` 返回基础设施错误时才例外。\n"
)
_TRADITIONAL_RULE = (
    "- 配置 Python 环境时不得调用 `pacs_build`；使用依赖解析、候选生成、环境池、失败解析、"
    "约束推导和验证工具完成任务。遇到安装失败要读取结构化错误后调整版本，不要只给操作步骤。\n"
)


def build_variant_dependencies(
    variant: str,
    workdir: str | Path,
    *,
    backend: Any | None = None,
    fixture: dict[str, Any] | None = None,
) -> tuple[Any, ToolRegistry, str]:
    """Build one in-memory experiment condition without changing production files."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant: {variant}")
    workdir = Path(workdir).resolve()
    production = build_default_registry()
    registry = ToolRegistry()
    for name in production.names():
        if variant == "traditional-agent" and name == "pacs_build":
            continue
        tool = production.get(name)
        if tool is not None:
            registry.register(tool)

    skills = load_skills()
    if variant == "traditional-agent":
        skills = [skill for skill in skills if skill.name != "python-env-builder"]
    prompt = inject_memory(
        build_system_prompt(skills_catalog(skills)), Memory(workdir / "MEMORY.md")
    )
    if variant == "traditional-agent":
        prompt = prompt.replace(_PACS_TOOL_LINE, "")
        if _PACS_RULE not in prompt:
            raise RuntimeError("PACS prompt rule changed; update the ablation adapter")
        prompt = prompt.replace(_PACS_RULE, _TRADITIONAL_RULE)
    return backend or DeepSeekBackend(), registry, prompt


@contextmanager
def _isolated_constraint_graph(workdir: str | Path) -> Iterator[None]:
    """Point low-level resolver tools at one trial-local graph and restore state."""
    previous = resolver_tools._constraint_graph
    graph_path = Path(workdir) / ".mini-openclaw" / "eval-constraint-graph.db"
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    graph = ConstraintGraph(graph_path)
    resolver_tools._constraint_graph = graph
    try:
        yield
    finally:
        graph.close()
        resolver_tools._constraint_graph = previous


@contextmanager
def _working_directory(path: str | Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(Path(path).resolve())
    try:
        yield
    finally:
        os.chdir(previous)


def _python_for_environment(path: str | Path) -> Path:
    return EnvironmentPool.python_path(path)


def independently_verify(workdir: str | Path, smoke_code: str) -> dict[str, Any]:
    """Find real valid environments without trusting the model's prose."""
    pool = EnvironmentPool(workdir)
    evidence: list[dict[str, Any]] = []
    winners: list[dict[str, Any]] = []
    for info in pool.list():
        python = _python_for_environment(info.path)
        commands = (
            [str(python), "-m", "pip", "check"],
            [str(python), "-c", smoke_code],
        )
        command_evidence = []
        success = True
        for command in commands:
            completed = subprocess.run(
                command, cwd=str(workdir), capture_output=True, text=True,
                timeout=90, check=False,
            )
            command_evidence.append({
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout[-2000:],
                "stderr": completed.stderr[-2000:],
            })
            success = success and completed.returncode == 0
        evidence.append({
            "environment_id": info.env_id,
            "environment_path": info.path,
            "success": success,
            "commands": command_evidence,
        })
        if success:
            winners.append(info.to_dict())
    return {
        "success": bool(winners),
        "winner": winners[0] if winners else None,
        "winners": winners,
        "environments": evidence,
    }


def _installation_requests(tools: Sequence[dict[str, Any]]) -> int:
    requests = 0
    for span in tools:
        arguments = span.get("arguments") or {}
        if span.get("name") == "env_run":
            for spec in arguments.get("specs") or []:
                if not isinstance(spec, dict):
                    continue
                argv = [str(item) for item in spec.get("argv") or []]
                is_pip_install = "pip" in argv and "install" in argv
                requests += bool(spec.get("packages")) or is_pip_install
        elif span.get("name") == "pacs_build":
            requests += 1
        elif span.get("name") == "bash" and "pip install" in str(arguments.get("command", "")):
            requests += 1
    return requests


def _trace_metrics(loop: AgentLoop) -> dict[str, Any]:
    tracer = loop.last_tracer
    spans = list(tracer.spans) if tracer is not None else []
    llm = [span for span in spans if span.get("kind") == "llm"]
    tools = [span for span in spans if span.get("kind") == "tool"]
    prompt_tokens = sum(int((span.get("usage") or {}).get("prompt_tokens", 0)) for span in llm)
    completion_tokens = sum(int((span.get("usage") or {}).get("completion_tokens", 0)) for span in llm)
    turns = {
        int(span["turn"]) for span in spans
        if isinstance(span.get("turn"), int)
    }
    installation_requests = _installation_requests(tools)
    return {
        "turns": max(turns) + 1 if turns else len(llm),
        "llm_calls": len(llm),
        "tool_calls": len(tools),
        "tool_names": [str(span.get("name", "")) for span in tools],
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "installation_requests": installation_requests,
        "trace_path": str(tracer.path) if tracer and tracer.path else None,
        "failed_spans": sum(not span.get("ok", True) for span in spans),
    }


def _latest_pacs_result(workdir: str | Path) -> dict[str, Any] | None:
    results = sorted(Path(workdir).glob(".mini-openclaw/pacs/runs/*/result.json"))
    if not results:
        return None
    result_path = max(results, key=lambda path: path.stat().st_mtime_ns)
    data = json.loads(result_path.read_text(encoding="utf-8"))
    return {
        "path": str(result_path),
        "success": data.get("success"),
        "attempted": data.get("attempted"),
        "failed": data.get("failed"),
        "constraints_learned": data.get("constraints_learned"),
        "rounds": data.get("rounds"),
        "duration_seconds": data.get("duration_seconds"),
    }


def _task(fixture: dict[str, Any], variant: str) -> str:
    tool_instruction = (
        "使用当前提供的 PACS 高层工具完成，不要只给步骤。"
        if variant == "pacs-agent"
        else "不要使用 pacs_build；使用现有常规工具多轮完成，不要只给步骤。"
    )
    hint = fixture.get("agent_hint", "")
    return (
        "给当前项目配好并验证 Python 环境。必须安装依赖、运行 pip check，并导入 "
        f"{', '.join(fixture['validation_modules'])}；成功后报告环境路径和验证结果。"
        f"{tool_instruction}{hint}"
    )


def _agent_completed(
    final: str, error: str | None, verified_environment_paths: Sequence[str]
) -> bool:
    """Require a non-failure response that reports an independently verified path."""
    if error is not None or not verified_environment_paths:
        return False
    response = final.strip()
    if not response or response == _MAX_TURNS_RESPONSE:
        return False
    if any(marker in response for marker in _FAILED_FINAL_MARKERS):
        return False
    return any(
        path in response or Path(path).name in response
        for path in verified_environment_paths
    )


def _create_fixture(fixture_kind: str, trial_root: str | Path) -> dict[str, Any]:
    if fixture_kind == "clean":
        return create_clean_project(trial_root)
    if fixture_kind == "real-conflict":
        return create_real_package_conflict_project(trial_root)
    return create_conflict_project(trial_root)


def run_trial(
    variant: str,
    trial_root: str | Path,
    *,
    fixture_kind: str = "conflict",
    max_turns: int = 60,
    fixture: dict[str, Any] | None = None,
    backend: Any | None = None,
) -> dict[str, Any]:
    trial_root = Path(trial_root).resolve()
    fixture = fixture or _create_fixture(fixture_kind, trial_root)
    workdir = Path(fixture["project"])
    backend, registry, prompt = build_variant_dependencies(
        variant, workdir, fixture=fixture, backend=backend
    )
    loop = AgentLoop(
        backend, registry, prompt, max_turns=max_turns,
        auto_approve=True, workdir=workdir,
    )
    started = time.monotonic()
    error = None
    final = ""
    try:
        with _working_directory(workdir), _isolated_constraint_graph(workdir):
            final = loop.run(_task(fixture, variant))
    except Exception as exc:  # one failed API/tool run must still produce a trial record
        error = f"{type(exc).__name__}: {exc}"
    agent_seconds = time.monotonic() - started
    verification_started = time.monotonic()
    verification = independently_verify(workdir, fixture["smoke_code"])
    verification_seconds = time.monotonic() - verification_started
    metrics = _trace_metrics(loop)
    pacs_result = _latest_pacs_result(workdir)
    metrics["candidate_attempts"] = (
        pacs_result.get("attempted") if pacs_result is not None else None
    )
    verified_paths = [
        str(winner["path"])
        for winner in verification.get("winners") or []
        if winner.get("path")
    ]
    completed = _agent_completed(final, error, verified_paths)
    cap_reached = final.strip() == _MAX_TURNS_RESPONSE
    if completed:
        termination_reason = "completed"
    elif cap_reached:
        termination_reason = "max_turns"
    elif error is not None:
        termination_reason = "exception"
    else:
        termination_reason = "incomplete_response"
    worker_cwd = str(Path.cwd().resolve())
    try:
        from tools.security import WRITE_ROOT
        worker_write_root = str(Path(WRITE_ROOT).resolve())
    except ImportError:
        worker_write_root = ""
    isolation_ok = worker_cwd == str(workdir.resolve()) == worker_write_root
    bwrap_present = shutil.which("bwrap") is not None
    bwrap_usable = os.environ.get("MINIOPENCLAW_EVAL_BWRAP_USABLE") == "1"
    isolation_ok = isolation_ok and bwrap_present
    return {
        "variant": variant,
        "fixture": fixture_kind,
        "success": bool(verification["success"] and completed and isolation_ok),
        "environment_verified": bool(verification["success"]),
        "agent_completed": completed,
        "duration_seconds": agent_seconds,
        "agent_seconds": agent_seconds,
        "verification_seconds": verification_seconds,
        "total_evaluation_seconds": agent_seconds + verification_seconds,
        "termination_reason": "isolation_failure" if not isolation_ok else termination_reason,
        "cap_reached": cap_reached,
        "turns_remaining": max(0, max_turns - metrics["turns"]),
        "isolation": {
            "cwd": worker_cwd,
            "write_root": worker_write_root,
            "trial_project": str(workdir.resolve()),
            "bwrap_present": bwrap_present,
            "bwrap_usable": bwrap_usable,
            "ok": isolation_ok,
        },
        "model": getattr(backend, "model", None),
        "max_turns": max_turns,
        "task": _task(fixture, variant),
        "final_response": final,
        "error": error,
        "metrics": metrics,
        "verification": verification,
        "pacs_result": pacs_result,
        "workdir": str(workdir),
    }


def _median_iqr(values: Sequence[float | int]) -> dict[str, float]:
    numeric = [float(value) for value in values]
    if not numeric:
        raise ValueError("cannot summarize an empty sequence")
    if len(numeric) == 1:
        iqr = 0.0
    else:
        q1, _, q3 = statistics.quantiles(numeric, n=4, method="inclusive")
        iqr = q3 - q1
    return {"median": statistics.median(numeric), "iqr": iqr}


def _paired_summary(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    blocks: dict[int, dict[str, dict[str, Any]]] = {}
    for row in records:
        block = row.get("block")
        if isinstance(block, int):
            blocks.setdefault(block, {})[row["variant"]] = row
    pairs = [
        rows for rows in blocks.values()
        if all(variant in rows for variant in VARIANTS)
    ]
    if not pairs:
        return {"blocks": 0}

    measurable_pairs = [
        pair for pair in pairs
        if all((row.get("worker") or {}).get("returncode") == 0 for row in pair.values())
    ]
    successful_pairs = [
        pair for pair in pairs
        if pair["traditional-agent"]["success"] and pair["pacs-agent"]["success"]
    ]

    def paired_metrics(selected: Sequence[dict[str, dict[str, Any]]]) -> dict[str, Any] | None:
        if not selected:
            return None
        return {
            "time_ratio_traditional_over_pacs": _median_iqr([
                pair["traditional-agent"]["duration_seconds"]
                / pair["pacs-agent"]["duration_seconds"]
                for pair in selected
            ]),
            "turn_reduction_traditional_minus_pacs": _median_iqr([
                pair["traditional-agent"]["metrics"]["turns"]
                - pair["pacs-agent"]["metrics"]["turns"]
                for pair in selected
            ]),
            "tool_call_reduction_traditional_minus_pacs": _median_iqr([
                pair["traditional-agent"]["metrics"]["tool_calls"]
                - pair["pacs-agent"]["metrics"]["tool_calls"]
                for pair in selected
            ]),
            "token_reduction_traditional_minus_pacs": _median_iqr([
                pair["traditional-agent"]["metrics"]["total_tokens"]
                - pair["pacs-agent"]["metrics"]["total_tokens"]
                for pair in selected
            ]),
        }

    return {
        "blocks": len(pairs),
        "both_successful": sum(
            pair["traditional-agent"]["success"] and pair["pacs-agent"]["success"]
            for pair in pairs
        ),
        "pacs_only_successful": sum(
            not pair["traditional-agent"]["success"] and pair["pacs-agent"]["success"]
            for pair in pairs
        ),
        "traditional_only_successful": sum(
            pair["traditional-agent"]["success"] and not pair["pacs-agent"]["success"]
            for pair in pairs
        ),
        "all_measurable_blocks_terminal_resource_contrast": paired_metrics(measurable_pairs),
        "unmeasurable_blocks": len(pairs) - len(measurable_pairs),
        "both_successful_blocks": {
            "blocks": len(successful_pairs),
            "completion_performance": paired_metrics(successful_pairs),
        },
    }


def _cap_assessment(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    variant_rows = {
        variant: [row for row in records if row["variant"] == variant]
        for variant in VARIANTS
    }
    paired = _paired_summary(records)
    blocks = paired.get("blocks", 0)
    required_successes = max(1, (4 * blocks + 4) // 5)
    allowed_cap_hits = blocks - required_successes
    checks: dict[str, bool] = {}
    for variant, rows in variant_rows.items():
        successful = [row for row in rows if row["success"]]
        max_turns = min((int(row.get("max_turns", 0)) for row in rows), default=0)
        headroom_limit = int(max_turns * 0.9)
        checks[f"{variant}_success_rate_at_least_80_percent"] = (
            blocks >= 5 and len(rows) == blocks and len(successful) >= required_successes
        )
        checks[f"{variant}_cap_hit_rate_at_most_20_percent"] = (
            blocks >= 5
            and sum(bool(row.get("cap_reached")) for row in rows) <= allowed_cap_hits
        )
        checks[f"{variant}_successful_median_turns_has_10_percent_headroom"] = (
            len(successful) >= required_successes
            and max_turns > 0
            and statistics.median(row["metrics"]["turns"] for row in successful) <= headroom_limit
        )
    checks["both_successful_blocks_at_least_60_percent"] = (
        blocks >= 5 and paired.get("both_successful", 0) * 5 >= blocks * 3
    )
    checks["all_trials_isolated"] = bool(records) and all(
        bool((row.get("isolation") or {}).get("ok")) for row in records
    )
    checks["no_worker_timeout"] = all(
        row.get("termination_reason") != "subprocess_timeout" for row in records
    )
    return {
        "eligible_blocks": paired.get("blocks", 0),
        "checks": checks,
        "accepted_for_completion_time_comparison": all(checks.values()),
    }


def summarize(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for variant in VARIANTS:
        rows = [row for row in records if row["variant"] == variant]
        if not rows:
            continue
        output[variant] = {
            "trials": len(rows),
            "success_rate": sum(row["success"] for row in rows) / len(rows),
            "cap_hit_rate": sum(bool(row.get("cap_reached")) for row in rows) / len(rows),
            "termination_reasons": {
                reason: sum(row.get("termination_reason") == reason for row in rows)
                for reason in sorted({str(row.get("termination_reason")) for row in rows})
            },
            "isolation_success_rate": sum(
                bool((row.get("isolation") or {}).get("ok")) for row in rows
            ) / len(rows),
            "terminal_seconds": _median_iqr(
                [row["duration_seconds"] for row in rows]
            ),
            "turns": _median_iqr([row["metrics"]["turns"] for row in rows]),
            "tool_calls": _median_iqr(
                [row["metrics"]["tool_calls"] for row in rows]
            ),
            "tokens": _median_iqr(
                [row["metrics"]["total_tokens"] for row in rows]
            ),
            "installation_requests": _median_iqr(
                [row["metrics"]["installation_requests"] for row in rows]
            ),
            "candidate_attempts": _median_iqr([
                row["metrics"]["candidate_attempts"]
                for row in rows if row["metrics"]["candidate_attempts"] is not None
            ]) if any(
                row["metrics"]["candidate_attempts"] is not None for row in rows
            ) else None,
        }
    output["paired"] = _paired_summary(records)
    output["cap_assessment"] = _cap_assessment(records)
    return output


def _fixture_hash(fixture: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    stable = {
        key: fixture.get(key)
        for key in ("kind", "catalog", "validation_modules", "smoke_code")
    }
    pip_args = []
    for argument in fixture.get("pip_args") or []:
        value = str(argument)
        if value == str(fixture.get("wheelhouse")):
            value = "<wheelhouse>"
        pip_args.append(value)
    stable["pip_args"] = pip_args
    digest.update(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    for key in ("project", "wheelhouse"):
        root_value = fixture.get(key)
        if not root_value:
            continue
        root = Path(root_value)
        if not root.exists():
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            digest.update(key.encode("utf-8"))
            digest.update(str(path.relative_to(root)).encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _bwrap_usable(workdir: Path) -> bool:
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return False
    completed = subprocess.run(
        [
            bwrap, "--ro-bind", "/", "/", "--bind", str(workdir), str(workdir),
            "--chdir", str(workdir), "--unshare-net", "--dev", "/dev", "--proc", "/proc",
            "bash", "-c", "true",
        ],
        capture_output=True, text=True, timeout=10, check=False,
    )
    return completed.returncode == 0


def _run_trial_subprocess(
    variant: str,
    trial_root: Path,
    *,
    fixture_kind: str,
    max_turns: int,
    timeout: float,
) -> dict[str, Any]:
    fixture = _create_fixture(fixture_kind, trial_root)
    workdir = Path(fixture["project"]).resolve()
    config_path = trial_root / "worker-config.json"
    result_path = trial_root / "worker-result.json"
    config = {
        "variant": variant,
        "trial_root": str(trial_root),
        "fixture_kind": fixture_kind,
        "max_turns": max_turns,
        "fixture": fixture,
        "result_path": str(result_path),
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    repository = Path(__file__).resolve().parent.parent
    environment = os.environ.copy()
    home = trial_root / "worker-home"
    pip_cache = trial_root / "pip-cache"
    home.mkdir()
    pip_cache.mkdir()
    environment["HOME"] = str(home)
    environment["XDG_CACHE_HOME"] = str(home / ".cache")
    environment["PIP_CACHE_DIR"] = str(pip_cache)
    bwrap_available = shutil.which("bwrap") is not None
    if not bwrap_available:
        return _worker_failure_record(
            variant, fixture_kind, max_turns, workdir,
            "isolation_failure", "bubblewrap executable is required for formal Agent trials",
            0.0,
        )
    environment["MINIOPENCLAW_EVAL_BWRAP_USABLE"] = "1" if _bwrap_usable(workdir) else "0"
    pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(repository) if not pythonpath else os.pathsep.join((str(repository), pythonpath))
    )
    started = time.monotonic()
    process = subprocess.Popen(
        [sys.executable, "-m", "eval.pacs_agent_ablation", "--_worker-config", str(config_path)],
        cwd=str(workdir),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        return _worker_failure_record(
            variant, fixture_kind, max_turns, workdir,
            "subprocess_timeout", f"trial exceeded {timeout:g} seconds",
            time.monotonic() - started,
            stdout=(exc.stdout or "") + (stdout or ""),
            stderr=(exc.stderr or "") + (stderr or ""),
        )
    returncode = process.returncode
    if returncode != 0 or not result_path.is_file():
        detail = f"worker exit code {returncode}"
        if not result_path.is_file():
            detail += "; result JSON missing"
        return _worker_failure_record(
            variant, fixture_kind, max_turns, workdir,
            "worker_error", detail, time.monotonic() - started,
            stdout=stdout, stderr=stderr,
        )
    try:
        record = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _worker_failure_record(
            variant, fixture_kind, max_turns, workdir,
            "worker_error", f"invalid worker result: {exc}", time.monotonic() - started,
            stdout=stdout, stderr=stderr,
        )
    record["worker"] = {
        "returncode": returncode,
        "wall_seconds": time.monotonic() - started,
        "stdout": stdout[-4000:],
        "stderr": stderr[-4000:],
    }
    record["fixture_hash"] = _fixture_hash(fixture)
    return record


def _worker_failure_record(
    variant: str,
    fixture_kind: str,
    max_turns: int,
    workdir: Path,
    reason: str,
    error: str,
    duration: float,
    *,
    stdout: str = "",
    stderr: str = "",
) -> dict[str, Any]:
    return {
        "variant": variant,
        "fixture": fixture_kind,
        "success": False,
        "environment_verified": False,
        "agent_completed": False,
        "duration_seconds": duration,
        "agent_seconds": duration,
        "verification_seconds": 0.0,
        "total_evaluation_seconds": duration,
        "termination_reason": reason,
        "cap_reached": False,
        "turns_remaining": max_turns,
        "model": None,
        "max_turns": max_turns,
        "task": "",
        "final_response": "",
        "error": error,
        "metrics": {
            "turns": 0, "llm_calls": 0, "tool_calls": 0, "tool_names": [],
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "installation_requests": 0, "trace_path": None, "failed_spans": 0,
            "candidate_attempts": None,
        },
        "verification": {"success": False, "winner": None, "winners": [], "environments": []},
        "pacs_result": None,
        "workdir": str(workdir),
        "isolation": {"cwd": "", "write_root": "", "trial_project": str(workdir), "ok": False},
        "worker": {"returncode": None, "wall_seconds": duration, "stdout": str(stdout)[-4000:], "stderr": str(stderr)[-4000:]},
    }


def _worker_main(config_path: Path) -> int:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    backend = None
    if config.get("fake_backend"):
        from backend.fake_backend import FakeBackend
        backend = FakeBackend()
    record = run_trial(
        config["variant"],
        config["trial_root"],
        fixture_kind=config["fixture_kind"],
        max_turns=int(config["max_turns"]),
        fixture=config["fixture"],
        backend=backend,
    )
    Path(config["result_path"]).write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


def _workspace_fingerprint() -> str | None:
    repository = Path(__file__).resolve().parent.parent
    digest = hashlib.sha256()
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD"], cwd=str(repository),
        capture_output=True, check=False,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=str(repository),
        capture_output=True, check=False,
    )
    if diff.returncode or untracked.returncode:
        return None
    digest.update(diff.stdout)
    for raw in sorted(item for item in untracked.stdout.split(b"\0") if item):
        relative = raw.decode("utf-8", errors="surrogateescape")
        if relative.startswith(".claude/worktrees/"):
            continue
        path = repository / relative
        digest.update(raw)
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_revision() -> str | None:
    repository = Path(__file__).resolve().parent.parent
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repository),
        capture_output=True, text=True, check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("ablation-results/pacs-agent"))
    parser.add_argument("--blocks", type=int, default=1)
    parser.add_argument(
        "--fixture", choices=("clean", "conflict", "real-conflict"), default="real-conflict"
    )
    parser.add_argument("--max-turns", type=int, default=60)
    parser.add_argument("--trial-timeout", type=float, default=600.0)
    parser.add_argument("--seed", type=int, default=20260715)
    parser.add_argument("--_worker-config", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args._worker_config is not None:
        return _worker_main(args._worker_config)
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)
    _load_dotenv()

    manifest = {
        "fixture": args.fixture,
        "blocks": max(1, args.blocks),
        "max_turns": args.max_turns,
        "trial_timeout_seconds": args.trial_timeout,
        "seed": args.seed,
        "git_revision": _git_revision(),
        "python": sys.version,
        "python_executable": sys.executable,
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        "base_url": os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "pip_index_url": os.environ.get("PIP_INDEX_URL"),
        "pip_trusted_host": os.environ.get("PIP_TRUSTED_HOST"),
        "workspace_fingerprint_before": _workspace_fingerprint(),
    }
    (args.output / "run-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    rng = random.Random(args.seed)
    records = []
    for block in range(1, max(1, args.blocks) + 1):
        order = list(VARIANTS)
        rng.shuffle(order)
        for variant in order:
            root = (args.output / f"block-{block}-{variant}").resolve()
            record = {
                "block": block,
                "order": order,
                **_run_trial_subprocess(
                    variant, root, fixture_kind=args.fixture,
                    max_turns=args.max_turns, timeout=args.trial_timeout,
                ),
            }
            records.append(record)
            print(json.dumps({
                "block": block,
                "variant": variant,
                "success": record["success"],
                "termination_reason": record["termination_reason"],
                "seconds": round(record["duration_seconds"], 3),
                "turns": record["metrics"]["turns"],
                "tools": record["metrics"]["tool_calls"],
                "installation_requests": record["metrics"]["installation_requests"],
            }, ensure_ascii=False), flush=True)

    (args.output / "trials.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records),
        encoding="utf-8",
    )
    summary = summarize(records)
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest["workspace_fingerprint_after"] = _workspace_fingerprint()
    manifest["workspace_unchanged"] = (
        manifest["workspace_fingerprint_before"] == manifest["workspace_fingerprint_after"]
    )
    (args.output / "run-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all(row["success"] for row in records) and manifest["workspace_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

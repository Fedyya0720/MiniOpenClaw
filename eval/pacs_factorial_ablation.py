"""Evaluation-only 2x2 ablation of PACS parallelism and pruning."""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

from eval.fixtures.pacs_projects import (
    create_conflict_project,
    create_parallel_speed_project,
    create_pruning_amplifier_project,
)
from pacs import PACSBuilder
import pacs.builder as builder_module


@dataclass(frozen=True)
class Variant:
    name: str
    parallel: int
    pruning: bool


VARIANTS = (
    Variant("serial-naive", 1, False),
    Variant("serial-pruning", 1, True),
    Variant("parallel-naive", 2, False),
    Variant("parallel-pruning", 2, True),
)


class NoLearningConstraintGraph:
    """ConstraintGraph-compatible null object for the pruning-off condition."""

    def load_all(self) -> list[dict[str, Any]]:
        return []

    def insert(self, _edges: list[dict[str, Any]]) -> int:
        return 0

    def infer_transitive(self, _seed_packages: set[str] | None = None) -> int:
        return 0

    def close(self) -> None:
        return None


@contextmanager
def _serial_mode(enabled: bool) -> Iterator[None]:
    key = "MINIOPENCLAW_PACS_SERIAL"
    previous = os.environ.get(key)
    try:
        if enabled:
            os.environ[key] = "1"
        else:
            os.environ.pop(key, None)
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def _independent_verify(result: dict[str, Any], smoke_code: str) -> dict[str, Any]:
    environment = result.get("environment_path")
    if not result.get("success") or not environment:
        return {"success": False, "detail": result.get("error") or "builder failed"}
    root = Path(environment)
    python = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    commands = ([str(python), "-m", "pip", "check"], [str(python), "-c", smoke_code])
    evidence = []
    for command in commands:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        evidence.append({
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-2000:],
            "stderr": completed.stderr[-2000:],
        })
        if completed.returncode:
            return {"success": False, "detail": "independent verification failed", "commands": evidence}
    return {"success": True, "commands": evidence}


def _create_fixture(
    kind: str, root: str | Path, *, payload_mib: float, addon_count: int
) -> dict[str, Any]:
    if kind == "negative-control":
        fixture = create_conflict_project(root)
        return {
            **fixture,
            "kind": "negative-control",
            "overlap_factor": 3,
            "expected_excluded_by_constraints": 3,
            "max_attempts": 8,
        }
    if kind == "parallel-speed":
        return create_parallel_speed_project(root, payload_mib=payload_mib)
    if kind == "pruning-amplifier":
        return create_pruning_amplifier_project(root, addon_count=addon_count)
    raise ValueError(f"unknown fixture: {kind}")


def run_trial(
    variant: Variant,
    root: str | Path,
    *,
    fixture_kind: str = "negative-control",
    payload_mib: float = 8.0,
    addon_count: int = 10,
    max_attempts: int | None = None,
) -> dict[str, Any]:
    fixture = _create_fixture(
        fixture_kind, root, payload_mib=payload_mib, addon_count=addon_count
    )
    builder = PACSBuilder(fixture["project"])
    if not variant.pruning:
        builder.graph.close()
        builder.graph = NoLearningConstraintGraph()

    lock = threading.Lock()
    active_preflights = 0
    max_preflights = 0
    preflight_calls = 0
    solver_calls: list[dict[str, int]] = []
    install_batches: list[dict[str, Any]] = []
    real_preflight = builder_module.preflight
    real_solver = builder_module.solve_candidates
    real_install = builder_module.install_for_environment

    def measured_preflight(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal active_preflights, max_preflights, preflight_calls
        with lock:
            preflight_calls += 1
            active_preflights += 1
            max_preflights = max(max_preflights, active_preflights)
        try:
            return real_preflight(*args, **kwargs)
        finally:
            with lock:
                active_preflights -= 1

    def measured_solver(
        catalog: dict[str, list[str]], constraints: list[dict[str, Any]] | None = None, *, limit: int = 20
    ) -> dict[str, Any]:
        result = real_solver(catalog, constraints, limit=limit)
        total_space = 1
        for versions in catalog.values():
            total_space *= len(versions)
        solver_calls.append({
            "constraints": len(constraints or []),
            "total_space": total_space,
            "returned": len(result["combinations"]),
        })
        return result

    def measured_install(*args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        batch = real_install(*args, **kwargs)
        install_batches.append({
            "mode": batch.mode,
            "wall_seconds": time.monotonic() - started,
            "attempted": batch.attempted_count,
            "cancelled": batch.cancelled_count,
            "submitted": batch.submitted_count,
            "sum_task_seconds": sum(item.duration_seconds for item in batch.results),
        })
        return batch

    with _serial_mode(variant.parallel == 1), \
         mock.patch("pacs.builder.preflight", side_effect=measured_preflight), \
         mock.patch("pacs.builder.solve_candidates", side_effect=measured_solver), \
         mock.patch("pacs.builder.install_for_environment", side_effect=measured_install):
        result = builder.build(
            max_parallel=variant.parallel,
            max_attempts=max_attempts or int(fixture["max_attempts"]),
            timeout=60,
            version_catalog=fixture["catalog"],
            validation_modules=fixture["validation_modules"],
            pip_args=fixture["pip_args"],
        )

    final_constraints = [
        edge
        for attempt in result["attempts"]
        for failure in attempt.get("failures", [])
        for edge in failure.get("constraints", [])
    ] if variant.pruning else []
    full_space = 1
    for versions in fixture["catalog"].values():
        full_space *= len(versions)
    constrained_space = len(real_solver(
        fixture["catalog"], final_constraints, limit=max(20, full_space)
    )["combinations"])
    excluded_by_constraints = max(0, full_space - constrained_space)
    verification = _independent_verify(result, fixture["smoke_code"])
    validation_failed = sum(
        item.get("stage") == "validation" and item.get("status") == "failed"
        for item in result["attempts"]
    )
    validation_ok = sum(
        item.get("stage") == "validation" and item.get("status") == "ok"
        for item in result["attempts"]
    )
    winner_rank = None
    if result.get("environment_id"):
        for rank, attempt in enumerate(result["attempts"], 1):
            if attempt.get("environment_id") == result["environment_id"]:
                winner_rank = rank
                break
    acceptance_checks = {
        "verified_success": bool(result["success"] and verification["success"]),
        "expected_winner_rank": (
            fixture.get("expected_winner_rank") is None
            or winner_rank == fixture["expected_winner_rank"]
        ),
        "broad_exclusion": (
            fixture.get("expected_excluded_by_constraints") is None
            or excluded_by_constraints >= fixture["expected_excluded_by_constraints"]
        ),
    }
    return {
        "fixture": fixture["kind"],
        "fixture_metrics": {
            "overlap_factor": fixture.get("overlap_factor"),
            "stage_counts": {
                "validation_failed": validation_failed,
                "validation_ok": validation_ok,
            },
            "winner_rank": winner_rank,
            "expected_winner_rank": fixture.get("expected_winner_rank"),
            "expected_excluded_by_constraints": fixture.get("expected_excluded_by_constraints"),
            "max_attempts": max_attempts or fixture["max_attempts"],
        },
        "acceptance_checks": acceptance_checks,
        "variant": asdict(variant),
        "success": bool(result["success"] and verification["success"]),
        "duration_seconds": result["duration_seconds"],
        "attempted": result["attempted"],
        "failed": result["failed"],
        "constraints_learned": result["constraints_learned"],
        "rounds": result["rounds"],
        "preflight_calls": preflight_calls,
        "max_concurrent_preflights": max_preflights,
        "excluded_by_constraints": excluded_by_constraints,
        "solver_calls": solver_calls,
        "install_batches": install_batches,
        "attempts": result["attempts"],
        "result_path": result["result_path"],
        "verification": verification,
    }


def _median_iqr(values: list[float | int]) -> dict[str, float]:
    numeric = [float(value) for value in values]
    if len(numeric) == 1:
        iqr = 0.0
    else:
        q1, _, q3 = statistics.quantiles(numeric, n=4, method="inclusive")
        iqr = q3 - q1
    return {"median": statistics.median(numeric), "iqr": iqr}


def _summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"variants": {}}
    for variant in (item.name for item in VARIANTS):
        rows = [row for row in records if row["variant"]["name"] == variant]
        if not rows:
            continue
        summary["variants"][variant] = {
            "trials": len(rows),
            "success_rate": sum(bool(row["success"]) for row in rows) / len(rows),
            "seconds": _median_iqr([row["duration_seconds"] for row in rows]),
            "attempted": _median_iqr([row["attempted"] for row in rows]),
            "preflights": _median_iqr([row["preflight_calls"] for row in rows]),
            "excluded_by_constraints": _median_iqr([
                row["excluded_by_constraints"] for row in rows
            ]),
        }

    blocks: dict[int, dict[str, dict[str, Any]]] = {}
    for row in records:
        blocks.setdefault(row["block"], {})[row["variant"]["name"]] = row
    complete = [block for block in blocks.values() if len(block) == len(VARIANTS)]
    summary["paired_effects"] = {"blocks": len(complete)}
    if complete:
        parallel_effects = []
        pruning_effects = []
        interactions = []
        for block in complete:
            serial_naive = block["serial-naive"]["duration_seconds"]
            serial_pruning = block["serial-pruning"]["duration_seconds"]
            parallel_naive = block["parallel-naive"]["duration_seconds"]
            parallel_pruning = block["parallel-pruning"]["duration_seconds"]
            parallel_naive_effect = serial_naive - parallel_naive
            parallel_pruning_effect = serial_pruning - parallel_pruning
            parallel_effects.append((parallel_naive_effect + parallel_pruning_effect) / 2)
            pruning_serial_effect = serial_naive - serial_pruning
            pruning_parallel_effect = parallel_naive - parallel_pruning
            pruning_effects.append((pruning_serial_effect + pruning_parallel_effect) / 2)
            interactions.append(parallel_pruning_effect - parallel_naive_effect)
        summary["paired_effects"].update({
            "parallel_seconds_saved": _median_iqr(parallel_effects),
            "pruning_seconds_saved": _median_iqr(pruning_effects),
            "parallel_by_pruning_interaction_seconds": _median_iqr(interactions),
        })
    summary["acceptance_checks"] = {
        "all_verified": all(row.get("acceptance_checks", {}).get("verified_success", row["success"]) for row in records),
        "winner_rank_checks_pass": all(row.get("acceptance_checks", {}).get("expected_winner_rank", True) for row in records),
        "broad_exclusion_observed": any(row.get("acceptance_checks", {}).get("broad_exclusion", False) for row in records),
    }
    return summary


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize homogeneous records compatibly, or partition mixed fixtures."""
    fixture_kinds = sorted({row.get("fixture", "negative-control") for row in records})
    if len(fixture_kinds) <= 1:
        summary = _summarize_records(records)
        summary["fixture"] = fixture_kinds[0] if fixture_kinds else None
        return summary
    return {
        "fixtures": {
            kind: _summarize_records([
                row for row in records if row.get("fixture", "negative-control") == kind
            ])
            for kind in fixture_kinds
        }
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("ablation-results/pacs-factorial"))
    parser.add_argument("--blocks", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260715)
    parser.add_argument(
        "--fixture",
        choices=("negative-control", "parallel-speed", "pruning-amplifier"),
        default="negative-control",
    )
    parser.add_argument("--payload-mib", type=float, default=8.0)
    parser.add_argument("--addon-count", type=int, default=10)
    parser.add_argument("--max-attempts", type=int)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)

    rng = random.Random(args.seed)
    records = []
    for block in range(max(1, args.blocks)):
        order = list(VARIANTS)
        rng.shuffle(order)
        for variant in order:
            trial_root = args.output / f"block-{block + 1}-{variant.name}"
            record = {
                "block": block + 1,
                "order": [item.name for item in order],
                **run_trial(
                    variant,
                    trial_root,
                    fixture_kind=args.fixture,
                    payload_mib=args.payload_mib,
                    addon_count=args.addon_count,
                    max_attempts=args.max_attempts,
                ),
            }
            records.append(record)
            print(json.dumps({
                "block": block + 1,
                "variant": variant.name,
                "success": record["success"],
                "seconds": round(record["duration_seconds"], 3),
                "attempted": record["attempted"],
                "excluded_by_constraints": record["excluded_by_constraints"],
            }, ensure_ascii=False))

    raw_path = args.output / "trials.jsonl"
    raw_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")
    summary = summarize(records)
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all(row["success"] for row in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())

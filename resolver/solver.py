"""Finite-domain constraint solving for PACS candidate selection."""
from __future__ import annotations

import itertools
from typing import Any


def _hard_conflicts(constraints: list[dict[str, Any]]) -> set[tuple[str, str, str, str]]:
    result: set[tuple[str, str, str, str]] = set()
    for item in constraints:
        if item.get("kind", "observed") != "observed":
            continue
        if float(item.get("confidence", 0.0)) < 0.7:
            continue
        edge = (
            str(item.get("pkg_a", "")).lower().replace("_", "-"), str(item.get("ver_a", "")),
            str(item.get("pkg_b", "")).lower().replace("_", "-"), str(item.get("ver_b", "")),
        )
        result.add(edge)
        result.add((edge[2], edge[3], edge[0], edge[1]))
    return result


def _rejected(combo: dict[str, str], conflicts: set[tuple[str, str, str, str]]) -> bool:
    names = list(combo)
    return any(
        (names[i], combo[names[i]], names[j], combo[names[j]]) in conflicts
        for i in range(len(names)) for j in range(i + 1, len(names))
    )


def _enumerate(
    catalog: dict[str, list[str]], constraints: list[dict[str, Any]], limit: int
) -> list[dict[str, str]]:
    names = list(catalog)
    domains = [catalog[name] for name in names]
    if not names or any(not domain for domain in domains):
        return []
    conflicts = _hard_conflicts(constraints)
    candidates: list[dict[str, str]] = []
    for values in itertools.product(*domains):
        combo = dict(zip(names, values))
        if not _rejected(combo, conflicts):
            candidates.append(combo)
        if len(candidates) >= limit:
            break
    return candidates


def solve_candidates(
    catalog: dict[str, list[str]],
    constraints: list[dict[str, Any]] | None = None,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """Return bounded models using Z3 when available, with an honest fallback."""
    constraints = list(constraints or [])
    if not catalog:
        return {"solver": "none", "combinations": [{}], "warnings": []}
    if any(not versions for versions in catalog.values()):
        missing = [name for name, versions in catalog.items() if not versions]
        return {"solver": "none", "combinations": [], "warnings": ["无可用版本: " + ", ".join(missing)]}
    try:
        import z3  # type: ignore
    except ImportError:
        return {
            "solver": "enumeration-fallback",
            "combinations": _enumerate(catalog, constraints, limit),
            "warnings": ["z3-solver 未安装，使用有限域枚举回退"],
        }

    names = list(catalog)
    variables = {name: z3.Int(f"pacs_{index}") for index, name in enumerate(names)}
    solver = z3.Solver()
    for name in names:
        solver.add(variables[name] >= 0, variables[name] < len(catalog[name]))
    for edge in _hard_conflicts(constraints):
        a, va, b, vb = edge
        if a not in variables or b not in variables or va not in catalog[a] or vb not in catalog[b]:
            continue
        solver.add(z3.Or(variables[a] != catalog[a].index(va), variables[b] != catalog[b].index(vb)))

    combinations: list[dict[str, str]] = []
    while len(combinations) < limit and solver.check() == z3.sat:
        model = solver.model()
        indices = {name: model.eval(variables[name]).as_long() for name in names}
        combinations.append({name: catalog[name][indices[name]] for name in names})
        solver.add(z3.Or(*[variables[name] != indices[name] for name in names]))
    return {"solver": "z3", "combinations": combinations, "warnings": []}

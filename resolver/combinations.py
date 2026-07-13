"""Candidate version generation and conflict pruning."""
from __future__ import annotations

import itertools
import re
from typing import Any, Iterable

from .dep_parser import DepSpec


_PRUNABLE_ERROR_TYPES = {
    "conflict", "dependency_conflict", "installed_version_conflict",
    "no_matching_distribution", "version_unavailable", "python_version_mismatch",
    "wheel_incompatible", "invalid_wheel", "transitive_conflict",
}


def version_matches(version: str, specifier: str) -> bool:
    if not specifier or specifier.startswith("@"):
        return True
    value = _version_tuple(version)
    for clause in filter(None, map(str.strip, specifier.split(","))):
        match = re.match(r"(===|==|!=|~=|>=|<=|>|<)\s*([^\s]+)", clause)
        if not match:
            continue
        op, expected = match.groups()
        if expected.endswith(".*"):
            equal = version.startswith(expected[:-1])
        else:
            target = _version_tuple(expected)
            equal = value == target
        if op in {"==", "==="} and not equal:
            return False
        if op == "!=" and equal:
            return False
        if op == ">=" and value < target:
            return False
        if op == "<=" and value > target:
            return False
        if op == ">" and value <= target:
            return False
        if op == "<" and value >= target:
            return False
        if op == "~=" and not (value >= target and value[:1] == target[:1]):
            return False
    return True


def _version_tuple(version: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", version)
    parts = list(map(int, numbers[:4])) or [0]
    return tuple((parts + [0, 0, 0, 0])[:4])


def version_sort_key(version: str) -> tuple[int, ...]:
    return _version_tuple(version)


def _candidate_versions(specifier: str, available: Iterable[str] | None = None, newest_first: bool = False) -> list[str]:
    if available is not None:
        versions = sorted(
            {str(version) for version in available if version_matches(str(version), specifier)},
            key=version_sort_key,
            reverse=newest_first,
        )
        return versions
    exact = re.search(r"(?:^|,)\s*={2,3}\s*([0-9][^,;*\s]*)", specifier)
    if exact:
        return [exact.group(1)]
    lower = re.search(r"(?:^|,)\s*(?:>=|~=|>)\s*([0-9]+(?:\.[0-9]+){0,3})", specifier)
    if lower:
        parts = list(_version_tuple(lower.group(1)))
        precision = max(2, len(lower.group(1).split(".")))
        base = parts[:precision]
        patch = parts[:max(3, precision)]
        minor = parts[:max(3, precision)]
        patch[2] += 1
        minor[1] += 1
        minor[2] = 0
        values = [".".join(map(str, item)) for item in (base, patch, minor)]
    else:
        values = ["latest"]
    return list(dict.fromkeys(value for value in values if value == "latest" or version_matches(value, specifier))) or [lower.group(1) if lower else "latest"]


def _dep_dict(dep: DepSpec | dict[str, Any]) -> tuple[str, str]:
    if isinstance(dep, DepSpec):
        return dep.name, dep.specifier
    return str(dep["name"]), str(dep.get("specifier", ""))


def _conflicts(combo: dict[str, str], constraints: Iterable[dict[str, Any]]) -> bool:
    normalized = {name.lower().replace("_", "-"): version for name, version in combo.items()}
    for edge in constraints:
        error_type = str(edge.get("error_type", "conflict"))
        if error_type not in _PRUNABLE_ERROR_TYPES:
            continue
        a = str(edge.get("pkg_a", "")).lower().replace("_", "-")
        b = str(edge.get("pkg_b", "")).lower().replace("_", "-")
        if a not in normalized or b not in normalized:
            continue
        a_match = version_matches(normalized[a], str(edge.get("ver_a", "")))
        b_match = version_matches(normalized[b], str(edge.get("ver_b", "")))
        if a_match and b_match:
            return True
    return False


def generate_combinations(
    deps: Iterable[DepSpec | dict[str, Any]],
    constraints: Iterable[dict[str, Any]] = (),
    max_candidates: int = 4,
    version_catalog: dict[str, list[str]] | None = None,
    newest_first: bool = False,
) -> list[dict[str, str]]:
    entries = [_dep_dict(dep) for dep in deps]
    if not entries or max_candidates <= 0:
        return []
    names = [name for name, _ in entries]
    catalog = version_catalog or {}
    versions = [_candidate_versions(spec, catalog.get(name), newest_first) for name, spec in entries]
    if any(not choices for choices in versions):
        return []
    result: list[dict[str, str]] = []
    for values in itertools.product(*versions):
        combo = dict(zip(names, values))
        if not _conflicts(combo, constraints):
            result.append(combo)
        if len(result) >= max_candidates:
            break
    return result

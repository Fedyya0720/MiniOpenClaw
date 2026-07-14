"""Version-combination generation with constraint pruning.

Phase 2: Given parsed dependency specs, fetch available versions via
``pip index versions``, filter by specifier, and produce a bounded set
of candidate version-combinations. Constraint-graph pruning (Phase 4)
is prepared: the ``constraints`` parameter already gates every pair.
"""
from __future__ import annotations

import concurrent.futures
import itertools
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

from .specifier import matches

# Per-session cache to avoid redundant pip subprocess calls.  Each key is a
# normalized package name; the value is the raw version list returned by pip.
_VERSION_CACHE: dict[str, list[str]] = {}

# Number of newest versions to keep per package when enumerating combinations.
# The Cartesian product of top-K versions grows quickly: 3 packages × 10
# versions = 1000 combos; we cap via ``max_candidates``, so keeping a
# manageable pool per package avoids exhausting the product iterator.
_TOP_VERSIONS = 10

# Max parallel pip index versions calls.
_MAX_WORKERS = 5

# Total timeout (seconds) for fetching all packages' version lists.
_FETCH_TOTAL_TIMEOUT = 60

# Injected by tests so that combination logic can be exercised without live
# network or a real package index.  Accepts a package name and returns a
# simulated version list.  Set to None to use the real ``pip index versions``.
_fetch_versions_impl: Callable[[str], list[str]] | None = None


# -- pip interaction ----------------------------------------------------------

def _parse_available_versions(stdout: str) -> list[str]:
    """Extract version strings from ``pip index versions <pkg>`` output.

    Handles pip ≥ 24 output::

        numpy (2.2.1)
        Available versions: 2.2.1, 2.2.0, ...

    and older pip (21.0–23.x)::

        numpy
        Available versions: 1.26.4, 1.26.3, ...

    Returns an empty list when the format is unrecognised or the package does
    not exist on the index.
    """
    for line in stdout.splitlines():
        if "Available versions:" in line:
            parts = line.split("Available versions:", 1)[1]
            return [v.strip() for v in parts.split(",") if v.strip()]
    return []


def _fetch_versions(package: str) -> list[str]:
    """Return available version strings for *package*, cached per session."""
    if package in _VERSION_CACHE:
        return _VERSION_CACHE[package]

    if _fetch_versions_impl is not None:
        versions = _fetch_versions_impl(package)
        _VERSION_CACHE[package] = versions
        return versions

    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pip", "index", "versions", package],
            capture_output=True, text=True, timeout=15,
            shell=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        _VERSION_CACHE[package] = []
        return []

    if completed.returncode != 0:
        _VERSION_CACHE[package] = []
        return []

    versions = _parse_available_versions(completed.stdout)
    _VERSION_CACHE[package] = versions
    return versions


# -- constraint helpers -------------------------------------------------------

def _build_constraint_set(
    constraints: Sequence[dict[str, Any]],
) -> set[tuple[str, str, str, str]]:
    """Index constraints as (name-a, ver-a, name-b, ver-b) tuples.

    Each constraint is a directed, unordered pair — both orderings are stored
    so one lookup catches the pair regardless of iteration order.
    """
    pairs: set[tuple[str, str, str, str]] = set()
    for c in constraints:
        entry = (c["pkg_a"], c["ver_a"], c["pkg_b"], c["ver_b"])
        pairs.add(entry)
        pairs.add((c["pkg_b"], c["ver_b"], c["pkg_a"], c["ver_a"]))
    return pairs


def _combination_rejected(
    names: list[str],
    combo: tuple[str, ...],
    constrained: set[tuple[str, str, str, str]],
) -> bool:
    """True when any pair within *combo* matches a known-bad constraint."""
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if (names[i], combo[i], names[j], combo[j]) in constrained:
                return True
    return False


# -- public API ---------------------------------------------------------------

def generate_combinations(
    dependencies: list[dict[str, Any]],
    constraints: list[dict[str, Any]] | None = None,
    max_candidates: int = 20,
) -> dict[str, Any]:
    """Produce a bounded list of version-combination dictionaries.

    Args:
        dependencies: Parsed dep specs (the ``dependencies`` list from
            ``parse_deps``). Each entry must have at least ``name``.
        constraints: Optional known-bad pairs like
            ``{"pkg_a": "numpy", "ver_a": "2.0.0",
              "pkg_b": "torch",  "ver_b": "2.0.0"}``.
        max_candidates: Stop enumeration once this many valid combinations
            have been collected.

    Returns:
        A dictionary with keys ``combinations`` (list of ``{name: version}``
        dicts), ``pruned_by_constraint``, ``returned``, ``version_sources``,
        and ``warnings``.
    """
    if not dependencies:
        return {
            "combinations": [], "pruned_by_constraint": 0, "total_product": 0,
            "returned": 0, "non_searchable_count": 0, "version_sources": {},
            "warnings": [],
        }
    constraints = list(constraints) if constraints else []
    searchable = [d for d in dependencies if not d.get("non_searchable")]
    non_searchable = [d for d in dependencies if d.get("non_searchable")]

    # -- Fetch & filter versions per package ----------------------------------
    per_package: dict[str, list[str]] = {}
    warnings: list[str] = []

    # Fetch all packages in parallel to avoid N sequential pip calls.
    fetched: dict[str, list[str]] = {}
    if searchable:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(_MAX_WORKERS, len(searchable)),
        ) as executor:
            future_map = {
                executor.submit(_fetch_versions, dep["name"]): dep["name"]
                for dep in searchable
            }
            try:
                for future in concurrent.futures.as_completed(
                    future_map, timeout=_FETCH_TOTAL_TIMEOUT,
                ):
                    name = future_map[future]
                    try:
                        fetched[name] = future.result()
                    except Exception:
                        fetched[name] = []
            except concurrent.futures.TimeoutError:
                # Some fetches didn't finish in time — mark remaining as empty.
                for future, name in future_map.items():
                    if not future.done():
                        future.cancel()
                        fetched[name] = []

    for dep in searchable:
        name = dep["name"]
        all_versions = fetched.get(name, [])
        specifier = dep.get("specifier", "")
        if specifier:
            filtered = [v for v in all_versions if matches(v, specifier)]
        else:
            filtered = list(all_versions)
        if not filtered:
            warnings.append(
                f"未找到符合约束的版本: {name}"
                + (f" ({specifier})" if specifier else "")
            )
        per_package[name] = filtered[:_TOP_VERSIONS]

    # -- Gather constraints ---------------------------------------------------
    constrained = _build_constraint_set(constraints)

    # -- Enumerate combinations -----------------------------------------------
    names = list(per_package.keys())
    version_lists = [per_package[name] for name in names]
    product_count = _product_size(version_lists)

    combinations: list[dict[str, Any]] = []
    pruned = 0

    if version_lists and all(not versions for versions in version_lists):
        # All searchable packages returned empty version lists — produce a
        # single pinned entry when non-searchable references exist, otherwise
        # return an empty set so the caller knows nothing is resolvable.
        combos: list[dict[str, Any]] = []
        if non_searchable:
            pinned: dict[str, Any] = {}
            for dep in non_searchable:
                pinned[dep["name"]] = dep.get("direct_reference") or dep.get("raw", "")
            combos = [pinned]
        return {
            "combinations": combos,
            "pruned_by_constraint": 0,
            "total_product": product_count,
            "returned": len(combos),
            "non_searchable_count": len(non_searchable),
            "version_sources": _version_sources(per_package),
            "warnings": warnings,
        }

    for combo in itertools.product(*version_lists):
        if len(combinations) >= max_candidates:
            break
        if constrained and _combination_rejected(names, combo, constrained):
            pruned += 1
            continue
        combinations.append(dict(zip(names, combo)))

    # Direct-reference / non-searchable deps are pinned; attach them to every
    # combination so the caller always has a complete picture.
    for dep in non_searchable:
        pinned = dep.get("direct_reference") or dep.get("raw", "")
        if combinations:
            for combo in combinations:
                combo[dep["name"]] = pinned
        else:
            # No searchable combos at all — produce one entry with just the pins.
            combinations.append({dep["name"]: pinned})

    return {
        "combinations": combinations,
        "pruned_by_constraint": pruned,
        "total_product": product_count,
        "returned": len(combinations),
        "non_searchable_count": len(non_searchable),
        "version_sources": _version_sources(per_package),
        "warnings": warnings,
    }


# -- internal helpers ---------------------------------------------------------

def _product_size(version_lists: list[list[str]]) -> int:
    length = 1
    for versions in version_lists:
        length *= len(versions) or 1
    return length


def _version_sources(per_package: dict[str, list[str]]) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "available_count": len(_VERSION_CACHE.get(name, [])),
            "candidates": len(versions),
        }
        for name, versions in per_package.items()
    }

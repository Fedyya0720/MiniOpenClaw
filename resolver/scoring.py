"""Deterministic and explainable PACS candidate scoring."""
from __future__ import annotations

from typing import Any


def score_candidates(
    combinations: list[dict[str, str]],
    catalog: dict[str, list[str]],
    metadata: dict[str, dict[str, dict[str, Any]]] | None = None,
    constraints: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    metadata = metadata or {}
    derived = [item for item in (constraints or []) if item.get("kind") == "derived"]
    scored: list[dict[str, Any]] = []
    for order, combo in enumerate(combinations):
        freshness = 0.0
        wheel = 0.0
        cached = 0.0
        for name, version in combo.items():
            domain = catalog.get(name, [])
            rank = domain.index(version) if version in domain else len(domain)
            freshness += max(0.0, 30.0 * (1.0 - rank / max(1, len(domain))))
            info = metadata.get(name, {}).get(version, {})
            wheel += 20.0 if info.get("has_wheel") else 0.0
            cached += 5.0 if info.get("cached") else 0.0
        count = max(1, len(combo))
        parts = {
            "python_compatible": 30.0,
            "freshness": round(freshness / count, 2),
            "wheel": round(wheel / count, 2),
            "cached": round(cached / count, 2),
            "derived_conflict_risk": 0.0,
        }
        for edge in derived:
            if combo.get(str(edge.get("pkg_a"))) == str(edge.get("ver_a")) and combo.get(
                str(edge.get("pkg_b"))
            ) == str(edge.get("ver_b")):
                parts["derived_conflict_risk"] -= 30.0 * float(edge.get("confidence", 0.5))
        total = round(sum(parts.values()), 2)
        scored.append({"combination": combo, "score": total, "score_parts": parts, "order": order})
    return sorted(scored, key=lambda item: (-item["score"], item["order"]))

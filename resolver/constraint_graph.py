"""SQLite-backed conflict graph and conservative transitive inference."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator


class ConstraintGraph:
    def __init__(self, path: str | Path | None = None) -> None:
        configured = os.environ.get("MINIOPENCLAW_CONSTRAINT_DB")
        self.path = Path(path or configured or ".miniopenclaw/constraint_graph.db").expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._session() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS constraints (
                id INTEGER PRIMARY KEY, pkg_a TEXT NOT NULL, ver_a TEXT NOT NULL,
                pkg_b TEXT NOT NULL, ver_b TEXT NOT NULL, error_type TEXT NOT NULL,
                confidence REAL NOT NULL, inferred INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL,
                UNIQUE(pkg_a, ver_a, pkg_b, ver_b, error_type)
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_constraints_a ON constraints(pkg_a)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_constraints_b ON constraints(pkg_b)")

    @staticmethod
    def _normalize(edge: dict[str, Any]) -> dict[str, Any]:
        return {
            "pkg_a": str(edge.get("pkg_a", "unknown")), "ver_a": str(edge.get("ver_a", "")),
            "pkg_b": str(edge.get("pkg_b", "environment")), "ver_b": str(edge.get("ver_b", "")),
            "error_type": str(edge.get("error_type", "conflict")),
            "confidence": float(edge.get("confidence", .5)), "inferred": int(bool(edge.get("inferred", False))),
            "source": str(edge.get("source", "")),
        }

    def add(self, edges: Iterable[dict[str, Any]]) -> int:
        count = 0
        with self._session() as db:
            for raw in edges:
                edge = self._normalize(raw)
                before = db.total_changes
                db.execute("""INSERT OR IGNORE INTO constraints
                    (pkg_a,ver_a,pkg_b,ver_b,error_type,confidence,inferred,source,created_at)
                    VALUES (:pkg_a,:ver_a,:pkg_b,:ver_b,:error_type,:confidence,:inferred,:source,:created_at)""",
                    {**edge, "created_at": time.time()})
                count += db.total_changes - before
        return count

    def all(self) -> list[dict[str, Any]]:
        with self._session() as db:
            return [dict(row) for row in db.execute("SELECT * FROM constraints ORDER BY id")]

    def related(self, package: str) -> list[dict[str, Any]]:
        with self._session() as db:
            rows = db.execute("SELECT * FROM constraints WHERE pkg_a=? OR pkg_b=? ORDER BY id", (package, package))
            return [dict(row) for row in rows]

    def infer(self) -> list[dict[str, Any]]:
        produced: list[dict[str, Any]] = []
        # Iterate to a fixed point so A-B, B-C, C-D can produce A-D.
        for _ in range(32):
            edges = self.all()
            known = {(e["pkg_a"], e["ver_a"], e["pkg_b"], e["ver_b"]) for e in edges}
            batch: list[dict[str, Any]] = []
            for left in edges:
                for right in edges:
                    key = (left["pkg_a"], left["ver_a"], right["pkg_b"], right["ver_b"])
                    if (
                        left["pkg_b"] != right["pkg_a"]
                        or left["ver_b"] != right["ver_a"]
                        or left["pkg_a"] == right["pkg_b"]
                        or key in known
                    ):
                        continue
                    known.add(key)
                    batch.append({
                        "pkg_a": left["pkg_a"], "ver_a": left["ver_a"],
                        "pkg_b": right["pkg_b"], "ver_b": right["ver_b"],
                        "error_type": "transitive_conflict",
                        "confidence": round(min(float(left["confidence"]), float(right["confidence"])) * .8, 4),
                        "inferred": True, "source": json.dumps([left["id"], right["id"]]),
                    })
            if not batch or not self.add(batch):
                break
            produced.extend(batch)
        return produced

    def prune(self, candidates: Iterable[dict[str, str]]) -> list[dict[str, str]]:
        from .combinations import generate_combinations
        constraints = self.all()
        result: list[dict[str, str]] = []
        for candidate in candidates:
            deps = [{"name": name, "specifier": f"=={version}"} for name, version in candidate.items()]
            if generate_combinations(deps, constraints, max_candidates=1):
                result.append(candidate)
        return result

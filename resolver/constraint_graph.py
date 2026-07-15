"""Constraint graph with SQLite persistence and transitive inference.

Phase 4: Maintains a directed-but-undirected graph of known version
incompatibilities.  ``observed`` edges come from real pip failures;
``derived`` edges are produced via BFS transitive reachability and carry
decayed confidence.  The graph persists across sessions at
``~/.cache/miniopenclaw/constraint_graph.db``.
"""
from __future__ import annotations

import sqlite3
import threading
from collections import deque
from pathlib import Path
from typing import Any, Sequence


# Confidence threshold below which we stop traversing during transitive
# inference.  Below 0.3 the signal is effectively noise.
_MIN_CONFIDENCE = 0.3

# Multiplicative factor applied per hop during BFS transitive inference.
_HOP_DECAY = 0.7

# Category labels for edge provenance.
_OBSERVED = "observed"
_DERIVED = "derived"


def _db_path() -> Path:
    base = Path.home() / ".cache" / "miniopenclaw"
    base.mkdir(parents=True, exist_ok=True)
    return base / "constraint_graph.db"


def _normalize(pkg_a: str, ver_a: str, pkg_b: str, ver_b: str) -> tuple[str, str, str, str]:
    """Return (pkg_a, ver_a, pkg_b, ver_b) with pkg_a <= pkg_b lexicographically."""
    if (pkg_a, ver_a) <= (pkg_b, ver_b):
        return pkg_a, ver_a, pkg_b, ver_b
    return pkg_b, ver_b, pkg_a, ver_a


class ConstraintGraph:
    """Persistent constraint graph backed by SQLite.

    Thread-safe: a module-level lock serialises write and compute-heavy
    operations so concurrent env_run batches do not corrupt the DB.
    """

    _lock = threading.Lock()

    def __init__(self, db_path: str | Path | None = None):
        self._db_path = str(db_path) if db_path else str(_db_path())
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema()

    # -- schema -----------------------------------------------------------------

    def _ensure_schema(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pkg_a  TEXT NOT NULL,
                ver_a  TEXT NOT NULL,
                pkg_b  TEXT NOT NULL,
                ver_b  TEXT NOT NULL,
                error_type TEXT DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.5,
                kind    TEXT NOT NULL CHECK(kind IN ('observed','derived')),
                source  TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        self._conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_unique
            ON edges(pkg_a, ver_a, pkg_b, ver_b)
        """)
        self._conn.commit()

    # -- load -------------------------------------------------------------------

    def load_all(self) -> list[dict[str, Any]]:
        """Return every edge in the graph as a dict."""
        rows = self._conn.execute(
            "SELECT pkg_a, ver_a, pkg_b, ver_b, error_type, confidence, kind, source "
            "FROM edges ORDER BY created_at"
        ).fetchall()
        return [
            {
                "pkg_a": r[0], "ver_a": r[1],
                "pkg_b": r[2], "ver_b": r[3],
                "error_type": r[4], "confidence": r[5],
                "kind": r[6], "source": r[7],
            }
            for r in rows
        ]

    # -- insert ----------------------------------------------------------------

    def insert(self, edges: list[dict[str, Any]]) -> int:
        """Insert observed edges (from parse_failure output).  Deduplicates.

        Returns the number of newly inserted rows.
        """
        with self._lock:
            return self._insert_locked(edges)

    def _insert_locked(self, edges: list[dict[str, Any]]) -> int:
        inserted = 0
        touched: set[str] = set()
        for e in edges:
            pkg_a, ver_a, pkg_b, ver_b = _normalize(
                str(e["pkg_a"]), str(e["ver_a"]),
                str(e["pkg_b"]), str(e["ver_b"]),
            )
            try:
                self._conn.execute(
                    "INSERT INTO edges (pkg_a, ver_a, pkg_b, ver_b, error_type, "
                    "confidence, kind, source) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        pkg_a, ver_a, pkg_b, ver_b,
                        e.get("error_type", ""),
                        float(e.get("confidence", 0.5)),
                        e.get("kind", _OBSERVED),
                        e.get("source", ""),
                    ),
                )
                inserted += 1
                touched.add(pkg_a)
                touched.add(pkg_b)
            except sqlite3.IntegrityError:
                # Already exists — update confidence if higher.
                cur = self._conn.execute(
                    "SELECT id, confidence FROM edges "
                    "WHERE pkg_a=? AND ver_a=? AND pkg_b=? AND ver_b=?",
                    (pkg_a, ver_a, pkg_b, ver_b),
                ).fetchone()
                if cur and float(e.get("confidence", 0.5)) > cur[1]:
                    self._conn.execute(
                        "UPDATE edges SET confidence=?, error_type=?, source=?, "
                        "kind=? WHERE id=?",
                        (
                            float(e.get("confidence", 0.5)),
                            e.get("error_type", ""),
                            e.get("source", ""),
                            e.get("kind", _OBSERVED),
                            cur[0],
                        ),
                    )
                    touched.add(pkg_a)
                    touched.add(pkg_b)
        self._conn.commit()
        return inserted

    # -- transitive inference ---------------------------------------------------

    def infer_transitive(self, seed_packages: set[str] | None = None) -> int:
        """Public entry point: run transitive inference, return new edge count."""
        with self._lock:
            if seed_packages is None:
                # Re-infer from all packages that have edges.
                rows = self._conn.execute(
                    "SELECT DISTINCT pkg_a FROM edges UNION SELECT DISTINCT pkg_b FROM edges"
                ).fetchall()
                seed_packages = {r[0] for r in rows}
            return self._infer_transitive_locked(seed_packages)

    def _infer_transitive_locked(self, touched: set[str]) -> int:
        """BFS reachability from each touched package (all its versions) → derived edges.

        Adjacency is built at the ``(pkg, ver)`` granularity so derived edges
        carry correct versions and normalisation is consistent regardless of
        which seed discovered the pair.
        """
        # Build adjacency keyed by (pkg, ver) → list of (neighbor_pkg, neighbor_ver, confidence).
        adj: dict[tuple[str, str], list[tuple[str, str, float]]] = {}
        rows = self._conn.execute(
            "SELECT pkg_a, ver_a, pkg_b, ver_b, confidence FROM edges"
        ).fetchall()
        for pkg_a, ver_a, pkg_b, ver_b, conf in rows:
            key_a = (pkg_a, ver_a)
            key_b = (pkg_b, ver_b)
            adj.setdefault(key_a, []).append((pkg_b, ver_b, conf))
            adj.setdefault(key_b, []).append((pkg_a, ver_a, conf))

        new_derived = 0
        for start_pkg in touched:
            # Find all versioned nodes for this package.
            start_keys = [
                k for k in adj if k[0] == start_pkg
            ]
            for start_key in start_keys:
                start_name, start_ver = start_key
                # BFS: (node_key, distance, path_min_confidence)
                visited: dict[tuple[str, str], float] = {start_key: 1.0}
                queue: deque[tuple[tuple[str, str], int, float]] = deque()
                queue.append((start_key, 0, 1.0))
                while queue:
                    cur_key, dist, path_conf = queue.popleft()
                    cur_name, cur_ver = cur_key
                    for neighbor_pkg, neighbor_ver, edge_conf in adj.get(cur_key, []):
                        new_dist = dist + 1
                        new_path_conf = min(path_conf, edge_conf)
                        derived_conf = new_path_conf * (_HOP_DECAY ** new_dist)
                        if derived_conf < _MIN_CONFIDENCE:
                            continue
                        nbr_key = (neighbor_pkg, neighbor_ver)
                        if nbr_key not in visited:
                            visited[nbr_key] = derived_conf
                            if new_dist >= 2:
                                # Create derived edge start ↔ neighbor.
                                a, va, b, vb = _normalize(
                                    start_name, start_ver,
                                    neighbor_pkg, neighbor_ver,
                                )
                                existing = self._conn.execute(
                                    "SELECT id, kind, confidence FROM edges "
                                    "WHERE pkg_a=? AND ver_a=? AND pkg_b=? AND ver_b=?",
                                    (a, va, b, vb),
                                ).fetchone()
                                if existing is None:
                                    self._conn.execute(
                                        "INSERT INTO edges (pkg_a, ver_a, pkg_b, ver_b, "
                                        "error_type, confidence, kind, source) "
                                        "VALUES (?,?,?,?,?,?,?,?)",
                                        (a, va, b, vb, "", derived_conf, _DERIVED,
                                         "transitive_inference"),
                                    )
                                    new_derived += 1
                                elif existing[1] == _DERIVED and derived_conf > existing[2]:
                                    self._conn.execute(
                                        "UPDATE edges SET confidence=? WHERE id=?",
                                        (derived_conf, existing[0]),
                                    )
                                    new_derived += 1
                            queue.append((nbr_key, new_dist, new_path_conf))
                        else:
                            # Already visited — maybe update via higher-confidence path.
                            prev_conf = visited[nbr_key]
                            if derived_conf > prev_conf and new_dist >= 2:
                                visited[nbr_key] = derived_conf
                                a, va, b, vb = _normalize(
                                    start_name, start_ver,
                                    neighbor_pkg, neighbor_ver,
                                )
                                existing = self._conn.execute(
                                    "SELECT id, kind, confidence FROM edges "
                                    "WHERE pkg_a=? AND ver_a=? AND pkg_b=? AND ver_b=?",
                                    (a, va, b, vb),
                                ).fetchone()
                                if existing is None:
                                    self._conn.execute(
                                        "INSERT INTO edges (pkg_a, ver_a, pkg_b, ver_b, "
                                        "error_type, confidence, kind, source) "
                                        "VALUES (?,?,?,?,?,?,?,?)",
                                        (a, va, b, vb, "", derived_conf, _DERIVED,
                                         "transitive_inference"),
                                    )
                                    new_derived += 1
                                elif existing[1] == _DERIVED and derived_conf > existing[2]:
                                    self._conn.execute(
                                        "UPDATE edges SET confidence=? WHERE id=?",
                                        (derived_conf, existing[0]),
                                    )
                                    new_derived += 1
        self._conn.commit()
        return new_derived

    # -- query ------------------------------------------------------------------

    def query(self, pkg: str) -> list[dict[str, Any]]:
        """Return all constraints (observed + derived) involving *pkg*."""
        rows = self._conn.execute(
            "SELECT pkg_a, ver_a, pkg_b, ver_b, error_type, confidence, kind, source "
            "FROM edges WHERE pkg_a=? OR pkg_b=? ORDER BY kind DESC, confidence DESC",
            (pkg, pkg),
        ).fetchall()
        return [
            {
                "pkg_a": r[0], "ver_a": r[1],
                "pkg_b": r[2], "ver_b": r[3],
                "error_type": r[4], "confidence": r[5],
                "kind": r[6], "source": r[7],
            }
            for r in rows
        ]

    # -- prune ------------------------------------------------------------------

    def prune(
        self, combinations: list[dict[str, str]],
    ) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
        """Split *combinations* into kept, rejected, and flagged lists.

        * **rejected** — any combination whose package-version pairs hit an
          *observed* edge in the graph (hard conflict).
        * **flagged** — any combination that hits only *derived* edges (no
          observed hits).  These are not rejected but the caller should be
          cautious.
        * **kept** — combinations that hit no edges at all.

        Returns ``(kept, rejected, flagged)``.
        """
        if not combinations:
            return [], [], []

        # Pre-load all edges into a fast lookup set.
        observed_set: set[tuple[str, str, str, str]] = set()
        derived_set: set[tuple[str, str, str, str]] = set()
        rows = self._conn.execute(
            "SELECT pkg_a, ver_a, pkg_b, ver_b, kind FROM edges"
        ).fetchall()
        for pkg_a, ver_a, pkg_b, ver_b, kind in rows:
            entry = (pkg_a, ver_a, pkg_b, ver_b)
            entry_rev = (pkg_b, ver_b, pkg_a, ver_a)
            if kind == _OBSERVED:
                observed_set.add(entry)
                observed_set.add(entry_rev)
            else:
                derived_set.add(entry)
                derived_set.add(entry_rev)

        kept: list[dict[str, str]] = []
        rejected: list[dict[str, str]] = []
        flagged: list[dict[str, str]] = []

        for combo in combinations:
            names = sorted(combo.keys())
            hit_observed = False
            hit_derived = False
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    a, b = names[i], names[j]
                    va, vb = combo[a], combo[b]
                    key = (a, va, b, vb)
                    if key in observed_set:
                        hit_observed = True
                        break
                    if key in derived_set:
                        hit_derived = True
                if hit_observed:
                    break
            if hit_observed:
                rejected.append(combo)
            elif hit_derived:
                flagged.append(combo)
            else:
                kept.append(combo)

        return kept, rejected, flagged

    # -- prompt injection -------------------------------------------------------

    @staticmethod
    def inject_constraints(system_prompt: str, graph: "ConstraintGraph") -> str:
        """Append a digest of high-confidence observed constraints to *system_prompt*."""
        rows = graph._conn.execute(
            "SELECT pkg_a, ver_a, pkg_b, ver_b, confidence, error_type "
            "FROM edges WHERE kind='observed' AND confidence >= 0.7 "
            "ORDER BY confidence DESC LIMIT 50"
        ).fetchall()
        if not rows:
            return system_prompt
        lines = ["\n\n## Known constraints"]
        lines.append(
            "The following version pairs are known to conflict (learned from "
            "previous install failures across sessions):"
        )
        for pkg_a, ver_a, pkg_b, ver_b, conf, err_type in rows:
            lines.append(
                f"- {pkg_a}=={ver_a}  ×  {pkg_b}=={ver_b}  "
                f"(confidence={conf:.2f}, {err_type})"
            )
        return system_prompt + "\n".join(lines)

    # -- close ------------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ConstraintGraph":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

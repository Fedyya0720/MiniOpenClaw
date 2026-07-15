"""Fast deterministic orchestration over MiniOpenClaw's PACS primitives."""
from __future__ import annotations

import concurrent.futures
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Sequence

from envpool.install import InstallSpec, install_for_environment
from envpool.manager import EnvironmentInfo, EnvironmentPool
from resolver.constraint_graph import ConstraintGraph
from resolver.dep_parser import parse_project
from resolver.failure_parser import parse_failure
from resolver.preflight import preflight
from resolver.scoring import score_candidates
from resolver.solver import solve_candidates
from resolver.specifier import matches
from resolver.version_index import VersionIndex


_PRUNABLE = {"version_conflict", "metadata_conflict", "yanked_version"}


class PACSBuilder:
    """Run bounded solve → preflight → parallel install → verify loops."""

    def __init__(self, project_path: str | Path) -> None:
        self.project = Path(project_path).expanduser().resolve()
        if not self.project.is_dir():
            raise ValueError(f"项目目录不存在: {self.project}")
        self.state = self.project / ".mini-openclaw" / "pacs"
        self.state.mkdir(parents=True, exist_ok=True)
        self.pool = EnvironmentPool(self.project)
        self.graph = ConstraintGraph(self.state / "constraint-graph.db")
        self.index = VersionIndex(self.state / "version-index.json")

    @staticmethod
    def _packages(combo: dict[str, str]) -> list[str]:
        return [f"{name} @ {version}" if "://" in version or version.startswith("git+") else f"{name}=={version}"
                for name, version in combo.items()]

    @staticmethod
    def _exact_constraints(entries: list[dict[str, Any]], combo: dict[str, str]) -> list[dict[str, Any]]:
        learned: list[dict[str, Any]] = []
        canonical = {name.lower().replace("_", "-"): name for name in combo}
        for entry in entries:
            if entry.get("error_type") not in _PRUNABLE:
                continue
            for raw in entry.get("constraints", []):
                edge = dict(raw)
                raw_a, raw_b = str(edge.get("pkg_a", "")), str(edge.get("pkg_b", ""))
                a = canonical.get(raw_a.lower().replace("_", "-"))
                b = canonical.get(raw_b.lower().replace("_", "-"))
                if a is None or b is None or raw_a == "unknown" or raw_b == "unknown":
                    continue
                # The graph stores exact failed candidates. Pip's prose often
                # contains a range for one side; bind it to this attempted model.
                edge.update({
                    "pkg_a": a, "ver_a": combo[a], "pkg_b": b, "ver_b": combo[b],
                    "error_type": entry.get("error_type", ""),
                    "confidence": max(0.7, float(entry.get("confidence", 0.7))),
                    "kind": "observed",
                    "source": "pacs_builder",
                })
                learned.append(edge)
        return learned

    @staticmethod
    def _verify(info: EnvironmentInfo, modules: Sequence[str]) -> dict[str, Any]:
        check = subprocess.run(
            [info.python, "-m", "pip", "check"], capture_output=True, text=True,
            timeout=60, check=False, shell=False,
        )
        if check.returncode != 0:
            return {"success": False, "stage": "pip-check", "detail": (check.stdout + check.stderr)[-3000:]}
        if modules:
            script = "import importlib; [importlib.import_module(name) for name in " + repr(list(modules)) + "]"
            imported = subprocess.run(
                [info.python, "-c", script], capture_output=True, text=True,
                timeout=60, check=False, shell=False,
            )
            if imported.returncode != 0:
                return {"success": False, "stage": "import", "detail": (imported.stdout + imported.stderr)[-3000:]}
        return {"success": True, "stage": "complete", "detail": check.stdout.strip()}

    def _install_project(self, info: EnvironmentInfo, timeout: float) -> dict[str, Any]:
        if not any((self.project / name).exists() for name in ("pyproject.toml", "setup.py", "setup.cfg")):
            return {"success": True, "installed": False, "detail": "no installable project metadata"}
        batch = install_for_environment(
            self.pool,
            [InstallSpec(
                env_id=info.env_id,
                label="editable-project",
                packages=["--no-deps", "-e", str(self.project)],
            )],
            timeout=timeout,
            max_workers=1,
        )
        installed = batch.results[0]
        return {
            "success": installed.success,
            "installed": installed.success,
            "detail": installed.summary,
            "log_path": installed.log_path,
        }

    @staticmethod
    def _freeze(info: EnvironmentInfo, path: Path) -> None:
        completed = subprocess.run(
            [info.python, "-m", "pip", "freeze"], capture_output=True, text=True,
            timeout=60, check=False, shell=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "pip freeze 失败")
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(completed.stdout, encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _write_report(path: Path, result: dict[str, Any]) -> None:
        rows = []
        for item in result["attempts"]:
            combo = ", ".join(f"{k}=={v}" for k, v in item["combination"].items())
            rows.append(
                f"| {item['round']} | {combo} | {item['score']} | {item['stage']} | {item['status']} |"
            )
        content = "\n".join([
            "# PACS Build Report", "",
            f"- Status: **{'success' if result['success'] else 'failed'}**",
            f"- Solver: `{result['solver']}`",
            f"- Rounds: {result['rounds']}",
            f"- Attempted: {result['attempted']}",
            f"- Constraints learned: {result['constraints_learned']}",
            f"- Version expansions: {result['version_expansions']}",
            f"- Version window: {result['version_limit']} per package",
            f"- Project installed: {result['project_installed']}",
            f"- Winner: `{result.get('environment_path') or 'none'}`",
            f"- Duration: {result['duration_seconds']:.3f}s", "",
            "| Round | Candidate | Score | Stage | Result |",
            "|---:|---|---:|---|---|", *rows, "",
            f"Lock: `{result.get('lock_path') or 'none'}`", "",
        ])
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    def build(
        self,
        *,
        python: str | None = None,
        max_parallel: int = 2,
        max_attempts: int = 8,
        timeout: float = 120.0,
        version_catalog: dict[str, list[str]] | None = None,
        validation_modules: Sequence[str] = (),
        pip_args: Sequence[str] = (),
        refresh_versions: bool = False,
        backend: str = "venv",
        version_batch_size: int = 5,
        max_versions_per_package: int = 20,
        install_project: bool = True,
    ) -> dict[str, Any]:
        started = time.monotonic()
        max_parallel = max(1, min(int(max_parallel), 8))
        max_attempts = max(1, min(int(max_attempts), 50))
        version_batch_size = max(1, min(int(version_batch_size), 20))
        max_versions_per_package = max(
            version_batch_size, min(int(max_versions_per_package), 100)
        )
        version_limit = version_batch_size
        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        run_dir = self.state / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        attempts: list[dict[str, Any]] = []
        attempted: set[tuple[tuple[str, str], ...]] = set()
        preflight_cache: dict[tuple[tuple[str, str], ...], dict[str, Any]] = {}
        created: set[str] = set()
        winner: EnvironmentInfo | None = None
        project_installed = False
        learned_count = 0
        rounds = 0
        version_expansions = 0
        solver_name = "none"
        error = ""
        catalog_warnings: list[str] = []

        try:
            parsed = parse_project(self.project)
            dependencies = list(parsed["dependencies"])
            requires_python = str(parsed["metadata"].get("requires_python", ""))
            selected_version = python if python and python[0].isdigit() else f"{sys.version_info.major}.{sys.version_info.minor}.0"
            if requires_python and not matches(selected_version, requires_python):
                raise RuntimeError(
                    f"项目要求 Python {requires_python}，当前/请求版本为 {selected_version}"
                )
            catalog_result = self.index.catalog(
                dependencies, refresh=refresh_versions, injected=version_catalog,
                limit=version_limit,
            )
            catalog_warnings.extend(catalog_result["warnings"])
            catalog = catalog_result["versions"]
            direct = {
                str(dep["name"]).lower().replace("_", "-"): str(dep.get("direct_reference") or dep.get("raw", ""))
                for dep in dependencies if dep.get("non_searchable")
            }

            if not dependencies:
                rounds = 1
                attempted.add(())
                info = self.pool.create(f"pacs-{run_id}-empty", python_executable=python, backend=backend)
                created.add(info.env_id)
                project_install = (
                    self._install_project(info, timeout)
                    if install_project else {"success": True, "installed": False, "detail": "skipped"}
                )
                verification = (
                    self._verify(info, validation_modules)
                    if project_install["success"] else {
                        "success": False, "stage": "project-install",
                        "detail": project_install["detail"],
                    }
                )
                attempts.append({
                    "round": 1, "combination": {}, "score": 0.0,
                    "score_parts": {}, "stage": "validation",
                    "status": "ok" if verification["success"] else "failed",
                    "environment_id": info.env_id, "verification": verification,
                    "project_install": project_install,
                })
                if verification["success"]:
                    winner = info
                    project_installed = bool(project_install["installed"])
                else:
                    error = verification["detail"]

            while dependencies and len(attempted) < max_attempts and winner is None:
                rounds += 1
                viable: list[dict[str, Any]] = []
                reserved: set[tuple[tuple[str, str], ...]] = set()
                domain_exhausted = False

                # Fill an installation batch. Preflight candidates concurrently;
                # failures learn constraints and free a slot which is refilled
                # before any expensive environment installation begins.
                while (
                    len(viable) < max_parallel
                    and len(attempted) + len(reserved) < max_attempts
                ):
                    constraints = self.graph.load_all()
                    solved = solve_candidates(catalog, constraints, limit=max_attempts * 2)
                    solver_name = solved["solver"]
                    combinations = [{**combo, **direct} for combo in solved["combinations"]]
                    scored = score_candidates(
                        combinations, catalog, catalog_result["metadata"], constraints
                    )
                    excluded = attempted | reserved
                    capacity = min(
                        max_parallel - len(viable),
                        max_attempts - len(attempted) - len(reserved),
                    )
                    batch = [
                        item for item in scored
                        if tuple(sorted(item["combination"].items())) not in excluded
                    ][:capacity]

                    if not batch:
                        can_expand = (
                            version_limit < max_versions_per_package
                            and any(catalog_result.get("has_more", {}).values())
                        )
                        if can_expand:
                            previous_catalog = catalog
                            version_limit = min(
                                max_versions_per_package,
                                version_limit + version_batch_size,
                            )
                            catalog_result = self.index.catalog(
                                dependencies,
                                refresh=False,
                                injected=version_catalog,
                                limit=version_limit,
                            )
                            catalog_warnings.extend(catalog_result["warnings"])
                            catalog = catalog_result["versions"]
                            if catalog != previous_catalog:
                                version_expansions += 1
                                continue
                        domain_exhausted = True
                        break

                    previews: dict[tuple[tuple[str, str], ...], dict[str, Any]] = {}
                    cache_flags: dict[tuple[tuple[str, str], ...], bool] = {}
                    pending: list[tuple[tuple[tuple[str, str], ...], dict[str, str]]] = []
                    for item in batch:
                        combo = item["combination"]
                        combo_key = tuple(sorted(combo.items()))
                        cache_flags[combo_key] = combo_key in preflight_cache
                        if combo_key in preflight_cache:
                            previews[combo_key] = preflight_cache[combo_key]
                        else:
                            pending.append((combo_key, combo))

                    if pending:
                        workers = min(max_parallel, len(pending))
                        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                            futures = {
                                executor.submit(
                                    preflight,
                                    self._packages(combo),
                                    workdir=self.project,
                                    pip_args=pip_args,
                                    timeout=timeout,
                                ): combo_key
                                for combo_key, combo in pending
                            }
                            for future, combo_key in futures.items():
                                try:
                                    preview = future.result()
                                except Exception as exc:
                                    preview = {
                                        "success": False,
                                        "returncode": None,
                                        "stdout": "",
                                        "stderr": f"{type(exc).__name__}: {exc}",
                                        "resolved": [],
                                    }
                                previews[combo_key] = preview
                                preflight_cache[combo_key] = preview

                    subbatch_learned = 0
                    for item in batch:
                        combo = item["combination"]
                        combo_key = tuple(sorted(combo.items()))
                        preview = previews[combo_key]
                        attempt = {
                            "round": rounds, "combination": combo, "score": item["score"],
                            "score_parts": item["score_parts"], "stage": "preflight",
                            "status": "ok" if preview["success"] else "failed",
                            "resolved": preview.get("resolved", []),
                            "preflight_cached": cache_flags[combo_key],
                        }
                        attempts.append(attempt)
                        if preview["success"]:
                            viable.append({"scored": item, "attempt": attempt})
                            reserved.add(combo_key)
                            continue
                        attempted.add(combo_key)
                        entries = parse_failure(
                            preview.get("stderr", ""), preview.get("stdout", "")
                        )
                        learned = self._exact_constraints(entries, combo)
                        if learned:
                            inserted = self.graph.insert(learned)
                            learned_count += inserted
                            subbatch_learned += inserted
                        attempt["failures"] = entries
                    if subbatch_learned:
                        self.graph.infer_transitive()

                if not viable:
                    if domain_exhausted:
                        error = "当前及扩展版本域的候选已耗尽"
                        break
                    continue

                specs: list[InstallSpec] = []
                infos: list[EnvironmentInfo] = []
                for index, item in enumerate(viable):
                    attempted.add(tuple(sorted(item["scored"]["combination"].items())))
                    info = self.pool.create(
                        f"pacs-{run_id}-{rounds}-{index}", python_executable=python, backend=backend
                    )
                    created.add(info.env_id)
                    infos.append(info)
                    specs.append(InstallSpec(
                        env_id=info.env_id,
                        label=f"round-{rounds}-candidate-{index}",
                        packages=[*pip_args, *self._packages(item["scored"]["combination"])],
                    ))
                installed = install_for_environment(
                    self.pool, specs, timeout=timeout, max_workers=max_parallel
                )
                for item, info, install in zip(viable, infos, installed.results):
                    attempt = item["attempt"]
                    attempt.update({
                        "stage": "install",
                        "status": "ok" if install.success else ("cancelled" if install.cancelled else "failed"),
                        "environment_id": info.env_id, "log_path": install.log_path,
                        "sandbox": install.sandbox,
                    })
                    if install.cancelled:
                        continue
                    if not install.success:
                        entries = parse_failure(Path(install.log_path).read_text(encoding="utf-8")) if install.log_path else []
                        learned = self._exact_constraints(entries, item["scored"]["combination"])
                        if learned:
                            learned_count += self.graph.insert(learned)
                        attempt["failures"] = entries
                        continue
                    if winner is not None:
                        attempt["stage"] = "selection"
                        attempt["status"] = "not-selected"
                        continue
                    project_install = (
                        self._install_project(info, timeout)
                        if install_project else {"success": True, "installed": False, "detail": "skipped"}
                    )
                    attempt["project_install"] = project_install
                    if not project_install["success"]:
                        attempt["stage"] = "project-install"
                        attempt["status"] = "failed"
                        attempt["failures"] = parse_failure(project_install["detail"], "")
                        continue
                    verification = self._verify(info, validation_modules)
                    attempt["verification"] = verification
                    attempt["stage"] = "validation"
                    attempt["status"] = "ok" if verification["success"] else "failed"
                    if verification["success"] and winner is None:
                        winner = info
                        project_installed = bool(project_install["installed"])

                if any(item.get("failures") for item in attempts if item["round"] == rounds):
                    self.graph.infer_transitive()

            lock_path = run_dir / "requirements.lock"
            if winner:
                self._freeze(winner, lock_path)
            else:
                lock_path = None
                if not error:
                    error = f"在 {len(attempted)} 个候选中未找到可用环境"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            lock_path = None
        finally:
            for env_id in sorted(created):
                if winner is None or env_id != winner.env_id:
                    try:
                        self.pool.cleanup(env_id)
                    except Exception:
                        pass

        result: dict[str, Any] = {
            "success": winner is not None,
            "project_path": str(self.project),
            "environment_path": winner.path if winner else None,
            "environment_id": winner.env_id if winner else None,
            "lock_path": str(lock_path) if lock_path else None,
            "report_path": str(run_dir / "PACS_REPORT.md"),
            "result_path": str(run_dir / "result.json"),
            "solver": solver_name,
            "rounds": rounds,
            "attempted": len(attempted),
            "failed": sum(item["status"] == "failed" for item in attempts),
            "constraints_learned": learned_count,
            "project_installed": project_installed,
            "version_limit": version_limit,
            "version_expansions": version_expansions,
            "catalog_warnings": catalog_warnings,
            "attempts": attempts,
            "duration_seconds": time.monotonic() - started,
            "error": error,
        }
        self._write_report(run_dir / "PACS_REPORT.md", result)
        self._write_json(run_dir / "result.json", result)
        self.graph.close()
        return result

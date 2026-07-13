"""Adaptive end-to-end Python environment construction."""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from envpool import EnvironmentPool, parallel_install
from resolver import ConstraintGraph, VersionIndex, generate_combinations, parse_dependencies, parse_failure


@dataclass
class Attempt:
    round: int
    env_id: str
    candidate: dict[str, str]
    status: str
    returncode: int
    error_tail: str = ""


@dataclass
class BuildResult:
    success: bool
    project_path: str
    environment_path: str = ""
    lock_path: str = ""
    report_path: str = ""
    constraint_db: str = ""
    rounds: int = 0
    duration_seconds: float = 0
    attempts: list[Attempt] = field(default_factory=list)
    error: str = ""
    project_installed: bool = False

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


class PACSBuilder:
    def __init__(self, project_path: str | Path) -> None:
        self.project = Path(project_path).expanduser().resolve()
        if not self.project.is_dir():
            raise ValueError(f"项目目录不存在：{self.project}")
        self.state_dir = self.project / ".miniopenclaw" / "pacs"
        self.pool = EnvironmentPool(self.state_dir / "envs")
        self.graph = ConstraintGraph(self.state_dir / "constraint_graph.db")
        self.index = VersionIndex(self.state_dir / "version-index.json")

    @staticmethod
    def _pins(candidate: dict[str, str], deps: list[dict[str, str]], pip_args: list[str]) -> list[str]:
        markers = {dep["name"]: dep.get("marker", "") for dep in deps}
        requirements = []
        for name, version in candidate.items():
            requirement = f"{name} {version}" if version.startswith("@") else f"{name}=={version}"
            if markers.get(name):
                requirement += f"; {markers[name]}"
            requirements.append(requirement)
        return ["--disable-pip-version-check", *pip_args, *requirements]

    @staticmethod
    def _verify(env_path: str, modules: list[str]) -> tuple[bool, str]:
        python = Path(env_path) / ("Scripts/python.exe" if __import__("os").name == "nt" else "bin/python")
        check = subprocess.run([str(python), "-m", "pip", "check"], capture_output=True, text=True, timeout=60, check=False)
        if check.returncode != 0:
            return False, (check.stdout or check.stderr).strip()
        script = f"import importlib; [importlib.import_module(name) for name in {modules!r}]"
        imports = subprocess.run([str(python), "-c", script], capture_output=True, text=True, timeout=60, check=False)
        detail = "\n".join(part.strip() for part in (check.stdout, imports.stdout, imports.stderr) if part.strip())
        return imports.returncode == 0, detail

    @staticmethod
    def _freeze(env_path: str, lock_path: Path) -> None:
        python = Path(env_path) / ("Scripts/python.exe" if __import__("os").name == "nt" else "bin/python")
        proc = subprocess.run([str(python), "-m", "pip", "freeze"], capture_output=True, text=True, timeout=60, check=False)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "pip freeze 失败")
        lock_path.write_text(proc.stdout, encoding="utf-8")

    def _install_project(self, env_path: str, timeout: float) -> tuple[bool, str]:
        if not any((self.project / name).exists() for name in ("pyproject.toml", "setup.py", "setup.cfg")):
            return True, "no installable project metadata; dependencies-only project"
        python = Path(env_path) / ("Scripts/python.exe" if __import__("os").name == "nt" else "bin/python")
        proc = subprocess.run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", "-e", str(self.project)],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        return proc.returncode == 0, (proc.stdout or proc.stderr).strip()

    def _report(self, result: BuildResult, deps: list[dict[str, str]], catalog: dict[str, list[str]]) -> None:
        attempts = "\n".join(
            f"- Round {a.round} `{a.env_id}` **{a.status}**: "
            + ", ".join(f"{name}=={version}" for name, version in a.candidate.items())
            for a in result.attempts
        ) or "- 无候选"
        content = f"""# PACS 构建报告 — {self.project.name}

## 结果
- 状态：{'成功' if result.success else '失败'}
- Python 环境：{result.environment_path or '无'}
- 锁文件：{result.lock_path or '无'}
- 错误：{result.error or '无'}
- 项目本体已安装：{'是' if result.project_installed else '否'}

## 依赖元信息
- 直接依赖数：{len(deps)}
- 真实候选版本数：{sum(len(items) for items in catalog.values())}
- 约束图记录：{len(self.graph.all())}

## 搜索过程
- 总轮次：{result.rounds}
- 尝试组合数：{len(result.attempts)}
- 失败：{sum(a.status != 'ok' for a in result.attempts)}
- 成功：{sum(a.status == 'ok' for a in result.attempts)}
- 搜索时长：{result.duration_seconds:.3f} 秒

{attempts}

## 持久化
- 约束数据库：{result.constraint_db}
- 版本缓存：{self.index.cache_path}
"""
        Path(result.report_path).write_text(content, encoding="utf-8")

    def build(
        self,
        *,
        python_version: str = "",
        max_parallel: int = 2,
        max_attempts: int = 8,
        timeout: float = 180,
        version_catalog: dict[str, list[str]] | None = None,
        refresh_versions: bool = False,
        newest_first: bool = True,
        validation_modules: list[str] | None = None,
        pip_args: list[str] | None = None,
        install_project: bool = True,
    ) -> BuildResult:
        started = time.monotonic()
        report_path = self.project / "PACS_REPORT.md"
        result = BuildResult(
            False, str(self.project), report_path=str(report_path),
            constraint_db=str(self.graph.path),
        )
        deps = [dep.as_dict() for dep in parse_dependencies(self.project)]
        catalog: dict[str, list[str]] = version_catalog or self.index.catalog(deps, refresh_versions)
        missing = [dep["name"] for dep in deps if not catalog.get(dep["name"])]
        if missing:
            result.error = "没有满足约束的真实版本：" + ", ".join(missing)
            result.duration_seconds = time.monotonic() - started
            self._report(result, deps, catalog)
            return result

        attempted: set[tuple[tuple[str, str], ...]] = set()
        selected_env = ""
        pip_args = list(pip_args or [])
        modules = list(validation_modules or [])
        max_parallel = max(1, int(max_parallel))
        try:
            while len(attempted) < max_attempts and not selected_env:
                candidates = generate_combinations(
                    deps, self.graph.all(), max_candidates=max_attempts,
                    version_catalog=catalog, newest_first=newest_first,
                )
                candidates = [item for item in candidates if tuple(sorted(item.items())) not in attempted]
                batch = candidates[:min(max_parallel, max_attempts - len(attempted))]
                if not batch:
                    break
                result.rounds += 1
                envs = [self.pool.create(python_version or None, f"r{result.rounds}-c{index + 1}") for index in range(len(batch))]
                installs = parallel_install(
                    envs, [self._pins(candidate, deps, pip_args) for candidate in batch], timeout, max_parallel,
                )
                keep: str | None = None
                for candidate, env, install in zip(batch, envs, installs):
                    attempted.add(tuple(sorted(candidate.items())))
                    status = install.status
                    error_tail = (install.stderr or install.stdout)[-3000:]
                    if status == "ok":
                        installed, project_detail = self._install_project(env.path, timeout) if install_project else (True, "skipped")
                        if not installed:
                            status = "project_install_failed"
                            error_tail = project_detail[-3000:]
                        verified, detail = self._verify(env.path, modules) if installed else (False, project_detail)
                        if verified and keep is None:
                            keep = env.id
                            selected_env = env.path
                            status = "ok"
                            result.project_installed = install_project and any(
                                (self.project / name).exists() for name in ("pyproject.toml", "setup.py", "setup.cfg")
                            )
                        elif not verified:
                            status = "verify_failed"
                            error_tail = detail[-3000:]
                    if status != "ok":
                        constraints = parse_failure(error_tail, candidate)
                        self.graph.add(constraints)
                    result.attempts.append(Attempt(result.rounds, env.id, candidate, status, install.returncode, error_tail))
                self.graph.infer()
                for env in envs:
                    if env.id != keep:
                        self.pool.cleanup(env.id)
            if selected_env:
                lock_path = self.project / "requirements.lock"
                self._freeze(selected_env, lock_path)
                result.success = True
                result.environment_path = selected_env
                result.lock_path = str(lock_path)
            else:
                result.error = f"在 {len(attempted)} 个真实候选中未找到可用组合"
        except Exception as exc:
            result.error = str(exc)
            for env in self.pool.list():
                if env.path != selected_env:
                    self.pool.cleanup(env.id)
        result.duration_seconds = time.monotonic() - started
        self._report(result, deps, catalog)
        return result

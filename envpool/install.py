"""Concurrent pip installation across isolated environments."""
from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from typing import Sequence

from .manager import Env


@dataclass
class InstallResult:
    env_id: str
    status: str
    stdout: str
    stderr: str
    returncode: int

    def as_dict(self) -> dict[str, str | int]:
        return asdict(self)


def _install_one(env: Env, packages: Sequence[str], timeout: float) -> InstallResult:
    command = [str(env.python), "-m", "pip", "install", *map(str, packages)]
    env.status = "running"
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        status = "ok" if proc.returncode == 0 else "fail"
        env.status = "idle" if status == "ok" else "failed"
        env.error = "" if status == "ok" else proc.stderr[-2000:]
        return InstallResult(env.id, status, proc.stdout, proc.stderr, proc.returncode)
    except subprocess.TimeoutExpired as exc:
        env.status = "failed"
        env.error = f"timeout after {timeout}s"
        return InstallResult(
            env.id,
            "timeout",
            (exc.stdout or "") if isinstance(exc.stdout, str) else "",
            (exc.stderr or "") if isinstance(exc.stderr, str) else env.error,
            -1,
        )
    except Exception as exc:
        env.status = "failed"
        env.error = str(exc)
        return InstallResult(env.id, "fail", "", str(exc), -1)


def parallel_install(
    envs: Sequence[Env],
    package_sets: Sequence[Sequence[str]],
    timeout: float = 120,
    max_workers: int | None = None,
) -> list[InstallResult]:
    if len(envs) != len(package_sets):
        raise ValueError("envs 与 package_sets 数量必须一致")
    if not envs:
        return []
    workers = max(1, min(max_workers or len(envs), len(envs)))
    indexed: dict[object, int] = {}
    results: list[InstallResult | None] = [None] * len(envs)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pacs-pip") as executor:
        for index, (env, packages) in enumerate(zip(envs, package_sets)):
            indexed[executor.submit(_install_one, env, packages, timeout)] = index
        for future in as_completed(indexed):
            results[indexed[future]] = future.result()
    return [result for result in results if result is not None]

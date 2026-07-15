"""Pluggable environment backends: venv (default) and conda (system-dep remediation).

Phase 3: When a failure parser classifies an error as ``system_dep_missing``
and conda/mamba is available on PATH, the skill retries the affected package
via the Conda backend, which bundles native system libraries inside the conda
environment.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


# -- interface ----------------------------------------------------------------

class EnvBackend:
    """Minimal contract for creating and querying isolated Python environments."""

    name: str  # "venv" | "conda"

    def probe(self) -> bool:  # pragma: no cover
        raise NotImplementedError

    def create(
        self, path: Path, python_version: str | None, *, timeout: float = 120
    ) -> None:  # pragma: no cover
        raise NotImplementedError

    def python_path(self, env_path: Path) -> Path:  # pragma: no cover
        raise NotImplementedError

    def pip_path(self, env_path: Path) -> Path:  # pragma: no cover
        raise NotImplementedError


# -- venv ---------------------------------------------------------------------

class VenvBackend(EnvBackend):
    name = "venv"

    @staticmethod
    def probe() -> bool:
        return True  # stdlib, always available

    @staticmethod
    def create(
        path: Path,
        python_version: str | None,
        *,
        timeout: float = 120,
        executable: str | None = None,
    ) -> None:
        exe = executable or python_version or sys.executable
        subprocess.run(
            [exe, "-m", "venv", str(path)],
            cwd=str(path.parent),
            check=True, capture_output=True, text=True, timeout=timeout,
        )

    @staticmethod
    def python_path(env_path: Path) -> Path:
        return env_path / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

    @staticmethod
    def pip_path(env_path: Path) -> Path:
        return env_path / ("Scripts/pip.exe" if sys.platform == "win32" else "bin/pip")


# -- conda --------------------------------------------------------------------

def _conda_executable() -> str | None:
    """Return the fastest available conda-compatible command."""
    for cmd in ("mamba", "micromamba", "conda"):
        found = shutil.which(cmd)
        if found:
            return found
    return None


class CondaBackend(EnvBackend):
    name = "conda"

    @staticmethod
    def probe() -> bool:
        return _conda_executable() is not None

    @staticmethod
    def executable() -> str:
        exe = _conda_executable()
        if not exe:
            raise RuntimeError("conda/mamba 不可用；无法创建 conda 环境")
        return exe

    @classmethod
    def create(
        cls,
        path: Path,
        python_version: str | None,
        *,
        timeout: float = 180,
    ) -> None:
        exe = cls.executable()
        argv = [exe, "create", "-p", str(path), "-y", "-q"]
        if python_version:
            argv.append(f"python={python_version}")
        subprocess.run(
            argv, cwd=str(path.parent),
            check=True, capture_output=True, text=True, timeout=timeout,
        )

    @staticmethod
    def python_path(env_path: Path) -> Path:
        base = env_path / "bin" / "python"
        if not base.is_file() and sys.platform == "win32":
            base = env_path / "python.exe"
        return base

    @staticmethod
    def pip_path(env_path: Path) -> Path:
        base = env_path / "bin" / "pip"
        if not base.is_file() and sys.platform == "win32":
            base = env_path / "Scripts" / "pip.exe"
        return base

    @classmethod
    def install(
        cls,
        env_path: Path,
        packages: list[str],
        *,
        timeout: float = 300,
    ) -> subprocess.CompletedProcess[str]:
        """Install packages with conda/mamba; pip fallback for conda-only deps."""
        exe = cls.executable()
        return subprocess.run(
            [exe, "install", "-p", str(env_path), "-y", "-q", *packages],
            cwd=str(env_path.parent),
            capture_output=True, text=True, timeout=timeout,
        )


# -- backend resolution -------------------------------------------------------

_BACKENDS: dict[str, EnvBackend] = {
    "venv": VenvBackend,
    "conda": CondaBackend,
}


def resolve_backend(name: str | None = None) -> tuple[EnvBackend, str]:
    """Return ``(backend_class, effective_name)``, falling back to venv."""
    if name and name in _BACKENDS:
        return _BACKENDS[name], name
    if name:
        # unknown backend requested — warn and use venv
        import warnings
        warnings.warn(f"未知环境后端 {name!r}，回退到 venv", RuntimeWarning, stacklevel=2)
    return VenvBackend, "venv"


def available_backends() -> list[dict[str, Any]]:
    """Describe backends installed on this machine for SKILL recon."""
    result: list[dict[str, Any]] = []
    for name, backend_cls in _BACKENDS.items():
        result.append({
            "name": name,
            "available": backend_cls.probe(),
            "executable": _conda_executable() if name == "conda" else sys.executable,
        })
    return result

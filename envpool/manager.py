"""Virtual-environment lifecycle management for PACS."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Env:
    id: str
    path: str
    status: str = "idle"
    label: str = ""
    python_version: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)

    @property
    def python(self) -> Path:
        root = Path(self.path)
        return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


class EnvironmentPool:
    """Create and track isolated venvs under a dedicated local directory."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        configured = os.environ.get("MINIOPENCLAW_ENVPOOL_DIR")
        self.base_dir = Path(base_dir or configured or ".miniopenclaw/envs").expanduser().resolve()
        self._envs: dict[str, Env] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _python_command(version: str | None) -> str:
        requested = (version or "").strip()
        current = f"{sys.version_info.major}.{sys.version_info.minor}"
        candidates = [sys.executable] if not requested or requested == current else [f"python{requested}"]
        for candidate in candidates:
            found = shutil.which(candidate)
            if found:
                return found
        raise ValueError(f"找不到 Python {requested or current} 解释器")

    def create(self, python_version: str | None = None, label: str = "") -> Env:
        executable = self._python_command(python_version)
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-")[:40]
        env_id = f"env-{uuid.uuid4().hex[:8]}"
        dirname = f"{env_id}-{safe_label}" if safe_label else env_id
        path = self.base_dir / dirname
        self.base_dir.mkdir(parents=True, exist_ok=True)
        env = Env(env_id, str(path), "creating", label, python_version or "current")
        with self._lock:
            self._envs[env_id] = env
        try:
            proc = subprocess.run(
                [executable, "-m", "venv", str(path)],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "venv 创建失败")
            env.status = "idle"
        except Exception as exc:
            env.status = "failed"
            env.error = str(exc)
            shutil.rmtree(path, ignore_errors=True)
            raise RuntimeError(f"创建环境 {env_id} 失败：{exc}") from exc
        return env

    def get(self, env_id: str) -> Env | None:
        with self._lock:
            return self._envs.get(env_id)

    def list(self) -> list[Env]:
        with self._lock:
            return list(self._envs.values())

    def set_status(self, env_id: str, status: str, error: str = "") -> None:
        with self._lock:
            env = self._envs.get(env_id)
            if env:
                env.status = status
                env.error = error

    def cleanup(self, env_id: str | None = None) -> list[str]:
        with self._lock:
            targets = [self._envs[env_id]] if env_id and env_id in self._envs else []
            if env_id is None:
                targets = list(self._envs.values())
            if env_id and not targets:
                raise KeyError(f"未知环境：{env_id}")
        removed: list[str] = []
        for env in targets:
            shutil.rmtree(env.path, ignore_errors=True)
            with self._lock:
                self._envs.pop(env.id, None)
            removed.append(env.id)
        if self.base_dir.exists() and not any(self.base_dir.iterdir()):
            self.base_dir.rmdir()
        return removed

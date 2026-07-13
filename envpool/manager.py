"""Restart-safe management of isolated Python virtual environments."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_ENV_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_SEMANTIC_PYTHON_RE = re.compile(r"^(\d+)\.(\d+)$")
_PYTHON_COMMAND_RE = re.compile(r"^python(\d+)\.(\d+)$")


@dataclass(frozen=True)
class EnvironmentInfo:
    env_id: str
    label: str
    path: str
    python: str
    requested_python: str | None
    created_at: str
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EnvironmentPool:
    """Create and discover venvs below ``<workdir>/.miniopenclaw_envs``.

    Manifests are the source of truth.  Every status/list operation scans disk,
    so a newly constructed manager sees environments made by an earlier process.
    """

    def __init__(self, workdir: str | Path) -> None:
        self.workdir = Path(workdir).expanduser().resolve()
        # Keep the lexical path until after the symlink check. Resolving here
        # would follow a pre-existing `.miniopenclaw_envs` symlink and silently
        # turn an out-of-workdir target into the trusted root.
        self.root = self.workdir / ".miniopenclaw_envs"

    def _ensure_root(self) -> None:
        if self.root.is_symlink():
            raise ValueError(f"环境池根目录不能是符号链接: {self.root}")
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.resolve().parent != self.workdir:
            raise ValueError(f"环境池根目录不安全: {self.root}")

    def _path_for(self, env_id: str) -> Path:
        if not isinstance(env_id, str) or not _ENV_ID_RE.fullmatch(env_id):
            raise ValueError(f"非法 env_id: {env_id!r}")
        path = self.root / env_id
        # lexical validation is required even before the path exists
        if path.parent != self.root:
            raise ValueError("环境路径越过环境池根目录")
        if path.exists() and (path.is_symlink() or not path.resolve().is_relative_to(self.root)):
            raise ValueError("环境路径越过环境池根目录")
        return path

    @staticmethod
    def _requested_version(requested: str) -> tuple[int, int] | None:
        """Return a semantic major/minor request from accepted request forms."""
        match = _SEMANTIC_PYTHON_RE.fullmatch(requested)
        if match is None:
            match = _PYTHON_COMMAND_RE.fullmatch(Path(requested).name)
        return (int(match.group(1)), int(match.group(2))) if match else None

    @staticmethod
    def _interpreter_version(executable: str) -> tuple[int, int] | None:
        """Ask an interpreter for its version without relying on its filename."""
        try:
            result = subprocess.run(
                [executable, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        match = _SEMANTIC_PYTHON_RE.fullmatch(result.stdout.strip())
        return (int(match.group(1)), int(match.group(2))) if match else None

    @classmethod
    def _find_python(cls, requested: str | None) -> tuple[str, str | None]:
        """Resolve an executable and verify any requested semantic version.

        A bare ``3.10`` maps to ``python3.10``. An absolute request is accepted
        only for an executable regular file rather than being searched via PATH.
        """
        if not requested:
            return sys.executable, None
        if not isinstance(requested, str) or not requested.strip():
            raise ValueError("python_executable 必须是非空字符串")
        requested = requested.strip()
        expected = cls._requested_version(requested)
        path_request = Path(requested).expanduser()
        if path_request.is_absolute():
            resolved = path_request.resolve(strict=False)
            candidate = str(resolved) if resolved.is_file() and os.access(resolved, os.X_OK) else None
        elif expected is not None and _SEMANTIC_PYTHON_RE.fullmatch(requested):
            candidate = shutil.which(f"python{requested}")
        else:
            candidate = shutil.which(requested)

        if candidate:
            selected = str(Path(candidate).resolve())
            actual = cls._interpreter_version(selected)
            if actual is not None and (expected is None or actual == expected):
                return selected, None
            detail = "无法读取其版本" if actual is None else f"实际版本为 {actual[0]}.{actual[1]}"
        else:
            detail = "未找到可执行文件"
        requested_detail = (
            f"兼容 Python {expected[0]}.{expected[1]}" if expected is not None else repr(requested)
        )
        message = f"未找到请求的 {requested_detail}（{detail}），回退到当前解释器 {sys.executable}"
        warnings.warn(message, RuntimeWarning, stacklevel=3)
        return sys.executable, message

    def create(
        self,
        label: str,
        env_id: str | None = None,
        python_executable: str | None = None,
        timeout: float = 120.0,
    ) -> EnvironmentInfo:
        """Create one venv and atomically publish its ``env.json`` manifest."""
        if not isinstance(label, str) or not label.strip():
            raise ValueError("label 不能为空")
        self._ensure_root()
        chosen_id = env_id or f"env-{uuid.uuid4().hex[:12]}"
        path = self._path_for(chosen_id)
        if path.exists():
            raise FileExistsError(f"环境已存在: {chosen_id}")
        executable, warning = self._find_python(python_executable)
        try:
            subprocess.run(
                [executable, "-m", "venv", str(path)],
                cwd=str(self.workdir),
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            info = EnvironmentInfo(
                env_id=chosen_id,
                label=label.strip(),
                path=str(path),
                python=str(self.python_path(path)),
                requested_python=python_executable,
                created_at=datetime.now(timezone.utc).isoformat(),
                warning=warning,
            )
            manifest = path / "env.json"
            temporary = path / ".env.json.tmp"
            temporary.write_text(
                json.dumps(info.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            temporary.replace(manifest)
            return info
        except BaseException:
            if path.exists() and path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            raise

    @staticmethod
    def python_path(env_path: str | Path) -> Path:
        path = Path(env_path)
        return path / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

    def _read_manifest(self, directory: Path) -> EnvironmentInfo | None:
        if directory.is_symlink() or not directory.is_dir():
            return None
        resolved = directory.resolve()
        if not resolved.is_relative_to(self.root) or resolved.parent != self.root:
            return None
        manifest = directory / "env.json"
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data.get("env_id") != directory.name:
                return None
            if Path(data.get("path", "")).resolve() != resolved:
                return None
            return EnvironmentInfo(**data)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def list(self) -> list[EnvironmentInfo]:
        """Scan valid manifests below the pool root, ignoring malformed entries."""
        if not self.root.exists():
            return []
        if self.root.is_symlink() or self.root.resolve() != self.root:
            raise ValueError(f"环境池根目录不安全: {self.root}")
        found = [self._read_manifest(path) for path in self.root.iterdir()]
        return sorted((item for item in found if item is not None), key=lambda item: item.env_id)

    def status(self, env_id: str | None = None) -> EnvironmentInfo | list[EnvironmentInfo] | None:
        if env_id is None:
            return self.list()
        path = self._path_for(env_id)
        return self._read_manifest(path) if path.exists() else None

    def cleanup(self, env_id: str | None = None) -> list[str]:
        """Delete one or all manifest-backed environments, never arbitrary paths."""
        self._ensure_root()
        targets = [self.status(env_id)] if env_id is not None else self.list()
        removed: list[str] = []
        for info in targets:
            if info is None or isinstance(info, list):
                continue
            path = self._path_for(info.env_id)
            if path.resolve() != Path(info.path).resolve() or path.parent != self.root:
                raise ValueError("清理目标不属于环境池")
            shutil.rmtree(path)
            removed.append(info.env_id)
        return removed

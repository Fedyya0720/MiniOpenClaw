"""Build argv-only installer commands with best-effort OS sandboxing."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True)
class ResourceLimits:
    cpu_seconds: int = 300
    memory_bytes: int = 2 * 1024 * 1024 * 1024
    file_bytes: int = 512 * 1024 * 1024
    processes: int = 128


@dataclass(frozen=True)
class SandboxDescriptor:
    argv: list[str]
    kind: str
    filesystem_isolated: bool
    network_enabled: bool
    writable_paths: list[str]
    readable_paths: list[str]
    warning: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resource_runner_command(
    command: Sequence[str], limits: ResourceLimits | None = None
) -> list[str]:
    """Run an installer through the trusted rlimit launcher without a pre-exec hook."""
    if isinstance(command, (str, bytes)) or not command:
        raise ValueError("command 必须是非空 argv 列表，不能是 shell 字符串")
    selected = limits or ResourceLimits()
    argv = [os.fspath(part) for part in command]
    if any("\x00" in part for part in argv):
        raise ValueError("argv 包含 NUL 字节")
    runner = Path(__file__).with_name("resource_runner.py").resolve()
    return [
        sys.executable,
        str(runner),
        "--limits-json",
        json.dumps(asdict(selected), separators=(",", ":")),
        "--",
        *argv,
    ]


@lru_cache(maxsize=8)
def probe_bwrap(executable: str) -> tuple[bool, str | None]:
    """Check whether bubblewrap can create the namespaces used by installs.

    Presence on PATH is insufficient in nested containers: user namespaces may
    be disabled even though `/usr/bin/bwrap` exists. Probe once per executable
    before running package code so fallback is chosen deliberately, never after
    a partially executed install.
    """
    try:
        completed = subprocess.run(
            [
                executable,
                "--die-with-parent",
                "--ro-bind", "/", "/",
                "--proc", "/proc",
                "--dev", "/dev",
                "--", "/bin/true",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"bubblewrap capability probe failed: {exc}"
    if completed.returncode == 0:
        return True, None
    detail = (completed.stderr or completed.stdout or "unknown error").strip()
    return False, f"bubblewrap unavailable at runtime: {detail[:300]}"


def _resolve_bwrap(candidate: str | None) -> tuple[str | None, str | None]:
    executable = candidate if candidate is not None else shutil.which("bwrap")
    if not executable:
        return None, "bubblewrap executable not found"
    usable, warning = probe_bwrap(executable)
    return (executable, None) if usable else (None, warning)


def build_sandbox(
    command: Sequence[str],
    env_path: str | Path,
    workdir: str | Path,
    *,
    bwrap_executable: str | None = None,
) -> SandboxDescriptor:
    """Wrap an argv command in bubblewrap when available.

    The host root is read-only, the selected venv is writable, and the project
    workdir remains readable so local wheel/source installs work.  Network is
    intentionally left enabled for package indexes.  Without bwrap only rlimits
    remain; the descriptor explicitly reports that no filesystem isolation exists.
    """
    if isinstance(command, (str, bytes)) or not command:
        raise ValueError("command 必须是非空 argv 列表，不能是 shell 字符串")
    argv = [os.fspath(part) for part in command]
    if any("\x00" in part for part in argv):
        raise ValueError("argv 包含 NUL 字节")
    venv = Path(env_path).expanduser().resolve()
    project = Path(workdir).expanduser().resolve()
    bwrap, probe_warning = _resolve_bwrap(bwrap_executable)
    if bwrap:
        wrapped = [
            bwrap,
            "--die-with-parent",
            "--ro-bind", "/", "/",
            "--ro-bind", str(project), str(project),
            "--bind", str(venv), str(venv),
            "--proc", "/proc",
            "--dev", "/dev",
            "--chdir", str(project),
            "--",
            *argv,
        ]
        return SandboxDescriptor(
            argv=wrapped,
            kind="bubblewrap",
            filesystem_isolated=True,
            network_enabled=True,
            writable_paths=[str(venv)],
            readable_paths=["/", str(project)],
            warning=None,
        )
    if os.getenv("MINIOPENCLAW_REQUIRE_PIP_SANDBOX") == "1":
        raise RuntimeError(
            "pip sandbox is required but bubblewrap is unavailable: "
            + (probe_warning or "unknown reason")
        )
    return SandboxDescriptor(
        argv=argv,
        kind="rlimits-only",
        filesystem_isolated=False,
        network_enabled=True,
        writable_paths=[],
        readable_paths=[],
        warning=(probe_warning or "bubblewrap 不可用") + "；仅启用资源限制，不提供文件系统隔离",
    )


def pip_command(env_path: str | Path, packages: Sequence[str]) -> list[str]:
    """Construct pip's argv without invoking a shell."""
    if isinstance(packages, (str, bytes)) or not packages:
        raise ValueError("packages 必须是非空列表")
    env = Path(env_path).expanduser().resolve()
    python = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return [str(python), "-m", "pip", "install", *[str(item) for item in packages]]

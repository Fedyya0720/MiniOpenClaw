"""Use pip's resolver as an authoritative full-dependency preflight."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from envpool.install import _validate_install_arguments


def preflight(
    packages: Sequence[str],
    *,
    workdir: str | Path,
    pip_args: Sequence[str] = (),
    timeout: float = 120.0,
) -> dict[str, Any]:
    args = [str(item) for item in pip_args]
    pins = [str(item) for item in packages]
    _validate_install_arguments([*args, *pins])
    state = Path(workdir).expanduser().resolve() / ".mini-openclaw" / "pacs-preflight"
    state.mkdir(parents=True, exist_ok=True)
    cache = state.parent / "pip-cache"
    home = state.parent / "pip-home"
    temporary = state.parent / "pip-tmp"
    for directory in (cache, home, temporary):
        directory.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update({
        "HOME": str(home),
        "PIP_CACHE_DIR": str(cache),
        "PYTHONNOUSERSITE": "1",
        "TMPDIR": str(temporary),
    })
    with tempfile.NamedTemporaryFile(prefix="report-", suffix=".json", dir=state, delete=False) as handle:
        report_path = Path(handle.name)
    command = [
        sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed",
        "--disable-pip-version-check", "--report", str(report_path), *args, *pins,
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(Path(workdir).resolve()),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            env=environment,
        )
        try:
            report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.stat().st_size else {}
        except (OSError, ValueError, json.JSONDecodeError):
            report = {}
        installs = []
        for item in report.get("install", []):
            metadata = item.get("metadata", {})
            installs.append({"name": metadata.get("name", ""), "version": metadata.get("version", "")})
        return {
            "success": completed.returncode == 0,
            "returncode": completed.returncode,
            "command": command,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
            "resolved": installs,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "success": False,
            "returncode": None,
            "command": command,
            "stdout": exc.stdout[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr": exc.stderr[-4000:] if isinstance(exc.stderr, str) else "",
            "resolved": [],
            "timed_out": True,
        }
    finally:
        report_path.unlink(missing_ok=True)

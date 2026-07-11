"""受控 shell 执行（Day5：bash；Day10：加沙箱与权限）。"""
from __future__ import annotations
import os
import shutil
import subprocess
from .base import Tool
from .security import check_bash_sandbox


def _bash(command: str, timeout: int = 30) -> str:
    """Execute a shell command with timeout protection and sandbox checks.

    Uses subprocess.run() with shell=True for flexibility.
    Captures stdout, stderr, and return code.

    Day10 sandbox: blocks dangerous commands, warns on write operations
    outside the current working directory.
    """
    # Day10: sandbox check (delegates to tools/security.py)
    danger = check_bash_sandbox(command)
    if danger:
        return danger

    try:
        workdir = os.path.realpath(os.getcwd())
        bwrap = shutil.which("bwrap")
        if bwrap:
            cmd = [
                bwrap,
                "--ro-bind", "/", "/",
                "--bind", workdir, workdir,
                "--chdir", workdir,
                "--unshare-net",
                "--dev", "/dev",
                "--proc", "/proc",
                "bash", "-c", command,
            ]
            result = subprocess.run(
                cmd, shell=False, capture_output=True, text=True,
                timeout=timeout, cwd=workdir,
            )
        else:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=timeout, cwd=workdir,
            )
    except subprocess.TimeoutExpired:
        return f"错误：命令超时（{timeout}s）"

    parts = []
    if result.stdout:
        parts.append(result.stdout.rstrip())
    if result.stderr:
        parts.append(f"[stderr]\n{result.stderr.rstrip()}")
    parts.append(f"[returncode: {result.returncode}]")
    return "\n".join(parts)


bash_tool = Tool(
    name="bash",
    description="在工作目录中执行一条 shell 命令并返回输出。",
    parameters={"type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"]},
    run=_bash,
)

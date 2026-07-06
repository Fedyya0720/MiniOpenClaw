"""受控 shell 执行（Day5：bash；Day10：加沙箱与权限）。"""
from __future__ import annotations
import subprocess
from .base import Tool


def _bash(command: str, timeout: int = 30) -> str:
    """Execute a shell command with timeout protection.

    Uses subprocess.run() with shell=True for flexibility.
    Captures stdout, stderr, and return code.

    NOTE[Day10]: A sandbox/permission layer will wrap this for
    working-directory restriction and dangerous-command detection.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=subprocess.os.getcwd(),
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

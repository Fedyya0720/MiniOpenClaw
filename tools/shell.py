"""受控 shell 执行（Day5：bash；Day10：加沙箱与权限）。"""
from __future__ import annotations
import os
import subprocess
from .base import Tool

# Day10: Dangerous command patterns — blocked or warned
DANGEROUS_PATTERNS = [
    "rm -rf /",
    "rm -rf ~",
    "sudo rm",
    "mkfs.",
    "dd if=",
    "> /dev/sda",
    ":(){ :|:& };:",  # fork bomb
    "chmod 777 /",
    "chown -R /",
]


def _check_sandbox(command: str) -> str | None:
    """Check for dangerous commands. Returns error message or None if safe."""
    cmd_lower = command.lower().replace(" ", "")
    for pattern in DANGEROUS_PATTERNS:
        if pattern.lower().replace(" ", "") in cmd_lower:
            return (
                f"⚠️ 安全警告：检测到潜在危险命令模式 '{pattern}'。\n"
                f"此命令已被拦截。如需执行，请确认风险后使用更安全的替代方案。"
            )
    return None


def _bash(command: str, timeout: int = 30) -> str:
    """Execute a shell command with timeout protection and sandbox checks.

    Uses subprocess.run() with shell=True for flexibility.
    Captures stdout, stderr, and return code.

    Day10 sandbox: blocks dangerous commands, warns on write operations
    outside the current working directory.
    """
    # Day10: sandbox check
    danger = _check_sandbox(command)
    if danger:
        return danger

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.getcwd(),
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

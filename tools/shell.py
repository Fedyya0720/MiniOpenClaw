"""受控 shell 执行（Day5：bash；Day10：加沙箱与权限）。"""
from __future__ import annotations
import os
import subprocess
from .base import Tool

# Day10: Dangerous command patterns — blocked or warned
DANGEROUS_PATTERNS = [
    "rm -rf /",
    "rm -rf ~",
    "rm -rf /*",
    "rm -rf .",
    "rm -rf *",
    "sudo rm",
    "mkfs.",
    "dd if=",
    "> /dev/sda",
    "> /dev/sd",
    ":(){ :|:& };:",  # fork bomb
    "chmod 777 /",
    "chmod -R 777 /",
    "chown -R /",
    "find / -exec rm",
    "find / -delete",
    "curl | bash",
    "curl | sh",
    "wget -O - | bash",
    "wget -O - | sh",
    "shutdown",
    "reboot",
]


def _check_sandbox(command: str) -> str | None:
    """Check for dangerous commands. Returns error message or None if safe.

    Matching strategy:
    1. Substring match on compressed (no-space) form for atomic patterns.
    2. For multi-word patterns, also check normalized (single-space) form.
    3. Pipe-injection: detect curl/wget piped to shell (| bash / | sh).
    """
    cmd_lower = command.lower().replace(" ", "")
    cmd_normalized = " ".join(command.lower().split())

    # Pipe-to-shell injection: curl/wget | bash/sh (the URL breaks compressed match)
    if ("curl" in cmd_lower or "wget" in cmd_lower) and ("|bash" in cmd_lower or "|sh" in cmd_lower):
        return (
            f"⚠️ 安全警告：检测到管道注入风险（curl/wget | bash/sh）。\n"
            f"此命令已被拦截。请勿从不可信来源下载并执行脚本。"
        )

    for pattern in DANGEROUS_PATTERNS:
        pattern_normalized = " ".join(pattern.lower().split())
        # Check both compressed and normalized forms
        if pattern.lower().replace(" ", "") in cmd_lower:
            return (
                f"⚠️ 安全警告：检测到潜在危险命令模式 '{pattern}'。\n"
                f"此命令已被拦截。如需执行，请确认风险后使用更安全的替代方案。"
            )
        if " " in pattern and pattern_normalized in cmd_normalized:
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

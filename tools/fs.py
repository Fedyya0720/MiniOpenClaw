"""文件读写工具（Day5：read / write；Day10：路径沙箱）。"""
from __future__ import annotations
import os
from pathlib import Path as _Path
from .base import Tool

# Day10: Working directory confinement for write operations.
# All write paths are resolved relative to this directory and blocked if they escape.
_WRITE_ROOT = os.path.realpath(os.getcwd())


def _read(path: str, max_bytes: int = 100_000) -> str:
    """Read a file and return its content with line numbers.

    Opens the file in binary mode to control byte-level truncation,
    decodes as UTF-8, and prefixes each line with a 6-digit padded
    line number.

    Args:
        path: File path to read.
        max_bytes: Maximum bytes to return before truncating.

    Returns:
        Content string with line numbers prepended.

    Raises:
        FileNotFoundError: If the file does not exist (not caught).
    """
    original_size = os.path.getsize(path)

    with open(path, "rb") as f:
        raw = f.read(max_bytes + 1)

    is_truncated = len(raw) > max_bytes
    if is_truncated:
        raw = raw[:max_bytes]

    # Decode as UTF-8.  If truncation split a multi-byte character,
    # trim the incomplete bytes at the end.
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        if is_truncated and e.start is not None:
            text = raw[: e.start].decode("utf-8")
        else:
            return f"Error reading file: cannot decode as UTF-8. {e}"

    # Add line numbers: 6-digit right-aligned.
    # splitlines() correctly handles trailing newlines (no extra blank
    # entry) and returns [] for empty input.
    lines = text.splitlines()
    if not lines:
        return ""
    result = "\n".join(f"{i + 1:>6}> {line}" for i, line in enumerate(lines))

    if is_truncated:
        result += f"\n...[truncated to {max_bytes} bytes, total {original_size} bytes]"

    return result


def _resolve_write_path(path: str) -> str | None:
    """Resolve a write path and check it stays within the working directory.

    Returns the resolved absolute path on success, or a blocking reason string
    if the path escapes the allowed root.

    Day10: permission/sandbox layer intercepts writes outside the working directory.
    """
    try:
        abs_path = os.path.realpath(os.path.join(_WRITE_ROOT, path))
    except (ValueError, OSError) as e:
        return f"错误：路径解析失败 — {e}"

    # Block writes that escape the working directory
    if not abs_path.startswith(_WRITE_ROOT + os.sep) and abs_path != _WRITE_ROOT:
        return (
            f"⚠️ 安全拦截：写入路径 '{abs_path}' 超出了工作目录 '{_WRITE_ROOT}'。\n"
            f"只允许在工作目录及其子目录内写入文件。"
        )

    # Block writes to hidden files/dirs that are system-critical
    parts = _Path(abs_path).relative_to(_WRITE_ROOT).parts
    for part in parts:
        if part in (".git", ".env", ".ssh", ".gnupg"):
            return f"⚠️ 安全拦截：禁止写入受保护的路径 '{part}'。"

    return abs_path


def _write(path: str, content: str) -> str:
    """Write content to a file, creating parent directories as needed.

    Overwrites existing files. Returns a confirmation message with
    the file path and byte count.

    Day10 sandbox: resolves paths relative to the working directory and
    blocks writes that attempt to escape it. System-protected paths
    (.git, .env, .ssh, .gnupg) are also blocked.
    """
    resolved = _resolve_write_path(path)
    if isinstance(resolved, str) and resolved.startswith("⚠️"):
        return resolved  # sandbox blocked the write

    path = resolved

    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    except (OSError, FileNotFoundError):
        pass  # dirname("") or root path — fall through to open()

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except (PermissionError, IsADirectoryError, OSError) as e:
        return f"Error writing file: {e}"

    return f"成功写入 {path}（{len(content.encode('utf-8'))} 字节）"


read_tool = Tool(
    name="read",
    description="读取指定路径的文本文件内容。",
    parameters={"type": "object",
                "properties": {"path": {"type": "string", "description": "文件路径"}},
                "required": ["path"]},
    run=_read,
)

write_tool = Tool(
    name="write",
    description="把内容写入指定路径（覆盖）。",
    parameters={"type": "object",
                "properties": {"path": {"type": "string"},
                               "content": {"type": "string"}},
                "required": ["path", "content"]},
    run=_write,
)

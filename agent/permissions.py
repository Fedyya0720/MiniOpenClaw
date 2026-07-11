"""Tool permission policy used by both CLI and TUI execution paths."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


READONLY = {"read", "grep", "glob"}
WRITE = {"write", "edit"}
EXEC = {"bash", "web_fetch"}

PROTECTED_PARTS = {".git", ".env", ".ssh", ".gnupg"}
SENSITIVE_NAMES = {
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "credentials", "credentials.json", "secrets.json",
}


@dataclass(frozen=True)
class Decision:
    verdict: str
    reason: str


def _resolved_path(raw: str, workdir: Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = workdir / path
    return path.resolve(strict=False)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_sensitive(path: Path) -> bool:
    return bool(PROTECTED_PARTS.intersection(path.parts)) or path.name.lower() in SENSITIVE_NAMES


def evaluate(tool: str, args: dict[str, Any], workdir: Path) -> Decision:
    """Return an allow/confirm/deny decision with a user-facing reason."""
    root = workdir.resolve()

    if tool in {"read", "grep"}:
        raw = str(args.get("path", "."))
        path = _resolved_path(raw, root)
        if _is_sensitive(path):
            return Decision("deny", f"禁止读取敏感路径：{path}")
        return Decision("allow", "只读工具自动放行")

    if tool == "glob":
        pattern = str(args.get("pattern", ""))
        if any(part in pattern for part in PROTECTED_PARTS):
            return Decision("deny", f"禁止搜索敏感路径模式：{pattern}")
        return Decision("allow", "只读工具自动放行")

    if tool in WRITE:
        raw = str(args.get("path", ""))
        if not raw:
            return Decision("deny", "写工具缺少 path 参数")
        path = _resolved_path(raw, root)
        if not _is_within(path, root):
            return Decision("deny", f"写入路径超出工作目录：{path}")
        if _is_sensitive(path):
            return Decision("deny", f"禁止写入受保护路径：{path}")
        return Decision("confirm", f"工具将写入工作目录：{path}")

    if tool in EXEC:
        return Decision("confirm", "执行或联网工具需要用户确认")

    return Decision("confirm", "未知或外部工具需要用户确认")


def check(tool: str, args: dict[str, Any], workdir: Path) -> str:
    """Compatibility helper matching the Day 6 allow/confirm/deny API."""
    return evaluate(tool, args, workdir).verdict


def permission_observation(
    tool: str,
    args: dict[str, Any],
    workdir: Path,
    *,
    auto_approve: bool = False,
    confirmer: Callable[[str, dict[str, Any], str], bool] | None = None,
) -> str | None:
    """Return a refusal observation, or None when execution is authorized."""
    decision = evaluate(tool, args, workdir)
    if decision.verdict == "deny":
        return f"[权限层] 拒绝：{decision.reason}"
    if decision.verdict == "allow" or auto_approve:
        return None
    if confirmer is not None and confirmer(tool, args, decision.reason):
        return None
    return f"[权限层] 需确认：{tool}({args})。{decision.reason}，本次未执行。"

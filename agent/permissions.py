"""Tool permission policy used by both CLI and TUI execution paths."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


READONLY = {"read", "grep", "glob", "skill"}
WRITE = {"write", "edit"}
EXEC = {"bash", "web_fetch"}

# Only resolver tools that do not accept filesystem locations are auto-allowed.
PACS_READONLY = {"parse_deps", "generate_combinations", "parse_failure", "infer_constraints"}
PACS_PATH_ARGUMENTS = {
    "parse_deps": "project_path",
    # parse_failure is currently compute-only, but reserve its log location
    # contract so adding it later cannot silently bypass workspace policy.
    "parse_failure": "log_path",
}
# PACS envpool tools create venvs + spawn pip subprocesses → treated like EXEC
# (auto-run under --auto-approve / MINIOPENCLAW_AUTO_APPROVE, confirm otherwise).
PACS_EXEC = {"env_create", "env_run", "env_status", "env_cleanup", "pacs_build"}

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

    if tool == "skill":
        return Decision("allow", "Skill 正文加载为只读操作")

    if tool in PACS_READONLY:
        path_arg = PACS_PATH_ARGUMENTS.get(tool)
        raw = args.get(path_arg) if path_arg else None
        if raw:
            path = _resolved_path(str(raw), root)
            if not _is_within(path, root):
                return Decision("deny", f"PACS 解析路径超出工作目录：{path}")
            if _is_sensitive(path):
                return Decision("deny", f"禁止读取敏感路径：{path}")
        return Decision("allow", "PACS 纯计算/受限解析工具自动放行")

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

    if tool in PACS_EXEC:
        if tool == "pacs_build":
            raw_project = args.get("project_path")
            if raw_project:
                project = _resolved_path(str(raw_project), root)
                if not _is_within(project, root):
                    return Decision("deny", f"PACS 项目路径超出工作目录：{project}")
                if _is_sensitive(project):
                    return Decision("deny", f"禁止 PACS 访问敏感路径：{project}")
        supplied_workdir = args.get("workdir")
        if supplied_workdir is not None:
            target = _resolved_path(str(supplied_workdir), root)
            if target != root:
                return Decision("deny", f"PACS 环境工具 workdir 必须等于当前工作目录：{root}")
        # envpool tools create venvs + spawn pip. They run in their own
        # venv-scoped sandbox (envpool/sandbox.py), not the bash bwrap.
        # Confirm by default; auto-approve under --auto-approve.
        return Decision("confirm", "PACS 环境池工具将创建 venv 并执行 pip 安装（venv 级沙箱内）")

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

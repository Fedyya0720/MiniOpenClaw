"""完整工具集：edit / grep / glob（Day6，→ v1）+ web_fetch / task_list（Day7）。

每个工具上午讲设计权衡，下午实现。这里只给签名与 TODO，便于你拆到独立文件。
建议最终拆成 edit.py / search.py / web.py / todo.py，再在 base.build_default_registry 注册。
"""
from __future__ import annotations
import subprocess
from pathlib import Path
from .base import Tool


# --- edit：search-replace（最稳策略）---
def _edit(path: str, old: str = "", new: str = "") -> str:
    """Replace `old` text with `new` in a file. Requires unique match."""
    try:
        content = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"错误：文件不存在 {path}"
    except Exception as e:
        return f"错误：无法读取文件 {path} — {e}"

    count = content.count(old)
    if count == 0:
        return f"错误：未找到要替换的文本（共 0 处匹配）"
    if count > 1:
        return f"错误：找到 {count} 处匹配，old 文本必须唯一。请使用更多上下文使其唯一。"

    new_content = content.replace(old, new, 1)
    try:
        Path(path).write_text(new_content, encoding="utf-8")
    except Exception as e:
        return f"错误：无法写入文件 {path} — {e}"

    return f"成功替换 {path}（1 处修改）"


# --- grep：基于 ripgrep ---
def _grep(pattern: str, path: str = ".") -> str:
    """Search files using ripgrep. Returns matches with filename:lineno:content."""
    try:
        result = subprocess.run(
            ["rg", "--line-number", "--no-heading", pattern, path],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        return "错误：未找到 ripgrep (rg)。请安装：apt install ripgrep 或 brew install ripgrep"
    except subprocess.TimeoutExpired:
        return "错误：grep 超时（30s）"

    if result.returncode == 1:
        return "未找到匹配项。"
    if result.returncode > 1:
        return f"rg 错误：{result.stderr.strip()}" if result.stderr else f"rg 退出码 {result.returncode}"

    output = result.stdout.rstrip()
    if not output:
        return "未找到匹配项。"
    # Truncate long output
    lines = output.split("\n")
    if len(lines) > 200:
        output = "\n".join(lines[:200]) + f"\n...[已截断，共 {len(lines)} 行匹配]"
    return output


# --- glob：按文件名模式找文件 ---
def _glob(pattern: str) -> str:
    """Find files matching a glob pattern using pathlib."""
    try:
        matches = list(Path(".").rglob(pattern))
    except Exception as e:
        return f"错误：glob 模式无效 — {e}"

    if not matches:
        return "未找到匹配的文件。"

    # Sort and truncate
    matches.sort()
    if len(matches) > 200:
        result = "\n".join(str(m) for m in matches[:200])
        result += f"\n...[已截断，共 {len(matches)} 个文件]"
        return result
    return "\n".join(str(m) for m in matches)


# --- web_fetch：URL -> markdown，控 token 预算 ---
def _web_fetch(url: str, max_tokens: int = 2000) -> str:
    # TODO[Day7] httpx 抓取 -> markdownify 转 markdown -> 截断到预算内
    raise NotImplementedError("Day7：实现 web_fetch")


# --- task_list（TodoWrite）：自维护待办，提升长任务成功率 ---
def _task_list(action: str, items: list | None = None) -> str:
    # TODO[Day7] 维护一个结构化待办（add/update/complete），作为模型的 scratchpad
    raise NotImplementedError("Day7：实现 task_list")


edit_tool = Tool("edit", "编辑文件：把 old 文本替换为 new。",
                 {"type": "object", "properties": {"path": {"type": "string"},
                  "old": {"type": "string"}, "new": {"type": "string"}},
                  "required": ["path", "old", "new"]}, _edit)
grep_tool = Tool("grep", "在文件中搜索匹配 pattern 的行（基于 ripgrep）。",
                 {"type": "object", "properties": {"pattern": {"type": "string"},
                  "path": {"type": "string"}}, "required": ["pattern"]}, _grep)
glob_tool = Tool("glob", "按通配模式查找文件路径。",
                 {"type": "object", "properties": {"pattern": {"type": "string"}},
                  "required": ["pattern"]}, _glob)
web_fetch_tool = Tool("web_fetch", "抓取 URL 并转为 markdown（受 token 预算限制）。",
                      {"type": "object", "properties": {"url": {"type": "string"}},
                       "required": ["url"]}, _web_fetch)
task_list_tool = Tool("task_list", "维护任务待办清单（add/update/complete）。",
                      {"type": "object", "properties": {"action": {"type": "string"},
                       "items": {"type": "array"}}, "required": ["action"]}, _task_list)

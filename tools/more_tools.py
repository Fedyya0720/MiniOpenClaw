"""完整工具集：edit / grep / glob（Day6，→ v1）+ web_fetch / task_list（Day7）。

每个工具上午讲设计权衡，下午实现。这里只给签名与 TODO，便于你拆到独立文件。
建议最终拆成 edit.py / search.py / web.py / todo.py，再在 base.build_default_registry 注册。
"""
from __future__ import annotations
import subprocess
from pathlib import Path
import json
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
# Day10: SSRF protection delegates to tools/security.py
from .security import is_internal_url


def _web_fetch(url: str, max_tokens: int = 2000) -> str:
    """Fetch a URL and convert to markdown, truncated to token budget.

    Day10: SSRF protection blocks requests to internal/private IP addresses.
    """
    # Day10: SSRF check (delegates to tools/security.py)
    if is_internal_url(url):
        return f"⚠️ 安全拦截：禁止访问内部地址 '{url}'（SSRF 防护）。"

    try:
        import httpx
    except ImportError:
        return "错误：需要 httpx 库。运行：pip install httpx"

    try:
        response = httpx.get(url, timeout=15.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.TimeoutException:
        return f"错误：请求超时 — {url}"
    except httpx.HTTPStatusError as e:
        return f"错误：HTTP {e.response.status_code} — {url}"
    except Exception as e:
        return f"错误：无法获取 {url} — {e}"

    # Try markdownify; fall back to plain text
    try:
        from markdownify import markdownify
        text = markdownify(response.text)
    except ImportError:
        text = response.text[:max_tokens * 4]  # rough char budget

    # Truncate to token budget (rough: chars/4)
    max_chars = max_tokens * 4
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n...[已截断，共 {len(text)} 字符]"

    return text


# --- task_list（TodoWrite）：自维护待办，提升长任务成功率 ---
_TASKS: list[dict] = []  # module-level task state

def _task_list(action: str, items: list | None = None) -> str:
    """Maintain a structured todo list (add/update/complete)."""
    action = action.strip().lower()

    if action == "add" and items:
        added = []
        for item in items:
            if isinstance(item, dict):
                item["_id"] = len(_TASKS) + 1
                _TASKS.append(item)
                added.append(f"  [{item['_id']}] {item.get('content', item.get('title', str(item)))}")
        return "已添加任务：\n" + "\n".join(added) if added else "未添加任何任务。"

    elif action == "update" and items:
        for update in items:
            tid = update.get("id")
            for t in _TASKS:
                if t["_id"] == tid:
                    t.update(update)
        return f"已更新 {len(items)} 个任务。"

    elif action == "complete" and items:
        ids = [i.get("id") for i in items if isinstance(i, dict)]
        remaining = [t for t in _TASKS if t["_id"] not in ids]
        completed = len(_TASKS) - len(remaining)
        _TASKS.clear()
        _TASKS.extend(remaining)
        return f"已完成 {completed} 个任务。剩余 {len(_TASKS)} 个。"

    elif action == "list" or action == "show":
        if not _TASKS:
            return "当前没有待办任务。"
        lines = ["当前待办："]
        for t in _TASKS:
            status = t.get("status", "pending")
            content = t.get("content", t.get("title", str(t)))
            lines.append(f"  [{t['_id']}] [{status}] {content}")
        return "\n".join(lines)

    else:
        return f"未知操作：{action}。支持：add, update, complete, list"


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

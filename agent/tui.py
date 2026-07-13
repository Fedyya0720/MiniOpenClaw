"""交互式 TUI（Day11）。

基于 Rich + prompt_toolkit 的 REPL 界面，提供：
  - 流式 token 显示（实时看到模型"思考"）
  - 彩色面板区分角色：用户 / 助手 / 工具调用 / 工具结果
  - 多轮对话历史（持久化到 ~/.mini_openclaw_history）
  - Ctrl+C 中断、/quit 退出

用法：
  python -m agent.cli --tui       # 启动交互模式
  python -m agent.cli -t          # 同上（短参数）

设计原则：
  - ReAct 循环逻辑在 agent/strategy.py 中统一实现。
  - TUI 只负责：流式后端包装、Rich 渲染回调、REPL 命令处理。
  - Rich Live 自带刷新线程，主线程同步迭代 SSE 即可，无需 async。
  - FakeBackend 无 chat_stream → 用 _fake_stream() 模拟逐字输出。
"""
from __future__ import annotations
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.completion import Completer, Completion, PathCompleter

from tools.base import ToolRegistry
from agent.context import resolve_token_budget
from agent.strategy import ReactCallbacks, run_react_turns
from agent.trace import ToolRunTrace


# ---------------------------------------------------------------------------
# 路径辅助
# ---------------------------------------------------------------------------

def _unescape_path(raw: str) -> str:
    """去掉 shell 风格反斜杠转义：\\  → （空格）等。"""
    return re.sub(r'\\(.)', r'\1', raw)


# ---------------------------------------------------------------------------
# /image 路径补全
# ---------------------------------------------------------------------------

class _ImagePathCompleter(Completer):
    """条件补全：仅当输入以 /image 开头时对后续路径做文件补全。"""

    def __init__(self) -> None:
        self._path_completer = PathCompleter(expanduser=True)

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        # 只在 /image 命令后激活
        if not text.lstrip().startswith("/image"):
            return
        # 拆出 /image 和后续路径部分
        m = re.match(r'\s*/image\s+(.*)', text)
        if m is None:
            return
        path_prefix = m.group(1)
        # 去掉 shell 转义的反斜杠再补全
        clean_prefix = _unescape_path(path_prefix)
        # 构造一个虚拟 document，只包含路径部分
        from prompt_toolkit.document import Document
        path_doc = Document(clean_prefix, len(clean_prefix))
        for comp in self._path_completer.get_completions(path_doc, complete_event):
            # 补全结果保持原样（prompt_toolkit 会替换光标前的文字）
            yield comp


# ---------------------------------------------------------------------------
# 终端宽度辅助
# ---------------------------------------------------------------------------

def _term_width() -> int:
    try:
        return os.get_terminal_size().columns
    except (ValueError, OSError):
        return 80


def _tool_name(tool: str) -> str:
    """给工具名加 emoji 前缀，方便一眼区分。"""
    ICONS = {
        "read": "📖",
        "write": "✏️",
        "bash": "⚡",
        "edit": "🔧",
        "grep": "🔍",
        "glob": "📁",
        "web_fetch": "🌐",
        "task_list": "📋",
    }
    icon = ICONS.get(tool, "🔨")
    return f"{icon} {tool}"


# ---------------------------------------------------------------------------
# DisplayManager
# ---------------------------------------------------------------------------

@dataclass
class DisplayManager:
    """管理 Rich 渲染：为不同角色产出彩色 Panel，并维护渲染历史。"""
    console: Console

    def render_user(self, text: str) -> Panel:
        return Panel(
            Text(text, style="white"),
            title="You",
            title_align="left",
            border_style="cyan",
            width=min(_term_width(), 120),
        )

    def render_assistant(self, text: str) -> Panel:
        return Panel(
            Text(text, style="white"),
            title="Assistant",
            title_align="left",
            border_style="green",
            width=min(_term_width(), 120),
        )

    def render_tool_call(self, name: str, args: dict[str, Any]) -> Panel:
        label = _tool_name(name)
        args_text = json.dumps(args, ensure_ascii=False, indent=2)
        return Panel(
            Text(args_text, style="bright_black"),
            title=label,
            title_align="left",
            border_style="yellow",
            width=min(_term_width(), 120),
        )

    def render_tool_result(self, name: str, result: str) -> Panel:
        label = _tool_name(name)
        # 截断过长结果，方便阅读
        if len(result) > 2000:
            result = result[:2000] + f"\n...[已截断，共 {len(result)} 字符]"
        return Panel(
            Text(result, style="bright_black"),
            title=f"Result: {label}",
            title_align="left",
            border_style="bright_black",
            width=min(_term_width(), 120),
        )

    def render_system(self, text: str) -> Panel:
        return Panel(
            Text(text, style="italic bright_black"),
            border_style="bright_black",
            width=min(_term_width(), 120),
        )

    def render_error(self, text: str) -> Panel:
        return Panel(
            Text(text, style="red"),
            title="Error",
            title_align="left",
            border_style="red",
            width=min(_term_width(), 120),
        )

    def print(self, renderable: Any) -> None:
        self.console.print(renderable)


# ---------------------------------------------------------------------------
# FakeBackend 流式适配
# ---------------------------------------------------------------------------

def _fake_stream(backend: Any, messages: list[dict], tools: list[dict] | None = None):
    """为 FakeBackend 模拟逐字流式输出（它没有 chat_stream）。"""
    resp = backend.chat(messages, tools)
    content = resp.get("content", "")
    tool_calls = resp.get("tool_calls") or []
    usage = resp.get("usage") or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    # 逐字产出 content
    for ch in content:
        yield {"type": "content", "content": ch}

    # 直接产出最终 tool_calls（FakeBackend 没有增量）
    for i, tc in enumerate(tool_calls):
        yield {
            "type": "tool_call_start",
            "index": i,
            "id": tc.get("id", f"fake_call_{i}"),
            "name": tc.get("name", ""),
        }
        args_str = json.dumps(tc.get("arguments", {}), ensure_ascii=False)
        # 一次给完
        yield {"type": "tool_call_args", "index": i, "delta": args_str}

    yield {"type": "done", "content": content, "tool_calls": tool_calls, "usage": usage}


def _get_stream(backend: Any):
    """返回 (backend 的 chat_stream 方法 或  None) —— None 表示需用 _fake_stream 兜底。"""
    if hasattr(backend, "chat_stream"):
        return backend.chat_stream
    return None


# ---------------------------------------------------------------------------
# 流式后端包装 + ReAct turn
# ---------------------------------------------------------------------------

def _make_backend_call(backend: Any, console: Console):
    """返回一个 backend_call(messages, tools) -> assistant_dict 包装函数。

    包装函数内部使用 chat_stream（或 _fake_stream 兜底）并实时刷新 Rich Live。
    返回的 dict 包含 ``content``、``tool_calls`` 和 ``usage``。
    """
    stream_fn = _get_stream(backend)

    def backend_call(messages: list[dict[str, Any]], tools: list[dict] | None) -> dict:
        final_content = ""
        tool_calls_result: list[dict[str, Any]] = []
        usage_result: dict[str, Any] = {}

        def _initial_panel() -> Panel:
            return Panel(
                "思考中...",
                title="Assistant",
                border_style="green",
                width=min(_term_width(), 120),
            )

        if stream_fn is not None:
            content_chunks: list[str] = []
            with Live(_initial_panel(), console=console, refresh_per_second=10, transient=True) as live:
                for event in stream_fn(messages, tools=tools):
                    if event["type"] == "content":
                        content_chunks.append(event["content"])
                        live.update(Panel(
                            Text("".join(content_chunks), style="white"),
                            title="Assistant",
                            border_style="green",
                            width=min(_term_width(), 120),
                        ))
                    elif event["type"] == "tool_call_start":
                        live.update(Panel(
                            Text(f"调用工具 {_tool_name(event['name'])}...", style="yellow"),
                            title="Assistant",
                            border_style="yellow",
                            width=min(_term_width(), 120),
                        ))
                    elif event["type"] == "done":
                        final_content = event["content"]
                        tool_calls_result = event["tool_calls"]
                        usage_result = event.get("usage") or {}
        else:
            with Live(_initial_panel(), console=console, refresh_per_second=20, transient=True) as live:
                for event in _fake_stream(backend, messages, tools=tools):
                    if event["type"] == "done":
                        final_content = event["content"]
                        tool_calls_result = event["tool_calls"]
                        usage_result = event.get("usage") or {}

        return {
            "content": final_content,
            "tool_calls": tool_calls_result,
            "usage": usage_result,
        }

    return backend_call


def _run_react_turn(
    backend: Any,
    registry: ToolRegistry,
    messages: list[dict[str, Any]],
    display: DisplayManager,
    console: Console,
    max_turns: int = 20,
    token_budget: int | None = None,
    spill_threshold: int | None = None,
    auto_approve: bool = False,
    confirmer: Any = None,
    workdir: Path | None = None,
) -> None:
    """跑一轮 ReAct 循环：流式显示助手响应 → 执行工具 → 注入观察 → 重复。

    实际逻辑委托给 agent/strategy.py:run_react_turns()；本函数只提供流式后端
    包装和 Rich 渲染回调。
    """
    backend_call = _make_backend_call(backend, console)

    callbacks = ReactCallbacks(
        on_context_compacted=lambda: console.print(
            Panel("[上下文已压缩]", border_style="bright_black")
        ),
        on_assistant_message=lambda content, _tool_calls: (
            display.print(display.render_assistant(content))
            if content.strip()
            else None
        ),
        on_tool_call=lambda name, args: display.print(display.render_tool_call(name, args)),
        on_tool_result=lambda name, result: display.print(display.render_tool_result(name, result)),
        on_max_turns_reached=lambda: display.print(display.render_system(
            "达到最大轮数上限，任务可能未完成。请尝试拆分任务或用 /clear 清空历史。"
        )),
    )

    run_react_turns(
        backend_call,
        registry,
        messages,
        max_turns=max_turns,
        token_budget=token_budget,
        spill_threshold=spill_threshold,
        auto_approve=auto_approve,
        workdir=workdir,
        confirmer=confirmer,
        callbacks=callbacks,
        trace=ToolRunTrace(workdir or Path.cwd()),
    )


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def run_tui(backend: Any, registry: ToolRegistry, system_prompt: str,
            auto_approve: bool = False, workdir: Path | None = None) -> None:
    """启动交互式 TUI REPL。

    Args:
        backend: DeepSeekBackend 或 FakeBackend 实例
        registry: 包含所有工具的 ToolRegistry
        system_prompt: 完整的系统提示词字符串
    """
    console = Console()
    display = DisplayManager(console)
    workspace = (workdir or Path.cwd()).resolve()

    # --- 输入会话（带持久历史）---
    history_path = Path.home() / ".mini_openclaw_history"
    session = PromptSession(
        history=FileHistory(str(history_path)),
        multiline=False,
        # Enter 直接提交；按 Alt+Enter 可换行输入多行
    )

    def confirm_tool(name: str, args: dict[str, Any], reason: str) -> bool:
        display.print(display.render_system(
            f"权限确认：{name} {json.dumps(args, ensure_ascii=False)}\n{reason}"
        ))
        answer = session.prompt("允许本次执行？[y/N] ").strip().lower()
        return answer in {"y", "yes"}

    # --- 欢迎面板 ---
    model_name = getattr(backend, "model", "unknown")
    token_budget = resolve_token_budget(model_name)
    console.print(Panel(
        "[bold blue]MiniOpenClaw[/bold blue]  [dim]交互模式[/dim]\n"
        f"  模型: [cyan]{model_name}[/cyan]   |   工具: [cyan]{len(registry)}[/cyan]\n"
        f"  工作空间: [cyan]{workspace}[/cyan]\n"
        f"  上下文预算: [cyan]{token_budget}[/cyan] tokens\n"
        "  Enter 发送  |  Ctrl+D 或 /quit 退出  |  /clear 清空历史\n"
        "  /image <path> 附加图片  |  Ctrl+C 中断正在生成的回复",
        title="Welcome",
        border_style="blue",
        width=min(_term_width(), 120),
    ))

    # --- 持久对话历史 ---
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]

    # --- 待附加的图片（/image 命令设置，下次用户消息时消费并清空）---
    pending_images: list[dict[str, Any]] = []

    # --- 路径补全器 ---
    path_completer = _ImagePathCompleter()

    # --- 主循环 ---
    while True:
        # 用户输入
        try:
            user_input = session.prompt(
                [("class:prompt", "\n> ")],
                completer=path_completer,
            ).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            return

        if not user_input:
            continue

        # ---- /image <path> — 附加图片到下一轮对话 ----
        if user_input.startswith("/image"):
            parts = user_input.split(None, 1)
            if len(parts) < 2:
                console.print(Panel(
                    "用法：/image <图片路径>\n示例：/image screenshot.png",
                    border_style="yellow",
                    width=min(_term_width(), 80),
                ))
                continue
            # 去掉 shell 风格反斜杠转义（\  → 空格等）
            img_path = Path(_unescape_path(parts[1])).expanduser()
            if not img_path.is_file():
                console.print(Panel(
                    f"图片文件不存在：{img_path}",
                    border_style="red",
                    width=min(_term_width(), 80),
                ))
                continue
            try:
                from backend.image_util import image_block
                block = image_block(str(img_path))
                pending_images.append(block)
                console.print(Panel(
                    f"已附加图片：[green]{img_path.name}[/green]"
                    f"（共 {len(pending_images)} 张，下次发送消息时生效）",
                    border_style="green",
                    width=min(_term_width(), 80),
                ))
            except Exception as e:
                console.print(Panel(
                    f"图片加载失败：{e}",
                    border_style="red",
                    width=min(_term_width(), 80),
                ))
            continue

        # ---- /clear-images — 清空待附加图片 ----
        if user_input.lower() in ("/clear-images",):
            count = len(pending_images)
            pending_images.clear()
            console.print(Panel(
                f"已清空 {count} 张待附加图片",
                border_style="bright_black",
                width=min(_term_width(), 80),
            ))
            continue

        # 内建命令
        if user_input.lower() in ("/quit", "/exit", "/q"):
            console.print("[dim]Goodbye.[/dim]")
            return

        if user_input.lower() in ("/clear",):
            # 清空对话历史，保留 system prompt
            messages[:] = [{"role": "system", "content": system_prompt}]
            pending_images.clear()
            console.print(Panel("对话历史已清空", border_style="bright_black"))
            continue

        # ---- 构建用户消息 ----
        if pending_images:
            # 多模态：文本 + 图片内容块
            content: Any = [{"type": "text", "text": user_input}] + pending_images
            # 显示时标注附加图片
            display.print(display.render_user(
                f"{user_input}\n[dim](附加 {len(pending_images)} 张图片)[/dim]"
            ))
            pending_images.clear()
        else:
            content = user_input
            display.print(display.render_user(user_input))

        messages.append({"role": "user", "content": content})

        # 运行 ReAct
        try:
            _run_react_turn(
                backend, registry, messages, display, console,
                token_budget=token_budget,
                auto_approve=auto_approve,
                confirmer=None if auto_approve else confirm_tool,
                workdir=workspace,
            )
        except KeyboardInterrupt:
            console.print(Panel("已中断，回到提示符", border_style="yellow"))
        except Exception as e:
            display.print(display.render_error(f"{type(e).__name__}: {e}"))

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
  - 不修改 AgentLoop / loop.py —— _run_react_turn() 是薄包装，ReAct 逻辑完全一样
  - Rich Live 自带刷新线程，主线程同步迭代 SSE 即可，无需 async
  - FakeBackend 无 chat_stream → 用 _fake_stream() 模拟逐字输出
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

from tools.base import ToolRegistry
from agent.context import estimate_tokens, maybe_compact, truncate_observation


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

    yield {"type": "done", "content": content, "tool_calls": tool_calls}


def _get_stream(backend: Any):
    """返回 (backend 的 chat_stream 方法 或  None) —— None 表示需用 _fake_stream 兜底。"""
    if hasattr(backend, "chat_stream"):
        return backend.chat_stream
    return None


# ---------------------------------------------------------------------------
# 流式 ReAct turn
# ---------------------------------------------------------------------------

def _run_react_turn(
    backend: Any,
    registry: ToolRegistry,
    messages: list[dict[str, Any]],
    display: DisplayManager,
    console: Console,
    max_turns: int = 20,
    token_budget: int = 8000,
) -> None:
    """跑一轮 ReAct 循环：流式显示助手响应 → 执行工具 → 注入观察 → 重复。

    与 agent/loop.py:AgentLoop.run() 的逻辑完全一致，**额外**做了：
      1. 用 chat_stream()（或 _fake_stream 兜底）替代 chat()
      2. 用 Rich Live 实时刷新，用户能看到逐个 token
      3. messages 是持久的（多轮对话），而非每次新建
    """
    # 判断是否有真正的流式后端
    stream_fn = _get_stream(backend)

    for turn in range(max_turns):
        # --- 上下文压缩（与 loop.py 相同）---
        if estimate_tokens(messages) > token_budget:
            messages[:] = maybe_compact(messages, token_budget)
            console.print(Panel("[上下文已压缩]", border_style="bright_black"))

        # --- 流式调用 ---
        final_content = ""
        tool_calls_result: list[dict[str, Any]] = []

        if stream_fn is not None:
            # ===== 真流式（DeepSeek 等）=====
            content_chunks: list[str] = []

            with Live(
                Panel("思考中...", title="Assistant", border_style="green",
                      width=min(_term_width(), 120)),
                console=console,
                refresh_per_second=10,
                transient=True,
            ) as live:
                try:
                    for event in stream_fn(messages, tools=registry.schemas()):
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

                except KeyboardInterrupt:
                    console.print(Panel("已中断", border_style="yellow"))
                    return
        else:
            # ===== FakeBackend 兜底 =====
            with Live(
                Panel("思考中...", title="Assistant", border_style="green",
                      width=min(_term_width(), 120)),
                console=console,
                refresh_per_second=20,
                transient=True,
            ) as live:
                try:
                    for event in _fake_stream(backend, messages, tools=registry.schemas()):
                        if event["type"] == "content":
                            pass  # _fake_stream 太快，只取最终结果
                        elif event["type"] == "done":
                            final_content = event["content"]
                            tool_calls_result = event["tool_calls"]
                except KeyboardInterrupt:
                    console.print(Panel("已中断", border_style="yellow"))
                    return

        # --- 显示最终助手文本 ---
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": final_content,
            "tool_calls": tool_calls_result,
        }

        if final_content.strip():
            display.print(display.render_assistant(final_content))

        # --- 无工具调用 → 最终答复，返回 ---
        if not tool_calls_result:
            messages.append(assistant_msg)
            return

        # --- 工具调度（与 loop.py 完全一致）---
        messages.append(assistant_msg)

        for call in tool_calls_result:
            # 显示工具调用
            display.print(display.render_tool_call(
                call["name"], call.get("arguments", {})
            ))

            # 执行工具
            tool = registry.get(call["name"])
            if tool is None:
                obs = f"错误：未知工具 {call['name']}"
            else:
                try:
                    obs = tool.run(**call.get("arguments", {}))
                except Exception as e:
                    obs = f"工具执行错误（{call['name']}）：{e}\n请检查参数并重试。"

            obs = truncate_observation(str(obs))

            # 显示工具结果
            display.print(display.render_tool_result(call["name"], obs))

            # 注入 observation
            messages.append({
                "role": "tool",
                "name": call["name"],
                "tool_call_id": call.get("id"),
                "content": obs,
            })

    # 达到最大轮数
    display.print(display.render_system(
        "达到最大轮数上限，任务可能未完成。请尝试拆分任务或用 /clear 清空历史。"
    ))


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def run_tui(backend: Any, registry: ToolRegistry, system_prompt: str) -> None:
    """启动交互式 TUI REPL。

    Args:
        backend: DeepSeekBackend 或 FakeBackend 实例
        registry: 包含所有工具的 ToolRegistry
        system_prompt: 完整的系统提示词字符串
    """
    console = Console()
    display = DisplayManager(console)

    # --- 输入会话（带持久历史）---
    history_path = Path.home() / ".mini_openclaw_history"
    session = PromptSession(
        history=FileHistory(str(history_path)),
        multiline=False,
        # Enter 直接提交；按 Alt+Enter 可换行输入多行
    )

    # --- 欢迎面板 ---
    model_name = getattr(backend, "model", "unknown")
    console.print(Panel(
        "[bold blue]MiniOpenClaw[/bold blue]  [dim]交互模式[/dim]\n"
        f"  模型: [cyan]{model_name}[/cyan]   |   工具: [cyan]{len(registry)}[/cyan]\n"
        "  Enter 发送  |  Ctrl+D 或 /quit 退出  |  /clear 清空历史\n"
        "  Ctrl+C 中断正在生成的回复",
        title="Welcome",
        border_style="blue",
        width=min(_term_width(), 120),
    ))

    # --- 持久对话历史 ---
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]

    # --- 主循环 ---
    while True:
        # 用户输入
        try:
            user_input = session.prompt(
                [("class:prompt", "\n> ")],
            ).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            return

        if not user_input:
            continue

        # 内建命令
        if user_input.lower() in ("/quit", "/exit", "/q"):
            console.print("[dim]Goodbye.[/dim]")
            return

        if user_input.lower() in ("/clear",):
            # 清空对话历史，保留 system prompt
            messages[:] = [{"role": "system", "content": system_prompt}]
            console.print(Panel("对话历史已清空", border_style="bright_black"))
            continue

        # 显示用户消息
        display.print(display.render_user(user_input))
        messages.append({"role": "user", "content": user_input})

        # 运行 ReAct
        try:
            _run_react_turn(backend, registry, messages, display, console)
        except KeyboardInterrupt:
            console.print(Panel("已中断，回到提示符", border_style="yellow"))
        except Exception as e:
            display.print(display.render_error(f"{type(e).__name__}: {e}"))

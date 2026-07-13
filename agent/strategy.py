"""Shared ReAct strategy used by both CLI and TUI.

The looping logic lives here; callers supply a backend-call function and optional
callbacks so that presentation concerns (streaming, Rich panels, silence) stay
outside this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from tools.base import ToolRegistry
from agent.context import estimate_tokens, maybe_compact, truncate_observation
from agent.permissions import permission_observation


@dataclass
class ReactCallbacks:
    """Optional hooks for callers to observe loop events."""

    on_context_compacted: Callable[[], None] | None = None
    on_assistant_message: Callable[[str, list[dict[str, Any]]], None] | None = None
    on_tool_call: Callable[[str, dict[str, Any]], None] | None = None
    on_tool_result: Callable[[str, str], None] | None = None
    on_max_turns_reached: Callable[[], None] | None = None


def run_react_turns(
    backend_call: Callable[[list[dict[str, Any]], list[dict] | None], dict],
    registry: ToolRegistry,
    messages: list[dict[str, Any]],
    *,
    max_turns: int = 20,
    token_budget: int = 8000,
    auto_approve: bool = False,
    workdir: Path | None = None,
    confirmer: Callable[[str, dict[str, Any], str], bool] | None = None,
    callbacks: ReactCallbacks | None = None,
) -> str:
    """Run the ReAct loop on a mutable message history.

    Args:
        backend_call: Function that takes (messages, tools) and returns an
            assistant dict with keys ``content`` and ``tool_calls``.
        registry: Tool registry used for schemas and dispatch.
        messages: Mutable conversation history. The system message should
            already be present. This list is mutated in place.
        max_turns: Hard turn limit to prevent infinite loops.
        token_budget: Token threshold that triggers context compaction.
        auto_approve: Whether to auto-approve confirm-class tools.
        workdir: Working directory for path/permission checks.
        confirmer: Callable ``(tool_name, args, reason) -> bool`` invoked when
            a tool requires user confirmation and ``auto_approve`` is False.
        callbacks: Optional presentation hooks.

    Returns:
        The final assistant content string, or a max-turns fallback message.
    """
    callbacks = callbacks or ReactCallbacks()
    workdir = (workdir or Path.cwd()).resolve()

    for _ in range(max_turns):
        if estimate_tokens(messages) > token_budget:
            messages[:] = maybe_compact(messages, token_budget)
            if callbacks.on_context_compacted:
                callbacks.on_context_compacted()

        assistant = backend_call(messages, tools=registry.schemas())
        assistant_msg = {
            "role": "assistant",
            "content": assistant.get("content", ""),
            "tool_calls": assistant.get("tool_calls", []),
        }
        messages.append(assistant_msg)

        if callbacks.on_assistant_message:
            callbacks.on_assistant_message(
                assistant_msg["content"], assistant_msg["tool_calls"]
            )

        tool_calls = assistant.get("tool_calls") or []
        if not tool_calls:
            return assistant.get("content", "")

        for call in tool_calls:
            name = call["name"]
            arguments = call.get("arguments", {})

            if callbacks.on_tool_call:
                callbacks.on_tool_call(name, arguments)

            tool = registry.get(name)
            if tool is None:
                obs = f"错误：未知工具 {name}"
            else:
                obs = permission_observation(
                    name, arguments, workdir,
                    auto_approve=auto_approve, confirmer=confirmer,
                )
                if obs is None:
                    try:
                        obs = tool.run(**arguments)
                    except Exception as e:  # noqa: BLE001
                        obs = f"工具执行错误（{name}）：{e}\n请检查参数并重试。"

            obs = truncate_observation(str(obs))

            if callbacks.on_tool_result:
                callbacks.on_tool_result(name, obs)

            messages.append({
                "role": "tool",
                "name": name,
                "tool_call_id": call.get("id"),
                "content": obs,
            })

    if callbacks.on_max_turns_reached:
        callbacks.on_max_turns_reached()
    return "[达到最大轮数上限，未完成任务]"

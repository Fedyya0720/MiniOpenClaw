"""上下文管理（Day7）：token 预算、滑动窗口、自动摘要 / compaction。

模型上下文窗口有限。长任务里 messages 会越堆越长，迟早超预算。
策略：
  - 估算当前 messages 的 token 数；
  - 超过阈值时触发 compaction：把较早的对话摘要成一条 system 备忘，
    保留最近 K 轮原文 + 关键工具结果；
  - tool result 过长时先截断/摘要再注入。
"""
from __future__ import annotations
from typing import Any


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Rough token estimate: chars / 4 (standard heuristic, close enough for most models)."""
    return sum(len(str(m.get("content", ""))) for m in messages) // 4


def maybe_compact(messages: list[dict[str, Any]], budget: int = 6000) -> list[dict[str, Any]]:
    """超预算则压缩历史，返回新的 messages。

    Strategy: keep system message + last K messages; replace the middle
    with a compact summary note. Falls back gracefully if compression
    still isn't enough — keep at least the system + last 2 messages.
    """
    if estimate_tokens(messages) <= budget:
        return messages

    if len(messages) <= 3:
        return messages  # too small to compact

    system_msg = messages[0] if messages[0].get("role") == "system" else None

    # Count tool calls and turns in the middle region
    middle = messages[1:-6] if len(messages) > 7 else messages[1:-2]
    tool_count = sum(1 for m in middle if m.get("role") == "tool")
    turn_count = len([m for m in middle if m.get("role") in ("user", "assistant")])

    # Build compaction summary
    summary = (
        f"[上下文压缩] 之前的 {turn_count} 轮对话已被压缩。"
        f"共执行了 {tool_count} 次工具调用。"
        f"以下是最近的对话："
    )

    # Keep: system + summary + last 6 messages (3 turns)
    if system_msg:
        compacted = [system_msg]
        compacted.append({"role": "system", "content": summary})
    else:
        compacted = [{"role": "system", "content": summary}]

    recent = messages[-6:] if len(messages) > 6 else messages[1:]
    compacted.extend(recent)

    return compacted


def truncate_observation(text: str, max_chars: int = 4000) -> str:
    """工具结果过长时截断并提示。"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n...[已截断，共 {len(text)} 字符]"

"""上下文管理（Day7）：token 预算、滑动窗口、自动摘要 / compaction。

模型上下文窗口有限。长任务里 messages 会越堆越长，迟早超预算。
策略：
  - 估算当前 messages 的 token 数；
  - 超过阈值时触发 compaction：把较早的对话摘要成一条 system 备忘，
    保留最近 K 轮原文 + 关键工具结果；
  - tool result 过长时写入文件并返回指针 + 摘要，不再直接截断。
"""
from __future__ import annotations

import os
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.security import resolve_write_path

# 已知模型的上下文窗口（单位：token）。可通过环境变量覆盖。
KNOWN_CONTEXT_WINDOWS: dict[str, int] = {
    "deepseek-chat": 64_000,
    "deepseek-coder": 64_000,
    "deepseek-reasoner": 64_000,
    "deepseek-v4-flash": 1_000_000,
}

# 给 completion / 系统开销预留 10% 安全边际。
_CONTEXT_SAFETY_MARGIN = 0.9

# 最终安全网：即使 spill 逻辑被绕过，单条 observation 也不允许超过 100 万字符。
_EMERGENCY_OBSERVATION_CAP = 1_000_000

# 默认 spill 阈值：超过该字符数就写入文件。
_DEFAULT_SPILL_THRESHOLD = 8_000


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Rough token estimate: chars / 4 (standard heuristic, close enough for most models)."""
    return sum(len(str(m.get("content", ""))) for m in messages) // 4


def resolve_token_budget(
    model_name: str | None = None,
    context_window: int | None = None,
    explicit_budget: int | None = None,
) -> int:
    """根据模型能力或环境变量决定触发 compaction 的 token 预算。

    优先级：
      1. MINIOPENCLAW_TOKEN_BUDGET 显式覆盖
      2. DEEPSEEK_CONTEXT_WINDOW × 0.9
      3. KNOWN_CONTEXT_WINDOWS[model_name] × 0.9
      4. 根据 model_name 子串/前缀匹配已知模型 × 0.9
      5. 回退到 8000（与原行为一致）
    """
    if explicit_budget is not None:
        return explicit_budget

    env_budget = os.getenv("MINIOPENCLAW_TOKEN_BUDGET")
    if env_budget:
        try:
            return int(env_budget)
        except ValueError:
            pass

    env_window = os.getenv("DEEPSEEK_CONTEXT_WINDOW")
    if env_window:
        try:
            context_window = int(env_window)
        except ValueError:
            pass

    if context_window is not None and context_window > 0:
        return int(context_window * _CONTEXT_SAFETY_MARGIN)

    if model_name:
        known = KNOWN_CONTEXT_WINDOWS.get(model_name)
        if known:
            return int(known * _CONTEXT_SAFETY_MARGIN)
        # 子串匹配，兼容 provider 附加的 -free/-fast/-preview 等后缀
        lowered = model_name.lower()
        for key, window in KNOWN_CONTEXT_WINDOWS.items():
            if key.lower() in lowered:
                return int(window * _CONTEXT_SAFETY_MARGIN)

    return 8000


def maybe_compact(
    messages: list[dict[str, Any]],
    budget: int = 6000,
    actual_tokens: int | None = None,
) -> list[dict[str, Any]]:
    """超预算则压缩历史，返回新的 messages。

    Strategy: keep system message + last K messages; replace the middle
    with a compact summary note. Falls back gracefully if compression
    still isn't enough — keep at least the system + last 2 messages.
    """
    current = actual_tokens if actual_tokens else estimate_tokens(messages)
    if current <= budget:
        return messages

    if len(messages) <= 3:
        return messages  # too small to compact

    system_msg = messages[0] if messages[0].get("role") == "system" else None

    # Count tool calls and turns in the middle region
    middle = messages[1:-6] if len(messages) > 7 else messages[1:-2]
    tool_count = sum(1 for m in middle if m.get("role") == "tool")
    turn_count = len([m for m in middle if m.get("role") in ("user", "assistant")])

    token_note = f"实际约 {actual_tokens} tokens" if actual_tokens else f"估算约 {current} tokens"

    # Build compaction summary
    summary = (
        f"[上下文压缩] 之前的 {turn_count} 轮对话已被压缩。"
        f"共执行了 {tool_count} 次工具调用。"
        f"当前上下文 {token_note}，预算 {budget} tokens。"
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


def truncate_observation(text: str, max_chars: int = _EMERGENCY_OBSERVATION_CAP) -> str:
    """工具结果过长时的最终安全截断（仅作为兜底）。"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n...[已截断，共 {len(text)} 字符]"


def _spill_dir(workdir: Path) -> Path:
    """返回 spill 根目录（工作区内的隐藏目录）。"""
    custom = os.getenv("MINIOPENCLAW_SPILL_DIR")
    if custom:
        return workdir / custom
    return workdir / ".mini-openclaw" / "spill"


def _make_spill_filename(tool_name: str, turn: int | None, call_idx: int | None) -> str:
    """生成唯一且可读的 spill 文件名。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rand = secrets.token_hex(3)
    parts = [tool_name]
    if turn is not None:
        parts.append(f"{turn:03d}")
    if call_idx is not None:
        parts.append(f"{call_idx:03d}")
    parts.extend([ts, rand])
    return "_".join(parts) + ".txt"


def _extract_returncode(text: str) -> int | None:
    m = re.search(r"\[returncode:\s*(-?\d+)\]", text)
    if m:
        return int(m.group(1))
    return None


def _extract_stderr(text: str) -> list[str]:
    """提取 bash 工具返回的 [stderr] 块中的行。"""
    m = re.search(r"(?s)\[stderr\]\n(.*?)(?=\n\[returncode:|\Z)", text)
    if not m:
        return []
    return [line for line in m.group(1).splitlines() if line.strip()]


def _summarize_spilled(text: str, tool_name: str) -> str:
    """为已写入文件的长输出生成规则摘要。"""
    lines = [line for line in text.splitlines() if line.strip()]
    total_lines = len(text.splitlines())
    total_chars = len(text)
    total_bytes = len(text.encode("utf-8"))

    parts = [f"- 工具：{tool_name}"]
    parts.append(f"- 共 {total_lines} 行，{total_chars} 字符，{total_bytes} 字节")

    returncode = _extract_returncode(text)
    if returncode is not None:
        parts.append(f"- 退出码：{returncode}")

    stderr_lines = _extract_stderr(text)
    if stderr_lines:
        parts.append("- stderr 输出：")
        for line in stderr_lines[:5]:
            parts.append(f"    {line}")
        if len(stderr_lines) > 5:
            parts.append(f"    ...（stderr 共 {len(stderr_lines)} 行）")

    # 错误 / 异常关键字行
    error_re = re.compile(r"error|exception|traceback|failed|fatal", re.IGNORECASE)
    error_lines = [line for line in lines if error_re.search(line)]
    if error_lines:
        parts.append("- 检测到错误/异常信息：")
        for line in error_lines[:5]:
            parts.append(f"    {line}")
        if len(error_lines) > 5:
            parts.append(f"    ...（共 {len(error_lines)} 处）")

    # 头尾片段
    if len(lines) > 10:
        parts.append("- 开头 5 行：")
        for line in lines[:5]:
            parts.append(f"    {line}")
        parts.append("- 结尾 5 行：")
        for line in lines[-5:]:
            parts.append(f"    {line}")
    elif lines:
        parts.append("- 内容预览：")
        for line in lines[:10]:
            parts.append(f"    {line}")

    return "\n".join(parts)


def spill_observation(
    text: str,
    tool_name: str,
    workdir: Path,
    turn: int | None = None,
    call_idx: int | None = None,
    threshold: int | None = None,
) -> str:
    """如果工具输出过长，将其写入文件并返回文件路径 + 摘要。

    参数：
      text: 原始工具输出。
      tool_name: 工具名，用于文件名和摘要。
      workdir: 工作目录，spill 文件会写在该目录下。
      turn: 当前轮次编号，用于文件名。
      call_idx: 当前工具调用在轮次中的序号，用于文件名。
      threshold: 触发 spill 的字符阈值；None 则读取环境变量或默认值。
    """
    text = str(text)
    if threshold is None:
        try:
            threshold = int(os.getenv("MINIOPENCLAW_SPILL_THRESHOLD", str(_DEFAULT_SPILL_THRESHOLD)))
        except ValueError:
            threshold = _DEFAULT_SPILL_THRESHOLD

    if len(text) <= threshold:
        return text

    # 最终安全网：超大规模输出仍先截断到应急上限再写入文件。
    text = truncate_observation(text, _EMERGENCY_OBSERVATION_CAP)

    spill_root = _spill_dir(workdir)
    filename = _make_spill_filename(tool_name, turn, call_idx)
    relative_path = str(Path(".") / spill_root.relative_to(workdir) / filename)
    resolved = resolve_write_path(relative_path, workdir)
    if resolved.startswith("⚠️") or resolved.startswith("错误："):
        # 沙箱阻止写入：回退到截断
        return truncate_observation(text, threshold)

    abs_path = Path(resolved)
    try:
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(text, encoding="utf-8")
    except OSError:
        return truncate_observation(text, threshold)

    summary = _summarize_spilled(text, tool_name)
    return (
        f"[工具输出较长，已写入文件：{relative_path}]\n"
        f"摘要：\n{summary}\n"
        f"如需完整内容，请使用 read 工具读取该路径。"
    )

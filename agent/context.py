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

# Final fallback for callers that explicitly request truncation. Normal spill
# artifacts are deliberately never capped: they are durable evidence, not context.
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
    """Return a validated spill root beneath the workspace.

    A custom directory is allowed only when it resolves inside ``workdir``;
    invalid configuration falls back to the normal project-local location.
    """
    default = workdir / ".mini-openclaw" / "spill"
    custom = os.getenv("MINIOPENCLAW_SPILL_DIR")
    if not custom:
        return default
    candidate = Path(custom).expanduser()
    if not candidate.is_absolute():
        candidate = workdir / candidate
    try:
        candidate.resolve(strict=False).relative_to(workdir.resolve())
    except (OSError, ValueError):
        return default
    return candidate


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


def _summarize_spilled(
    original: str, stored: str, tool_name: str, *, redacted: bool, sensitive_retention: bool,
) -> str:
    """Summarize a spill without reintroducing sensitive content into context."""
    # Import lazily: trace imports no context code, and context remains usable on its own.
    from agent.trace import content_metadata

    metadata = content_metadata(original, stored)
    lines = [line for line in stored.splitlines() if line.strip()]
    total_lines = len(original.splitlines())
    stored_lines = len(stored.splitlines())

    parts = [f"- 工具：{tool_name}"]
    parts.append(
        "- 原始内容：{original_chars} 字符，{original_utf8_bytes} 字节，SHA-256: {original_sha256}".format(
            **metadata
        )
    )
    parts.append(
        "- 存储内容：{stored_chars} 字符，{stored_utf8_bytes} 字节，SHA-256: {stored_sha256}".format(
            **metadata
        )
    )
    parts.append(
        f"- 原始 {total_lines} 行；存储 {stored_lines} 行；已脱敏：{'是' if redacted else '否'}"
    )
    if sensitive_retention:
        parts.append("- 敏感内容保留：是（MINIOPENCLAW_TRACE_SENSITIVE=1；摘要不展示其内容）")

    returncode = _extract_returncode(stored)
    if returncode is not None:
        parts.append(f"- 退出码：{returncode}")

    # A forensic spill can retain the original data on disk, but context must
    # never replay it.  Redacted output can be previewed safely.
    if redacted or sensitive_retention:
        return "\n".join(parts)

    stderr_lines = _extract_stderr(stored)
    if stderr_lines:
        parts.append("- stderr 输出：")
        for line in stderr_lines[:5]:
            parts.append(f"    {line}")
        if len(stderr_lines) > 5:
            parts.append(f"    ...（stderr 共 {len(stderr_lines)} 行）")

    error_re = re.compile(r"error|exception|traceback|failed|fatal", re.IGNORECASE)
    error_lines = [line for line in lines if error_re.search(line)]
    if error_lines:
        parts.append("- 检测到错误/异常信息：")
        for line in error_lines[:5]:
            parts.append(f"    {line}")
        if len(error_lines) > 5:
            parts.append(f"    ...（共 {len(error_lines)} 处）")

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
    """Persist a large observation under the workspace and return a safe pointer.

    By default the persisted form follows ``agent.trace`` redaction.  Set
    ``MINIOPENCLAW_TRACE_SENSITIVE=1`` only for an intentional forensic case;
    even then, the context summary never previews sensitive content.
    """
    text = str(text)
    if threshold is None:
        try:
            threshold = int(os.getenv("MINIOPENCLAW_SPILL_THRESHOLD", str(_DEFAULT_SPILL_THRESHOLD)))
        except ValueError:
            threshold = _DEFAULT_SPILL_THRESHOLD

    if len(text) <= threshold:
        return text

    # Lazy imports avoid a trace/context import cycle while guaranteeing that
    # trace artifacts and generic spills share one default redaction policy.
    from agent.trace import redact_text, sensitive_retention_enabled

    stored, sensitive = redact_text(text)
    retained = sensitive_retention_enabled()
    if sensitive and retained:
        stored = text

    spill_root = _spill_dir(workdir)
    filename = _make_spill_filename(tool_name, turn, call_idx)
    try:
        relative_root = spill_root.resolve(strict=False).relative_to(workdir.resolve())
    except (OSError, ValueError):
        # Defensive fallback if a path changes between validation and use.
        spill_root = workdir / ".mini-openclaw" / "spill"
        relative_root = spill_root.relative_to(workdir)
    relative_path = str(Path(".") / relative_root / filename)
    resolved = resolve_write_path(relative_path, workdir)
    if resolved.startswith("⚠️") or resolved.startswith("错误："):
        # 沙箱阻止写入：回退到截断
        return truncate_observation(text, threshold)

    abs_path = Path(resolved)
    try:
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        for parent in (workdir / ".mini-openclaw", abs_path.parent):
            try:
                parent.chmod(0o700)
            except OSError:
                pass
        abs_path.write_text(stored, encoding="utf-8")
        try:
            abs_path.chmod(0o600)
        except OSError:
            pass
    except OSError:
        return truncate_observation(stored, threshold)

    summary = _summarize_spilled(
        text, stored, tool_name,
        redacted=bool(sensitive and not retained),
        sensitive_retention=bool(sensitive and retained),
    )
    return (
        f"[工具输出较长，已写入文件：{relative_path}]\n"
        f"摘要：\n{summary}\n"
        f"如需完整内容，请使用 read 工具读取该路径。"
    )

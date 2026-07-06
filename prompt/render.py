"""对话模板渲染器（Day3 的核心交付物）。

目标：把结构化的 messages + tools，渲染成模型真正看到的**一整段文本/token**。
关键认知：模型从不"接收一个 messages 列表"——它只接收一段拼好的字符串，
里面用特殊标记区分角色，工具 schema 也只是被塞进 system 段的普通文本，
模型输出的 <tool_call>{...}</tool_call> 同样只是它学会生成的普通 token。

Day3 你要：
  1. 用 tokenizers 库观察 GLM tokenizer 对这些特殊标记的切分；
  2. 不借助任何 function-calling API，纯字符串拼接实现下面的 render_prompt；
  3. 送入本地模型，手动解析它生成的工具调用。
"""
from __future__ import annotations
from typing import Any
import json

# DeepSeek ChatML variant role tokens as (begin, end) pairs.
# BOS/EOS framing is NOT included — the caller/tokenizer is responsible.
ROLE_TOKENS = {
    "system": ("<|begin_of_system|>", "<|end_of_system|>"),
    "user": ("<|begin_of_user|>", "<|end_of_user|>"),
    "assistant": ("<|begin_of_assistant|>", "<|end_of_assistant|>"),
    "tool": ("<|begin_of_tool|>", "<|end_of_tool|>"),
}


def render_tools_block(tools: list[dict[str, Any]]) -> str:
    """把 tool schema 列表渲染成放进 system 段的文本说明。"""
    if not tools:
        return ""
    lines = ["你可以调用以下工具，调用格式：<tool_call>{\"name\": ..., \"arguments\": {...}}</tool_call>"]
    for t in tools:
        f = t["function"]
        lines.append(f"- {f['name']}: {f['description']}  参数schema={json.dumps(f['parameters'], ensure_ascii=False)}")
    return "\n".join(lines)


def render_prompt(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> str:
    """messages + tools -> 一整段送入模型的文本。

    不包含 BOS/EOS 标记——由调用方/tokenizer 负责。
    末尾始终以 assistant begin token 结尾，提示模型开始生成。
    """
    # --- 输入校验 ---
    if not isinstance(messages, list):
        raise TypeError(f"messages must be a list, got {type(messages).__name__}")

    # --- 渲染工具说明 ---
    tools_text = ""
    if tools:
        tools_text = render_tools_block(tools)

    parts: list[str] = []
    tools_rendered = False

    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            raise TypeError(f"messages[{i}] must be a dict, got {type(msg).__name__}")

        role = msg.get("role")
        if role is None:
            raise TypeError(f"messages[{i}] is missing required 'role' key")
        if role not in ROLE_TOKENS:
            raise ValueError(f"unknown role: {role!r}")

        begin, end = ROLE_TOKENS[role]
        content = msg.get("content", "")
        if content is None:
            content = ""

        # 系统消息 + 工具说明：把工具说明放在系统段最前面
        if role == "system" and tools_text and not tools_rendered:
            content = tools_text + "\n" + content if content else tools_text
            tools_rendered = True

        # 助手消息中的工具调用
        if role == "assistant":
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                tc_parts: list[str] = []
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    name = tc.get("name")
                    if name is None:
                        continue  # 跳过没有 name 的工具调用
                    arguments = tc.get("arguments", {})
                    if arguments is None:
                        arguments = {}
                    tc_json = json.dumps(
                        {"name": name, "arguments": arguments},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    tc_parts.append(f"<tool_call>{tc_json}</tool_call>")
                if tc_parts:
                    tc_text = "\n".join(tc_parts)
                    content = content + "\n" + tc_text if content else tc_text

        # 工具/观测消息：在内容前加上工具名
        if role == "tool":
            name = msg.get("name")
            if name is not None:
                content = f"{name}: {content}"

        parts.append(f"{begin}{content}{end}")

    # 有工具说明但没有任何 system 消息 → 创建合成 system 段
    if tools_text and not tools_rendered:
        sys_begin, sys_end = ROLE_TOKENS["system"]
        parts.insert(0, f"{sys_begin}{tools_text}{sys_end}")

    # 末尾始终以 assistant begin token 结尾，提示模型开始生成
    assistant_begin, _ = ROLE_TOKENS["assistant"]
    parts.append(assistant_begin)

    return "".join(parts)


def parse_tool_calls(text: str) -> list[dict[str, Any]]:
    """从模型生成的文本里解析出工具调用（手动解析，不依赖 API）。"""
    # TODO[Day3] 用正则/状态机提取所有 <tool_call>...</tool_call>，json.loads 出 name/arguments
    raise NotImplementedError("Day3：实现 parse_tool_calls")

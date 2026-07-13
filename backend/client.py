"""大模型后端：DeepSeek API 客户端（OpenAI 兼容）。

本课程的 mini-OpenClaw 不本地部署模型，而是调用 DeepSeek API 作为"大脑"。
DeepSeek 的接口与 OpenAI 完全兼容，所以下面用通用的 OpenAI 协议写法，
只要改 base_url / api_key / model 就能换任意 OpenAI 兼容厂商。

接口约定（和 FakeBackend 一致，主循环 agent/loop.py 只认这个）：
    chat(messages, tools) -> {"role": "assistant", "content": str, "tool_calls": [ {name, arguments}, ... ]}

环境变量：
    DEEPSEEK_API_KEY   你的 key（千万别提交进 git！）
    DEEPSEEK_BASE_URL  默认 https://api.deepseek.com
    DEEPSEEK_MODEL     默认 deepseek-chat
"""
from __future__ import annotations
import os
import json
import time
from typing import Any

import httpx

# 可重试的错误类型：网络层 + 服务端临时故障（不重试 4xx 客户端错误）
RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
)

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def _chain_stream(first_event: dict[str, Any], rest: Any):
    """把预先消费的第一个事件和剩余生成器链回一个生成器。"""
    yield first_event
    yield from rest


class DeepSeekBackend:
    def __init__(self,
                 api_key: str | None = None,
                 base_url: str | None = None,
                 model: str | None = None,
                 timeout: float = 60.0,
                 max_retries: int = 3,
                 retry_delay: float = 1.0):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = (base_url or os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")).rstrip("/")
        self.model = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
        if not self.api_key:
            raise RuntimeError("缺少 DEEPSEEK_API_KEY 环境变量")
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._client = httpx.Client(timeout=timeout)

    # ------------------------------------------------------------------
    # 重试逻辑
    # ------------------------------------------------------------------
    def _should_retry(self, exc: Exception, status_code: int | None = None) -> bool:
        """判断是否应该重试：网络错误或临时服务端错误。"""
        if isinstance(exc, RETRYABLE_EXCEPTIONS):
            return True
        if status_code is not None and status_code in RETRYABLE_STATUSES:
            return True
        return False

    def _retry_request(self, request_fn, *, _stream: bool = False):
        """带指数退避的请求重试包装器。

        request_fn: 无参 callable，执行实际请求并返回响应/生成器
        _stream: True 时返回生成器（chat_stream），False 时返回响应对象（chat）
        """
        last_exc: Exception | None = None
        last_status: int | None = None

        for attempt in range(self.max_retries + 1):
            try:
                return request_fn()
            except httpx.HTTPStatusError as e:
                last_exc = e
                last_status = e.response.status_code
                if not self._should_retry(e, last_status):
                    raise
            except Exception as e:
                last_exc = e
                last_status = None
                if not self._should_retry(e):
                    raise

            if attempt < self.max_retries:
                delay = self.retry_delay * (2 ** attempt)
                print(f"[重试] 请求失败 ({last_exc.__class__.__name__}"
                      f"{f', HTTP {last_status}' if last_status else ''})，"
                      f"{delay:.1f}s 后第 {attempt + 1}/{self.max_retries} 次重试...")
                time.sleep(delay)

        # 所有重试已用完
        raise last_exc  # type: ignore[misc]

    def chat(self, messages: list[dict[str, Any]], tools: list[dict] | None = None,
             temperature: float = 0.0) -> dict[str, Any]:
        """一次（非流式）对话补全，返回归一化的 assistant 消息。"""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_openai_messages(messages),
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools           # OpenAI tools 格式，base.Tool.schema() 已生成
            payload["tool_choice"] = "auto"

        debug = os.environ.get("MINIOPENCLAW_DEBUG") == "1"
        if debug:
            # Console-only preview, opt-in because tool schemas can be large.
            import json as _json
            _serialized = _json.dumps(payload, ensure_ascii=False, indent=2)
            print(f"\n[DEBUG] --- outgoing payload preview ({len(_serialized)} chars total) ---")
            print(_serialized[:4000])
            if len(_serialized) > 4000:
                print(f"...[preview truncated, total {len(_serialized)} chars]")
            print("[DEBUG] --- end outgoing payload preview ---\n")

        def _do_request():
            resp = self._client.post(
                f"{self.base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            if debug and not resp.is_success:
                print(f"[DEBUG] HTTP {resp.status_code}: {resp.text[:2000]}")
            resp.raise_for_status()
            data = resp.json()
            msg = data["choices"][0]["message"]
            usage = data.get("usage") or {}
            return self._normalize(msg, usage)

        return self._retry_request(_do_request)

    def chat_stream(self, messages: list[dict[str, Any]], tools: list[dict] | None = None,
                    temperature: float = 0.0):
        """流式对话补全（Day11 TUI 用），逐 token 产出结构化事件。

        事件类型：
          {"type": "content", "content": "好"}              -- 文本增量
          {"type": "tool_call_start", "index": 0,          -- 新工具调用开始
           "id": "call_xxx", "name": "read"}
          {"type": "tool_call_args", "index": 0,           -- 工具参数增量
           "delta": "{\\"path\\":"}
          {"type": "done", "content": "...",               -- 完整响应
           "tool_calls": [{"id":"call_xxx","name":"read","arguments":{...}}]}
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_openai_messages(messages),
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        collected_content: list[str] = []
        tool_calls_acc: dict[int, dict[str, Any]] = {}  # index -> {id, name, args_str}
        stream_usage: dict[str, Any] = {}

        def _do_stream():
            """构建并迭代 SSE 流（由 _retry_request 包装，失败时整体重试）。"""
            nonlocal collected_content, tool_calls_acc, stream_usage
            collected_content.clear()
            tool_calls_acc.clear()
            stream_usage.clear()

            with self._client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    # OpenAI-compatible providers may emit usage on the final chunk.
                    if data.get("usage"):
                        stream_usage.update(data["usage"])

                    choices = data.get("choices")
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}

                    # 文本增量
                    if delta.get("content"):
                        collected_content.append(delta["content"])
                        yield {"type": "content", "content": delta["content"]}

                    # 工具调用增量
                    for tc_delta in delta.get("tool_calls") or []:
                        idx = tc_delta.get("index", 0)
                        if idx not in tool_calls_acc:
                            fn = tc_delta.get("function", {})
                            tc_info = {
                                "id": tc_delta.get("id", ""),
                                "name": fn.get("name", ""),
                                "args_str": fn.get("arguments", ""),
                            }
                            tool_calls_acc[idx] = tc_info
                            yield {
                                "type": "tool_call_start",
                                "index": idx,
                                "id": tc_info["id"],
                                "name": tc_info["name"],
                            }
                        else:
                            fn = tc_delta.get("function", {})
                            if fn.get("arguments"):
                                delta_args = fn["arguments"]
                                tool_calls_acc[idx]["args_str"] += delta_args
                                yield {
                                    "type": "tool_call_args",
                                    "index": idx,
                                    "delta": delta_args,
                                }

            # 组装最终响应
            final_content = "".join(collected_content)
            final_tool_calls: list[dict[str, Any]] = []
            for idx in sorted(tool_calls_acc):
                tc = tool_calls_acc[idx]
                try:
                    args = json.loads(tc["args_str"]) if tc["args_str"] else {}
                except json.JSONDecodeError:
                    args = {}
                final_tool_calls.append({
                    "id": tc["id"],
                    "name": tc["name"],
                    "arguments": args,
                })
            yield {"type": "done", "content": final_content,
                   "tool_calls": final_tool_calls,
                   "usage": stream_usage}

        # 对初始连接/状态码重试；流中解析错误不重试（由上游 ReAct 循环兜底）
        def _connect_and_start_stream():
            stream = _do_stream()
            # 立即触发第一个 yield（会执行到第一个 yield 或 raise 连接错误）
            first = next(stream)
            # 如果第一个事件成功，把剩余部分拼回去
            return _chain_stream(first, stream)

        return self._retry_request(_connect_and_start_stream, _stream=True)

    # --- 把内部 messages（含 role=tool）转成 OpenAI 标准格式 ---
    def _to_openai_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for m in messages:
            role = m.get("role")
            if role == "tool":
                # OpenAI 要求 tool 消息带 tool_call_id。
                # 注意：dict.get() 在 key 存在但值为 None 时不会走默认值，
                # 所以先取出来再显式处理 None。
                tc_id = m.get("tool_call_id") or m.get("name") or "tool"
                out.append({"role": "tool", "content": str(m.get("content", "")),
                            "tool_call_id": tc_id})
            elif role == "assistant" and m.get("tool_calls"):
                # 有 tool_calls 时 content 必须为 null（OpenAI 规范）
                out.append({"role": "assistant", "content": m.get("content") or None,
                            "tool_calls": self._to_openai_tool_calls(m["tool_calls"])})
            elif role == "assistant":
                # 纯文本回复：跳过空 content（部分 API 拒收空字符串）
                content = m.get("content", "")
                if not content:
                    continue
                out.append({"role": role, "content": content})
            else:
                # 支持纯文本或内容块列表（多模态：文本+图片）
                content = m.get("content", "")
                if isinstance(content, list):
                    # 将内部内容块转为 OpenAI Vision API 格式
                    out.append({"role": role, "content": self._convert_content_blocks(content)})
                else:
                    out.append({"role": role, "content": str(content)})
        return out

    @staticmethod
    def _convert_content_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """将内部内容块（Anthropic 风格 image block）转为 OpenAI Vision 格式。

        内部格式（Anthropic）：
          {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}}

        OpenAI Vision 格式：
          {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}

        文本块透传不变。
        """
        converted: list[dict[str, Any]] = []
        for block in blocks:
            if block.get("type") == "image":
                src = block.get("source", {})
                media_type = src.get("media_type", "image/png")
                data = src.get("data", "")
                # 构造 data URL: data:image/png;base64,<b64>
                data_url = f"data:{media_type};base64,{data}"
                converted.append({
                    "type": "image_url",
                    "image_url": {"url": data_url},
                })
            else:
                # 文本块或其他 — 透传
                converted.append(block)
        return converted

    @staticmethod
    def _to_openai_tool_calls(calls: list[dict]) -> list[dict]:
        out = []
        for i, c in enumerate(calls):
            name = c.get("name")
            if not name:  # skip malformed tool calls (missing name → API 400)
                continue
            out.append({"id": c.get("id", f"call_{i}"), "type": "function",
                        "function": {"name": name,
                                     "arguments": json.dumps(c.get("arguments", {}), ensure_ascii=False)}})
        return out

    # --- 把 OpenAI 返回归一化成内部格式 ---
    @staticmethod
    def _normalize(msg: dict[str, Any], usage: dict[str, Any] | None = None) -> dict[str, Any]:
        tool_calls = []
        for tc in (msg.get("tool_calls") or []):
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({"id": tc.get("id"), "name": fn.get("name"), "arguments": args})
        return {
            "role": "assistant",
            "content": msg.get("content") or "",
            "tool_calls": tool_calls,
            "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

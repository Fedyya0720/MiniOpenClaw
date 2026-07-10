"""ReAct 主循环（Agent 的心脏）。

  while 没到最终答复:
      assistant = backend.chat(messages, tools)      # 模型这一步：思考 or 调工具
      if assistant 有 tool_calls:
          for call in tool_calls:
              obs = registry.get(call.name).run(**call.arguments)   # 执行工具
              messages.append(tool_result(obs))                     # 注入 observation
      else:
          return assistant.content                                 # 最终答复

Day5 你要把下面的 run() 真正实现出来（Day6 随工具集扩展完善）。骨架已给出结构与防呆上限。
"""
from __future__ import annotations
from typing import Any

from tools.base import ToolRegistry
from agent.context import estimate_tokens, maybe_compact, truncate_observation


class AgentLoop:
    def __init__(self, backend: Any, registry: ToolRegistry, system_prompt: str,
                 max_turns: int = 20, token_budget: int = 8000):
        self.backend = backend
        self.registry = registry
        self.system_prompt = system_prompt
        self.max_turns = max_turns          # 防死循环：硬上限
        self.token_budget = token_budget    # 触发 compaction 的 token 阈值

    def run(self, user_task: str, images: list[str] | None = None) -> str:
        # 构建 user 消息：纯文本 or 文本+图片内容块
        if images:
            from backend.image_util import image_block
            content: Any = [{"type": "text", "text": user_task}]
            for img_path in images:
                content.append(image_block(img_path))
        else:
            content = user_task

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": content},
        ]
        for turn in range(self.max_turns):
            # Day7: context management — compact if over budget
            if estimate_tokens(messages) > self.token_budget:
                messages = maybe_compact(messages, self.token_budget)

            assistant = self.backend.chat(messages, tools=self.registry.schemas())
            messages.append({"role": "assistant",
                             "content": assistant.get("content", ""),
                             "tool_calls": assistant.get("tool_calls", [])})

            tool_calls = assistant.get("tool_calls") or []
            if not tool_calls:
                return assistant.get("content", "")

            for call in tool_calls:
                tool = self.registry.get(call["name"])
                if tool is None:
                    obs = f"错误：未知工具 {call['name']}"
                else:
                    # Day7: error recovery — exception text as observation
                    try:
                        obs = tool.run(**call.get("arguments", {}))
                    except Exception as e:
                        obs = f"工具执行错误（{call['name']}）：{e}\n请检查参数并重试。"
                # Day7: truncate long observations
                obs = truncate_observation(str(obs))
                messages.append({"role": "tool", "name": call["name"],
                                 "tool_call_id": call.get("id"), "content": obs})

        return "[达到最大轮数上限，未完成任务]"

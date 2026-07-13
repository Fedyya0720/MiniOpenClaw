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
from pathlib import Path

from tools.base import ToolRegistry
from agent.context import resolve_token_budget
from agent.strategy import run_react_turns


class AgentLoop:
    def __init__(self, backend: Any, registry: ToolRegistry, system_prompt: str,
                 max_turns: int = 20, token_budget: int | None = None,
                 spill_threshold: int | None = None,
                 auto_approve: bool = False, workdir: Path | None = None):
        self.backend = backend
        self.registry = registry
        self.system_prompt = system_prompt
        self.max_turns = max_turns          # 防死循环：硬上限
        # 根据模型能力或环境变量决定触发 compaction 的 token 阈值
        model_name = getattr(backend, "model", None)
        self.token_budget = token_budget if token_budget is not None else resolve_token_budget(model_name)
        self.spill_threshold = spill_threshold
        self.auto_approve = auto_approve
        self.workdir = (workdir or Path.cwd()).resolve()

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

        return run_react_turns(
            self.backend.chat,
            self.registry,
            messages,
            max_turns=self.max_turns,
            token_budget=self.token_budget,
            spill_threshold=self.spill_threshold,
            auto_approve=self.auto_approve,
            workdir=self.workdir,
        )

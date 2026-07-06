"""评测任务集与指标（Day4 体验 / Day7 评测；Day10 任务成功率 / 消融）。

两类评测：
  A) 工具调用质量：在固定测试集上算三项指标（Day4 用 API 体验，Day7 系统化）。
  B) 端到端任务成功率（Day7 起 / Day10 消融）：跑一批任务，看完成率，对比不同配置。
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ToolCallCase:
    request: str                 # 用户请求
    expected_tool: str           # 期望调用的工具名
    expected_args: dict          # 期望参数（可只校验关键字段）


# Day6 固定测试集（教师会提供 ~50 条；这里给格式示例）
TOOLCALL_TESTSET: list[ToolCallCase] = [
    # read tool
    ToolCallCase("把 a.txt 的内容读出来", "read", {"path": "a.txt"}),
    ToolCallCase("read the file config.json", "read", {"path": "config.json"}),
    ToolCallCase("读取 README.md", "read", {"path": "README.md"}),
    # write tool
    ToolCallCase("create a file test.txt with hello world", "write", {"path": "test.txt"}),
    ToolCallCase("把内容写入 output.log", "write", {"path": "output.log"}),
    # bash tool
    ToolCallCase("在当前目录运行 ls", "bash", {"command": "ls"}),
    ToolCallCase("run pytest", "bash", {"command": "pytest"}),
    ToolCallCase("显示当前时间", "bash", {"command": "date"}),
    # edit tool
    ToolCallCase("把 hello.py 里的 print('old') 改成 print('new')", "edit", {"path": "hello.py"}),
    # grep tool
    ToolCallCase("搜索所有包含 TODO 的文件", "grep", {"pattern": "TODO"}),
    ToolCallCase("find where User class is defined", "grep", {"pattern": "class User"}),
    # glob tool
    ToolCallCase("列出所有 .py 文件", "glob", {"pattern": "*.py"}),
    # web_fetch tool
    ToolCallCase("fetch https://example.com", "web_fetch", {"url": "https://example.com"}),
    # task_list tool
    ToolCallCase("add a task to review the PR", "task_list", {"action": "add"}),
]


@dataclass
class E2ETask:
    name: str
    instruction: str
    check: str                   # 如何判定成功（人工/脚本）


# Day10 端到端任务集（消融用）
E2E_TASKS: list[E2ETask] = [
    E2ETask("hello", "创建 hello.py 并运行，输出当前时间", "存在 hello.py 且运行打印了时间"),
    E2ETask("todo-report", "扫描本项目所有 Python 文件里的 TODO 注释，生成 markdown 报告",
            "生成的报告列出了真实存在的 TODO"),
    # Day10: domain-specific E2E tasks
    E2ETask("fix-bug", "test_script.py 运行时出现 NameError，请修复",
            "脚本能正常运行，不再报 NameError"),
    E2ETask("refactor", "把 tools/fs.py 里的 _read 函数拆成一个独立的 reader 模块",
            "reader 模块可独立导入，原 tools/fs.py 通过 import 使用它"),
    E2ETask("csv-report", "用 bash 生成一个包含 3 列 10 行的随机 CSV，然后给出统计概览",
            "CSV 文件存在且有 10 行数据，统计概览描述了每列特征"),
    E2ETask("multi-step", "创建一个 Python 项目：main.py 调用 lib/helper.py 里的函数，写 README，用 bash 运行验证",
            "项目结构完整，运行成功，README 描述了用法"),
]

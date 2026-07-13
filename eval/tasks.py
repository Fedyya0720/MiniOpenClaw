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
    # PACS: parallel adaptive constraint search
    E2ETask("pacs-analyze", "分析 ./test-project 的 Python 依赖并生成不超过 4 个兼容候选组合",
            "调用 parse_deps 和 generate_combinations，候选数量不超过 4"),
    E2ETask("pacs-failure", "解析一段 pip ResolutionImpossible 日志并记录冲突约束",
            "调用 parse_failure 和 infer_constraints，输出结构化 dependency_conflict"),
    E2ETask("pacs-env", "为 ./test-project 创建隔离环境并验证，失败时清理环境",
            "调用 env_create/env_run/env_status，失败环境由 env_cleanup 清理"),
]

# ========== Day3 下午 · 评估 harness ==========

# Trajectory 类型：一次任务运行的记录
Trajectory = dict

@dataclass
class Task:
    name: str
    instruction: str                       # 给 agent 的指令
    check: Callable[[Trajectory], bool]    # 成功判据：吃一条轨迹，判成败

# ---- 成功判据（程序化优先）----
def _check_read_config(traj: Trajectory) -> bool:
    used_read = any(
        tc["name"] == "read"
        for s in traj["steps"] for tc in s.get("tool_calls", [])
    )
    return used_read and "30" in traj.get("final", "")

def _check_list_dir(traj: Trajectory) -> bool:
    return any(
        tc["name"] == "bash" and "ls" in str(tc.get("arguments", {}))
        for s in traj["steps"] for tc in s.get("tool_calls", [])
    )

def _check_read_code(traj: Trajectory) -> bool:
    """代码阅读领域：成功 = 调用过 read 且最终答复包含代码关键信息（函数名或类名）。"""
    used_read = any(
        tc["name"] == "read"
        for s in traj["steps"] for tc in s.get("tool_calls", [])
    )
    final = traj.get("final", "")
    has_code_info = any(kw in final for kw in ["函数", "类", "def ", "class ", "功能", "实现"])
    return used_read and has_code_info

SAMPLE_TASKS: list[Task] = [
    Task("read-config", "读取 config.json，告诉我 timeout 是多少", _check_read_config),
    Task("list-dir", "列出当前目录下的文件", _check_list_dir),
    Task("read-code", "读取 main.py 并解释 main 函数的功能", _check_read_code),
]

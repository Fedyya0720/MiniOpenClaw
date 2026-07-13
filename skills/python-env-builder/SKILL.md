---
name: python-env-builder
description: 使用 PACS 为 Python 项目发现真实依赖版本、并行搜索兼容组合、安装项目、验证环境并生成锁文件。用户要求配置 Python 环境、安装 requirements/pyproject 依赖、解决版本冲突、生成 lock、修复 pip ResolutionImpossible，或验证项目能否安装时使用。
---

# PACS Python 环境构建

## 选择入口

- 用户要求实际完成环境配置：调用一次 `pacs_build`，不要手工编排 8 个原子工具。
- 用户只要求分析依赖或调试 PACS：按需调用 `parse_deps`、`generate_combinations`、`parse_failure`、`infer_constraints` 及 `env_*`。

## 实际构建流程

1. 确认 `project_path` 指向包含 `requirements.txt` 或 `pyproject.toml` 的目录。
2. 从 `pyproject.toml` 的 `requires-python` 或用户要求推断 `python_version`；无法确定时省略，使用当前 Python。
3. 推断 `validation_modules`：优先查看 `src/<module>/__init__.py`、顶层包目录或项目入口。无法可靠推断时传空数组；`pacs_build` 仍会执行 `pip check`。
4. 根据规模设置参数：
   - 普通项目：`max_parallel=2`，`max_attempts=8`。
   - 依赖很多或资源有限：`max_parallel=2`，不要盲目提高并行度。
   - 实际安装项目本体：保持 `install_project=true`。
5. 调用 `pacs_build`。该工具会查询真实版本、并行运行 pip、记录冲突、继续搜索、安装项目本体、验证、freeze，并清理失败环境。
6. 解析 JSON 结果，不要仅凭自然语言猜测成功：
   - 只有 `success=true` 才算完成。
   - 报告 `environment_path`、`lock_path`、`report_path`、轮次和尝试数。
   - `success=false` 时报告 `error` 与失败尝试，不声称环境可用。

## 失败处理

- 找不到 Python 版本：向用户说明需要安装对应解释器；不要换版本后假装满足原约束。
- 网络、证书或超时：允许调整 `timeout` 后重试一次；不要把瞬态错误当作版本冲突。
- 没有可用版本或 ResolutionImpossible：报告已尝试组合和 `PACS_REPORT.md`。
- `project_install_failed`：查看构建日志，区分构建后端缺失与项目源码问题。
- 工具需要执行确认时等待用户确认；处于明确授权的自动批准测试中可继续。

## 成功回复

必须包含：

```text
环境：<environment_path>
激活：source <environment_path>/bin/activate
锁文件：<lock_path>
报告：<report_path>
搜索：<rounds> 轮，<attempts 数> 个候选
```

不要把“已解析依赖”或“已创建 venv”表述为完整安装成功。

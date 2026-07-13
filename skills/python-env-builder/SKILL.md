---
name: python-env-builder
description: 配置环境、安装依赖或解决 pip 冲突时，项目路径已知就直接调用一次 pacs_build；该工具会自行发现版本、预求解、并行安装、验证并生成锁文件，无需先 read/glob。
dependencies:
  tools:
    - pacs_build
    - parse_deps
    - generate_combinations
    - parse_failure
    - infer_constraints
    - env_create
    - env_run
    - env_status
    - env_cleanup
---

# Python 环境构建 Skill

## 默认快速流程

1. TUI/CLI 在目标项目目录启动时，项目路径就是 `.`，不要先扫描目录或读取依赖文件。
2. 默认第一次工具调用就是 `pacs_build(project_path=".")`，把完整搜索循环交给确定性编排器。
3. 检查返回 JSON 的 `success`，不要仅凭日志猜测成功。
4. 成功时汇报：环境路径、lock、报告、轮次、尝试数、验证结果和耗时。
5. 失败时汇报：主要失败、尝试数和报告路径；不要自动重复同样的调用。

推荐参数：

```json
{
  "project_path": ".",
  "max_parallel": 2,
  "max_attempts": 6,
  "timeout": 120,
  "validation_modules": []
}
```

只有用户明确提供本地 wheelhouse 时，才传递类似参数：

```json
{
  "pip_args": ["--no-index", "--find-links", "/absolute/wheelhouse"],
  "version_catalog": {"demo-core": ["2.0.0", "1.0.0"]}
}
```

## 何时使用低层工具

只有以下情况才逐个调用 `parse_deps`、`generate_combinations`、`env_*` 等工具：

- 用户只要依赖分析，不允许安装；
- `pacs_build` 返回基础设施错误，需要定位某个组件；
- 用户明确要求查看候选、约束图或 serial/parallel 对照。

不要让 Agent 自己承担多轮候选循环；这会增加模型调用次数并降低速度和稳定性。

## 安全与清理

- 不访问当前工作目录之外的项目；
- 不传 shell 字符串，只传结构化参数；
- 不绕过 pip 写入位置限制；
- `success=true` 后不要重复创建环境；
- 保留 winner，确认失败环境已经清理；
- 如实报告 `bubblewrap` 或 `rlimits-only`，不要把普通 venv 描述为系统级沙箱。

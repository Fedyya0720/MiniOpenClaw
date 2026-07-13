# MiniOpenClaw Agent → PACS 自然语言 E2E 报告

日期：2026-07-13  
后端：`DeepSeekBackend`（模型 `deepseek-v4-flash`）  
目标：`sampleproject` 的临时干净副本

## 路由测试

自然语言要求只识别方案、不安装。Agent 轨迹：

```text
skill_read(python-env-builder)
→ glob / bash / read 项目侦察
→ 输出 pacs_build 参数计划
```

Agent 首次尝试用 `read` 读取目录而失败，随后改用 glob/ls 并完成恢复。该阶段未调用 `pacs_build`。

## 完整安装测试

输入为自然语言，不直接指定工具调用结构。Agent 轨迹：

```text
skill_read(python-env-builder)
→ bash/read/glob 识别 pyproject、Python 要求和 sample 模块
→ pacs_build(
     project_path=/tmp/mini-agent-pacs-e2e/sampleproject,
     python_version=3.14,
     max_parallel=2,
     max_attempts=8,
     install_project=true,
     validation_modules=[sample],
     timeout=180)
→ bash 独立导入与函数验证
→ read requirements.lock / PACS_REPORT.md
→ 最终自然语言汇报
```

## 结果

- `pacs_build.success=true`
- 搜索 1 轮、2 个真实候选（peppercorn 0.6 / 0.5）
- 项目本体 editable 安装成功
- `pip check`：无损坏依赖
- `import sample`：成功
- `sample.simple.add_one(41) == 42`：成功
- `requirements.lock`：存在
- `PACS_REPORT.md`：存在
- 失败/非选中环境已清理，只保留 1 个成功环境
- Agent 最终回复准确报告环境、锁文件、报告、轮次和候选数

## 回归

Skill 官方结构校验通过。全量测试 43/43 通过，并将 `ResourceWarning` 视为错误；`git diff --check` 通过。

## 结论

本次证明调用主体是 MiniOpenClaw Agent：模型自主加载 Skill、选择并传参 `pacs_build`、读取 observation、执行二次验证并形成最终回复。外部 Codex 仅启动 CLI、检查结构化轨迹和独立复核产物。

# PACS 真实端到端执行计划

## 等级与执行方式

L，单代理串行。先稳定版本与候选契约，再实现编排和外部入口，最后运行真实联网验收。

## 阶段

1. 版本发现：PyPI JSON、缓存、注入目录、specifier 过滤。
2. 编排：批次创建、并行安装、失败约束、下一批次、验证、freeze、报告和清理。
3. 接入：`pacs_build` 工具、CLI、Skill 文档。
4. 验证：确定性本地 E2E、真实 PyPI 冲突 E2E、35 项既有回归与新增测试。
5. 清理：删除失败环境和临时测试项目，只保留明确的验收证据。

## 回滚与安全

- 构建输出只写目标项目的 `.miniopenclaw/`、`requirements.lock`、`PACS_REPORT.md`。
- 失败时尽力清理本轮环境并输出失败报告。
- Agent 高层工具继续走执行确认策略。

## 验收命令

- `python -m unittest discover -s tests -v`
- `python -m pacs.cli <fixture> --max-parallel 2 --max-attempts 4`
- 对成功环境执行 import，并核查 lock/report/constraint DB。

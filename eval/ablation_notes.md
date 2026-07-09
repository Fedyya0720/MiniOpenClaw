# 消融草稿（Day3 · 样本轨迹）

- **变量**：system-prompt（有 / 无），其余（任务集、模型 deepseek-v4-flash）固定
- **固定项**：`SAMPLE_TASKS` 三条（read-config / list-dir / read-code），样本轨迹结构一致
- **结果**：有 system-prompt = 1.00 / 无 system-prompt = 0.00；token 有 system-prompt 更高（多了工具说明）
- **归因**：无 system-prompt 时 agent 不知道 `<tool_call>` 约定 → 从不调工具 → 全失败
- **局限**：样本量太小（各 3 条）、样本是构造的；D4 起用真轨迹、每组多次运行取均值再下结论

# Agent PACS E2E 执行计划

执行等级 L，串行执行：清理旧副本 → 更新并校验 Skill → 增加按需 Skill 加载和轨迹 → 自然语言路由测试 → 自然语言安装测试 → 独立复核 → 全量回归 → 清理。

真实模型必须是 `DeepSeekBackend`。FakeBackend 结果不得计入验收。工具权限确认按用户明确授权使用 `--auto-approve`，权限层 deny 仍不可绕过。

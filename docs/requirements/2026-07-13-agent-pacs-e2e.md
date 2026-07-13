# MiniOpenClaw Agent 调用 PACS 验收

## 目标

证明 MiniOpenClaw Agent 能从自然语言自主召回 `python-env-builder`、加载 Skill、调用 `pacs_build`，并完成真实项目环境安装，而非由外部 Codex 直接调用 PACS API。

## 验收

1. 路由测试轨迹包含 `skill_read(name=python-env-builder)`。
2. 安装测试从自然语言入口运行，使用 `--auto-approve` 执行用户已授权的确认项。
3. 安装轨迹包含 Agent 发起的 `pacs_build`，observation 为 `success=true`。
4. 最终环境通过 `pip check` 和主模块 import，并存在 lock/report。
5. 原始桌面仓库不被修改，临时测试副本在验收后清理。

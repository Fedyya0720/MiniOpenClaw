# 项目记忆

## 技术栈

- Python 3.11 命令行 Agent，核心采用 ReAct 主循环。
- 大模型后端使用 OpenAI 兼容接口；未配置 API key 时使用 FakeBackend。

## 项目约定

- 优先沿用现有轻量框架，新增能力通过独立模块和既有注册点接入。
- 项目级长期记忆写入 `MEMORY.md`，只记录跨会话仍成立且会影响未来行为的信息。
- 不在记忆中保存 API 密钥、密码、令牌或个人隐私。

## 常用命令

- 自检：`python -m agent.cli --selfcheck`
- 运行任务：`python -m agent.cli "任务描述"`
- 运行测试：`python -m unittest discover -s tests`

## 已知边界

- `agent/context.py` 只管理单次运行的上下文窗口，不提供跨会话持久化。
- 长期记忆不是代码库检索系统；大型只读知识应由检索能力处理。

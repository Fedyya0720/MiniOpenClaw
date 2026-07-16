# MiniOpenClaw

> 一个运行在命令行中的通用智能体：用户用自然语言描述任务，大模型判断下一步是直接回答还是调用工具；程序负责检查权限、执行工具、保存结果，并把结果送回模型，形成“判断—行动—观察”的闭环。

## 这是什么

MiniOpenClaw 是一个 Claude Code 式的命令行 Agent：

- 一个 **ReAct 主循环**（`agent/loop.py` + `agent/strategy.py`）反复调用 **大模型后端**（`backend/`）；
- 模型输出 **工具调用**（read/write/bash/edit/grep/glob/web_fetch/task/…），主循环执行工具、把结果喂回模型，直到任务完成；
- 叠加 **MCP**（可插拔外部工具）、**Skills**（可加载领域能力）、**安全层**（权限/沙箱/注入防护）与 **PACS** 子系统（Python 环境自动配置）。

```
用户
 │  单次 CLI / 交互式 TUI
 ▼
Backend（DeepSeek 或 FakeBackend）
 │  返回文本、工具调用和 token usage
 ▼
ReAct 执行策略（agent/strategy.py）
 ├─ 上下文预算与压缩（agent/context.py）
 ├─ 权限判断（agent/permissions.py）
 ├─ 工具调度（tools/）
 ├─ 长输出文件化保存
 └─ 工具 trace 记录（agent/tracer.py / trace.py）
 │
 ▼
ToolRegistry
 ├─ 文件、命令、检索、网页和任务列表
 ├─ 项目记忆（tools/memory.py）与 Skill（tools/skills.py）
 ├─ MCP 外部工具（mcp/）
 └─ PACS 高层入口及底层环境工具（pacs/ + tools/pacs_tools.py）
```

## 目录结构

| 模块 | 职责 |
|------|------|
| `agent/` | CLI 入口、ReAct 主循环、执行策略、上下文管理、权限、TUI、trace |
| `backend/` | DeepSeek API 客户端、FakeBackend、图像工具、OpenAI 兼容 server |
| `prompt/` | `render_prompt(messages, tools)` 对话模板渲染与工具调用解析 |
| `tools/` | 内置工具（fs/shell/grep/glob/web_fetch/memory/skills/security/pacs/resolver/env）|
| `mcp/` | 最小 MCP 客户端（stdio + JSON-RPC）与示例 server |
| `skills/` | Skill 加载器与领域 Skill（codebase-guide / csv-quick-report / python-debug / python-env-builder）|
| `security/` | 权限/沙箱/注入防护实现与红队测试 |
| `resolver/` | 依赖解析、约束图、组合求解、失败解析与评分（PACS 底层）|
| `envpool/` | 隔离虚拟环境池、沙箱、安装与资源管理（PACS 执行层）|
| `pacs/` | PACS 高层入口：并行候选搜索、失败学习、环境固化 |
| `eval/` | 任务集、指标评测、裁判模型与消融实验 |
| `demo/` | 演示项目（B1-simple / B2-conflict / pacs_demo.md）|
| `tests/` | 单元测试与集成测试 |
| `docs/` | 技术设计文档、测试说明与报告 |

> 各模块的设计决策记录在各自的 `README.md` 中；项目级长期记忆见 `MEMORY.md`；完整架构与 PACS 设计见 [`docs/TECHNICAL_DESIGN.md`](docs/TECHNICAL_DESIGN.md)。

## 快速开始

```bash
# 1. Python 环境（agent 侧不吃显存）
conda create -n openclaw python=3.11 && conda activate openclaw
pip install -r requirements.txt

# 2. 配置大模型 API（可选；不配也能用 FakeBackend 跑通骨架）
cp .env.example .env
# 编辑 .env，填入你的 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL
# CLI 启动时会自动加载 .env，无需每次手动 export

# 3. 先跑通骨架的"假后端"自检
python -m agent.cli --selfcheck

# 4. 运行一个真实任务
python -m agent.cli "创建 hello.py 并运行输出当前时间"

# 5. 运行测试
python -m unittest discover -s tests
```

## CLI 用法

```bash
python -m agent.cli "任务描述"                 # 单次任务
python -m agent.cli --tui                     # 交互式 TUI 模式
python -m agent.cli --selfcheck               # 自检骨架
python -m agent.cli --security-check          # 安全配置检查

python -m agent.cli --image img.png "分析这张图"  # 附加图片
python -m agent.cli --max-turns 10 "任务"        # 限制最大轮次（默认 20）
python -m agent.cli --auto-approve "任务"        # 跳过权限确认
python -m agent.cli --serial "任务"              # 串行工具调用模式
python -m agent.cli -C /path/to/project "任务"   # 指定工作目录
```

## Docker 部署

```bash
docker build -t mini-openclaw .
docker run -it --env-file .env -v $(pwd):/app mini-openclaw bash
# 进入容器后：python -m agent.cli --selfcheck
```

## PACS 子系统

PACS（Parallel Adaptive Compatibility Search，并行自适应兼容性搜索）处理 Python 项目的环境配置：读取依赖声明，生成有限数量的版本候选，在隔离虚拟环境中并行验证，依据真实失败日志记录不兼容组合，最后输出通过校验的环境与锁定文件。设计理念是——自然语言理解交给大模型，而依赖解析、候选求解、安装、验证和证据记录由确定性代码完成，降低模型幻觉率。详见 `pacs/`、`resolver/`、`envpool/` 与 `docs/TECHNICAL_DESIGN.md`。

## 测试

当前基线 144 个测试全部通过。测试环境、单项回归、完整测试、PACS 离线测试
和真实 TUI 验收步骤见 [`docs/TESTING.md`](docs/TESTING.md)。

## 约定

- 每个模块自带一个 `README.md`，记录设计决策。
- 项目级长期记忆写入 `MEMORY.md`，只记录跨会话仍成立且影响未来行为的信息；不保存密钥、密码、令牌或个人隐私。

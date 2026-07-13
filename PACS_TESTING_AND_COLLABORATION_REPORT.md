# PACS 测试与协作复现报告

## 1. 当前版本概览

当前开发分支为 `codex/pacs-env-builder`，基于 `origin/main@aa86294`，尚未合并。

本版本已具备：

- 从 `requirements.txt` 或 PEP 621 `pyproject.toml` 解析直接依赖；
- 从 PyPI JSON API 查询真实、稳定且未被完全 yanked 的发布版本；
- 在多个隔离 venv 中并行运行真实 pip；
- 解析安装失败并将版本冲突持久化到 SQLite 约束图；
- 根据已知冲突剪枝并继续搜索；
- editable 安装项目本体、运行 `pip check` 和指定模块 import；
- 生成 `requirements.lock` 和 `PACS_REPORT.md`；
- 清理失败或未选中的环境，只保留最终环境；
- 通过 `pacs_build` 高层工具、`python -m pacs.cli` 和 MiniOpenClaw Agent 使用；
- 通过 `skill_read` 按需加载 `python-env-builder` Skill；
- 用 `--trace` 将 Agent 工具调用和 observation 记录为 JSONL。

## 2. 使用 TUI 测试

### 2.1 准备运行环境

建议在 MiniOpenClaw 仓库根目录创建独立运行环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

配置真实模型后端：

```bash
export DEEPSEEK_API_KEY="<your-key>"
```

也可以将该变量放在仓库根目录 `.env` 中。不要提交 `.env`。

启动 TUI：

```bash
python -m agent.cli --tui --auto-approve
```

`--auto-approve` 会自动放行权限层的 `confirm`，适合受控测试；安全层的 `deny` 仍然不会被绕过。若希望逐次确认，去掉该参数。

### 2.2 最推荐的 TUI 说法

把路径替换为本机仓库路径：

```text
请为 /absolute/path/to/project 实际配置一个可用的 Python 环境。
请自主加载合适的 Skill，使用 PACS 完成真实依赖安装和项目本体安装，
验证 <module_name> 模块可以导入，并在完成后准确汇报环境、锁文件、
报告、搜索轮次和候选数。
```

例如测试 Flask：

```text
请为 /Users/me/test/flask 实际配置一个可用的 Python 环境。
请自主加载合适的 Skill，使用 PACS 完成真实依赖安装和项目本体安装，
验证 flask 模块可以导入，并汇报环境路径、requirements.lock、
PACS_REPORT.md、搜索轮次和候选数。
```

只分析、不安装：

```text
请分析 /absolute/path/to/project 的 Python 环境配置方案。
先加载最合适的 Skill，只说明准备调用的工具与参数，不要执行安装。
```

遇到依赖冲突时：

```text
请使用 PACS 为 /absolute/path/to/project 解决 pip 依赖冲突。
实际尝试候选组合，失败约束要写入约束图；成功后安装项目本体，
运行 pip check 和 import <module_name>，生成锁文件和报告。
```

### 2.3 TUI 中应观察到什么

理想工具调用顺序：

```text
skill_read(name="python-env-builder")
→ 项目侦察（read / glob / bash）
→ pacs_build(...)
→ 可选的 bash 二次验证
→ read requirements.lock / PACS_REPORT.md
→ 最终自然语言汇报
```

成功回复至少应包含：

- `environment_path`：最终虚拟环境；
- 激活命令：`source <environment_path>/bin/activate`；
- `lock_path`：通常是 `<project>/requirements.lock`；
- `report_path`：通常是 `<project>/PACS_REPORT.md`；
- 搜索轮次和候选数量；
- 项目本体是否安装；
- `pip check` 和 import 是否通过。

只有 `pacs_build` observation 中 `success=true` 才能判定完成。仅创建 venv、解析依赖或生成候选不能视为安装成功。

### 2.4 文件产物

项目根目录：

```text
requirements.lock
PACS_REPORT.md
.miniopenclaw/pacs/
├── constraint_graph.db
├── version-index.json
└── envs/
    └── env-...-r...-c.../
```

- `requirements.lock`：最终环境的 `pip freeze`；
- `PACS_REPORT.md`：搜索结果、轮次、候选、耗时和环境路径；
- `constraint_graph.db`：已发现冲突及推导约束；
- `version-index.json`：PyPI 版本查询缓存；
- `envs/`：最终成功环境，失败环境应已清理。

## 3. 已验证的 Agent 自然语言流程

我们使用真实 `DeepSeekBackend`（测试时模型为 `deepseek-v4-flash`）对 `sampleproject` 的干净副本执行了自然语言 E2E。不是由外部脚本直接调用 `PACSBuilder`。

实际轨迹：

```text
自然语言任务
→ skill_read("python-env-builder")
→ Agent 检查 pyproject.toml、src/sample 和 Python 版本
→ Agent 自主调用：
   pacs_build(
     project_path=".../sampleproject",
     python_version="3.14",
     max_parallel=2,
     max_attempts=8,
     install_project=true,
     validation_modules=["sample"],
     timeout=180
   )
→ Agent 使用 bash 再次验证 import sample 和 add_one(41) == 42
→ Agent 读取 requirements.lock 和 PACS_REPORT.md
→ Agent 汇报最终环境与搜索结果
```

结果：1 轮、2 个真实候选、项目本体安装成功、`pip check` 通过、`import sample` 通过、只保留 1 个成功环境。全量自动化测试为 43/43 通过。

详细证据见 `outputs/agent-pacs-natural-language-e2e-report.md`。

## 4. 当前 Agent 与 PACS 内部流程

```text
用户自然语言
  ↓
MiniOpenClaw AgentLoop
  ↓  根据 Skills catalog 判断领域
skill_read("python-env-builder")
  ↓
项目侦察与参数推断
  ↓
pacs_build
  ↓
PACSBuilder
  ├─ parse_dependencies
  ├─ VersionIndex 查询/缓存 PyPI 真实版本
  ├─ ConstraintGraph 加载历史冲突
  ├─ generate_combinations 生成并剪枝候选
  ├─ EnvironmentPool 创建隔离 venv
  ├─ parallel_install 并行运行 pip
  ├─ parse_failure + ConstraintGraph.infer
  ├─ editable 安装项目本体
  ├─ pip check + validation_modules import
  ├─ pip freeze → requirements.lock
  ├─ 生成 PACS_REPORT.md
  └─ 清理非成功环境
  ↓
Agent 解析 JSON observation
  ↓
可选二次验证并向用户汇报
```

## 5. 五个真实仓库的复现

### 5.1 仓库链接与测试提交

| 仓库 | GitHub | 测试提交 | import 模块 |
|---|---|---|---|
| uv-fastapi-example | [astral-sh/uv-fastapi-example](https://github.com/astral-sh/uv-fastapi-example) | `a1e3131` | `app.main` |
| Flask | [pallets/flask](https://github.com/pallets/flask) | `36e4a824` | `flask` |
| sampleproject | [pypa/sampleproject](https://github.com/pypa/sampleproject) | `621e497` | `sample` |
| Requests | [psf/requests](https://github.com/psf/requests) | `f361ead0` | `requests` |
| Poetry | [python-poetry/poetry](https://github.com/python-poetry/poetry) | `f4670233` | `poetry` |

复现指定提交：

```bash
git clone https://github.com/pypa/sampleproject.git
git -C sampleproject checkout 621e497
```

其余仓库同理。建议一个仓库一个仓库测试，避免同时创建大量 venv 和 pip 下载任务。

### 5.2 实测结果

测试平台为 macOS、Python 3.14.4。测试使用真实 PyPI、真实并行 pip、editable 项目安装、`pip check` 和主模块 import。

| 仓库 | 直接依赖 | 候选/轮次 | PACS 耗时 | 项目安装 | pip check | import | lock 行数 |
|---|---:|---:|---:|---|---|---|---:|
| sampleproject | 1 | 2 / 1 | 19.31s | 通过 | 通过 | 通过 | 3 |
| uv-fastapi-example | 1 | 2 / 1 | 24.67s | 通过 | 通过 | 通过 | 12 |
| Requests | 4 | 2 / 1 | 19.06s | 通过 | 通过 | 通过 | 6 |
| Flask | 6 | 2 / 1 | 27.95s | 通过 | 通过 | 通过 | 8 |
| Poetry | 22 | 2 / 1 | 58.15s | 通过 | 通过 | 通过 | 37 |

五个仓库环境构建成功率为 5/5。Poetry 覆盖了括号式 PEP 508 约束、平台 marker 和 Git 直接依赖。

## 6. 当前限制

1. **TUI 尚未做自动化驱动测试**：自然语言 Agent E2E 已通过 CLI 完成；TUI 复用相同注册表、Skill、权限层和后端，但仍建议合作者手工走一遍上述对话。
2. **不是完整 SAT/PubGrub 求解器**：当前通过候选枚举和约束剪枝搜索，超大版本空间仍可能效率较低。
3. **PEP 440/508 支持是轻量实现**：常用范围、marker、直接引用已覆盖，但复杂 extras、复合 marker、预发布策略仍需增强。
4. **项目侦察调用偏多**：Agent E2E 对简单 sampleproject 使用了多轮 read/bash/glob；模型延迟约占完整流程一半。
5. **重复构建的环境复用有限**：版本缓存和约束图可复用，但成功环境尚缺少稳定 manifest、健康检查和自动复用策略。
6. **测试范围**：当前验证环境构建、项目安装和 import，不等于运行各上游仓库完整的 pytest/nox/tox 套件。
7. **网络与平台差异**：PyPI、Git、证书、系统编译器、Python ABI 或平台 wheel 可用性会影响复现耗时和结果。

## 7. 后续改进方向

### P0：提升 Agent 调用效率与可观测性

- 新增 `project_inspect` 工具，一次返回依赖文件、`requires-python`、构建后端和候选 import 模块；
- 将常见 Agent 流程压缩为 `skill_read → project_inspect → pacs_build → 汇报`；
- 为 TUI 增加 `--trace` 或会话内轨迹导出；
- 默认关闭后端完整 payload DEBUG，改为可选诊断日志；
- 修正工具 schema 与模型行为细节，例如避免对目录调用 `read`、避免传入未声明的 `offset`。

### P0：增强环境生命周期

- 为成功环境持久化 manifest，记录 Python、候选、lock hash、创建时间和健康状态；
- 重复任务优先验证并复用已有成功环境；
- 提供明确的 `pacs clean/list/activate` CLI；
- 增加磁盘配额、并行度和中断后的清理机制。

### P1：增强解析和求解

- 使用完整 PEP 440/508 语义或成熟 resolver 库；
- 依据 Python 版本、OS、架构、wheel tag 和 yanked 状态在安装前剪枝；
- 从 pip `--report` 或结构化元数据提取更准确的冲突双方；
- 区分稳定冲突与网络/证书/磁盘等瞬态失败；
- 引入信息增益、历史成功率和包影响范围作为候选排序依据。

### P1：扩展构建系统

- 原生支持 uv、Poetry、PDM 和 Conda 锁文件；
- 支持 extras、dev/test dependency groups；
- 可选运行项目自带 smoke test、pytest/nox/tox；
- 输出跨平台 lock 或按平台拆分 lock。

### P2：性能评测

- 建立固定冲突基准集；
- 对比串行 pip、并行无反馈和 PACS；
- 记录 `T_success`、尝试数、下载缓存命中、CPU、内存和磁盘峰值；
- 将 Agent 模型耗时与 PACS 安装耗时分开统计。

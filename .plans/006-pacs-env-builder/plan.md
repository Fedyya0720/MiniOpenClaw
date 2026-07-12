# Step 006: PACS 并行自适应约束搜索子系统

## Goal

在 MiniOpenClaw 现有 ReAct Agent 框架之上，实现**并行自适应约束搜索（PACS）**子系统，将 Python 环境配置从串行试错转变为多路并行探测 + 约束传播驱动的搜索。

入口：`skills/python-env-builder/`（SKILL.md 已创建）

## Day Mapping

PACS — 超越原始 10 天课程的新增子系统。依赖 Day 10 完成后的全部基础设施（ReAct loop、tool registry、skills loader、安全层）。

## Context

已有设计文档 `g07_Python环境配置智能体.md` 完整描述了 5 大功能模块。`skills/python-env-builder/SKILL.md` 已作为编排入口创建，定义了六阶段流程（Phase 0-6）和 8 个需实现的工具接口。

本计划覆盖从零到可运行的完整实现路径。

## Files

### 新建（11 个文件）

| # | 文件 | 内容 |
|---|------|------|
| 1 | `envpool/__init__.py` | 空包 |
| 2 | `envpool/manager.py` | `EnvironmentPool` 类：venv 创建/删除/路径跟踪/状态管理 |
| 3 | `envpool/install.py` | 并行 pip 安装器：`concurrent.futures.ThreadPoolExecutor` + 超时管理 |
| 4 | `tools/env_tools.py` | 注册 4 个 Tool：`env_create`, `env_run`, `env_status`, `env_cleanup` |
| 5 | `resolver/__init__.py` | 空包 |
| 6 | `resolver/dep_parser.py` | 依赖文件解析器：`requirements.txt` / `pyproject.toml` → `[DepSpec]` |
| 7 | `resolver/combinations.py` | 候选版本组合生成器：基于约束图剪枝，支持枚举策略 |
| 8 | `resolver/failure_parser.py` | pip 失败日志规则引擎：覆盖 15+ 种失败模式 → 结构化冲突约束 |
| 9 | `resolver/constraint_graph.py` | 约束图数据结构 + 传递推导算法 + SQLite 持久化 |
| 10 | `tools/resolver_tools.py` | 注册 4 个 Tool：`parse_deps`, `generate_combinations`, `parse_failure`, `infer_constraints` |
| 11 | `eval/tasks.py` | **修改**：新增 PACS 相关 E2E 测试任务 |
| 12 | `tools/base.py` | **修改**：`build_default_registry()` 注册 8 个新工具 |

### 约束与设计决策

1. **并行策略选型 A**（工具内自管理平行）：`env_run` 内部用 `ThreadPoolExecutor` 管理多进程 pip install，一次调用返回全部结果。对现有 ReAct loop 零侵入。
2. **简单 YAML 无外部依赖**：`resolver/dep_parser.py` 手写解析，不引入 `packaging` / `toml` 库，保持与项目现有依赖一致。
3. **SQLite 轻量持久化**：`constraint_graph.db` 用 `sqlite3`（标准库），零额外依赖。
4. **规则引擎朴素实现**：`failure_parser.py` 用正则 + if/elif 链，不引入 parser generator。

## Dependencies

- MiniOpenClaw 核心框架（Day 10 完成态）：ReAct loop、tool registry、skills loader、安全层
- 系统依赖：`ripgrep`（已有），`python3` 和 `pip`（目标环境标配）
- 无需新 pip 包

## Constraints

- 所有工具必须返回字符串（Tool 接口约束：`run(**kwargs) -> str`）
- 并行安装结果需序列化为文本供模型消费
- 约束图持久化文件保持在项目 `~/.cache/miniopenclaw/` 或工作目录下
- 所有新模块须通过 `python -c "from ... import ..."` 无报错

## Risks

| 风险 | 缓解 |
|------|------|
| Windows 上 venv 创建路径含空格 | `manager.py` 统一用 `subprocess` + 引号包裹 |
| 并行 pip 竞争全局锁 | 每个 venv 隔离，pip 锁在 venv 内部互不干扰 |
| 失败规则引擎漏匹配 | 规则引擎输出 `unknown_error` 兜底，不遗漏；后续通过测试用例补规则 |
| 约束图规模增长 | SQLite 索引优化；会话层级 `T` 字段管理时效性 |
| 模型长上下文消化并行结果 | `env_run` 返回结构化摘要（成功/失败分节），完整日志可选展开 |

## Steps

### Step 1: `envpool/` 模块 — 环境池管理器
- `manager.py`: `EnvironmentPool` 类，`create(python_version, label)` → `Env(id, path, status)`
- `install.py`: `parallel_install(envs, packages, timeout)` → `[InstallResult]`
- 验证：创建 2 个 venv，各装不同包，互不影响

### Step 2: `tools/env_tools.py` — 注册环境池工具
- 4 个 Tool 实例，参数 JSON Schema
- 在 `build_default_registry()` 中注册
- 验证：`registry.get('env_create').run(python_version='3.10')` 返回 env_id

### Step 3: `resolver/` 模块 — 依赖解析 + 约束引擎
- `dep_parser.py`: 解析 `requirements.txt`（`pkg==ver`, `pkg>=ver` 等），`pyproject.toml`（`[project.dependencies]` 部分）
- `combinations.py`: 基于 dep spec + 约束图生成候选组合列表
- `failure_parser.py`: 规则引擎，覆盖 15+ pip 失败模式
- `constraint_graph.py`: 图数据结构 + 传递推导 + SQLite 持久化

### Step 4: `tools/resolver_tools.py` — 注册解析器工具
- 4 个 Tool 实例
- 在 `build_default_registry()` 中注册
- 验证：端到端调用链 `parse_deps → generate_combinations → parse_failure → infer_constraints`

### Step 5: 端到端集成验证
- 用 `skills/python-env-builder/SKILL.md` 指导一个真实 Python 项目环境配置
- 验证 Phase 0 依赖自检机制正常触发
- 验证 Phase 3 并行安装正常运行

### Step 6: 评估任务
- `eval/tasks.py` 增加 PACS E2E 任务
- 手动运行验证

## Success Criteria

1. `python -m agent.cli "配置 ./test-project 的环境"` 可用 PACS skill 完成配置
2. Phase 0 依赖缺失时正确提示用户
3. 并行安装 N 个环境的时间 < 串行安装单个环境的时间 × N（受限于资源，提前知会）
4. 约束传播可推导传递冲突（A↔B + B↔C → A↔C）
5. 所有新模块 `import` 无报错

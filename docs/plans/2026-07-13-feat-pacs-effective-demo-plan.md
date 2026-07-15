# PACS 增强 Demo 一天开发计划

> 基线：`origin/feat/pacs`
>
> 参考：吸收 `codex/pacs-env-builder` 的高层编排与真实 E2E 思路
>
> 环境：Linux Docker；工期约 1～1.5 天
>
> 实施状态（2026-07-13）：Demo 已完成并通过 Linux Docker 回归。

## 1. 交付目标

在 `feat/pacs` 现有底层模块上补齐一个稳定、可解释的完整 Demo：

```text
读取依赖
→ PyPI JSON 获取有限版本域
→ SAT/SMT 过滤硬冲突
→ 多因素评分排序
→ pip dry-run 全量依赖预求解
→ 多环境并行真实安装
→ 失败约束学习并重新求解
→ pip check/import 验证
→ lock + 报告 + 清理
```

正常使用由 Agent 调用一次 `pacs_build`。搜索、求解和重试由 `PACSBuilder` 控制，不依赖模型和skill逐个串联底层工具。

## 2. 本次范围

### 必须完成

- [x] `PACSBuilder` 高层编排器；
- [x] PyPI JSON 版本索引和本地缓存；
- [x] 有限版本域 SAT/SMT 求解；
- [x] 可解释的候选多因素评分；
- [x] `pip --dry-run --report` 全量依赖预求解；
- [x] 多 venv 并行真实安装；
- [x] 失败解析、约束持久化和下一轮重求解；
- [x] `pip check` 和指定模块 import 验证；
- [x] `requirements.lock` 和简洁 `PACS_REPORT.md`；
- [x] 失败环境清理；
- [x] Agent 工具 `pacs_build` 和最小 CLI；
- [x] Linux Docker 离线真实 pip E2E。

### 明确不做

- 不实现完整 PEP 440/508 通用求解器；
- 不预先解析所有 PyPI 包的完整历史依赖图；
- 不扩展 conda、CUDA 和系统依赖自动安装；
- 不做 Web UI、复杂图表和大型项目测试；
- 不处理 macOS 专属问题；
- 不合并参考分支的旧 AgentLoop。

## 3. 实现边界

### 3.1 PyPI JSON

新增 `resolver/version_index.py`：

- 请求 `https://pypi.org/pypi/<package>/json`；
- 过滤无文件、全部 yanked、明显不符合 `requires_python` 的版本；
- 首轮每个包只载入符合声明约束的最新 Top 5 稳定版本；
- 当前版本窗口候选耗尽时，每次再向旧版本扩展 5 个，默认最多 20 个；
- 精确 pin 始终直接保留，不受版本窗口限制；
- exact pin 不联网；
- 缓存到 `.mini-openclaw/pacs/version-index.json`；
- 网络失败时使用有效缓存；
- JSON 失败时优先回退项目本地有效缓存；
- Demo 可直接注入本地 catalog，保证离线运行。

### 3.2 SAT/SMT

使用固定版本的 `z3-solver`，只求解有限版本域：

- 每个直接依赖恰好选择一个版本；
- 版本必须满足项目声明的 specifier；
- Python 不兼容版本不可选择；
- 约束图中的已知坏组合不可同时选择；
- Z3 输出若干可行模型，再交给评分器排序。

传递依赖和平台最终正确性仍由 pip resolver 验证。若 Z3 在 Docker 中无法安装，允许回退现有有界枚举，但此时报告必须写明 `solver=enumeration-fallback`，不能声称运行了 SAT/SMT。

### 3.3 多因素评分

使用简单、确定、可解释的加权评分：

| 因素 | 建议权重 |
|---|---:|
| Python 兼容 | +30 |
| 有当前平台 wheel | +20 |
| 版本新鲜度 | 0～30 |
| 版本缓存命中 | +5 |
| 派生冲突风险 | 0～-30 |

每个候选返回总分和分项，不实现机器学习或自动调参。

### 3.4 全量依赖预求解

候选在创建正式安装环境前执行：

```bash
python -m pip install --dry-run --ignore-installed \
  --report <preflight.json> <candidate requirements>
```

- 成功：保存 pip 解析出的直接和传递依赖计划；
- 失败：解析 stderr，学习约束并跳过真实安装；
- 本地 Demo 追加 `--no-index --find-links <wheelhouse>`；
- dry-run 不是自研 resolver，而是对候选的真实 pip 预检。

### 3.5 报告

从 `BuildResult` 生成简洁 `PACS_REPORT.md`，只包含：

- 最终状态、solver、winner 和总耗时；
- 每轮候选、评分、preflight 和安装结果；
- 学到的约束数量；
- lock、报告和环境路径。

## 4. 最小代码改动

新增：

```text
pacs/__init__.py
pacs/__main__.py
pacs/builder.py
pacs/cli.py
resolver/version_index.py
resolver/solver.py
resolver/scoring.py
resolver/preflight.py
tools/pacs_tools.py
tests/test_pacs_demo.py
demo/pacs_demo/run_demo.sh
demo/pacs_demo/README.md
```

小幅修改：

- `requirements.txt`：固定 `z3-solver` 版本；
- `tools/base.py`：注册 `pacs_build`；
- `agent/permissions.py`：把 `pacs_build` 归为需要确认的执行工具；
- `skills/python-env-builder/SKILL.md`：默认调用一次 `pacs_build`。

数据类和报告生成暂时都放进 `pacs/builder.py`，避免过度拆分。

## 5. `PACSBuilder` 核心循环

1. 使用现有 `parse_project()` 读取依赖；
2. 从 PyPI JSON、缓存或本地 catalog 获得 Top-K 版本域；
3. SAT/SMT 应用声明约束和历史冲突，生成可行候选；
4. 评分器排序，取前 `max_parallel` 个候选；
5. 对一批候选并行执行 pip dry-run 预求解；
6. preflight 失败则解析日志、更新约束图，并继续补足安装批次；
7. preflight 成功的候选进入现有 envpool 并行真实安装；
8. 安装失败继续学习约束；
9. 安装成功执行 `pip check` 和 import；
10. 按候选排序选择第一个验证成功者；
11. `pip freeze` 生成 lock，输出 JSON/Markdown 报告；
12. 清理所有非 winner 环境。

要求：

- 网络、权限、磁盘、sandbox 和 unknown 错误不作为版本硬冲突；
- 所有退出路径清理非 winner 环境；
- 业务失败返回结构化 `success=false`；
- 沿用现有 argv-only、路径限制、durable log 和 sandbox。

## 6. 离线 Demo

用标准库生成三个本地 wheel：

```text
demo-core 1.0.0
demo-core 2.0.0
demo-plugin 1.0.0，要求 demo-core < 2
```

项目依赖：

```text
demo-core>=1,<3
demo-plugin==1.0.0
```

Demo 过程：

1. 本地 catalog 提供两个 core 版本；
2. SAT/SMT 排除已有硬冲突并生成候选；
3. 评分器优先尝试较新的 `core 2.0`；
4. pip dry-run 或真实 pip 得到依赖冲突；
5. failure parser 将冲突写入约束图；
6. 重新求解后选择 `core 1.0`；
7. 真实安装、`pip check` 和 import 成功；
8. 生成 lock/report，清理失败环境。

Demo 使用 `--no-index --find-links <wheelhouse>`，不依赖公网。

另加一个非阻断在线 smoke test，只验证 PyPI JSON 能获取小型公共包版本。

## 7. 一天排期

| 时间 | 工作 |
|---|---|
| 0～1 小时 | Linux 基线、分支、接口确认 |
| 1～2.5 小时 | PyPI JSON、缓存、本地 catalog |
| 2.5～4.5 小时 | 有限域 Z3 求解和评分 |
| 4.5～5.5 小时 | pip dry-run preflight |
| 5.5～8.5 小时 | `PACSBuilder` 完整循环、验证、清理 |
| 8.5～9.5 小时 | `pacs_build`、CLI、lock/report |
| 9.5～12 小时 | 本地 wheel E2E、Docker 回归、修复 |

超过时间盒后停止增加功能，只修 Demo、清理、工具调用和核心测试回归。

## 8. 验收线

- [x] Linux Docker 一条命令运行 Demo；
- [x] PyPI JSON、缓存和离线 catalog 有单测；
- [x] 报告明确记录 `z3` 或 fallback solver；
- [x] 候选包含评分总分和分项；
- [x] preflight 输出传递依赖计划或结构化失败；
- [x] 至少一个候选失败、一个候选成功；
- [x] 失败约束影响下一轮求解；
- [x] 至少两个候选可并行安装；
- [x] winner 通过 `pip check` 和 import；
- [x] 生成精确 lock 和 `PACS_REPORT.md`；
- [x] 失败环境被清理；
- [x] `pacs_build` 返回可解析 JSON，CLI 完成同一流程；
- [x] 离线 E2E 连续运行 3 次通过；
- [x] 原有 resolver、envpool、security 核心测试通过；
- [x] 如实报告 bubblewrap 或 rlimits-only。

建议命令：

```bash
python -m unittest tests.test_pacs_demo -v
bash demo/pacs_demo/run_demo.sh
python -m unittest discover -s tests -v
```

## 9. 进度落后时的降级顺序

1. 在线 PyPI smoke test降为手工验证，离线 catalog 保留；
2. 报告只保留必要表格，不做额外格式；
3. 评分只保留 Python 兼容、版本新鲜度、wheel 三项；
4. Z3 失败时回退现有枚举，并在结果中明确标记；
5. Agent 自动化 E2E 改为手工自然语言演示。

不能砍掉：`PACSBuilder`、pip preflight、真实并行安装、失败约束学习、下一轮搜索、成功验证、lock 和清理。

## 10. 最终演示

控制在 5 分钟：

1. 展示依赖和有限版本域；
2. 展示 SAT/SMT 候选及评分；
3. 展示 pip preflight 的完整依赖计划；
4. 展示 `core 2.0` 冲突和新约束；
5. 展示重求解后 `core 1.0` 成功；
6. 展示真实并行安装、`pip check` 和 import；
7. 展示 lock、报告、winner 和失败环境清理；
8. 说明边界：这是有限版本域上的约束求解与真实 pip 验证，不是完整通用 Python 依赖求解器。

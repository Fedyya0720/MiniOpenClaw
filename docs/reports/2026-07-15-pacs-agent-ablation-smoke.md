# PACS Agent 消融实验（初始 smoke）

日期：2026-07-15  
模型：`deepseek-v4-flash`  
状态：完成流程 1–2–3 的最小 smoke；正式多 trial 数据尚未收集。

## 问题与实验层次

主问题：给同一个 Agent 加入 `pacs_build` 高层工具后，是否比依赖低层工具的多轮试错更快、更省模型轮次，并更稳定地完成环境配置？

- **主消融（Agent A/B）**：`traditional-agent` 在评估进程内移除 `pacs_build` 与 PACS skill/强制提示；`pacs-agent` 保留生产配置。两组均经过真实 DeepSeek 多轮 ReAct，并由 runner 独立执行 `pip check` 与 import/smoke 验证。
- **辅助消融（PACS 2×2）**：直接调用 PACS，比较 serial/parallel × pruning off/on，用于区分并行和剪枝的贡献。

生产目录 `agent/`、`pacs/`、`resolver/`、`envpool/`、`tools/`、`skills/` 均未为实验修改。

## Agent A/B：离线真实 pip 冲突 smoke

项目由本地 wheels 组成，pip 真实执行 resolver、安装与验证：

- `demo-core`: 2.0.0 / 1.0.0
- `demo-plugin==1.0.0` 要求 `demo-core<2`
- `demo-addon`: 3.0.0 / 2.0.0 / 1.0.0

| 指标 | Traditional Agent | PACS Agent |
|---|---:|---:|
| 独立环境验证 | 通过 | 通过 |
| Agent 正常完成 | **否，达到 30 turns 上限** | 是 |
| 严格 task success | **0/1** | **1/1** |
| 端到端时间 | 110.67 s | 24.68 s |
| LLM calls / turns | 30 | 5 |
| Tool calls | 30 | 7 |
| Prompt + completion tokens | 313,931 | 25,275 |
| PACS candidate attempts | 不适用 | 4 |
| Agent 层安装请求 | 旧 trace 未按修正口径重算 | 1 次 `pacs_build` |

PACS 相对传统路径：

- 端到端快约 **4.48×**；
- LLM calls 减少 **83.3%**；
- tool calls 减少 **76.7%**；
- tokens 减少约 **91.9%**；
- PACS 记录 4 个 candidate attempts；旧 runner 曾把 `env_run` 中的 `pip check` 和 import specs 误计为安装工作，因此撤回原先报告的传统安装次数。修正后的正式 runner 只把带 `packages` 的 `env_run` spec、包含 `pip install` 的 shell 命令或一次 `pacs_build` 计为 Agent 层 `installation_requests`；PACS 内部候选数继续单列，不计算跨口径 attempt reduction。

需要严格区分两个结果：传统 Agent 确实在 turn 上限前留下了一个能通过独立验证的环境，但没有完成任务和最终汇报，返回的是 `[达到最大轮数上限，未完成任务]`。因此其 `environment_verified=true`，但 `agent_completed=false`，严格 success 必须记为失败。

PACS 内部记录：1 round、4 个候选、2 个失败、学习 1 条 observed constraint，PACS 本身耗时 5.62 s；剩余端到端时间来自模型选择/汇报与其他工具调用。

原始证据：`/tmp/miniopenclaw-agent-ablation-20260715-a/`。

## Agent A/B：真实 PyPI 冲突 smoke

2026-07-16 使用真实 PyPI 包完成了第二个 paired smoke。候选固定为 `requests==2.25.0`、`urllib3==2.0.0/1.26.20` 和三个 `certifi` 版本，两组使用相同项目、catalog、镜像环境、30 turns 上限与独立验证。

| 指标 | Traditional Agent | PACS Agent |
|---|---:|---:|
| 独立环境验证 | 通过 | 通过 |
| Agent 正常完成 | 否，达到 30 turns 上限 | 是 |
| 严格 task success | 0/1 | 1/1 |
| 到终止状态时间 | 115.39 s | 44.74 s |
| LLM calls / turns | 30 | 10 |
| Tool calls | 32 | 11 |
| Prompt + completion tokens | 358,526 | 73,515 |
| Agent 层安装请求 | 1 | 1 次 `pacs_build` |
| PACS candidate attempts | 不适用 | 4（2 failed preflight、2 install candidates） |

PACS 到终止状态快约 **2.58×**，turns 减少 **66.7%**，tool calls 减少 **65.6%**，tokens 减少约 **79.5%**。传统组已经留下可通过 runner 独立 `pip check` 与 import smoke 的环境，但继续进行无效的重复验证和文件写入，最终未能在 30 turns 内汇报，因此严格 success 为失败。这证明本次差异主要是 Agent 编排效率，而不是传统路径完全不能求出兼容版本。

PACS 在 1 round 内评估 4 个候选，其中两个 `urllib3==2.0.0` 组合产生真实 pip resolver failure；failure parser 提取 `requests==2.25.0` 与 `urllib3==2.0.0` 的 observed constraint，最终选择 `urllib3==1.26.20`。本次模型在调用 `pacs_build` 前先执行了 `glob/read/read`，偏离 fast-path prompt，因此 PACS 的 10 turns 不是人为构造的理想下界。

原始证据：`/tmp/miniopenclaw-agent-ablation-real-20260716-a/`。

## PACS 内部 2×2 smoke

| 组别 | 成功 | 总时间 / s | attempted | preflight | 学到约束 | 约束排除空间 |
|---|---:|---:|---:|---:|---:|---:|
| serial-naive | 1/1 | 3.40 | 3 | 3 | 0 | 0 |
| serial-pruning | 1/1 | 3.07 | 2 | 2 | 1 | 3 |
| parallel-naive | 1/1 | 5.61 | 5 | 5 | 0 | 0 |
| parallel-pruning | 1/1 | 5.03 | 4 | 4 | 1 | 3 |

该 fixture 清楚证明约束空间缩减：一次 core/plugin 失败得到的 observed constraint 能在 addon 三个版本形成的切片上排除 3 个组合；这不等于净避免执行 3 次，因为产生约束及同一 speculative batch 中已启动的组合可能已经执行。serial 条件下实际 evaluated candidates 从 3 降为 2。

它**不能证明并行更快**：该项目非常小，venv 创建与 speculative work 开销超过了并发安装收益，parallel 反而更慢且启动更多候选。这是合理反例，也说明 B3 时间结论必须来自体量更大的真实项目，不能用微型 fixture 制造结论。

原始证据：`/tmp/miniopenclaw-pacs-factorial-smoke-20260715-b/`。

## 下一阶段：真实项目 paired trials

正式报告建议采用真实 PyPI 包/固定仓库 revision，并把上述离线实验保留为 harness 校准与因果机制证据：

1. 小型控制项目：`pypa/sampleproject`，固定 commit `621e4974ca25ce531773def586ba3ed8e736b3fc`。
2. 中型项目：`psf/requests`，固定 commit `f361ead047be5cb873174218582f7d8b9fcd9f49`。
3. 冲突项目：固定 `requests==2.25.0`，候选 `urllib3==2.0.0/1.26.20`，再加入多个 `certifi` 版本形成可剪枝切片；所有包均来自真实 PyPI。
4. 复杂项目可再加入 Poetry，但应单独报告，避免一个重型 outlier 掩盖其余结果。

每项目至少 5 个 paired blocks，block 内随机化 A/B 顺序，trial 之间顺序执行。两组固定同一模型、prompt 公共部分、镜像、Python、缓存策略、max turns 和独立验证。镜像通过进程级 `PIP_INDEX_URL`/`PIP_TRUSTED_HOST` 传递；当前 `pacs_build` 并不支持 skill 文档中示例的 `env` 参数。

## 限制

- 当前每组仅 1 次，数字只能作为 smoke，不是统计结论。
- Agent 输出存在模型随机性，正式报告须使用配对重复并报告 median/IQR 与 raw rows。
- 离线 fixture 是真实 pip 行为，但不是公开生态项目。
- Agent A/B 同时消融了高层工具、PACS skill 和相应 fast-path prompt；它回答的是“完整 PACS 能力加入 Agent 是否有用”，不是单独某一代码函数的贡献。
- `installation_requests` 统一按 Agent 发起的真实安装请求计数：带 `packages` 的 `env_run` spec、包含 `pip install` 的 shell 命令或一次 `pacs_build`；`pip check` 和 import 验证不计。PACS 的 candidate/preflight 数另列，不能与该指标直接计算 reduction。

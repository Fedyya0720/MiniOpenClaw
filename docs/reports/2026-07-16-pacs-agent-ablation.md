# PACS Agent 消融实验结果

日期：2026-07-16  
模型：`deepseek-v4-flash`

## 实验设置

实验包含两部分：

1. **端到端 Agent A/B**：比较不含 `pacs_build` 的 Traditional Agent 与包含完整 PACS tool、skill 和 fast-path prompt 的 PACS Agent。
2. **PACS 内部 2×2**：比较 serial/parallel × pruning off/on，区分并行调度与约束学习的作用。

### 端到端项目

主实验使用固定的真实 PyPI 包候选：

- `requests==2.25.0`
- `urllib3==2.0.0/1.26.20`
- `certifi==2025.1.31/2024.12.14/2023.11.17`

两组使用相同模型、自然语言任务、候选版本、独立验证标准和 **60-turn 共同上限**。共运行 5 个 paired blocks，block 内随机化执行顺序，trials 顺序运行。

严格成功要求：

- 环境独立通过 `pip check`；
- `requests`、`urllib3`、`certifi` 可导入；
- 安装版本来自固定候选，且 `urllib3==1.26.20`；
- Agent 在轮次上限内完成最终汇报，并报告独立验证通过的环境。

每个 trial 在独立 Python 子进程和 trial-local 项目、HOME、pip cache、环境池、constraint graph 与 trace 中运行。全部 trials 的 worker 路径隔离检查通过，实验前后 workspace fingerprint 未变化。

## 端到端 Agent A/B 结果

| 指标（median，IQR） | Traditional Agent | PACS Agent |
|---|---:|---:|
| 严格成功率 | **4/5（80%）** | **5/5（100%）** |
| 独立环境验证 | 5/5 | 5/5 |
| Agent 时间 / s | 260.87（33.36） | 47.68（6.68） |
| Agent turns | 56（1） | 12（2） |
| Tool calls | 64（3） | 13（1） |
| Tokens | 1,373,589（384,607） | 88,981（21,341） |
| Agent 层安装请求 | 10（2） | 1（0） |
| PACS candidate attempts | 不适用 | 4（0） |
| 达到 60-turn 上限 | 1/5 | 0/5 |

### 配对完成时间

5 个 paired blocks 中：

- 双方均严格成功：**4**；
- 仅 PACS 成功：**1**；
- 仅 Traditional 成功：0；
- 双方均失败：0。

仅在双方均成功的 4 个 blocks 上比较完成性能：

| 配对指标 | Median | IQR |
|---|---:|---:|
| Traditional/PACS 完成时间比 | **5.72×** | 1.18 |
| Turns 减少（Traditional − PACS） | **43.5** | 2.75 |
| Tool calls 减少（Traditional − PACS） | **50.5** | 5.75 |
| Tokens 减少（Traditional − PACS） | **1,341,058** | 265,519 |

在相同任务和共同 60-turn 上限下，PACS Agent 5/5 完成，Traditional Agent 4/5 完成。双方均完成的 blocks 中，PACS 的完成时间中位数约为 Traditional 的 **1/5.72**，同时显著减少模型轮次、工具调用、tokens 和安装请求。

Traditional 的 4 个成功 trials 分别在 52、55、56、56 turns 完成，另有 1 个 trial 达到 60-turn 上限。因此 60 turns 已能产生 4 个双方成功 blocks并支持配对完成时间比较，但对 Traditional 仍是接近边界的预算；本报告同时保留成功率与 cap-hit 结果，不把 capped trial 当作完成时间。

## PACS 内部机制实验

为分别观察 parallel 和 pruning 的正向作用，使用两个受控复杂项目各运行 5 个随机化 blocks；每个项目包含 serial/parallel × pruning off/on 四个条件，共 20 个 trials。另保留原微型项目作为负对照。

### Parallel-speed：正向并行收益

该项目包含 4 个有序候选 wheel，每个 wheel 含 16 MiB 固定 payload。四个候选均通过 preflight；前三个安装成功后在 validation 失败，第四个为 winner。因此 serial 必须依次完成四次安装，parallel 可以每批重叠两个安装。Pruning 在该项目中没有可学习冲突，理论上不改变候选集合。

所有 20 个 trials 均成功，且每次都得到 3 个 validation failures 和第 4 个 winner。

| 条件 | 成功率 | 时间 / s（median，IQR） | Attempted | Preflight | 最大并发 preflight |
|---|---:|---:|---:|---:|---:|
| serial-naive | 5/5 | 12.888（0.362） | 4 | 4 | 1 |
| serial-pruning | 5/5 | 13.505（0.962） | 4 | 4 | 1 |
| parallel-naive | 5/5 | 11.311（0.828） | 4 | 4 | 2 |
| parallel-pruning | 5/5 | 11.215（1.314） | 4 | 4 | 2 |

结果：

- 5/5 blocks 的平均 parallel effect 均为正；
- Parallel 主效应节省 **1.736 s**（median，IQR 0.407）；
- Parallel install batch 的 overlap factor 最低为 1.68，中位约为 1.94；
- 所有条件 attempted/preflight 都为 4，说明时间差来自相同候选工作发生重叠，而不是少做候选。

该项目证明：当安装阶段足够重且多个失败候选位于 winner 之前时，PACS 的并行调度可以产生稳定的正向总时间收益。

### Pruning-amplifier：正向剪枝收益

该项目包含 2 个 core 版本、1 个 plugin 版本和 10 个 addon 版本，共 20 个组合。`amp-plugin==1.0.0` 要求 `amp-core<2`；一条 observed exact constraint 可以排除 `amp-core==2.0.0` 跨 10 个 addon 版本的完整坏 slice。

所有 20 个 trials 均成功。Pruning-on 在每个 trial 都学习 1 条目标约束，并排除 10 个组合。

| 条件 | 成功率 | 时间 / s（median，IQR） | Attempted | Preflight | 学习约束 | 约束排除空间 |
|---|---:|---:|---:|---:|---:|---:|
| serial-naive | 5/5 | 5.148（0.993） | 4 | 4 | 0 | 0 |
| serial-pruning | 5/5 | 4.303（0.538） | 2 | 2 | 1 | 10 |
| parallel-naive | 5/5 | 7.910（1.360） | 6 | 6 | 0 | 0 |
| parallel-pruning | 5/5 | 6.573（0.490） | 4 | 4 | 1 | 10 |

结果：

- Serial attempted/preflight 从 4 降至 2，减少 **50%**；
- Parallel attempted/preflight 从 6 降至 4，减少 **33%**；
- 5/5 blocks 的 serial 和 parallel wall time 都改善；
- Pruning 主效应节省 **0.949 s**（median，IQR 0.503）；
- Parallel × pruning interaction 为 **+0.118 s**（median，IQR 0.660）。

`约束排除空间=10` 表示最终 learned constraint 从完整候选空间排除十个组合；它不等同于净避免十次执行，因为约束产生前已经启动的 speculative candidates 仍计入 attempted。

### 微型项目：负对照

原 2 × 1 × 3 微型 fixture 的四条件也各运行 5 次。它证明了真实并发和约束学习，但 parallel 主效应为 **−1.799 s**，即 parallel 更慢；pruning 主效应节省 0.288 s。

该负对照说明 parallel 并非对所有项目都更快：在短安装任务中，额外 venv 创建和 speculative scheduling 开销可能超过并发收益。它与 parallel-speed 的正向结果共同说明，并行收益取决于候选安装成本和任务规模。

## 结论

端到端结果表明，完整 PACS 能力能够显著提高 Agent 的环境配置效率。在双方均成功的 paired blocks 中，PACS 的完成时间中位数快 **5.72×**，并减少约 43.5 个 Agent turns、50.5 次 tool calls 和 134 万 tokens。PACS 还将 Agent 层安装请求的中位数从 10 降至 1。

Traditional Agent 并非完全无法找到兼容环境：所有 trials 最终都有可独立验证的环境，但其中一个未能在 60 turns 内完成最终汇报。PACS 的主要端到端价值是把依赖发现、候选求解、安装、失败解析、约束学习和验证封装成高层操作，避免模型在低层工具之间反复安装和重复验证。

内部机制实验进一步表明：

- 在 16 MiB wheel、三个 validation-failed 候选位于 winner 之前的项目中，parallel 主效应稳定节省 1.736 s，5/5 blocks 为正；
- 在 20 组合 conflict amplifier 中，一条 exact constraint 排除 10 个组合，使 serial 工作量减少 50%、parallel 工作量减少 33%，并节省 0.949 s；
- 微型负对照中 parallel 仍然更慢，说明并行收益取决于任务规模，而不是自动成立。

因此，本实验支持的结论是：**PACS 显著改善了端到端 Agent 的完成时间和资源效率；约束学习能够大幅减少无效候选；并行执行在安装成本足够高时能够稳定加速，而在微型任务中可能因调度开销变慢。**

## 数据

### 共同 60-turn Agent A/B

- [Raw trials](artifacts/2026-07-16-pacs-ablation-60turn/agent-trials-raw.jsonl)
- [Raw summary](artifacts/2026-07-16-pacs-ablation-60turn/agent-summary-raw.json)
- [Final path-gate summary](artifacts/2026-07-16-pacs-ablation-60turn/agent-summary-path-gate-v2.json)
- [Run manifest](artifacts/2026-07-16-pacs-ablation-60turn/run-manifest.json)

### PACS 复杂机制实验

- [Parallel-speed raw trials](artifacts/2026-07-16-pacs-complex-factorial/parallel-speed/trials.jsonl)
- [Parallel-speed summary](artifacts/2026-07-16-pacs-complex-factorial/parallel-speed/summary.json)
- [Pruning-amplifier raw trials](artifacts/2026-07-16-pacs-complex-factorial/pruning-amplifier/trials.jsonl)
- [Pruning-amplifier summary](artifacts/2026-07-16-pacs-complex-factorial/pruning-amplifier/summary.json)

### PACS 微型负对照

- [Raw trials](artifacts/2026-07-16-pacs-ablation/factorial-trials.jsonl)
- [Summary](artifacts/2026-07-16-pacs-ablation/factorial-summary.json)

实验校准、问题处理和审计记录见：[PACS 消融实验审计记录](2026-07-16-pacs-agent-ablation-audit.md)。

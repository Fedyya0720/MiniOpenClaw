# PACS 消融实验审计记录

日期：2026-07-15 至 2026-07-16  
对应正式结果：[PACS Agent 消融实验结果](2026-07-16-pacs-agent-ablation.md)

本文保存实验校准、口径修正和问题处理过程，不作为正式结果正文。

## 1. 初始校准

实验先通过两类最小 smoke 校准 harness：

1. Agent A/B：Traditional Agent 与 PACS Agent 各运行一次；
2. PACS 2×2：serial/parallel × pruning off/on 各运行一次。

离线 local-wheel fixture 和真实 PyPI fixture 均使用真实 pip resolver、安装和验证流程。早期 smoke 数据见：[2026-07-15-pacs-agent-ablation-smoke.md](2026-07-15-pacs-agent-ablation-smoke.md)。这些单次数据只用于校准，不进入正式 5-block 聚合。

## 2. Pip progress bar 线程问题

最初 factorial smoke 在受限进程环境中触发：

```text
RuntimeError: can't start new thread
```

根因是 pip rich progress bar 尝试创建额外线程。所有实验 fixture 后续统一传入：

```text
--progress-bar off
```

该参数对所有比较条件一致。

## 3. Agent 条件公平性

早期 PACS evaluation wrapper 会在模型漏传时静默补入：

- `version_catalog`
- `validation_modules`
- `pip_args`

审计认为这会给 PACS 条件额外结构化输入，而 Traditional 只能读取自然语言提示。正式 runner 已移除静默注入；两组仅从相同任务文本和 catalog 文件获取信息。模型传参错误、重试和低层回退均作为真实 Agent 行为保留。

## 4. Trial-local constraint graph

低层 resolver tools 原先引用模块级 constraint graph singleton，可能导致 trial 间约束污染。正式 runner 为每个 trial 创建：

```text
<workdir>/.mini-openclaw/eval-constraint-graph.db
```

并在 `finally` 中关闭 graph、恢复原 singleton。

## 5. 严格成功 gate

早期 success 只依赖是否存在可验证环境，导致 Agent 达到 max-turns、未完成最终汇报时仍可能被判成功。正式 gate 将结果拆为：

- `environment_verified`
- `agent_completed`
- `success = environment_verified && agent_completed`

`agent_completed` 要求：

- 无 API/tool-level exception；
- 非空且非明确失败回复；
- 未达到 max-turns sentinel；
- 最终回复包含至少一个独立验证通过的环境路径。

独立验证器遍历所有 trial-local 环境，并接受模型报告其中任意一个通过验证的 winner。

## 6. 真实包版本规范化

一次 corrected smoke 中 PACS 环境被误判失败。原因是：

```python
certifi.__version__ == "2025.01.31"
```

而发行版 metadata/catalog 为：

```text
2025.1.31
```

正式验证改用：

```python
importlib.metadata.version("certifi")
```

并继续严格检查版本来自固定候选集合。修正后的 smoke code 在同一 Traditional 和 PACS 环境上重放，均返回 0。原始假失败 record 未被覆盖或纳入正式数据。

## 7. 安装请求指标 v2

安装请求的早期统计存在两次口径修正：

1. `env_run` 中用于 `pip check` 和 import 的 argv specs 不应算安装；
2. `env_run(argv=[..., "pip", "install", ...])` 应算安装，不能只统计 `env_run(packages=...)`。

最终定义为一次 Agent 发起的以下任一操作：

- 带非空 `packages` 的 `env_run` spec；
- argv 同时包含 `pip` 和 `install` 的 `env_run` spec；
- shell command 包含 `pip install`；
- 一次 `pacs_build` 高层请求。

正式 5-block 运行结束后，使用不可变 raw trace 离线重算 v2。原始 `agent-trials.jsonl` 与 `agent-summary.json` 未覆盖；每行旧值、新值及 trace 路径保存在：

- [`agent-installation-requests-v2.json`](artifacts/2026-07-16-pacs-ablation/agent-installation-requests-v2.json)

正式报告使用 v2：Traditional median 7（IQR 2），PACS median 1（IQR 1）。

## 8. 终止时间与完成时间

早期汇总把所有完整 blocks 的时间比直接称为 speedup。但当一侧达到 max-turns 失败时，这不是双方成功条件下的完成时间比较。

Summary 分为：

- `all_measurable_blocks_terminal_resource_contrast`：worker 正常结束的完整 block 到终止状态资源差异；
- `both_successful_blocks.completion_performance`：仅双方严格成功时的完成性能。

旧 30-turn study 中 Traditional 严格成功为 0/5，因此第二项为空；当时只将 2.27 倍表述为固定预算下的终止时间比。后续共同 60-turn study 获得 4 个双方成功 blocks，正式报告改为仅在这 4 个 blocks 上比较完成时间。

### 共同 turn-cap 校准与 60-turn study

为获得双方完成后的时间比较，使用相同 cap 顺序进行独立 calibration：

- 40 turns：Traditional 已留下可验证环境但达到上限；PACS 12 turns 完成；
- 50 turns：Traditional 已留下可验证环境但达到上限；PACS 13 turns 完成；
- 60-turn feasibility：Traditional 44 turns 完成，PACS 11 turns 完成。

随后冻结共同 60 turns，重新运行 5 个正式 paired blocks。Raw gate 最初把两个 PACS 回复记为 `incomplete_response`，因为回复分别使用了唯一 environment ID 对应的相对路径和带省略号的缩写路径，而非逐字复述超长绝对路径。两条回复均明确报告正确 environment ID、成功状态和验证结果，其环境也独立通过完整验证。

完成 gate 因此修正为接受：

- 独立验证通过的完整环境路径；或
- 该环境的唯一 environment ID。

不可变 raw records 未覆盖；reclassification 及最终 summary 单独保存在 [`agent-summary-path-gate-v2.json`](artifacts/2026-07-16-pacs-ablation-60turn/agent-summary-path-gate-v2.json)。最终结果为 Traditional 4/5、PACS 5/5、both-successful 4/5，completion-time ratio median 5.72 倍（IQR 1.18）。

Traditional 成功 trials 在 52、55、56、56 turns 完成，说明 60 turns 对它仍接近边界。原计划可进一步运行共同 75-turn study，但在结果已能回答双方完成时间问题后停止扩展；正式报告明确披露 1/5 Traditional cap hit 和完成 turns，不将 capped trial 当作完成时间。

## 9. PACS result 选择

PACS run 目录名包含秒级时间戳和随机片段。按路径字典序选择“最新”结果，在同一秒多次调用时可能取错。runner 改为按 `result.json` 的 `st_mtime_ns` 选择最新结果。

## 10. Factorial 剪枝指标

早期字段 `pruned_before_execution` 比较 unconstrained 与 constrained 完整空间，并把差值称为执行前剪枝数。这会高估净避免执行工作，因为产生约束的失败组合和 speculative batch 中已启动的组合可能已经执行。

正式字段改为：

```text
excluded_by_constraints
```

它只表示最终 observed constraints 从完整组合空间排除的组合数。实际执行减少单独通过 `attempted` 和 `preflight_calls` 展示。

## 11. Factorial timing instrumentation

早期 solver wrapper 为计算空间差异，在 builder 计时区间内额外调用 solver 两次，可能污染 wall time。正式 runner 的计时路径只执行真实 solver 调用；完整空间与约束空间的比较在 builder 返回后离线计算。

Factorial summary 同时增加：

- median/IQR；
- block 内 parallelism 主效应；
- block 内 pruning 主效应；
- parallel × pruning interaction。

## 12. 复杂机制 fixture 校准与冻结

为避免用同一个微型项目强行证明所有机制，新增两个 evaluation-only fixture：

- `parallel-speed`：四个有序候选，前三个通过 preflight/install 后在 validation 失败，第四个为 winner；wheel 带固定 payload；
- `pruning-amplifier`：2 core × 1 plugin × N addon，一条 exact observed constraint 排除整个 addon slice。

Semantic smoke 只验证候选顺序、stage、winner 和 constraint exclusion，不进入正式性能聚合。Parallel payload 按预注册顺序从 16 MiB 开始；16 MiB calibration 的平均 parallel main effect 节省 3.66 s，达到至少 1 秒且平均 10% 的标准，因此冻结 16 MiB，没有继续试 32/64 MiB。

正式 complex studies 各运行 5 randomized blocks：

- Parallel-speed：20/20 成功，5/5 blocks parallel effect 为正，parallel main effect median 1.736 s（IQR 0.407），install overlap factor 最低 1.68；
- Pruning-amplifier（10 addons，20 组合）：20/20 成功，每次排除 10 个组合；serial attempted/preflight 4→2，parallel 6→4；pruning main effect median 0.949 s（IQR 0.503）。

原微型 2×1×3 fixture 保留为负对照，不与 complex fixture 混合聚合。

## 13. PACS 旧 30-turn trial 中的一次编排失败

正式 block 2 的 PACS Agent 两次把 pip 参数错误传为：

```json
["--progress-bar off"]
```

正确形式应为：

```json
["--progress-bar", "off"]
```

PACS build 因此失败。模型随后退回低层工具，创建了可通过独立验证的环境，但在最终汇报前达到 30 turns。该 trial 保留为 PACS 严格失败，没有重跑、删除或替换。

## 14. Bash 权限规则

Agent ablation 会把实验 prompt、tool schema 和 fixture 内容发送到配置的 DeepSeek API。Claude Code auto mode 因外部数据边界阻止后台运行。经明确授权，在项目本地配置加入最小规则：

```json
"Bash(python -m eval.pacs_agent_ablation *)"
```

规则位于 `.claude/settings.local.json`，不全局开放 Bash。

## 15. Workspace 路径污染

部分 Agent `write`/`edit` 调用解析到了仓库启动目录，而不是 trial-local `/tmp` workdir，曾覆盖根 `requirements.txt` 并创建若干验证脚本。

处理方式：

- 覆盖后的 `requirements.txt` 先复制留证，再恢复 Git 版本；
- trial 明确生成的 untracked 文件不删除，移动到：
  - [`workspace-pollution/`](artifacts/2026-07-16-pacs-ablation/workspace-pollution/README.md)
- 实验前已存在且归属不明的 `.verify_pkg/` 和 `setup_verify.py` 保持原位。

Canonical success evidence 来自 trial-local `/tmp` 环境中的独立验证，不依赖仓库根目录污染文件。该问题仍说明后续 runner 应在工具层强制所有相对路径绑定到 trial workdir。

## 16. 最终验证

最终 evaluation implementation 通过：

- `python -m unittest tests.test_pacs_ablation`：13/13；
- `python -m agent.cli --selfcheck`：15/15；
- Python compileall；
- IDE diagnostics；
- `git diff --check`。

生产目录 `agent/`、`pacs/`、`resolver/`、`envpool/`、`tools/` 和 `skills/` 未因消融实验修改。

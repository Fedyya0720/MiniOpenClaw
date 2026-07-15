# PACS Demo — g07 Python 环境配置智能体

## 前置条件

- `DEEPSEEK_API_KEY` 已配置（或在 `.env` 中设置）
- 磁盘空间充足（每个 venv ~100 MB，并行批次会创建多个）
- `python -m agent.cli --selfcheck` 显示 17 个工具
- 建议：`export MINIOPENCLAW_AUTO_APPROVE=1`（无人值守运行）
- B4 安全演示：`export MINIOPENCLAW_REQUIRE_PIP_SANDBOX=1`（要求 bwrap 可用）

## A 现场演示

### 1. 干净项目（B1）

```bash
time python -m agent.cli "给这个项目配好环境：demo/simple-test-project"
```

预期：
- `naive_success=true`, `N_attempts==1`
- 输出 `PACS_REPORT.md` 中记录了一次尝试即成功

### 2. 冲突项目（B2）

```bash
time python -m agent.cli "给这个项目配好环境：demo/torch-numpy-conflict-project"
```

预期：
- 第一个候选（naive）失败 → `parse_failure` 提取冲突
- `infer_constraints` 记录约束 → `generate_combinations` 排除「坏」组合
- 并行搜索找到可行组合，`N_attempts` 明显小于串行基线
- 最终环境能 `import torch, numpy` 并输出具体版本号

### 3. 串行 vs 并行比较（B3）

先跑串行基线：
```bash
time python -m agent.cli --serial "给这个项目配好环境：demo/torch-numpy-conflict-project"
```
记下 N_attempts 和 wall-clock 时间。

再跑并行默认模式：
```bash
time python -m agent.cli "给这个项目配好环境：demo/torch-numpy-conflict-project"
```

比较：并行 N_attempts 应明显少于串行。将对比写入 `PACS_REPORT.md`。

### 4. 恶意包沙箱（B4）

准备一个包含恶意 `setup.py` 的假包（或使用内置 fixtures），运行：
```bash
MINIOPENCLAW_REQUIRE_PIP_SANDBOX=1 python -m agent.cli \
  "给这个项目配好环境：demo/malicious-package-project"
```

预期：
- 沙箱拦截了恶意包的越界写入
- 若 bwrap 不可用，严格模式下 `env_run` 拒绝执行（硬错误）
- 默认模式下 rlimits-only 底线：确认 `filesystem_isolated=false` 时仅作资源限制

### 5. 约束图持久化（知识复用率）

```bash
# 第一次运行（约束图为空，需全部探测）
python -m agent.cli "给这个项目配好环境：demo/torch-numpy-conflict-project"

# 第二次运行同一项目（约束图已加载，跳过已知冲突）
python -m agent.cli "给这个项目配好环境：demo/torch-numpy-conflict-project"
```

预期：第二次运行的 N_attempts < 第一次，且 agent 系统提示词包含 `## Known constraints` 摘要。

## C 防御要点

### C1 — 真实并发

```bash
grep -rniE "ThreadPool|Process|Pool|并行|parallel|async" tools/ | head
```
- 应看到 `ThreadPoolExecutor` 和 `并行` 关键词

### C2 — 约束与剪枝

```bash
grep -rniE "constraint|约束|prune|剪枝|conflict" . | head
```
- 应看到 `ConstraintGraph`、`infer_transitive`、`constraint_graph.db`

### C3 — 结构化失败解析

```bash
grep -rniE "parse.*error|结构化|structured|traceback" tools/ | head
```
- 应看到 `parse_failure`、`error_type`、`structured`

### 快捷验证脚本

```bash
bash verify_pacs_greps.sh
```

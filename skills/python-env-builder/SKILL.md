---
name: python-env-builder
description: 并行自适应约束搜索（PACS）构建 Python 环境。配置环境/安装依赖/解决版本冲突时使用。编排 envpool/resolver 工具组 + codebase-guide。
dependencies:
  tools:
    - env_create
    - env_run
    - env_status
    - env_cleanup
    - parse_deps
    - generate_combinations
    - parse_failure
    - infer_constraints
  skills:
    - codebase-guide
---

# Python 环境构建 Skill — PACS 编排

## 职责定位

本 skill **不执行具体操作**，只编排调度。具体能力下放给各 tool 和 sub-skill：
- **codebase-guide** → 项目侦察（读 README、识别构建系统、检查 Python 版本）
- **envpool 工具组** → 环境创建/并行安装/状态跟踪/清理
- **resolver 工具组** → 依赖解析/版本组合/失败解析/约束传播
- 本 skill 只决定 **什么时候调用谁、下一步是什么**

---

## 0. 依赖自检（必须先执行）

依次试探调用以下工具（空参即可，预期看到 usage 错误而非"未知工具"）：
1. `env_create` — 若返回"未知工具"→ 提示用户需实现 `envpool/` 模块后终止
2. `parse_deps` — 若返回"未知工具"→ 提示用户需实现 `resolver/` 模块后终止
3. `env_run` / `env_status` / `env_cleanup` / `generate_combinations` / `parse_failure` / `infer_constraints` — 同上

全部通过则继续。缺失项汇总报告，不逐个报错。

---

## 1. 侦察（复用 codebase-guide）

调用 `codebase-guide` skill 的阶段 1-2：
1. 读 README，识别构建系统（pip/poetry/conda）
2. 检查 Python 版本要求
3. 定位依赖文件路径

**产出**：项目元信息（Python 版本范围、依赖文件路径、构建系统类型）

---

## 2. 依赖分析与候选生成

### 2.1 解析依赖
调用 `parse_deps(project_path)` 解析依赖文件 → 约束列表 `[{name, specifier}]`
- 检查约束图持久化文件（`constraint_graph.db`），加载历史约束，避免重复测试已知冲突组合
- 若无历史约束图，输出空图

### 2.2 生成候选
调用 `generate_combinations(deps, constraints)` 生成首批候选组合
- 关键决策点（Python 版本、核心框架版本）优先枚举正交组合
- `max_candidates` 取环境池槽位数

---

## 3. 广度优先采样（BFS）

### 3.1 创建环境池
调用 `env_create(python_version, label)` 批量创建 N 个隔离环境
- N = min(候选数, 可用资源估算)

### 3.2 并行安装
对每个候选组合调用 `env_run(env_id, packages=[pkg1, pkg2], timeout=120)`
- 所有环境**同时**下发
- 等待全部完成（或超时）

### 3.3 结果分类
遍历各环境结果：
- `returncode == 0` → **候选可行**，标记为"基础环境候选"
- `returncode != 0` → **失败**，进入下一阶段分析

---

## 4. 约束传播与分析

### 4.1 解析失败
对每个失败的安装，调用 `parse_failure(log_text, attempted_combo)` → 冲突约束列表

### 4.2 更新约束图
调用 `infer_constraints(new_constraints)` 追加到全局约束图
- 引擎自动执行传递推导和子空间剪枝

### 4.3 决策
- 当前轮有成功环境 → 进入阶段 5
- 候选耗尽 → 返回失败报告（含约束图快照）
- 还有候选但浅层失败 → 回到阶段 2.2 生成下一批候选

---

## 5. 精化与锁环境

### 5.1 安装剩余依赖
在成功环境中安装不在批处理范围内的次要依赖：
```
pip install -r requirements.txt
```
失败时调用 `parse_failure` + `infer_constraints` 微调单个包版本

### 5.2 验证
```bash
python -c "import <主包>; print(<主包>.__version__)"
```
失败则重新进入约束传播循环

### 5.3 锁文件
生成 `pip freeze` 快照到 `requirements.lock`

### 5.4 清理
调用 `env_cleanup(env_id)` 清理所有**非成功**环境（保留成功环境供后续使用）

---

## 6. 报告

用 `write` 输出 `PACS_REPORT.md`，含：
```markdown
# PACS 构建报告 — <项目名>

## 依赖元信息
- Python 版本：<x.y>
- 依赖总数：<N>
- 关键冲突发现：<K> 条

## 搜索过程
- 总轮次：<R>
- 尝试组合数：<T> | 失败：<F> | 成功：<S>
- 搜索时长：<秒>

## 环境位置
- 路径：<path>
- 锁文件：requirements.lock

## 约束图摘要（跨项目复用）
- 已记录约束数：<C>
- 可复用冲突模式：<M> 条
- 持久化路径：constraint_graph.db
```

---

## 剪裁规则
- 项目只有单个 `requirements.txt` 且无版本限制 → 跳过阶段 2-4，直接用阶段 5
- 用户只问"能不能配置"不做最终安装 → 只做阶段 1-2，输出依赖分析报告
- 命令行单次调用（非 TUI）→ 阶段 6 报告写到文件；TUI 模式下额外口头总结

# Step 006: Acceptance Criteria（PACS 子系统）

## 功能性

### F1: 环境池管理
- [ ] `EnvironmentPool.create("3.10", "test-1")` 返回 `Env(id="env-1", path="...", status="idle")`
- [ ] 创建的 venv 可独立 pip install，互不影响
- [ ] `env_status` 返回所有环境状态列表
- [ ] `env_cleanup` 删除指定/全部虚拟环境目录

### F2: 并行安装
- [ ] `parallel_install([env1, env2], [["torch"], ["numpy"]], timeout=60)` 同时返回两个结果
- [ ] 安装结果包含 `{env_id, status(ok/fail/timeout), stdout, stderr, returncode}`
- [ ] 一个环境超时不阻塞其他环境

### F3: 依赖解析
- [ ] `parse_deps` 解析 `requirements.txt`：`torch>=2.0` → `{"name": "torch", "specifier": ">=2.0"}`
- [ ] `parse_deps` 解析 `pyproject.toml` 的 `[project.dependencies]`
- [ ] 无依赖文件时返回错误提示

### F4: 候选组合生成
- [ ] `generate_combinations([{name:"torch",specifier:">=2.0,<3.0"}], [])` 返回至少一个候选 `[{"torch":"2.0.1"}, ...]`
- [ ] 给定冲突约束（torch 2.x ↔ numpy 2.x），生成结果不应包含冲突组合
- [ ] `max_candidates` 参数生效

### F5: 失败日志解析
- [ ] 覆盖 15+ 种 pip 失败模式（版本冲突、平台不兼容、Python 版本不匹配、系统库缺失等）
- [ ] 每条输入产生至少一个结构化约束 `{pkg_a, ver_a, pkg_b, ver_b, error_type, confidence}`
- [ ] 未知模式输出 `{error_type: "unknown"}` 兜底

### F6: 约束图与传播
- [ ] `infer_constraints(C1)` 追加约束到图
- [ ] 传递推导：A↔B + B↔C → 查询 A 相关约束返回 A↔C
- [ ] `constraint_graph.db` 持久化，重启后加载历史约束
- [ ] 剪枝接口：给定候选集 + 约束 → 过滤掉冲突组合

### F7: 工具注册
- [ ] `build_default_registry()` 后 `registry.names()` 包含 8 个新工具名
- [ ] 每个工具 `run()` 返回字符串

### F8: Skill 集成
- [ ] `skills/python-env-builder` 被 `load_skills()` 正确加载
- [ ] Phase 0 依赖自检：调用缺失工具时 LLM 收到"未知工具"并正确提示用户
- [ ] TUI 模式下 `python-env-builder` 出现在 skills catalog

## 非功能性

- [ ] 所有新建模块 `python -c "from envpool.manager import EnvironmentPool"` 无报错
- [ ] 不引入新 pip 依赖（仅用标准库 + 项目已有依赖）
- [ ] 失败路径不抛未经处理的异常

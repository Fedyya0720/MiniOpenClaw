"""resolver — 依赖解析与约束引擎（PACS 功能二/三/四）。

把环境配置建模为约束满足问题：
  - dep_parser     解析 requirements.txt / pyproject.toml / environment.yml → [DepSpec]
  - specifier      手写版本说明符匹配（>=,<=,==,~=,!=，逗号为 AND），不依赖 packaging
  - combinations   基于 pip index versions + 约束图剪枝枚举候选版本组合
  - failure_parser 结构化解析 pip 失败日志 → 冲突约束（覆盖 15+ 失败模式）
  - constraint_graph 约束图：observed/derived 边 + 传递推导 + SQLite 持久化 + 剪枝

约束图持久化于 ~/.cache/miniopenclaw/constraint_graph.db，跨会话/跨项目复用，
支撑 g07「知识复用率」度量。
"""

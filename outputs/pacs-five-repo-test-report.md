# PACS 五仓库实测报告

测试日期：2026-07-13  
运行平台：macOS，Python 3.14.4  
测试方式：复制仓库到 `/tmp`，PACS 查询真实 PyPI 版本、并行安装直接依赖、editable 安装项目本体、执行 `pip check`、导入主模块、生成 lock/report、清理非选中环境。桌面原仓库未写入。

| 仓库 | 源提交 | 直接依赖 | 候选/轮次 | 耗时 | 项目安装 | pip check | import | lock 行数 | 保留环境 |
|---|---|---:|---:|---:|---|---|---|---:|---:|
| sampleproject | `621e497` | 1 | 2 / 1 | 19.31s | 通过 | 通过 | `sample` 通过 | 3 | 1 |
| uv-fastapi-example | `a1e3131` | 1 | 2 / 1 | 24.67s | 通过 | 通过 | `app.main` 通过 | 12 | 1 |
| requests | `f361ead0` | 4 | 2 / 1 | 19.06s | 通过 | 通过 | `requests` 通过 | 6 | 1 |
| flask | `36e4a824` | 6 | 2 / 1 | 27.95s | 通过 | 通过 | `flask` 通过 | 8 | 1 |
| poetry | `f4670233` | 22 | 2 / 1 | 58.15s | 通过 | 通过 | `poetry` 通过 | 37 | 1 |

## 汇总

- 环境构建成功率：5/5。
- 项目本体 editable 安装成功率：5/5。
- `pip check`：5/5 无损坏依赖。
- 主模块 import：5/5 成功。
- 每个项目的两个候选均由真实 pip 并行执行；完成后均只保留一个成功环境。
- 修改后全量回归：42/42 通过，`ResourceWarning` 按错误处理。

## 实测发现与修复

1. Poetry 使用 `build (>=1.2,<2)` 一类括号式 PEP 508 约束，原解析器未去除括号；已修复并增加测试。
2. Poetry 使用 `poetry-core @ git+https://...` 直接引用；已支持真实 Git requirement 安装。
3. 条件依赖不应被无条件要求存在；最终验证改为 `pip check` 加显式主模块 import。
4. PyPI 最新列表可能包含 yanked 发布。本次 Poetry 首轮曾选中可安装但已撤回的 Cleo 2.2.1；版本索引现已排除完全 yanked 的发布，并增加回归测试。

## 边界

本报告验证的是 PACS 环境配置流程，不等同于运行五个上游仓库各自的完整 pytest/nox/tox 测试套件。

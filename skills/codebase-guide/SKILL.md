---
name: codebase-guide
description: 当用户要求搭建/运行一个 Python 开源项目环境、或需要梳理陌生 Python 仓库结构并跑通基础流程时使用。
---

# Python 项目环境搭建与验证 Skill

## 何时使用
用户提供一个 Python 开源项目（本地路径或 GitHub URL），要求：
- 分析项目结构，了解模块组成
- 搭建可运行环境（虚拟环境、依赖安装）
- 跑通项目的基礎运行流程（测试、示例脚本、入口程序）
- 排查环境搭建过程中的报错

## 核心原则：零试错、一次跑通
与裸 agent 的区别：本 Skill 将常见的试错路径固化为检查清单，每条规则背后都是「先探测再行动」——不做无根据的猜测，每个动作都有前置验证。

## 步骤

### 阶段 1：快速侦察（并行，≤2 步）
**目标**：30 秒内摸清项目骨架，不做任何修改。

1. **读入口文档**：用 `read` 打开 README.md（或 README.rst / CONTRIBUTING.md），重点看 "Installation" / "Development" / "Quick Start" 段落。
2. **识别构建系统**：用 `glob` 找 `setup.py`、`setup.cfg`、`pyproject.toml`、`requirements.txt`、`requirements/*.txt`、`Pipfile`、`poetry.lock`、`environment.yml`。这一步决定后续安装策略。
3. **检查 Python 版本要求**：在 setup.cfg / pyproject.toml / setup.py 中搜索 `python_requires`，或在 README 中找 "Python 3.x+" 字样。

**决策点**：若项目是 Poetry 管理 → 走 Poetry 路径；pip + requirements.txt → 走 venv 路径；conda → 走 conda 路径。本 Skill 默认优先 venv + pip。

### 阶段 2：环境搭建（严格按序）
**目标**：一键搭建，不因遗漏而重跑。

1. **确认 Python 版本**：`bash python3 --version`。与项目要求的版本比较。若版本不够，提示用户安装目标版本。
2. **创建虚拟环境**（跳过已存在的 .venv/venv）：
   ```bash
   python3 -m venv .venv
   ```
   若项目已有 .venv 或 venv 目录，先用 `bash .venv/bin/python --version` 验证可用性，可用则跳过创建。
3. **激活并升级 pip**：
   ```bash
   .venv/bin/pip install --upgrade pip setuptools wheel
   ```
4. **安装依赖**（按优先级）：
   - 若 pyproject.toml 存在 → `.venv/bin/pip install -e ".[dev,test]"` （先试 dev/test extras，失败则退到 `.venv/bin/pip install -e .`）
   - 若 setup.py 存在 → `.venv/bin/pip install -e .`
   - 若 requirements.txt 存在 → `.venv/bin/pip install -r requirements.txt`
   - 若 requirements/ 目录存在 → 依次安装 `requirements/*.txt`
   - **关键**：安装失败时，读错误信息定位缺失的系统依赖（如 libpq-dev、python3-dev），给出 apt/brew 安装命令，**不要**盲目重试 pip install。

### 阶段 3：验证基础运行
**目标**：确认项目能「动起来」，揭示隐性配置缺失。

1. **跑测试**（若存在）：
   - 有 pytest → `.venv/bin/pytest -x --tb=short -q`（先跑一个快速 smoke，-x 首失败即停）
   - 有 tox/nox → `.venv/bin/tox -e py3 -- -x`
   - 有 Makefile 且含 test 目标 → `make test`
   - 无测试框架 → 跳过
2. **跑示例/入口**（若 README 提到）：
   - 找出 README 中 "Usage" / "Quick Start" 的第一个命令，直接执行
   - 若有 `examples/` 目录，挑一个最简单的跑
   - 若项目是 CLI 工具，跑 `--help` 确认可执行
3. **导入检查**（无测试/示例时的保底）：
   ```bash
   .venv/bin/python -c "import <主包名>; print('<主包名>', getattr(<主包名>, '__version__', 'no version'))"
   ```
   主包名从 setup.py/pyproject.toml 的 name 字段获取。

### 阶段 4：输出结构化报告
用 `write` 写出 `SETUP_REPORT.md`，包含：
```markdown
# 环境搭建报告 — <项目名>

## 项目概况
- Python 版本要求：<x.y> | 当前：<x.y.z>
- 包管理器：<pip/poetry/conda>
- 主要依赖数：<N>

## 搭建结果
- 虚拟环境：.venv/（Python <version>）
- 依赖安装：✅ 成功 / ⚠️ <N> 个失败
- 测试结果：✅ <P> passed / ⚠️ <F> failed / ⏭ 跳过

## 运行验证
| 验证项 | 命令 | 结果 |
|--------|------|------|
| 导入主包 | `python -c "import xxx"` | ✅ |
| 基础示例 | `python examples/basic.py` | ✅ |
| --help | `python -m xxx --help` | ✅ |

## 注意事项
- （记录任何特殊配置、系统依赖、版本兼容问题）
```

## 常见陷阱速查
| 现象 | 根因 | 解法 |
|------|------|------|
| `error: externally-managed-environment` | PEP 668，系统 Python 不允许 pip | 必须用 venv |
| `ModuleNotFoundError: No module named 'xxx'` | 未用 venv 的 pip 或缺少 extras | 确认 `.venv/bin/pip` 路径 |
| `gcc: command not found` | 缺少 C 编译器 | `apt install build-essential` |
| `fatal error: Python.h: No such file` | 缺少 Python 头文件 | `apt install python3-dev` |
| pip install 超时 | 网络或大包 | 加 `--default-timeout=120` 或换镜像 |

## 剪裁规则（减少 token 消耗）
- 若用户只问「这个项目怎么跑」，只做阶段 1-3，口头回答，不写 SETUP_REPORT.md。
- 若项目是纯 Python（无 C 扩展），跳过 build-essential / python3-dev 检查。
- 若 README ≤ 50 行，全读；否则只读 Installation / Quick Start 相关段落。

---
name: python-env-builder
description: 配置环境、安装依赖或解决 pip 冲突时，项目路径已知就直接调用一次 pacs_build；该工具会自行发现版本、预求解、并行安装、验证并生成锁文件，无需先 read/glob。
dependencies:
  tools:
    - pacs_build
    - parse_deps
    - generate_combinations
    - parse_failure
    - infer_constraints
    - env_create
    - env_run
    - env_status
    - env_cleanup
---

# Python 环境构建 Skill

## 默认快速流程

1. TUI/CLI 在目标项目目录启动时，项目路径就是 `.`，不要先扫描目录或读取依赖文件。
2. 默认第一次工具调用就是 `pacs_build(project_path=".")`，把完整搜索循环交给确定性编排器。
3. 检查返回 JSON 的 `success`，不要仅凭日志猜测成功。
4. 成功时汇报：环境路径、lock、报告、轮次、尝试数、验证结果和耗时。
5. 失败时汇报：主要失败、尝试数和报告路径；不要自动重复同样的调用。

推荐参数：

```json
{
  "project_path": ".",
  "max_parallel": 2,
  "max_attempts": 6,
  "timeout": 120,
  "validation_modules": []
}
```

只有用户明确提供本地 wheelhouse 时，才传递类似参数：

```json
{
  "pip_args": ["--no-index", "--find-links", "/absolute/wheelhouse"],
  "version_catalog": {"demo-core": ["2.0.0", "1.0.0"]}
}
```

## 镜像站点与网络回退

当直接访问 PyPI / GitHub / HuggingFace 超时时，建议通过环境变量切换到国内镜像，避免重复失败：

| 用途 | 环境变量 | 建议值 |
|------|---------|--------|
| PyPI 索引 | `PIP_INDEX_URL` | `https://pypi.tuna.tsinghua.edu.cn/simple` |
| PyPI 信任主机 | `PIP_TRUSTED_HOST` | `pypi.tuna.tsinghua.edu.cn` |
| HuggingFace | `HF_ENDPOINT` | `https://hf-mirror.com` |
| GitHub 资源代理 | `GITHUB_MIRROR_PREFIX` | `https://gh-proxy.com/` |

上述值仅为建议，可根据网络环境替换为其他镜像（如阿里云、中科大等）。

### 使用方式

**方式一：通过 `env` 参数传入 `pacs_build`**

```json
{
  "project_path": ".",
  "env": {
    "PIP_INDEX_URL": "https://pypi.tuna.tsinghua.edu.cn/simple",
    "PIP_TRUSTED_HOST": "pypi.tuna.tsinghua.edu.cn",
    "HF_ENDPOINT": "https://hf-mirror.com",
    "GITHUB_MIRROR_PREFIX": "https://gh-proxy.com/"
  }
}
```

`pacs_build` 会将这些环境变量注入子进程，pip / huggingface_hub / git 等工具会自动遵循。

**方式二：运行前在 shell 中导出**

```bash
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
export HF_ENDPOINT=https://hf-mirror.com
export GITHUB_MIRROR_PREFIX=https://gh-proxy.com/
```

### 触发时机

- 当 `pacs_build` 返回的网络相关错误中包含 `timeout`、`ConnectionError`、`ReadTimeout`、`ConnectTimeout` 等关键词时，自动在重试中使用镜像。
- 用户说 "用镜像"、"换国内源"、"网络超时" 时，直接启用。
- 镜像也超时时，尝试回退到直连，或切换其他镜像（如 `https://mirrors.aliyun.com/pypi/simple`）。

## 何时使用低层工具

只有以下情况才逐个调用 `parse_deps`、`generate_combinations`、`env_*` 等工具：

- 用户只要依赖分析，不允许安装；
- `pacs_build` 返回基础设施错误，需要定位某个组件；
- 用户明确要求查看候选、约束图或 serial/parallel 对照。

不要让 Agent 自己承担多轮候选循环；这会增加模型调用次数并降低速度和稳定性。

## 安全与清理

- 不访问当前工作目录之外的项目；
- 不传 shell 字符串，只传结构化参数；
- 不绕过 pip 写入位置限制；
- `success=true` 后不要重复创建环境；
- 保留 winner，确认失败环境已经清理；
- 如实报告 `bubblewrap` 或 `rlimits-only`，不要把普通 venv 描述为系统级沙箱。

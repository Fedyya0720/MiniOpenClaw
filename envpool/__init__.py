"""envpool — 并行环境池（PACS 功能一）。

提供隔离的虚拟环境创建、并行 pip 安装、状态跟踪与清理。
并行通过 ThreadPoolExecutor 在工具内部完成（策略 A），
对 ReAct 主循环零侵入——一次 env_run 调用返回全部并行结果。

本包刻意绕过 bash 工具的 bwrap 沙箱（--unshare-net），
因为 pip install 需要 PyPI 网络；取而代之的是 envpool/sandbox.py
提供的 venv 级 pip 安装沙箱（venv 可写、其余只读、网络开、资源上限），
这是 B4「装坏包」测试的安全边界。
"""

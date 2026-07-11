"""命令行入口。

用法：
  python -m agent.cli --selfcheck          # Day1：自检骨架是否装好
  python -m agent.cli "创建 hello.py 并运行"  # Day5 起：真正跑任务（v1 在 Day6）
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

from tools.base import build_default_registry
from agent.prompts import build_system_prompt
from skills.loader import load_skills, skills_catalog


def _load_dotenv() -> None:
    """从项目根目录 .env 加载环境变量（仅在未设置时生效），免去每次手动 export。"""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        # 去掉可选引号
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def selfcheck() -> int:
    print("== mini-OpenClaw 自检 ==")
    ok = True
    try:
        reg = build_default_registry()
        print(f"[ok] 工具注册表加载成功，当前内置工具数：{len(reg)}（Day5 起会变多）")
    except Exception as e:  # noqa
        print(f"[FAIL] 工具注册表：{e}"); ok = False

    try:
        from backend.fake_backend import FakeBackend
        FakeBackend().chat([{"role": "user", "content": "hi"}], tools=[])
        print("[ok] FakeBackend 可用（未配 DEEPSEEK_API_KEY 时的离线占位后端）")
    except Exception as e:  # noqa
        print(f"[FAIL] FakeBackend：{e}"); ok = False

    try:
        from agent.loop import AgentLoop  # noqa
        print("[ok] 主循环模块可导入（Day5 实现 run 逻辑）")
    except Exception as e:  # noqa
        print(f"[FAIL] 主循环：{e}"); ok = False

    print("== 自检", "通过 ✅" if ok else "未通过 ❌", "==")
    print("\n所有模块已就绪。运行 python -m agent.cli '任务' 开始使用。")
    return 0 if ok else 1


def _make_backend():
    """统一的后端工厂：DeepSeek API → FakeBackend 兜底。"""
    try:
        from backend.client import DeepSeekBackend
        return DeepSeekBackend()                       # 需要 DEEPSEEK_API_KEY
    except Exception as e:  # noqa
        from backend.fake_backend import FakeBackend
        print(f"[提示] 未启用真后端（{e}），回退 FakeBackend。配置 DEEPSEEK_API_KEY 后即用真模型。")
        return FakeBackend()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mini-openclaw")
    p.add_argument("task", nargs="?", help="要让 agent 完成的任务（自然语言）")
    p.add_argument("--selfcheck", action="store_true", help="只做骨架自检")
    p.add_argument("--tui", "-t", action="store_true",
                   help="启动交互式 TUI 模式（REPL + 流式显示）")
    p.add_argument("--image", "-i", action="append", default=None,
                   help="附加图片到用户消息（可多次指定），打通多模态输入通道")
    p.add_argument("--auto-approve", action="store_true",
                   help="自动批准需确认的工具调用（权限层 deny 仍会拦截）")
    args = p.parse_args(argv)

    # --- MCP 工具接入 ---
    def _wire_mcp(reg):
        """尝试连接 MCP echo server，将其工具并入注册表。失败不阻塞启动。"""
        from mcp.client import MCPClient, register_mcp_tools
        try:
            mcp = MCPClient(["python", "mcp/echo_server.py"])
            mcp.start()
            register_mcp_tools(reg, mcp)
        except Exception as e:  # noqa
            print(f"[提示] MCP 未接入（{e}），仅用内置工具。")

    # --- TUI 模式 ---
    if args.tui:
        from agent.tui import run_tui
        reg = build_default_registry()
        _wire_mcp(reg)
        backend = _make_backend()
        skills = load_skills()
        system_prompt = build_system_prompt(skills_catalog(skills))
        run_tui(backend, reg, system_prompt, auto_approve=args.auto_approve)
        return 0

    if args.selfcheck or not args.task:
        return selfcheck()

    # 真正跑任务：优先用 DeepSeek API；没配 key 时回退到 FakeBackend（离线打通管道）
    from agent.loop import AgentLoop
    reg = build_default_registry()
    _wire_mcp(reg)
    backend = _make_backend()
    skills = load_skills()
    system_prompt = build_system_prompt(skills_catalog(skills))
    agent = AgentLoop(backend, reg, system_prompt,
                      auto_approve=args.auto_approve, workdir=Path.cwd())
    print(agent.run(args.task, images=args.image))
    return 0


if __name__ == "__main__":
    sys.exit(main())

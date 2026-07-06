"""最小 MCP 客户端（Day8）。

MCP（Model Context Protocol）让工具集从"写死在代码里"变成"可插拔的外部 server"。
本文件实现一个最小客户端：通过 stdio 跟 server 通信，做 JSON-RPC。

要实现的握手与调用：
  1. 启动 server 子进程（stdio transport）
  2. initialize 握手
  3. tools/list  —— 拉取 server 暴露的工具
  4. tools/call  —— 把某次调用转发给 server，拿回结果
然后在 agent/loop 里，把这些 MCP 工具**透明合并**进内置 ToolRegistry。
"""
from __future__ import annotations
import json
import subprocess
from typing import Any

from tools.base import Tool, ToolRegistry


class MCPClient:
    def __init__(self, command: list[str]):
        self.command = command
        self.proc: subprocess.Popen[bytes] | None = None
        self._id = 0

    def start(self) -> None:
        """Launch the server subprocess and perform the initialize handshake."""
        self.proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Step 1: initialize handshake
        result = self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mini-openclaw", "version": "0.1"},
        })
        if "protocolVersion" not in result:
            raise RuntimeError(f"MCP initialize failed: {result}")
        # Step 2: send initialized notification (no response expected)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, msg: dict) -> None:
        """Send a JSON-RPC message to the server."""
        assert self.proc and self.proc.stdin
        line = json.dumps(msg, ensure_ascii=False)
        self.proc.stdin.write((line + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def _recv(self) -> dict:
        """Read a JSON-RPC response line from the server."""
        assert self.proc and self.proc.stdout
        line = self.proc.stdout.readline().decode("utf-8").strip()
        if not line:
            raise RuntimeError("MCP server closed stdout unexpectedly")
        return json.loads(line)

    def _rpc(self, method: str, params: dict | None = None) -> Any:
        """Send a JSON-RPC request and return the result."""
        self._id += 1
        self._send({
            "jsonrpc": "2.0",
            "id": self._id,
            "method": method,
            "params": params or {},
        })
        response = self._recv()
        if "error" in response:
            raise RuntimeError(f"MCP error: {response['error']}")
        return response.get("result", {})

    def list_tools(self) -> list[dict]:
        """Call tools/list and return the tool descriptions."""
        result = self._rpc("tools/list")
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> str:
        """Call tools/call and return the result text."""
        result = self._rpc("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        # Extract text from content array
        content = result.get("content", [])
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(item.get("text", ""))
            return "\n".join(texts)
        return str(content)


def register_mcp_tools(registry: ToolRegistry, client: MCPClient) -> None:
    """把一个 MCP server 的工具包装成内置 Tool 并注册，实现透明合并。"""
    for spec in client.list_tools():
        name = spec["name"]
        registry.register(Tool(
            name=f"mcp__{name}",            # 命名空间避免和内置工具撞名
            description=spec.get("description", ""),
            parameters=spec.get("inputSchema", {"type": "object", "properties": {}}),
            run=lambda _n=name, **kw: client.call_tool(_n, kw),
        ))

"""一个最小 MCP server —— 计算器，暴露 add(a, b) 工具。

用于 Day 8 验证 MCP 客户端能连接非 echo 的 server。仿照 echo_server.py 的
stdio + JSON-RPC 循环模式。
"""
from __future__ import annotations
import json
import sys

TOOLS = [{
    "name": "add",
    "description": "返回 a + b 的和。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "a": {"type": "number", "description": "第一个加数"},
            "b": {"type": "number", "description": "第二个加数"},
        },
        "required": ["a", "b"],
    },
}]


def handle(req: dict) -> dict | None:
    method = req.get("method")
    rid = req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid,
                "result": {"protocolVersion": "2024-11-05",
                           "serverInfo": {"name": "calc", "version": "0.1"},
                           "capabilities": {"tools": {}}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        args = req["params"]["arguments"]
        a = args.get("a", 0)
        b = args.get("b", 0)
        result = a + b
        return {"jsonrpc": "2.0", "id": rid,
                "result": {"content": [{"type": "text", "text": str(result)}]}}
    if rid is None:           # 通知类（如 notifications/initialized）无需回应
        return None
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "method not found"}}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        resp = handle(json.loads(line))
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

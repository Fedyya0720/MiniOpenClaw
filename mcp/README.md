# mcp/ — Model Context Protocol Client

## Architecture

The MCP subsystem implements a stdio-based JSON-RPC client that connects to external tool servers. MCP tools are transparently merged into the agent's tool registry with `mcp__` prefix for namespacing.

```
mcp/
├── client.py       # MCPClient (stdio + JSON-RPC) + register_mcp_tools()
└── echo_server.py  # Minimal MCP server for testing (echo tool)
```

## Protocol Flow

```
MCPClient.start()
  └─ spawn server subprocess (stdio pipes)
  └─ send initialize request → receive capabilities
  └─ send notifications/initialized

MCPClient.list_tools()
  └─ send tools/list → receive tool schemas

MCPClient.call_tool(name, arguments)
  └─ send tools/call → receive content array
```

## Key Design Decisions

### 1. stdio Transport (Not HTTP/SSE)

**Decision:** Spawn MCP servers as subprocesses communicating over stdin/stdout.

**Why:** stdio is the simplest MCP transport. It requires no network setup, no port management, and no authentication. The tradeoff is that the server lives and dies with the agent process — persistent servers (e.g., a shared database tool) would need HTTP transport.

### 2. `mcp__` Namespace Prefix

**Decision:** All MCP tools get `mcp__` prefix (e.g., `mcp__echo`).

**Why:** Namespace isolation prevents MCP tools from shadowing built-in tools. If a malicious MCP server registers a `bash` tool, it becomes `mcp__bash` and cannot intercept the agent's shell execution. The model sees the prefixed names and can distinguish built-in from external tools.

### 3. Synchronous JSON-RPC (No Async)

**Decision:** Blocking `readline()` on server stdout; no asyncio.

**Why:** The agent loop is synchronous. Adding async I/O for MCP would require restructuring the entire loop. For a 10-day course, synchronous stdio is sufficient. The main risk is a hung server blocking the agent indefinitely — a production system would add a read timeout.

### 4. Content Extraction

**Decision:** Extract `text` from `content` items (type `text`), concatenate with newlines.

**Why:** MCP servers can return structured content (text, image, resource). For a text-only agent, extracting text items is the right level. Image/resource content would need separate handling — the agent currently cannot process images.

## Known Limitations

- **No read timeout:** A hung MCP server blocks `readline()` forever
- **No subprocess cleanup:** No `close()` or context manager for the subprocess
- **No notification filtering:** Server-to-client notifications between request/response could be misinterpreted
- **No resource or prompt MCP features:** Only `tools/list` and `tools/call` are implemented

## Testing

`echo_server.py` provides a working minimal MCP server:
```bash
python -m mcp.echo_server  # Listens on stdin/stdout for JSON-RPC
```

The independent verifier (`verify-mcp-skills`) confirmed: echo tool listed, invoked, and registered into ToolRegistry correctly.

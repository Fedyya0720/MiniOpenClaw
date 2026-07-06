# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

mini-OpenClaw is a **10-day educational course** for building a Claude Code-style command-line AI agent from scratch. This repo is the student starter skeleton — a "fill-in-the-blanks" framework where `# TODO[DayN]` markers guide what to implement on each day. The course builds a ReAct (Reasoning + Acting) agent loop that calls a DeepSeek API backend, dispatches tool calls locally, and feeds results back until the task is complete.

## Commands

```bash
# Self-check (Day 1 skeleton verification — tool registry + FakeBackend + loop import)
python -m agent.cli --selfcheck

# Run a real task (Day 5+ once tools are implemented)
python -m agent.cli "create hello.py and run it"

# Find all unimplemented TODO markers across the codebase
grep -rn "TODO\[Day" .
```

No test framework exists. Verification is manual: `--selfcheck` for Day 1, and ad-hoc runs of `eval/metrics.py` / `eval/tasks.py` for later days.

## Architecture

```
User Request → [agent/loop.py: ReAct main loop] → [backend/client.py → DeepSeek API]
                   ↑   |  LLM returns <tool_call>{...}</tool_call>
                   |   ↓
             Tool Result ← [Tool dispatch: read/write/bash/edit/grep/glob/web_fetch/task_list]
                               ├── Built-in tools (tools/)
                               ├── MCP tools (mcp/)
                               └── Skills (skills/)
```

### Backend Contract

All backends (`DeepSeekBackend`, `FakeBackend`) implement this single interface:

```python
chat(messages: list[dict], tools: list[dict] | None) -> dict
# Returns: {"role": "assistant", "content": str, "tool_calls": [{name, arguments, id}, ...]}
```

`DeepSeekBackend` in [backend/client.py](backend/client.py) calls the DeepSeek API at `{DEEPSEEK_BASE_URL}/v1/chat/completions` (OpenAI-compatible). It normalizes OpenAI tool-call format into the internal flat `{name, arguments, id}` shape. `FakeBackend` in [backend/fake_backend.py](backend/fake_backend.py) is a rule-based offline placeholder for testing the skeleton without an API key.

### Main Loop ([agent/loop.py](agent/loop.py))

`AgentLoop.run(user_task)` assembles `[system, user]` messages, then loops up to `max_turns` (default 20):
1. Call `backend.chat(messages, tools=registry.schemas())`
2. If the response has `tool_calls`, look up each in the `ToolRegistry`, run it, inject the result as a `role="tool"` message, and loop
3. If no tool calls, return `assistant.content` as the final answer

### Tool System ([tools/base.py](tools/base.py))

`Tool` is a dataclass: `name`, `description`, `parameters` (JSON Schema), and a `run(**kwargs) -> str` callable. `ToolRegistry` holds them and exposes `schemas()` (OpenAI tools format) for the backend.

`build_default_registry()` in [tools/base.py:59-75](tools/base.py#L59-L75) is the single registration point — stubs for each tool are uncommented and registered as they're implemented across days.

### Prompt Rendering ([prompt/render.py](prompt/render.py))

Day 3's core deliverable: renders structured `messages + tools` into a **single text string** the model consumes (no function-calling API — pure string templating with role tokens like `<|system|>`, `<|user|>`, `<|assistant|>`, `<|observation|>`). `parse_tool_calls()` extracts `<tool_call>{...}</tool_call>` blocks from model output.

### MCP ([mcp/client.py](mcp/client.py) + [mcp/echo_server.py](mcp/echo_server.py))

Day 8: `MCPClient` spawns an external tool server over stdio + JSON-RPC, does `initialize` handshake, then exposes tools via `list_tools()` / `call_tool()`. `register_mcp_tools()` wraps MCP tools as `Tool` objects with `mcp__` prefix and merges them into the registry. `echo_server.py` is a working minimal MCP server for testing the client.

### Skills ([skills/loader.py](skills/loader.py))

Day 9: Skills are domain-knowledge packs defined in `SKILL.md` files with YAML frontmatter (`name`, `description`) + markdown body. The loader scans `skills/*/SKILL.md`, parses frontmatter, and injects skill descriptions into the system prompt so the model can recognize when to request a skill. Distinct from Tools — skills are procedural guidance, not single function calls.

### Context Management ([agent/context.py](agent/context.py))

Day 7: `estimate_tokens()` (rough char/4 heuristic), `maybe_compact()` (summarize old history when over budget, keeping system + recent K turns), `truncate_observation()` (cap tool output at max_chars).

## 10-Day Build Schedule

| Day | Module | What Gets Built |
|-----|--------|-----------------|
| 1 | Skeleton | Self-check passes; understand the architecture |
| 2 | `backend/` + `agent/prompts.py` | Wire up DeepSeek API, draft system prompt |
| 3 | `prompt/render.py` | `render_prompt()` + `parse_tool_calls()` — string-based tool calling |
| 5 | `tools/fs.py`, `tools/shell.py`, `agent/loop.py` | `read`, `write`, `bash` tools; working main loop |
| 6 | `tools/more_tools.py` (edit/grep/glob) | Full tool set → **v1 milestone** (end-to-end usable) |
| 7 | web_fetch, task_list, context compaction, eval | Long-task robustness → eval metrics |
| 8 | `mcp/client.py` | Pluggable external tools via MCP |
| 9 | `skills/loader.py` + custom skill | Extensible domain capabilities → **v3 milestone** |
| 10 | Security layer (sandbox, permissions), ablation studies | Final demo day |

Every `# TODO[DayN]` in the codebase corresponds to one of these milestones. `grep -rn "TODO\[Day" .` lists all implementation points.

## Configuration

- `.env` at the project root (gitignored) — loaded automatically by `cli.py` on startup, sets env vars only if not already present
- `DEEPSEEK_API_KEY` — required for real LLM; without it, the CLI falls back to `FakeBackend`
- `DEEPSEEK_BASE_URL` — defaults to `https://api.deepseek.com`
- `DEEPSEEK_MODEL` — defaults to `deepseek-chat`
- System dependency: `ripgrep` (`rg`) must be installed via system package manager for the `grep` tool (Day 6)

## Key Conventions

- Git tags at milestones: `v1` (Day 6), `v3` (Day 9), `final` (Day 10)
- Each module should have its own `README.md` documenting design decisions (graded as technical documentation)
- The `.env` file is gitignored — never commit API keys
- `DeepSeekBackend` is OpenAI-compatible: swapping `base_url`/`api_key`/`model` lets you use any OpenAI-compatible provider

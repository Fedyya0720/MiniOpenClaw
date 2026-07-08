# backend/ — LLM Backend Abstraction

## Architecture

All backends implement a single interface:
```python
chat(messages: list[dict], tools: list[dict] | None) -> dict
# Returns: {"role": "assistant", "content": str, "tool_calls": [{name, arguments, id}, ...]}
```

```
backend/
├── client.py        # DeepSeekBackend — calls DeepSeek API (OpenAI-compatible)
├── fake_backend.py  # FakeBackend — rule-based offline placeholder
└── server.py        # Deprecated — originally planned for local model deployment
```

## Key Design Decisions

### 1. Single `chat()` Interface

**Decision:** All backends implement the same `chat(messages, tools) -> dict` method.

**Why:** The main loop never knows which backend it's talking to. This is dependency inversion at its simplest — `AgentLoop` depends on the interface, not the implementation. Testing with `FakeBackend` and production with `DeepSeekBackend` require zero loop changes.

### 2. OpenAI-Compatible Format (Internal Normalization)

**Decision:** DeepSeek's API is OpenAI-compatible, so `DeepSeekBackend` translates between internal and OpenAI formats.

**Why:** The internal format is flatter and simpler than OpenAI's nested structure:
```python
# Internal format
{"name": "read", "arguments": {"path": "file.txt"}, "id": "call_1"}

# OpenAI format
{"id": "call_1", "type": "function",
 "function": {"name": "read", "arguments": '{"path": "file.txt"}'}}
```

Normalization at the backend boundary keeps the rest of the codebase simple. If we switch to a non-OpenAI provider (e.g., Anthropic), only the normalization layer changes.

### 3. `FakeBackend` for Skeleton Testing

**Decision:** `FakeBackend` is intentionally simplistic — keyword matching triggers tool calls.

**Why:** The skeleton must be testable without an API key. `FakeBackend` returns `read` when the user mentions "file", `bash` when they mention "run", etc. It's not useful for real work but critical for Day 1 selfcheck.

### 4. `tool_choice: "auto"` (Not "required")

**Decision:** Let the model decide whether to call a tool or return text.

**Why:** `"auto"` means the model can answer simple questions directly ("what is Python?") without forcing a tool call. `"required"` would force a tool call even when the model could answer from its training data.

### 5. Configuration via Environment Variables

**Decision:** `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL` — all from env vars.

**Why:** This follows the 12-factor app pattern. No config files, no hardcoded keys. `.env` provides convenience, env vars provide deployment flexibility. The backend is trivially swappable to any OpenAI-compatible provider by changing `DEEPSEEK_BASE_URL`.

## Message Format Handling

`_to_openai_messages()` handles internal-to-OpenAI conversion:
- `role="tool"` messages include `tool_call_id` (falls back to `name` for compatibility)
- `role="assistant"` messages with `tool_calls` inject them as OpenAI-format blocks
- The final `assistant` message with only `content` (no tool_calls) is passed through

`_normalize()` handles OpenAI-to-internal conversion:
- JSON-decodes `arguments` (with graceful handling of malformed JSON)
- Handles missing/empty `content`
- Keeps extra fields beyond `name` and `arguments` (like `id`)

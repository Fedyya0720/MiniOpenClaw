# agent/ — Agent Core

## Architecture

The `agent/` package contains the core agent infrastructure: main loop, CLI entry point, system prompt, and context management.

```
agent/
├── loop.py      # ReAct main loop (think → act → observe → repeat)
├── cli.py        # CLI entry point (python -m agent.cli)
├── prompts.py    # System prompt with tool catalog + skills template
└── context.py    # Token estimation, compaction, observation truncation
```

## Key Design Decisions

### 1. ReAct Loop (`loop.py`)

**Decision:** Simple while-loop with max_turns cap (default 20).

**Why:** Educational clarity over framework abstraction. A `while turns < max_turns` loop is the simplest possible implementation of the ReAct pattern. Students can trace every iteration. Production agents might want async/streaming, but for a 10-day course this is the right tradeoff.

**Key behaviors:**
- Tool calls from the model are dispatched synchronously in order
- Each tool result is injected as a `role="tool"` message before the next turn
- Unknown tools return an error string rather than crashing — lets the model self-correct
- Exceptions in tool execution are caught and fed back as observations (error recovery)
- Loop terminates when the model stops emitting tool_calls, or at max_turns

### 2. Context Compaction (`context.py`)

**Decision:** Template-based sliding window rather than LLM summarization.

**Why:** LLM-based summarization requires an extra API call per compaction event, adding latency and cost. The template approach ("previous N turns compressed, M tool calls executed") is lossy but keeps the most recent context intact. The token estimator uses the standard char/4 heuristic — deepseek-chat is close enough to 4 chars/token for budget management.

**Tradeoff:** Semantic detail in discarded messages is lost. A production system might warm up a summarizer model or use structured key-value extraction from tool results.

### 3. System Prompt (`prompts.py`)

**Decision:** Single template string with `{skills_catalog}` injection point.

**Why:** The prompt is the most impactful artifact in the system. A single template ensures consistency. The `{skills_catalog}` slot allows skills (from `skills/loader.py`) to be injected at runtime without modifying the prompt, following the open-closed principle.

### 4. CLI (`cli.py`)

**Decision:** Auto-load `.env` before imports, fall back to FakeBackend if no API key.

**Why:** `.env` loading avoids the "remember to export variables" friction for students. The FakeBackend fallback means the skeleton is testable without any API key — critical for Day 1.

## Verification

- `--selfcheck` verifies: tool registry loads, FakeBackend works, main loop imports
- All 15 independent verifier tests pass (see `.plans/verify-*/`)

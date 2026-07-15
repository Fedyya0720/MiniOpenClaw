# agent/ — Agent Core

## Architecture

The `agent/` package contains the core agent infrastructure: main loop, CLI entry point, system prompt, and context management.

```
agent/
├── loop.py      # ReAct main loop (think → act → observe → repeat)
├── strategy.py  # Shared CLI/TUI execution and tool evidence integration
├── trace.py     # Tool-only durable evidence, integrity metadata, and redaction
├── tracer.py    # Developer spans: LLM/tool latency, replay, and token cost
├── cli.py        # CLI entry point (python -m agent.cli)
├── prompts.py    # System prompt with tool catalog + skills template
├── context.py    # Token estimation, compaction, observation truncation
└── memory.py     # Cross-session persistence, recall, and structured memory
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

Use `--workdir` (or `-C`) to run the agent against another repository while keeping
MiniOpenClaw's code and runtime in their original location:

```bash
PYTHONPATH=/path/to/MiniOpenClaw /path/to/python -m agent.cli \
  --tui --workdir /path/to/target-project --auto-approve
```

The directory is resolved and validated before the backend or tools start, then becomes
the process current directory and the shared permission, memory, trace, constraint, and
PACS project boundary. An absolute `pacs_build` path is allowed only when it remains
inside this workspace.

### 5. Persistent Memory (`memory.py`)

**Decision:** Keep project memory in human-readable `MEMORY.md` and expose writes through
the normal tool registry. The CLI recalls this file once at session startup and appends it
to the system prompt. `KVMemory` separately supports key-based replacement and deletion.

**Boundary:** Context compaction handles one running task; memory persists stable facts
across processes. Memory is not intended for secrets, transient chat, or codebase RAG.

### 6. Durable Tool Evidence (`trace.py`)

**Scope:** A trace records only tool-call metadata and tool-result artifacts. It never
stores user/system/model/final prose or backend request/response payloads.

Each CLI run writes to `<workdir>/.mini-openclaw/tool-runs/<run-id>/`, while the TUI
creates a trace for each submitted ReAct turn. `trace.jsonl` is append-only and each
result artifact is retained in `artifacts/`, even when it is larger than the context
spill threshold. Records include call ID, turn/index, result status, original/stored
character and UTF-8 byte counts, plus SHA-256 hashes. Directories/files use best-effort
`0700`/`0600` permissions, and an evidence-write failure never interrupts the agent.

**Redaction:** likely credentials in arguments and textual output are redacted by
default: JSON secret fields, common secret key names, Bearer/Basic authorization
values, sensitive `NAME=value` environment assignments, and URL credentials. Clean
output remains exact. Context spills apply the same policy before writing their
artifact, and their summaries disclose original/stored counts and hashes plus whether
redaction occurred without previewing sensitive data. Set
`MINIOPENCLAW_TRACE_SENSITIVE=1` only for an intentional forensic investigation to
retain exact sensitive values; trace/spill metadata records that warning state. This
opt-in is never enabled automatically.

**Permission boundary:** resolver paths such as `parse_deps.project_path` must resolve
within the AgentLoop workspace and cannot traverse sensitive paths or symlink escapes.
Environment-tool `workdir`, when supplied, must canonically equal the AgentLoop
workspace; the permission layer rejects arbitrary alternate project roots.

**Retention:** traces and context spills are local operational evidence. There is no
automatic retention cleanup; remove `.mini-openclaw/tool-runs/` manually according to
your project policy.

### 7. Developer Observability (`tracer.py`)

Each CLI/TUI ReAct run also writes a compact JSONL span trace under
`.mini-openclaw/agent-runs/<run-id>/trace.jsonl`. LLM and tool spans include order,
latency, success state, and redacted bounded previews; LLM spans additionally retain
provider token usage. Raw model prose is deliberately excluded so this debugging view
does not weaken the tool-evidence privacy boundary above.

The latest non-interactive run is available as `AgentLoop.last_tracer`:

```python
from agent.tracer import replay, cost_report

replay(agent.last_tracer)
cost_report(agent.last_tracer, prompt_price_per_1k=0.001,
            completion_price_per_1k=0.002)
```

Both helpers also accept a persisted `trace.jsonl` path. Prices are explicit estimates,
not provider billing data.

## Verification

- `--selfcheck` verifies: tool registry loads, FakeBackend works, main loop imports
- All 15 independent verifier tests pass (see `.plans/verify-*/`)

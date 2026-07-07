# eval/ — Evaluation Framework

## Architecture

The evaluation framework measures agent performance on tool calling and end-to-end tasks.

```
eval/
├── tasks.py    # Test case definitions (tool-call + E2E)
└── metrics.py  # Scoring functions (JSON validity, tool choice, arg accuracy)
```

## Key Design Decisions

### 1. Three Metrics

**Decision:** Measure tool calling along three independent axes.

**Why:** Tool calling failures can happen at multiple levels:
- **JSON validity** (`json_valid_rate`): Did the model produce parseable JSON? Raw output quality.
- **Tool choice accuracy** (`tool_choice_accuracy`): Did the model pick the right tool? Reasoning quality.
- **Argument accuracy** (`arg_accuracy`): Did the model pass the right arguments? Precision.

A model might produce perfect JSON but pick the wrong tool, or pick the right tool but mangle arguments. Measuring all three gives a complete picture.

### 2. `_extract_json()` — Brace-Based Extraction

**Decision:** Find outermost `{...}` via `text.find("{")` / `text.rfind("}")`.

**Why:** Simpler than regex for the common case where tool call output is a single JSON object. For production, `prompt.render.parse_tool_calls()` provides more robust extraction from `<tool_call>` tags.

### 3. Test Case Design (`tasks.py`)

**Decision:** 14 tool-call cases + 6 E2E tasks covering all 8 tools.

**Why:** Tool-call cases test individual tool selection in isolation. E2E tasks test multi-tool coordination. Both are needed — a model that nails individual tool calls might fail at task decomposition across multiple tools.

### 4. No Automated Test Runner

**Decision:** Metric functions are callable but there's no harness that runs all cases automatically.

**Why:** E2E tasks require a live LLM backend (API key + latency + cost). An automated harness would be fragile (API outages, rate limits) and expensive (each run costs tokens). Manual invocation keeps things simple for the course context.

## Ablation Framework

The E2E tasks in `tasks.py` are labeled "消融用" (for ablation). To run an ablation:
1. Pick a configuration variable (compaction on/off, task_list on/off, temperature, etc.)
2. Run all 6 E2E tasks under each configuration
3. Score with `metrics.py` functions
4. Compare results with data tables and analysis

The 6 E2E tasks: hello, todo-report, fix-bug, refactor, csv-report, multi-step.

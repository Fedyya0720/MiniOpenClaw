# Step 002: `parse_tool_calls()`

## Goal
Implement `parse_tool_calls()` in `prompt/render.py` — extract and parse `<tool_call>{json}</tool_call>` blocks from raw model output text.

## Day Mapping
Day 3, resolves TODO[Day3] in `prompt/render.py` line 54.

## Files
- `prompt/render.py` — MODIFY: implement the `parse_tool_calls()` function body

## Dependencies
Step 001 (`render_prompt()`) — same file, the parse function must be compatible with the render format.

## Constraints
- Must parse the exact format produced by `render_prompt()` tool call serialization: `<tool_call>{"name": "...", "arguments": {...}}</tool_call>`
- Must use regex or simple state machine — NO dependency on the API's native tool calling
- Must handle: zero tool calls, single call, multiple calls, malformed JSON
- Must return `list[dict]` with `{"name": str, "arguments": dict}` format (matching what `AgentLoop.run()` expects)
- `json.loads` for the JSON inside the tags
- Compact JSON format (no spaces) as produced by `json.dumps(ensure_ascii=False)`

## Risks
- Model might output partial/malformed `<tool_call>` tags — need graceful handling
- Model might output text before/after the tool_call blocks (thinking/reasoning) — need to extract only the tagged blocks
- Nested braces in arguments (e.g., `{"code": "x = {1: 2}"}`) — simple brace matching might fail
- Multiple tool calls might not be separated by newlines
- The regex must be non-greedy to handle multiple calls on the same line

## Why This Step Now
`parse_tool_calls()` is the inverse of `render_prompt()` — together they form the manual tool-calling path. The eval/metrics module (Step 011) needs `parse_tool_calls()` to extract tool calls from model outputs. Completing this finishes the Day 3 prompt module.

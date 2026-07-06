# Step 001: render_prompt() — Done

## Implementation Summary

### What was changed

**File modified**: `/home/l/Desktop/MiniOpenClaw/prompt/render.py`

### Changes

1. **ROLE_TOKENS updated** from GLM-style single-marker strings to DeepSeek ChatML begin/end pair tuples:
   - system: `("<|begin_of_system|>", "<|end_of_system|>")`
   - user: `("<|begin_of_user|>", "<|end_of_user|>")`
   - assistant: `("<|begin_of_assistant|>", "<|end_of_assistant|>")`
   - tool: `("<|begin_of_tool|>", "<|end_of_tool|>")`

2. **render_prompt() fully implemented** replacing the stub that raised `NotImplementedError`. The function:

   - **Input validation**: Non-list `messages` raises `TypeError` (mentions "list"). Non-dict message entries raise `TypeError` (mentions "dict"). Unknown roles raise `ValueError` (identifies the role).
   - **Tools rendering**: Calls `render_tools_block()` to produce the tools description text. If a system message exists, the tools block is prepended to its content. If no system message exists, a synthetic system segment is created containing the tools block.
   - **Message wrapping**: Each message's content is wrapped with its role's `(begin_token, end_token)` pair. Missing or `None` content defaults to `""`.
   - **Tool calls in assistant messages**: Each `tool_call` is serialized as `<tool_call>{compact_json}</tool_call>` using `json.dumps` with `separators=(",", ":")` and `ensure_ascii=False`. Multiple tool calls are separated by `\n`. Calls without `name` are skipped; missing `arguments` defaults to `{}`; non-dict entries are skipped gracefully.
   - **Tool observation messages**: Content is prefixed with `name: ` (e.g. `search: result 42`). If `name` is absent, content is rendered as-is.
   - **Generation prompt**: Always ends with `<|begin_of_assistant|>` (no end counterpart).
   - **No input mutation**: The function is pure — it reads from inputs but never modifies them.

3. **render_tools_block() kept unchanged** — it does not reference ROLE_TOKENS directly and produces tool description text compatible with both old and new token formats.

### Design decisions

- **BOS/EOS excluded**: As stated in the contract, BOS/EOS framing is the caller/tokenizer's responsibility. The function produces only the conversation body.
- **Tools placement**: Tools block is prepended to the first system message's content (if a system message exists). If no system message exists, a synthetic system segment is created. This ensures tools are always rendered before user messages.
- **Compact JSON for tool calls**: `separators=(",", ":")` removes whitespace, saving tokens. `ensure_ascii=False` preserves Unicode.
- **Skipping malformed tool_calls**: Tool call entries without a `name` or that are non-dicts are silently skipped rather than crashing. Missing `arguments` defaults to `{}`.

### Deviations from contract

None. All 18 ACs pass.

---

## Self-Check: Acceptance Criteria

### AC 1: No-tools, single message
**[PASS]**
```
$ python -c "..."
PASS
```

### AC 2: No-tools, multi-message with ordering
**[PASS]**
```
$ python -c "..."
PASS
```

### AC 3: Tools integrated into system area
**[PASS]**
```
$ python -c "..."
PASS
```

### AC 4: Assistant end-token always
**[PASS]**
```
$ python -c "..."
PASS
```

### AC 5: Assistant tool_calls serialized with structural equality
**[PASS]**
```
$ python -c "..."
PASS
```

### AC 6: Multiple tool_calls with newline separation
**[PASS]**
```
$ python -c "..."
PASS
```

### AC 7: Tool/observation message includes tool name
**[PASS]**
```
$ python -c "..."
PASS
```

### AC 8: Empty content does not crash
**[PASS]**
```
$ python -c "..."
PASS
```

### AC 9: Empty messages list
**[PASS]**
```
$ python -c "..."
PASS
```

### AC 10: tools=None vs tools=[]
**[PASS]**
```
$ python -c "..."
PASS
```

### AC 11: Integrates render_tools_block (behavioral)
**[PASS]**
```
$ python -c "..."
PASS
```

### AC 12: Return type is always str
**[PASS]**
```
$ python -c "..."
PASS
```

### AC 13: Idempotent / pure, no input mutation
**[PASS]**
```
$ python -c "..."
PASS
```

### AC 14: ROLE_TOKENS uses DeepSeek ChatML begin/end pairs
**[PASS]**
```
$ python -c "..."
PASS
```

### AC 15: No system message but tools provided
**[PASS]**
```
$ python -c "..."
PASS
```

### AC 16: Non-list messages raises TypeError
**[PASS]**
```
$ python -c "..."
PASS
```

### AC 17: Non-dict message entry raises TypeError
**[PASS]**
```
$ python -c "..."
PASS
```

### AC 18: Unknown role raises ValueError
**[PASS]**
```
$ python -c "..."
PASS
```

### Summary: 18/18 PASS, 0 FAIL

---

## Known Limitations

- **No BOS/EOS**: As designed, BOS/EOS tokens are not included. The caller must prepend/append them if needed.
- **Chinese system prompt**: `render_tools_block()` uses a Chinese-language prompt for tool calling instructions. This is acceptable for DeepSeek but may need localization for other models.
- **No escaping**: Literal `<|begin_of_user|>` or `<tool_call>` text in user messages is rendered as-is without escaping. This matters at parse time (Step 002), not at render time.
- **System message ordering**: If multiple system messages exist, only the first one gets the tools block prepended. Subsequent system messages are rendered normally.

# prompt/ — Prompt Rendering and Tool Call Parsing

## Architecture

The `prompt/` module contains the text-based tool calling layer. Instead of using the API's native function-calling feature, tool schemas and tool calls are rendered as text tokens the model generates directly.

```
prompt/
└── render.py    # render_prompt() + parse_tool_calls()
```

## Key Design Decisions

### 1. Text-Based Tool Calling (Not API Function Calling)

**Decision:** Render tools as text instructions + `<tool_call>` XML tags, parse model output with regex.

**Why:** This is how Claude Code works under the hood — it uses XML-style tool call blocks rather than the API's function-calling feature. Benefits:
- **Model-agnostic:** Works with any model that can generate structured text, not just those with function-calling APIs
- **Full control:** No dependency on API-specific tool call formats
- **Observable:** Tool calls are visible in the raw text output for debugging

**Tradeoff:** Requires a robust parser. Malformed JSON or missing tags need graceful handling.

### 2. ChatML Role Tokens

**Decision:** Use DeepSeek's ChatML variant tokens: `<|begin_of_system|>`, `<|begin_of_user|>`, `<|begin_of_assistant|>`, `<|begin_of_tool|>`.

**Why:** These are the native role markers DeepSeek models are trained on. Using them ensures the model correctly interprets which parts are instructions, which are conversation, and which are tool results.

### 3. `render_tools_block()` — Inline Schema Injection

**Decision:** Render tool schemas as text inside the first system message, not as a separate API parameter.

**Why:** Consistent with the text-based approach. The model sees:
```
## 可用工具
1. read: 读取文件...
   Parameters: {"path": "string"}
2. write: 写入文件...
   ...
```

### 4. `parse_tool_calls()` — Regex + Validation

**Decision:** Extract `<tool_call>{json}</tool_call>` blocks via regex, validate each one.

**Why:** The regex `r"<tool_call>(.*?)</tool_call>"` with `re.DOTALL` handles multi-line JSON naturally. Each extracted block is validated:
- Must parse as valid JSON
- Must be a dict
- Must have `name` (non-None string)
- `arguments` must be a dict (defaults to `{}` if absent)

Validation failures emit `warnings.warn()` — they don't crash the loop. This is important because a single malformed tool call shouldn't terminate the entire agent run.

## Edge Cases Handled

- **Missing content:** Messages with `None` content get empty string
- **Empty arguments:** `"arguments": None` → `{}`
- **Trailing assistant content:** Assumes the model hasn't started generating yet
- **Malformed UTF-8 in JSON:** Caught by `json.loads`, warned, skipped
- **Multiple tool calls in one message:** Each `<tool_call>` block parsed independently

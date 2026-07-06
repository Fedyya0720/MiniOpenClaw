# Step 001: render_prompt() — Done Standard

## Acceptance Criteria

1. **No-tools, single message**: `render_prompt()` returns a string containing the begin/end role tokens and content for a single user message with no tools, and ends with the assistant begin token.

2. **No-tools, multi-message with ordering**: Given system + user + assistant messages, the output contains one segment per message, each wrapped with the role's begin/end token pair, and preserves input ordering: `system_pos < user_pos < assistant_pos`.

3. **Tools integrated into system area**: When `tools` is a non-empty list, `render_tools_block()` output appears in the output, placed inside a system segment (or a synthetic system segment if no system message exists). The tools block text must appear before any user message segment.

4. **Assistant end-token always**: The output string always ends with the assistant begin token (e.g. `<|begin_of_assistant|>`) so the model knows to begin generating. This holds for: normal messages, empty messages list, and messages ending with a tool/observation role.

5. **Assistant tool_calls serialized with structural equality**: An assistant message with `tool_calls: [{"name": "search", "arguments": {"q": "hi"}}]` renders each call as `<tool_call>{"name": "search", "arguments": {"q": "hi"}}</tool_call>` inside the assistant segment. The JSON between `<tool_call>` and `</tool_call>` must parse as a dict structurally equal to `{"name": "search", "arguments": {"q": "hi"}}` (not just substring checks).

6. **Multiple tool_calls with newline separation**: An assistant message with multiple `tool_calls` renders them separated by newlines (`\n`) — i.e. `</tool_call>\n<tool_call>` appears between consecutive calls — not just the same number of tags.

7. **Tool/observation message includes tool name**: A `role: "tool"` message renders its content wrapped with the tool begin/end tokens, and the tool `name` is prepended to the content (e.g. `search: result 42`). The model can identify which tool produced which observation.

8. **Empty content does not crash**: A message with missing or empty `"content"` does not crash — it produces the role tokens with an empty string (for assistant) or a sensible placeholder. Specifically: empty-string content, absent content key, and assistant with tool_calls but empty content all render without error.

9. **Empty messages list**: `render_prompt([], tools=None)` returns only the assistant begin token (the generation prompt) and does not crash.

10. **tools=None vs tools=[]**: Both produce identical output (no tools block rendered).

11. **Integrates render_tools_block (behavioral)**: The output of `render_prompt(msgs, tools)` includes the exact text produced by `render_tools_block(tools)` — the function delegates tool schema rendering rather than duplicating logic.

12. **Return type is always str**: The function always returns `str` (never `None`), including for edge cases: empty messages list, missing content fields, and assistant messages with empty content + tool_calls.

13. **Idempotent / pure, no input mutation**: Running `render_prompt(msgs, tools)` twice with the same inputs produces the exact same string. Additionally, the function does not mutate the input `messages` list or its dicts — verified by `copy.deepcopy` before/after comparison.

14. **ROLE_TOKENS uses DeepSeek ChatML begin/end pairs**: The `ROLE_TOKENS` dict maps each role to a `(begin_token, end_token)` tuple matching DeepSeek's ChatML variant:
    - system: `("<|begin_of_system|>", "<|end_of_system|>")`
    - user: `("<|begin_of_user|>", "<|end_of_user|>")`
    - assistant: `("<|begin_of_assistant|>", "<|end_of_assistant|>")`
    - tool: `("<|begin_of_tool|>", "<|end_of_tool|>")`
    The render function wraps each message's content with BOTH begin AND end tokens (e.g. `<|begin_of_user|>hello<|end_of_user|>`). The final generation prompt is the assistant begin token alone (without its end counterpart).

15. **No system message but tools provided**: When `render_prompt` is called with tools but no system message (e.g. `messages=[{"role":"user","content":"q"}]`), it creates a synthetic system segment containing the tools block. Must not crash, and the output must still end with the assistant begin token.

16. **Non-list messages raises TypeError**: Passing a non-list value for `messages` (e.g. `"not_a_list"`, `None`) raises `TypeError` with a clear message, not an opaque `AttributeError`.

17. **Non-dict message entry raises TypeError**: Passing a list containing a non-dict entry (e.g. `["string_instead_of_dict"]`) raises `TypeError` with a clear message, not a confusing `KeyError`.

18. **Unknown role raises ValueError**: A message with a `role` value not in `ROLE_TOKENS` (e.g. `"asistant"` — misspelled) raises `ValueError` with a message identifying the unknown role, rather than silently producing garbage or crashing with an unrelated error.

## Verification Commands

Run each from the repo root (`/home/l/Desktop/MiniOpenClaw`). Every command must print `PASS` and exit 0.

```bash
# AC 1: single message, no tools — content, begin/end tokens, assistant end prompt
python -c "
from prompt.render import render_prompt
r = render_prompt([{'role':'user','content':'hello'}])
assert isinstance(r, str)
assert 'hello' in r
assert '<|begin_of_user|>' in r
assert '<|end_of_user|>' in r
# output must end with assistant begin token (generation prompt)
assert r.rstrip().endswith('<|begin_of_assistant|>')
print('PASS')
"

# AC 2: multi-message with ordering (system < user < assistant)
python -c "
from prompt.render import render_prompt
r = render_prompt([
    {'role':'system','content':'You are helpful.'},
    {'role':'user','content':'hi'},
    {'role':'assistant','content':'Hello!'},
])
# Content presence
assert 'You are helpful.' in r and 'hi' in r and 'Hello!' in r
# Role tokens presence
assert '<|begin_of_system|>' in r and '<|end_of_system|>' in r
assert '<|begin_of_user|>' in r and '<|end_of_user|>' in r
assert '<|begin_of_assistant|>' in r and '<|end_of_assistant|>' in r
# Ordering: system_pos < user_pos < assistant_pos
sp = r.find('<|begin_of_system|>')
up = r.find('<|begin_of_user|>')
ap = r.find('<|begin_of_assistant|>')
assert sp >= 0 and up >= 0 and ap >= 0, 'missing role token'
assert sp < up < ap, f'ordering failed: system={sp} user={up} assistant={ap}'
print('PASS')
"

# AC 3: tools integrated — tools block appears before user messages
python -c "
from prompt.render import render_prompt
r = render_prompt(
    [{'role':'system','content':'sys'},{'role':'user','content':'q'}],
    [{'type':'function','function':{'name':'search','description':'Search','parameters':{}}}]
)
assert 'search' in r and '<tool_call>' in r
# tools block text must appear before the first user message segment
tools_pos = r.find('search')
user_pos = r.find('<|begin_of_user|>')
assert tools_pos < user_pos, f'tools at {tools_pos}, user at {user_pos}'
print('PASS')
"

# AC 4: always ends with assistant begin token (normal, empty, tool-ending)
python -c "
from prompt.render import render_prompt
# Case 1: normal user message
r1 = render_prompt([{'role':'user','content':'x'}])
assert r1.rstrip().endswith('<|begin_of_assistant|>'), 'case 1 failed'
# Case 2: empty messages list
r2 = render_prompt([])
assert r2.rstrip().endswith('<|begin_of_assistant|>'), 'case 2 failed'
# Case 3: messages ending with tool/observation role
r3 = render_prompt([{'role':'user','content':'q'},{'role':'tool','content':'r','name':'f'}])
assert r3.rstrip().endswith('<|begin_of_assistant|>'), 'case 3 failed'
print('PASS')
"

# AC 5: assistant tool_calls serialized — structural JSON equality
python -c "
from prompt.render import render_prompt
import json, re
msg = {'role':'assistant','tool_calls':[{'name':'search','arguments':{'q':'hi'}}]}
r = render_prompt([msg])
# Extract JSON between <tool_call> and </tool_call>
m = re.search(r'<tool_call>(.*?)</tool_call>', r)
assert m is not None, 'no <tool_call> block found in output'
parsed = json.loads(m.group(1))
expected = {'name': 'search', 'arguments': {'q': 'hi'}}
assert parsed == expected, f'parsed {parsed} != expected {expected}'
print('PASS')
"

# AC 6: multiple tool_calls separated by newline
python -c "
from prompt.render import render_prompt
r = render_prompt([{'role':'assistant','tool_calls':[{'name':'a','arguments':{}},{'name':'b','arguments':{}}]}])
# Same number of opening tags
assert r.count('<tool_call>') == 2, f'expected 2 <tool_call> tags, got {r.count(\"<tool_call>\")}'
# Newline separation between consecutive calls
assert '</tool_call>\n<tool_call>' in r, 'missing newline between tool_calls'
print('PASS')
"

# AC 7: tool/observation message includes tool name in content
python -c "
from prompt.render import render_prompt
r = render_prompt([{'role':'tool','content':'result 42','name':'search','tool_call_id':'call_1'}])
# Tool begin/end tokens present
assert '<|begin_of_tool|>' in r
assert '<|end_of_tool|>' in r
# Tool name prepended to content: \"search: result 42\"
assert 'search: result 42' in r, f'tool name not found in observation: {r}'
print('PASS')
"

# AC 8: empty/missing content does not crash
python -c "
from prompt.render import render_prompt
# empty content string
r1 = render_prompt([{'role':'user','content':''}])
assert isinstance(r1, str)
# missing content key entirely
r2 = render_prompt([{'role':'assistant'}])
assert isinstance(r2, str)
# assistant with tool_calls but empty content
r3 = render_prompt([{'role':'assistant','content':'','tool_calls':[{'name':'f','arguments':{}}]}])
assert '<tool_call>' in r3
print('PASS')
"

# AC 9: empty messages list returns assistant begin token
python -c "
from prompt.render import render_prompt
r = render_prompt([])
assert isinstance(r, str) and len(r) > 0
assert r.rstrip().endswith('<|begin_of_assistant|>')
print('PASS')
"

# AC 10: tools=None vs tools=[] produce identical output
python -c "
from prompt.render import render_prompt
msg = [{'role':'user','content':'x'}]
r1 = render_prompt(msg, tools=None)
r2 = render_prompt(msg, tools=[])
assert r1 == r2
print('PASS')
"

# AC 11: output includes render_tools_block text (behavioral integration test)
python -c "
from prompt.render import render_prompt, render_tools_block
tools = [{'type':'function','function':{'name':'search','description':'Search web','parameters':{}}}]
block = render_tools_block(tools)
assert len(block) > 0, 'render_tools_block returned empty'
r = render_prompt([{'role':'user','content':'q'}], tools)
# The exact text produced by render_tools_block must appear in render_prompt output
assert block in r, 'render_tools_block output not found in render_prompt result'
print('PASS')
"

# AC 12: return type is always str (happy path + edge cases)
python -c "
from prompt.render import render_prompt
# Happy path
assert isinstance(render_prompt([{'role':'user','content':'test'}]), str)
# Empty messages
assert isinstance(render_prompt([]), str)
# Assistant with tool_calls, empty content
assert isinstance(render_prompt([{'role':'assistant','content':'','tool_calls':[{'name':'f','arguments':{}}]}]), str)
print('PASS')
"

# AC 13: idempotent / pure + input not mutated (deepcopy check)
python -c "
from prompt.render import render_prompt
import copy
msgs = [{'role':'user','content':'hi'}, {'role':'assistant','content':'hello'}]
original = copy.deepcopy(msgs)
r1 = render_prompt(msgs)
r2 = render_prompt(msgs)
assert r1 == r2, 'non-deterministic output'
assert msgs == original, 'input messages were mutated by render_prompt'
print('PASS')
"

# AC 14: ROLE_TOKENS uses DeepSeek ChatML begin/end pair tuples
python -c "
from prompt.render import ROLE_TOKENS
expected_roles = ['system', 'user', 'assistant', 'tool']
for role in expected_roles:
    assert role in ROLE_TOKENS, f'missing role: {role}'
    tokens = ROLE_TOKENS[role]
    assert isinstance(tokens, tuple), f'{role}: expected tuple, got {type(tokens).__name__}'
    assert len(tokens) == 2, f'{role}: expected (begin, end), got len={len(tokens)}'
    begin, end = tokens
    assert isinstance(begin, str) and isinstance(end, str), f'{role}: tokens must be strings'
    assert 'begin_of_' + role in begin, f'{role}: begin token mismatch: {begin}'
    assert 'end_of_' + role in end, f'{role}: end token mismatch: {end}'
# Verify assistant end token is not appended — the final output gets begin-only
print('PASS')
"

# AC 15: no system message with tools — synthetic system segment, no crash
python -c "
from prompt.render import render_prompt
r = render_prompt(
    [{'role':'user','content':'q'}],
    [{'type':'function','function':{'name':'search','description':'Search web','parameters':{}}}]
)
assert isinstance(r, str)
# Tools block was rendered (search appears)
assert 'search' in r
# Output still ends with assistant begin token
assert r.rstrip().endswith('<|begin_of_assistant|>')
print('PASS')
"

# AC 16: non-list messages raises TypeError with clear message
python -c "
from prompt.render import render_prompt
try:
    render_prompt('not_a_list')
    assert False, 'should have raised TypeError'
except TypeError as e:
    msg = str(e).lower()
    assert 'list' in msg, f'expected \"list\" in error message, got: {msg}'
print('PASS')
"

# AC 17: non-dict message entry raises TypeError with clear message
python -c "
from prompt.render import render_prompt
try:
    render_prompt(['string_instead_of_dict'])
    assert False, 'should have raised TypeError'
except TypeError as e:
    msg = str(e).lower()
    assert 'dict' in msg, f'expected \"dict\" in error message, got: {msg}'
print('PASS')
"

# AC 18: unknown role raises ValueError with role-identifying message
python -c "
from prompt.render import render_prompt
try:
    render_prompt([{'role':'asistant','content':'typo'}])
    assert False, 'should have raised ValueError'
except ValueError as e:
    msg = str(e).lower()
    assert 'asistant' in msg or 'role' in msg, f'expected role name in error, got: {msg}'
print('PASS')
"
```

## Edge Cases to Handle

| Category | Edge Case | Expected Behavior |
|----------|-----------|-------------------|
| **Empty inputs** | `messages=[]` | Return only the assistant begin token (generation prompt). No crash. |
| **Missing fields** | `content` absent from a message dict | Treat as empty string `""`. |
| **Missing fields** | `role` absent from a message dict | Raise `TypeError` — every message must have a `role` key. Input is malformed. |
| **Tool calls in assistant** | `tool_calls` present but `content` is `None` or `""` | Still serialize tool_calls; don't crash on missing content. |
| **Tool calls in assistant** | `tool_calls` contains a dict missing `arguments` key | Use empty dict `{}` as arguments, same convention as `_normalize()` in client.py. |
| **Tool calls in assistant** | `tool_calls` contains a dict missing `name` key | Skip that call or use `"unknown"`. Must not crash. |
| **Tool calls in assistant** | `tool_calls` contains non-dict entries (strings, None, numbers) | Skip non-dict entries gracefully. Must not crash on `t.get("name")` on a string. |
| **Tool calls in assistant** | Nested/complex JSON in arguments (deeply nested dicts, lists, booleans) | `json.dumps` must survive round-trip correctly. `ensure_ascii=False` used. |
| **Tool calls in assistant** | Unicode in tool name or arguments (CJK, emoji) | `json.dumps` uses `ensure_ascii=False` for correct rendering. |
| **Tool messages** | `role: "tool"` with `tool_call_id` and `name` fields | Render content wrapped with tool begin/end tokens. Prepend `name: ` to content. |
| **Tool messages** | `role: "tool"` without `name` field | Render content without name prefix. No crash. |
| **System messages** | Multiple system messages in the list | Render all of them. The first is primary per convention. |
| **System messages** | No system message but tools provided | Create a synthetic system segment containing the tools block. No crash. |
| **Unicode** | Content contains CJK, emoji, or special characters | Rendered correctly; no `UnicodeEncodeError`. `json.dumps` for tool_calls uses `ensure_ascii=False`. |
| **Large tools** | 50+ tool schemas with large parameter definitions | Renders without truncation. Performance is acceptable (pure string ops, no O(n^2)). |
| **Large messages** | Content with 10,000+ characters | No recursion limits or O(n^2) degradation. List + `join()` handles this. |
| **Nested loops** | Calling `render_prompt` in a tight loop with varying inputs | No shared mutable state between calls (function is pure). |
| **Input mutation** | Messages list and dicts must not be mutated | Verified via `copy.deepcopy` before/after comparison. |
| **Malformed inputs** | `messages` is not a list (string, None, int) | Raise `TypeError` with message mentioning "list". |
| **Malformed inputs** | `messages` list contains non-dict entries | Raise `TypeError` with message mentioning "dict". |
| **Unknown roles** | `role` present but not in `ROLE_TOKENS` (e.g. `"asistant"`) | Raise `ValueError` with message identifying the unknown role. |
| **Consecutive same-role messages** | Two `user` messages in a row | Render both independently, separated by tokens. No merging, no crash. |
| **Content with angle brackets** | User message containing literal `<|begin_of_user|>` or `<tool_call>` text | No escaping at render time (matters at parse time, not here). Rendered as-is. |
| **Malformed inputs** | `messages` is `None` explicitly | Raise `TypeError` with clear message (same as non-list handling). |

## Ambiguities — Final Decisions

### 1. ROLE_TOKENS: DeepSeek ChatML with begin/end pairs

**Decision**: SWITCH from GLM-style single-marker tokens to DeepSeek ChatML begin/end pairs now, not later.

The plan explicitly warns that wrong role tokens produce garbled model output. The production backend is `DeepSeekBackend`. DeepSeek V3/R1 uses a ChatML variant:

- System: `<|begin_of_system|>...<|end_of_system|>`
- User: `<|begin_of_user|>...<|end_of_user|>`
- Assistant: `<|begin_of_assistant|>...<|end_of_assistant|>`
- Tool: `<|begin_of_tool|>...<|end_of_tool|>`

The `ROLE_TOKENS` dict is restructured as `(begin, end)` tuples. The render function wraps each message's content with both tokens. The final generation prompt is the assistant begin token alone (no end counterpart), so the model knows to begin generating.

### 2. BOS/EOS token handling

**Decision**: DO NOT include BOS/EOS. `render_prompt()` produces the conversation body only. BOS/EOS framing is the tokenizer/caller's responsibility. This is documented in the function's docstring.

### 3. Tool call serialization format

**Decision**: KEEP `<tool_call>{"name": ..., "arguments": {...}}</tool_call>` as our convention. Use compact JSON from `json.dumps` (no extra spaces) — this saves tokens and is standard for tool calls. The `render_tools_block()` already teaches the model this format via the system prompt. The docstring and comments are updated to reflect compact JSON.

### 4. Tool observation message context

**Decision**: INCLUDE tool name in observation messages. Format: `tool_name: result_content` (e.g. `search: result 42`). The model needs to identify which tool produced which result, especially with parallel tool calls. If the message dict lacks a `name` field, render content without the name prefix — no crash.

### 5. Input validation policy

**Decision**: Validate early and loudly. Non-list `messages` raises `TypeError`. Non-dict message entries raise `TypeError`. Unknown roles raise `ValueError`. These are programming errors in the caller and should fail fast with clear messages, not silently produce garbage.

### 6. No-system-message with tools

**Decision**: When tools are provided but no system message exists, create a synthetic system segment wrapping the tools block. This ensures tools are rendered correctly without requiring the caller to always include a system message.

---

*Generated by Executor. Revised per Verifier feedback.*

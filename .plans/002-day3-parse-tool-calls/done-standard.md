# Done Standard: `parse_tool_calls()`

## Acceptance Criteria

Each criterion is falsifiable and includes a verification command.
All commands must be run from the project root (`/home/l/Desktop/MiniOpenClaw`).

### A1. No tool calls returns empty list
**Criterion:** When the input text contains zero `<tool_call>...</tool_call>` blocks, the function returns `[]`.

**Verification:**
```bash
python3 -c "
from prompt.render import parse_tool_calls
assert parse_tool_calls('plain text') == []
assert parse_tool_calls('') == []
print('PASS')
"
```

### A2. Single tool call parsed correctly
**Criterion:** A single `<tool_call>{"name":"foo","arguments":{"k":"v"}}</tool_call>` block returns a list with one dict containing `name` (str) and `arguments` (dict).

**Verification:**
```bash
python3 -c "
from prompt.render import parse_tool_calls
result = parse_tool_calls('<tool_call>{\"name\":\"greet\",\"arguments\":{\"who\":\"world\"}}</tool_call>')
assert len(result) == 1
assert result[0]['name'] == 'greet'
assert result[0]['arguments'] == {'who': 'world'}
print('PASS')
"
```

### A3. Multiple tool calls returned in order
**Criterion:** When the input contains multiple `<tool_call>` blocks, each is parsed and returned in the order they appear in the text.

**Verification:**
```bash
python3 -c "
from prompt.render import parse_tool_calls
text = '<tool_call>{\"name\":\"a\",\"arguments\":{}}</tool_call>\n<tool_call>{\"name\":\"b\",\"arguments\":{}}</tool_call>'
result = parse_tool_calls(text)
assert len(result) == 2
assert [r['name'] for r in result] == ['a', 'b']
print('PASS')
"
```

### A4. Multiple calls on the same line (non-greedy regex)
**Criterion:** Regex is non-greedy so two `<tool_call>` blocks on the same line without a newline separator are both extracted (not merged into one mangled call).

**Verification:**
```bash
python3 -c "
from prompt.render import parse_tool_calls
text = '<tool_call>{\"name\":\"x\",\"arguments\":{}}</tool_call><tool_call>{\"name\":\"y\",\"arguments\":{}}</tool_call>'
result = parse_tool_calls(text)
assert len(result) == 2, f'expected 2 calls, got {len(result)}'
assert result[0]['name'] == 'x'
assert result[1]['name'] == 'y'
print('PASS')
"
```

### A5. Leading/trailing text ignored
**Criterion:** Model thinking/reasoning text before the first tool_call block and after the last tool_call block is ignored. Only the tagged blocks are parsed.

**Verification:**
```bash
python3 -c "
from prompt.render import parse_tool_calls
text = 'Let me think...\n<tool_call>{\"name\":\"search\",\"arguments\":{\"q\":\"hi\"}}</tool_call>\nDone thinking.'
result = parse_tool_calls(text)
assert len(result) == 1
assert result[0]['name'] == 'search'
print('PASS')
"
```

### A6. Text between tool_call blocks ignored
**Criterion:** When text appears between two tool_call blocks, both blocks are still extracted correctly.

**Verification:**
```bash
python3 -c "
from prompt.render import parse_tool_calls
text = '<tool_call>{\"name\":\"a\",\"arguments\":{}}</tool_call>\nsome chatter\n<tool_call>{\"name\":\"b\",\"arguments\":{}}</tool_call>'
result = parse_tool_calls(text)
assert len(result) == 2
assert result[0]['name'] == 'a'
assert result[1]['name'] == 'b'
print('PASS')
"
```

### A7. Malformed JSON skipped with `warnings.warn()`
**Criterion:** A `<tool_call>` block containing invalid JSON (not parseable by `json.loads`) is skipped. A `UserWarning` is emitted via `warnings.warn()` so callers (e.g., `eval/metrics.py`) can detect and count unparseable blocks. Remaining valid blocks are still returned.

**Resolution:** Ambiguity #1 — Option B (warn, not silent). The `eval/metrics.py` module needs to distinguish "no tag" from "tag present but unparseable" for JSON validity rate computation.

**Verification:**
```bash
python3 -c "
import warnings
from prompt.render import parse_tool_calls
text = '<tool_call>{\"name\":\"good\",\"arguments\":{}}</tool_call>\n<tool_call>{bad json!}</tool_call>\n<tool_call>{\"name\":\"also_good\",\"arguments\":{}}</tool_call>'
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter('always')
    result = parse_tool_calls(text)
    assert len(result) == 2, f'expected 2 valid calls, got {len(result)}'
    assert result[0]['name'] == 'good'
    assert result[1]['name'] == 'also_good'
    assert len(w) >= 1, f'expected at least 1 warning for malformed JSON, got {len(w)}'
    assert any('malformed' in str(x.message).lower() or 'json' in str(x.message).lower() for x in w)
print('PASS')
"
```

### A8. Missing `name` field skipped with `warnings.warn()`
**Criterion:** A block whose parsed JSON lacks the `"name"` key is skipped. A `UserWarning` is emitted describing the reason.

**Verification:**
```bash
python3 -c "
import warnings
from prompt.render import parse_tool_calls
text = '<tool_call>{\"arguments\":{\"x\":1}}</tool_call>\n<tool_call>{\"name\":\"valid\",\"arguments\":{}}</tool_call>'
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter('always')
    result = parse_tool_calls(text)
    assert len(result) == 1
    assert result[0]['name'] == 'valid'
    assert len(w) >= 1, f'expected at least 1 warning for missing name, got {len(w)}'
    assert any('name' in str(x.message).lower() for x in w)
print('PASS')
"
```

### A9. Missing `arguments` field defaults to empty dict
**Criterion:** A block whose parsed JSON lacks the `"arguments"` key gets `arguments` defaulted to `{}`. No warning is emitted (missing arguments is a valid no-arg call).

**Verification:**
```bash
python3 -c "
import warnings
from prompt.render import parse_tool_calls
text = '<tool_call>{\"name\":\"no_args\"}</tool_call>'
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter('always')
    result = parse_tool_calls(text)
    assert len(result) == 1
    assert result[0]['name'] == 'no_args'
    assert result[0]['arguments'] == {}
    assert len(w) == 0, f'expected no warnings, got {len(w)}'
print('PASS')
"
```

### A10. `arguments: null` defaults to empty dict
**Criterion:** A block whose `arguments` value is JSON `null` (Python `None`) gets `arguments` defaulted to `{}`. No warning is emitted.

**Verification:**
```bash
python3 -c "
from prompt.render import parse_tool_calls
text = '<tool_call>{\"name\":\"f\",\"arguments\":null}</tool_call>'
result = parse_tool_calls(text)
assert len(result) == 1
assert result[0]['arguments'] == {}
print('PASS')
"
```

### A11. Nested braces in argument values handled correctly
**Criterion:** When `arguments` contains a string value with literal braces (e.g., source code `{1: 2}`), the JSON is parsed correctly without the regex breaking on those inner braces.

**Verification:**
```bash
python3 -c "
from prompt.render import parse_tool_calls
text = '<tool_call>{\"name\":\"eval\",\"arguments\":{\"code\":\"x = {1: 2}\"}}</tool_call>'
result = parse_tool_calls(text)
assert len(result) == 1
assert result[0]['name'] == 'eval'
assert result[0]['arguments']['code'] == 'x = {1: 2}'
print('PASS')
"
```

### A12. Return type + extra fields passthrough (superset key check)
**Criterion:** The return value is a `list`, each element is a `dict`, and every dict has **at least** the `name` (str) and `arguments` (dict) keys. Extra fields (e.g., `id`) are preserved — the key check uses `>=` (superset), not `==` (equality).

**Resolution:** Ambiguity #4 — Option B (pass through all fields). `AgentLoop.run()` accesses `call.get("id")`, and `DeepSeekBackend._normalize()` produces `{"id": ..., "name": ..., "arguments": ...}`. Stripping extra fields would lose data with no benefit.

**Verification:**
```bash
python3 -c "
from prompt.render import parse_tool_calls
# Standard call (name + arguments only)
text1 = '<tool_call>{\"name\":\"f\",\"arguments\":{\"a\":1}}</tool_call>'
result1 = parse_tool_calls(text1)
assert isinstance(result1, list)
assert isinstance(result1[0], dict)
assert isinstance(result1[0]['name'], str)
assert isinstance(result1[0]['arguments'], dict)
assert set(result1[0].keys()) >= {'name', 'arguments'}

# Call with extra 'id' field (as produced by DeepSeekBackend._normalize)
text2 = '<tool_call>{\"name\":\"g\",\"arguments\":{\"b\":2},\"id\":\"call_abc\"}</tool_call>'
result2 = parse_tool_calls(text2)
assert result2[0].get('id') == 'call_abc', 'extra field id must be preserved'
assert result2[0]['name'] == 'g'
assert result2[0]['arguments'] == {'b': 2}
assert set(result2[0].keys()) >= {'name', 'arguments', 'id'}
print('PASS')
"
```

### A13. Unicode / non-ASCII preserved
**Criterion:** `ensure_ascii=False` is used in `render_prompt`, so the JSON inside tool_call blocks may contain raw Unicode. `parse_tool_calls` must handle this.

**Verification:**
```bash
python3 -c "
from prompt.render import parse_tool_calls
text = '<tool_call>{\"name\":\"hello\",\"arguments\":{\"msg\":\"你好世界\"}}</tool_call>'
result = parse_tool_calls(text)
assert result[0]['arguments']['msg'] == '你好世界'
print('PASS')
"
```

### A14. Incomplete / truncated blocks are skipped
**Criterion:** A `<tool_call>` opening tag with no matching `</tool_call>` closing tag is ignored (not causing a crash or consuming the rest of the text). No warning is emitted for a simple non-match (the regex just finds zero matches).

**Verification:**
```bash
python3 -c "
from prompt.render import parse_tool_calls
text = '<tool_call>{\"name\":\"incomplete\",\"arg'
result = parse_tool_calls(text)
assert result == []
print('PASS')
"
```

### A15. Zero-argument tool calls work
**Criterion:** A tool call with empty arguments dict `{}` is parsed correctly.

**Verification:**
```bash
python3 -c "
from prompt.render import parse_tool_calls
text = '<tool_call>{\"name\":\"ping\",\"arguments\":{}}</tool_call>'
result = parse_tool_calls(text)
assert len(result) == 1
assert result[0]['name'] == 'ping'
assert result[0]['arguments'] == {}
print('PASS')
"
```

### A16. Non-string `name` field skipped with `warnings.warn()`
**Criterion:** If the parsed JSON has a `"name"` field whose value is not a string (e.g., integer `123`, `null`, `true`, array), the block is skipped and a `UserWarning` is emitted. Coercing `str(123)` would dispatch to a tool literally named `"123"`, which is almost certainly wrong.

**Resolution:** Ambiguity #5 — Option A (skip, don't coerce).

**Verification:**
```bash
python3 -c "
import warnings
from prompt.render import parse_tool_calls
text = '<tool_call>{\"name\":123,\"arguments\":{}}</tool_call>\n<tool_call>{\"name\":\"valid\",\"arguments\":{}}</tool_call>'
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter('always')
    result = parse_tool_calls(text)
    assert len(result) == 1, f'expected 1 valid call, got {len(result)}'
    assert result[0]['name'] == 'valid'
    assert len(w) >= 1, f'expected at least 1 warning for non-string name, got {len(w)}'
    assert any('name' in str(x.message).lower() for x in w)
print('PASS')
"
```

### A17. Non-dict, non-null `arguments` field skipped with `warnings.warn()`
**Criterion:** If the parsed JSON's `"arguments"` value is neither a dict nor `None` (e.g., a string `"foo"`, an array `[1,2,3]`, a number), the block is skipped and a `UserWarning` is emitted. `AgentLoop.run()` does `tool.run(**call.get("arguments", {}))` — `**` on a string or list would raise `TypeError`.

**Resolution:** Ambiguity #3 — Option B (skip the block). Defaulting to `{}` would silently discard the model's actual argument value.

**Verification:**
```bash
python3 -c "
import warnings
from prompt.render import parse_tool_calls
# string arguments
text1 = '<tool_call>{\"name\":\"bad1\",\"arguments\":\"some_string\"}</tool_call>\n<tool_call>{\"name\":\"ok\",\"arguments\":{}}</tool_call>'
# array arguments
text2 = '<tool_call>{\"name\":\"bad2\",\"arguments\":[1,2,3]}</tool_call>\n<tool_call>{\"name\":\"ok\",\"arguments\":{}}</tool_call>'
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter('always')
    r1 = parse_tool_calls(text1)
    assert len(r1) == 1 and r1[0]['name'] == 'ok', 'string arguments should be skipped'
    r2 = parse_tool_calls(text2)
    assert len(r2) == 1 and r2[0]['name'] == 'ok', 'array arguments should be skipped'
    assert len(w) >= 2, f'expected at least 2 warnings, got {len(w)}'
    assert any('argument' in str(x.message).lower() for x in w)
print('PASS')
"
```

### A18. Multiline JSON inside tags (regex `re.DOTALL`)
**Criterion:** The regex uses `re.DOTALL` so that `.` matches newlines. Real models may emit pretty-printed JSON spanning multiple lines: `<tool_call>\n{"name":...}\n</tool_call>`. Such blocks are parsed correctly.

**Verification:**
```bash
python3 -c "
from prompt.render import parse_tool_calls
text = '''<tool_call>
{\"name\":\"search\",\"arguments\":{\"q\":\"hello\",\"limit\":5}}
</tool_call>'''
result = parse_tool_calls(text)
assert len(result) == 1
assert result[0]['name'] == 'search'
assert result[0]['arguments'] == {'q': 'hello', 'limit': 5}
print('PASS')
"
```

### A19. Lenient whitespace around tags
**Criterion:** The regex allows optional whitespace inside the `<tool_call>` and `</tool_call>` tags (e.g., `< tool_call >`, `<  /tool_call >`). Models sometimes inject spaces around tags, especially at higher temperatures. The `render_prompt` function never produces such whitespace, but being lenient has near-zero cost and zero false-positive risk.

**Resolution:** Ambiguity #2 — Option B (lenient). Regex pattern: `<\s*tool_call\s*>(.*?)<\s*/\s*tool_call\s*>`

**Verification:**
```bash
python3 -c "
from prompt.render import parse_tool_calls
text = '< tool_call >{\"name\":\"f\",\"arguments\":{}}< /tool_call >'
result = parse_tool_calls(text)
assert len(result) == 1
assert result[0]['name'] == 'f'
print('PASS')
"
```

### A20. Round-trip integration: `parse_tool_calls(render_prompt(...))` recovers original tool calls
**Criterion:** `parse_tool_calls` must correctly consume the exact format produced by `render_prompt` (compact JSON via `separators=(",", ":")`, `ensure_ascii=False`). This is THE contract: what `render_prompt` produces, `parse_tool_calls` must consume. The test verifies recovery of tool calls that pass through the full render-then-parse cycle.

**Verification:**
```bash
python3 -c "
from prompt.render import parse_tool_calls, render_prompt

# Single tool call
msgs1 = [{'role': 'assistant', 'tool_calls': [{'name': 'search', 'arguments': {'q': 'hello world'}}]}]
text1 = render_prompt(msgs1)
result1 = parse_tool_calls(text1)
assert len(result1) == 1
assert result1[0]['name'] == 'search'
assert result1[0]['arguments'] == {'q': 'hello world'}

# Multiple tool calls
msgs2 = [{'role': 'assistant', 'tool_calls': [
    {'name': 'read', 'arguments': {'path': '/tmp/a'}},
    {'name': 'write', 'arguments': {'path': '/tmp/b', 'content': 'x'}},
]}]
text2 = render_prompt(msgs2)
result2 = parse_tool_calls(text2)
assert len(result2) == 2
assert result2[0]['name'] == 'read'
assert result2[1]['name'] == 'write'
assert result2[0]['arguments'] == {'path': '/tmp/a'}
assert result2[1]['arguments'] == {'path': '/tmp/b', 'content': 'x'}

# Tool call with Unicode in arguments
msgs3 = [{'role': 'assistant', 'tool_calls': [{'name': 'hello', 'arguments': {'msg': '你好'}}]}]
text3 = render_prompt(msgs3)
result3 = parse_tool_calls(text3)
assert len(result3) == 1
assert result3[0]['arguments']['msg'] == '你好'

# No tool calls (assistant text-only message)
msgs4 = [{'role': 'assistant', 'content': 'Hello, how can I help?'}]
text4 = render_prompt(msgs4)
result4 = parse_tool_calls(text4)
assert result4 == []

# Tool call with content + tool_calls (both present)
msgs5 = [{'role': 'assistant', 'content': 'Let me search that.', 'tool_calls': [{'name': 'search', 'arguments': {'q': 'x'}}]}]
text5 = render_prompt(msgs5)
result5 = parse_tool_calls(text5)
assert len(result5) == 1
assert result5[0]['name'] == 'search'

print('PASS')
"
```

---

## Edge Cases Table

| # | Input | Expected Behavior | Rationale |
|---|-------|-------------------|-----------|
| 1 | Empty string `""` | Return `[]` | No blocks to parse |
| 2 | Whitespace-only text `"  \n  "` | Return `[]` | No valid tool_call blocks |
| 3 | Single tag, compact JSON | Return `[{name, arguments}]` | Happy path |
| 4 | Multiple tags, newline-separated | Return list of all, in order | Standard model output format from `render_prompt` |
| 5 | Multiple tags, no separator (concatenated on one line) | Return list of all, in order | Non-greedy regex critical here |
| 6 | Text before first block (reasoning) | Ignored, blocks still parsed | Models often emit thinking text |
| 7 | Text after last block | Ignored | Models may emit trailing text |
| 8 | Text between blocks | Both blocks parsed, interleaving text discarded | Models may interleave narrative |
| 9 | Invalid JSON inside `<tool_call>...</tool_call>` | Block skipped; `warnings.warn()` emitted | Don't crash on model mistakes; `eval/metrics.py` needs detectability |
| 10 | Valid JSON but missing `"name"` key | Block skipped; `warnings.warn()` emitted | `name` is required to dispatch; caller must be informed |
| 11 | Valid JSON but missing `"arguments"` key | Default `arguments` to `{}` (no warning) | Friendly normalisation; missing args is a valid no-arg call |
| 12 | `"arguments": null` | Default to `{}` (no warning) | Same as missing — treat as no-arg call |
| 13 | `"arguments"` is a string (e.g., `"foo"`) | Block skipped; `warnings.warn()` emitted | `**kwargs` on a string raises `TypeError`; resolved: Ambiguity #3 Option B |
| 14 | Nested braces in string values | Parsed correctly by `json.loads`, regex unaffected | Regex matches `</tool_call>`, not balanced braces |
| 15 | Unicode/emoji in arguments | Preserved as-is | `ensure_ascii=False` in render |
| 16 | Incomplete opening tag (no closing `</tool_call>`) | Skipped (no match); no warning | Regex requires the closing tag; a simple non-match is not a parse failure |
| 17 | Unclosed tag at EOF | Skipped (no match); no warning | Regex requires the closing tag |
| 18 | Extra whitespace inside tags (e.g., `< tool_call > {...} < /tool_call >`) | Parsed correctly (lenient regex) | Resolved: Ambiguity #2 Option B — `<\s*tool_call\s*>` pattern |
| 19 | `id` field present in JSON (e.g., `{"name":"f","arguments":{},"id":"call_0"}`) | Preserved as extra key in returned dict | Resolved: Ambiguity #4 Option B — `AgentLoop.run()` accesses `call.get("id")` |
| 20 | Deeply nested arguments dict | Parsed correctly by `json.loads` | JSON parser handles arbitrary depth |
| 21 | Very large input (100k+ chars) | Function completes without O(n^2) blowup | Regex `finditer` is linear; `json.loads` is linear per match |
| 22 | `<tool_call>` tag nested inside another (malformed output) | Outer extracted, inner treated as literal text (or both matched) | Non-greedy regex stops at first `</tool_call>` |
| 23 | Escaped characters in JSON (`\"`, `\\`, `\n`) | Correctly parsed by `json.loads` | These are valid JSON escapes |
| 24 | JSON with pretty-printed newlines between tags | Parsed correctly (`re.DOTALL` makes `.` match `\n`) | Models sometimes emit multiline; the regex must be `re.DOTALL` |
| 25 | `<tool_call>` inside a markdown code fence (e.g., ` ```\n<tool_call>...</tool_call>\n``` `) | Still parsed (it is a real tool call, not a demo) | Models may wrap output in ``` fences; the regex does not care about surrounding characters |
| 26 | `"name"` field is integer `123` | Block skipped; `warnings.warn()` emitted | Resolved: Ambiguity #5 Option A — non-string names can't dispatch; coercing `str(123)` → tool named `"123"` is wrong |
| 27 | `"arguments"` field is a string `"foo"` | Block skipped; `warnings.warn()` emitted | Resolved: Ambiguity #3 Option B — `**` on a string raises `TypeError` |
| 28 | `"arguments"` field is an array `[1,2,3]` | Block skipped; `warnings.warn()` emitted | Same rationale as #27 |
| 29 | Tags with lenient whitespace: `< tool_call > {...} < /tool_call >` | Parsed correctly; recognised as valid tool call | Resolved: Ambiguity #2 Option B |
| 30 | Round-trip: `parse_tool_calls(render_prompt(msgs))` | Recovers original `name` and `arguments` values from tool calls | Integration contract; ensures `render_prompt` output format and `parse_tool_calls` input tolerance are aligned |

---

## Resolved Ambiguities

All five ambiguities from the original done-standard have been resolved per the Verifier's recommendations. The resolutions are encoded in the ACs and edge cases above.

### Ambiguity #1: Warning on skipped blocks?
**Decision: Option B — `warnings.warn()` on each skipped block.**

- `eval/metrics.py` needs to distinguish "no tool_call tag at all" from "tool_call tag present but unparseable" for JSON validity rate computation.
- `warnings.warn()` is the standard Python zero-config mechanism for "worth knowing but not fatal."
- Specific warning messages: malformed JSON, missing `name`, non-string `name`, non-dict `arguments`.
- Do NOT use `logging.warning()` — that requires logger configuration and is overkill for a library function.
- Implemented in: A7, A8, A16, A17.

### Ambiguity #2: Whitespace tolerance around tags?
**Decision: Option B — Lenient. Allow optional whitespace.**

- Regex pattern: `<\s*tool_call\s*>(.*?)<\s*/\s*tool_call\s*>` with `re.DOTALL`.
- Real models (especially smaller ones, or when temperature > 0) do inject spaces around tags.
- The cost of handling this is near zero; no legitimate text looks like `< tool_call >{valid json}< /tool_call >`.
- Implemented in: A19, edge cases #18 and #29.

### Ambiguity #3: Non-dict `arguments` value?
**Decision: Option B — Skip the block entirely.**

- `AgentLoop.run()` does `tool.run(**call.get("arguments", {}))`. If `arguments` is a string or list, `**` raises `TypeError`.
- Defaulting to `{}` (Option A) silently discards the model's actual output.
- Wrapping in `{"value": ...}` (Option C) invents a schema the tool doesn't expect.
- Combined with `warnings.warn()`, the caller knows a block was skipped and why.
- Implemented in: A17, edge cases #13, #27, #28.

### Ambiguity #4: Extra fields in parsed JSON?
**Decision: Option B — Pass through all fields.**

- `AgentLoop.run()` accesses `call.get("id")`. `DeepSeekBackend._normalize()` produces `{"id": ..., "name": ..., "arguments": ...}`.
- `eval/metrics.py` only accesses `.get("name")` and `.get("arguments")` — extra fields are invisible.
- Stripping is extra code for no real benefit. AC A12 uses `>=` (superset), not `==` (equality).
- Implemented in: A12, edge case #19.

### Ambiguity #5: `name` field that is not a string?
**Decision: Option A — Skip the block.**

- `AgentLoop.run()` does `self.registry.get(call["name"])`. `ToolRegistry.get()` expects a string key.
- Coercing `str(123)` → `"123"` would dispatch to a tool literally named `"123"`, which almost certainly doesn't exist.
- The plan requires `name: str` in the return type. Skipping non-strings enforces this invariant.
- Combined with `warnings.warn()`, the caller knows why the block was dropped.
- Implemented in: A16, edge case #26.

---

## Known Limitation

**`</tool_call>` as literal text inside arguments.** E.g., `{"name":"explain","arguments":{"topic":"the </tool_call> tag"}}`. The non-greedy regex `(.*?)` terminates at the first `</tool_call>`, yielding truncated JSON that fails `json.loads`. The block is then skipped with a warning. This is rare in practice and degrades gracefully.

---

## Implementation Notes

- **Regex pattern:** `<\s*tool_call\s*>(.*?)<\s*/\s*tool_call\s*>` with `re.DOTALL`.
- **Flags:** `re.DOTALL` is required so `.` matches newlines (for multiline JSON inside tags).
- **Non-greedy:** The `?` in `(.*?)` ensures the regex stops at the first `</tool_call>`, preventing two adjacent blocks from being merged into one.
- **Warning module:** Use `import warnings` + `warnings.warn(message, UserWarning)`. Do NOT use `logging`.
- **Return type:** `list[dict[str, Any]]` where each dict has `name: str` and `arguments: dict` at minimum.

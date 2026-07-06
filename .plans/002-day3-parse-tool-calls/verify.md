# Step 002: parse_tool_calls() -- VERIFY
## Verdict: **PASS**

All 20 Acceptance Criteria pass. All 30 additional edge case tests pass. No implementation defects found.

## Contract AC Checklist

| AC | Description | Verdict | Evidence |
|----|-------------|---------|----------|
| AC1 | No tool calls returns empty list | PASS | `parse_tool_calls('plain text') == []`, `parse_tool_calls('') == []` |
| AC2 | Single tool call parsed correctly | PASS | Returns `[{'name': 'greet', 'arguments': {'who': 'world'}}]` |
| AC3 | Multiple tool calls returned in order | PASS | Names extracted in order: `['a', 'b']` |
| AC4 | Multiple calls on same line (non-greedy regex) | PASS | Adjacent tags produce 2 separate calls, not 1 merged |
| AC5 | Leading/trailing text ignored | PASS | Reasoning text before/after block is discarded |
| AC6 | Text between tool_call blocks ignored | PASS | Both blocks extracted despite interleaving text |
| AC7 | Malformed JSON skipped with `warnings.warn()` | PASS | 1 warning emitted, message contains "malformed"; valid calls still returned |
| AC8 | Missing `name` field skipped with `warnings.warn()` | PASS | 1 warning emitted, message contains "name"; valid call still returned |
| AC9 | Missing `arguments` field defaults to empty dict | PASS | `arguments` defaults to `{}`; zero warnings emitted |
| AC10 | `arguments: null` defaults to empty dict | PASS | `arguments` defaults to `{}` |
| AC11 | Nested braces in argument values handled correctly | PASS | Source code `x = {1: 2}` preserved as string value |
| AC12 | Return type + extra fields passthrough (superset key check) | PASS | `id` field preserved; `set(keys) >= {'name', 'arguments', 'id'}` holds |
| AC13 | Unicode / non-ASCII preserved | PASS | Chinese characters `你好世界` preserved correctly |
| AC14 | Incomplete / truncated blocks are skipped | PASS | No closing tag -> empty list |
| AC15 | Zero-argument tool calls work | PASS | `{"arguments": {}}` parsed correctly |
| AC16 | Non-string `name` field skipped with `warnings.warn()` | PASS | Integer name 123 triggers warning; valid call still returned |
| AC17 | Non-dict, non-null `arguments` field skipped with `warnings.warn()` | PASS | String and array arguments both skip with warnings; 2+ warnings emitted |
| AC18 | Multiline JSON inside tags (regex `re.DOTALL`) | PASS | Pretty-printed JSON across 3 lines parsed correctly |
| AC19 | Lenient whitespace around tags | PASS | `< tool_call > {...} < /tool_call >` parsed correctly |
| AC20 | Round-trip integration: `parse_tool_calls(render_prompt(...))` recovers original tool calls | PASS | All 5 sub-cases pass: single, multiple, Unicode, no-tool-calls, content+tool_calls |

## Code Review Notes

### Implementation Matches Spec Exactly

- **Regex pattern:** `<\s*tool_call\s*>(.*?)<\s*/\s*tool_call\s*>` with `re.DOTALL`. Verified by `inspect.getsource()`.
- **JSON validation pipeline (5 layers):**
  1. `json.loads()` with `JSONDecodeError`/`TypeError` catch -- malformed JSON warned, skipped
  2. `isinstance(parsed, dict)` guard -- non-dict JSON (list, string, number, bool, null) warned, skipped
  3. `name` presence check (`parsed.get("name") is None`) -- missing name warned, skipped
  4. `name` type check (`isinstance(name, str)`) -- non-string name warned, skipped
  5. `arguments` type check -- missing/null defaults to `{}` (no warning); non-dict args warned, skipped
- **Warning module:** Uses `warnings.warn(message, UserWarning)` as specified. Not `logging`.
- **Extra fields passthrough:** All JSON keys preserved in returned dict (no stripping).
- **Return type:** `list[dict[str, Any]]` with each dict having at least `name: str` and `arguments: dict`.

### Minor Observation (non-blocking)

The spec's edge case table (#21) mentions "Regex `finditer` is linear". The implementation uses `re.findall` rather than `re.finditer`. Both are O(n) linear. `re.findall` with a single capture group returns a list of captured strings, which is functionally identical and simpler. Not a defect.

### Known Limitation (per contract, not a bug)

`</tool_call>` as literal text inside arguments (e.g. `{"topic":"the </tool_call> tag"}`) causes the non-greedy regex to terminate early, yielding truncated JSON that fails `json.loads`. The block is skipped with a warning. This is documented in the contract and degrades gracefully.

## Additional Edge Cases Tested (30 tests beyond the 20 ACs)

| # | Edge Case | Input | Result | Verdict |
|---|-----------|-------|--------|---------|
| E1 | Empty string | `""` | `[]` | PASS |
| E2 | Whitespace only | `"  \n  "` | `[]` | PASS |
| E3 | 150 tool calls (performance) | 150 concatenated `<tool_call>` blocks | All 150 parsed correctly in 0.0003s | PASS |
| E4 | 100k+ char input | Single tool call with 100k-char string argument | Parsed correctly | PASS |
| E5 | Emoji in tool name | `<tool_call>{"name":"🎉celebration",...}</tool_call>` | Name preserved as `🎉celebration` | PASS |
| E6 | Emoji in arguments | `{"arguments":{"emoji":"🎊"}}` | Preserved | PASS |
| E7 | Unicode special chars | `naïve_café` / `résumé` / `café ☕` | All preserved | PASS |
| E8 | Complex JSON escaping | Backslashes, quotes, newlines, tabs in strings | All correctly parsed by `json.loads` | PASS |
| E9 | Deep nesting (6 levels) | `{"l1":{"l2":{...}}}` | Fully traversed | PASS |
| E10 | Nested tool_call tags (malformed) | `<tool_call><tool_call>{...}</tool_call></tool_call>` | Non-greedy regex stops at first `</tool_call>`, inner JSON malformed, skipped with warning | PASS |
| E11 | Code fence around tool_call | ` ```\n<tool_call>...</tool_call>\n``` ` | Still parsed (correct) | PASS |
| E12 | Non-dict JSON: list | `<tool_call>[1,2,3]</tool_call>` | Skipped with warning ("not a dict") | PASS |
| E13 | Non-dict JSON: string | `<tool_call>"just a string"</tool_call>` | Skipped with warning ("not a dict") | PASS |
| E14 | Non-dict JSON: number | `<tool_call>42</tool_call>` | Skipped with warning ("not a dict") | PASS |
| E15 | Non-dict JSON: bool | `<tool_call>true</tool_call>` | Skipped with warning ("not a dict") | PASS |
| E16 | Non-dict JSON: null | `<tool_call>null</tool_call>` | Skipped with warning ("not a dict") | PASS |
| E17 | `name` is `null` | `{"name":null,...}` | Skipped with warning (missing name) | PASS |
| E18 | `name` is bool | `{"name":true,...}` | Skipped with warning (non-string name) | PASS |
| E19 | `name` is empty string | `{"name":"",...}` | Accepted (empty string IS a valid string) | PASS |
| E20 | `arguments` is integer | `{"arguments":42}` | Skipped with warning (non-dict) | PASS |
| E21 | `arguments` is bool | `{"arguments":false}` | Skipped with warning (non-dict) | PASS |
| E22 | Lenient whitespace: tabs | `<\ttool_call\t>...<\t/\ttool_call\t>` | Parsed correctly | PASS |
| E23 | Lenient whitespace: newlines | `<\ntool_call\n>...<\n/\ntool_call\n>` | Parsed correctly | PASS |
| E24 | Truncated closing tag `</tool` | Missing final `_call>` | No match, returns `[]` | PASS |
| E25 | Truncated closing tag `</tool_call` | Missing final `>` | No match, returns `[]` | PASS |
| E26 | Misspelled opening tag | `<toool_call>` | No match | PASS |
| E27 | Misspelled closing tag | `</toool_call>` | No match | PASS |
| E28 | Tags in wrong order | `</tool_call>...<tool_call>` | No match (regex requires opening first) | PASS |
| E29 | Empty content between tags | `<tool_call></tool_call>` | JSON parse error, warning, skipped | PASS |
| E30 | Known limitation: `</tool_call>` as literal text | `{"topic":"the </tool_call> tag"}` | Non-greedy regex truncates at first `</tool_call>`, malformed JSON, skipped with warning. Degrades gracefully per contract. | PASS |

## Retry Count: 1 of 3

# Step 002: parse_tool_calls() — VERIFY

## Verdict: **PASS**

## Contract AC Checklist

| AC | Status | Evidence |
|----|--------|----------|
| AC1 | PASS | No calls returns `[]` |
| AC2 | PASS | Single call: name="search", arguments={"q":"hi"} |
| AC3 | PASS | Two calls returned in order: a then b |
| AC4 | PASS | Two calls on same line both extracted (non-greedy regex) |
| AC5 | PASS | Leading/trailing text "think..."/"done." ignored |
| AC6 | PASS | Text between blocks ignored, both calls extracted |
| AC7 | PASS | Malformed JSON emits UserWarning, returns [] |
| AC8 | PASS | Missing name emits UserWarning, skipped |
| AC9 | PASS | Missing arguments defaults to {} |
| AC10 | PASS | arguments=null defaults to {} |
| AC11 | PASS | Nested braces `{1: 2}` in string value handled |
| AC12 | PASS | Extra field `id: "call_abc"` passes through |
| AC13 | PASS | CJK characters preserved (搜索, 你好) |
| AC14 | PASS | Incomplete `<tool_call>{"name": "f"` skipped (no closing tag) |
| AC15 | PASS | Empty arguments `{}` works |
| AC16 | PASS | Non-string name (integer 123) emits warning, skipped |
| AC17 | PASS | Non-dict arguments (string) emits warning, skipped |
| AC18 | PASS | Multiline JSON with newlines inside tags parsed (re.DOTALL) |
| AC19 | PASS | Lenient whitespace `< tool_call >` parsed |
| AC20 | PASS | Round-trip: render_prompt → parse_tool_calls recovers original tool calls |

## Additional Edge Cases Tested

- Empty string input: returns `[]`
- 100 tool calls in one string: all 100 parsed correctly
- JSON with complex nested structures: parsed correctly
- Emoji in tool names and arguments: preserved

## Code Review Notes

- Clean implementation, 61 lines
- Proper use of `warnings.warn(UserWarning)` for all skip paths
- `re.DOTALL` correctly handles multiline tool_call content
- Superset key check allows `id` and other extra fields
- Imports (`re`, `warnings`) added to module

## Retry Count

1 of 3

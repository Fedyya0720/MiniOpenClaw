# Step 002: parse_tool_calls() — Standard Feedback (Round 2)

## Previous Issues — Status (each: FIXED/PARTIALLY/NOT)

1. **ACs for non-string name + non-dict arguments (with warnings.warn):** FIXED. A16 covers non-string `name` (integer, null, etc.) skipped with `warnings.warn()`. A17 covers non-dict `arguments` (string, array, etc.) skipped with `warnings.warn()`.

2. **A7/A8 use warnings.warn instead of silent skip:** FIXED. Both A7 (malformed JSON) and A8 (missing name) now emit `warnings.warn()` with captured-warning assertions in their verification scripts.

3. **A12 key check relaxed to superset (allows 'id' field):** FIXED. Verification uses `set(keys) >= {'name', 'arguments'}` (superset). Extra `id` field passthrough is tested explicitly with `{"name":"g","arguments":{"b":2},"id":"call_abc"}`.

4. **Round-trip AC added:** FIXED. A20 covers `parse_tool_calls(render_prompt(...))` with 5 sub-cases: single call, multiple calls, Unicode, no-tool-call message, and content+tool_calls message.

## Any New Issues

None. The revised done-standard is thorough and self-consistent.

All should-fix items from Round 1 were also incorporated:
- A18: Multiline JSON inside tags (`re.DOTALL`)
- A19: Lenient whitespace around tags (`<\s*tool_call\s*>`)
- Edge cases table expanded to 30 entries (was 23)
- All 5 ambiguities have explicit resolution sections with rationale
- Known limitation (`</tool_call>` as literal text in arguments) is documented
- Implementation notes specify regex pattern, flags, warning mechanism, and return type

## Verdict: READY TO IMPLEMENT

# Step 001: render_prompt() -- Standard Feedback (Round 2)

## Previous Issues -- Status

1. **Fix AC 11 (source-code inspection -> behavioral)**: FIXED. The revised AC 11 calls `render_tools_block()` separately and asserts its exact text appears in `render_prompt()` output -- pure behavioral test, no `inspect.getsource`.

2. **Strengthen AC 2 (add ordering assertions)**: FIXED. Verification now computes `r.find()` for system/user/assistant begin tokens and asserts `sp < up < ap`.

3. **Strengthen AC 5 (JSON parse, structural equality)**: FIXED. Verification uses `re.search` + `json.loads` and asserts `parsed == expected` dict equality.

4. **Strengthen AC 4 (add tests for "always" claim)**: FIXED. Three cases tested: normal user message, empty messages `[]`, and messages ending with tool/observation role. All assert `.endswith('<|begin_of_assistant|>')`.

5. **Strengthen AC 6 (verify newline separation)**: FIXED. Asserts both tag count AND `'</tool_call>\n<tool_call>' in r`.

6. **Strengthen AC 7 (include tool name in output)**: FIXED. Verification asserts `'search: result 42' in r`, confirming the `name: content` format.

7. **Add AC for ROLE_TOKENS format (Ambiguity #1)**: FIXED. AC 14 validates that ROLE_TOKENS has system/user/assistant/tool, each is a `(begin, end)` tuple of strings, containing `begin_of_<role>` / `end_of_<role>` substrings. The AC text specifies exact DeepSeek ChatML token strings.

8. **Add AC for tool name in observation (Ambiguity #4)**: FIXED. Strengthened AC 7 covers this -- `search: result 42` format is verified.

9. **Add ACs for edge cases M1-M4**: FIXED.
   - M1 (no system message + tools): AC 15 -- synthetic system segment, no crash, ends with assistant begin token.
   - M2 (malformed messages list): AC 16 -- TypeError with "list" in message.
   - M3 (non-dict message entry): AC 17 -- TypeError with "dict" in message.
   - M4 (unknown role): AC 18 -- ValueError with role-identifying message.

10. **Fix AC 13 (add deepcopy mutation check)**: FIXED. Verification now does `original = copy.deepcopy(msgs)` before calls, then `assert msgs == original` after.

## AC Review -- any NEW issues with the revised ACs?

1. **Missing `role` key: edge case without verification command.** The edge case table (line 301) says "`role` absent from a message dict -- Raise `TypeError`." This is a distinct code path from AC 17 (non-dict entries) and AC 18 (unknown role). A dict like `{"content": "hello"}` with no `role` key will cause `KeyError` on `msg["role"]` if not explicitly handled. There is no formal AC or verification command for this edge case. This is a moderate gap -- the implementor must remember to add this check without an automated guardrail.

2. **AC 14 token string verification is structural, not exact.** The verification checks that tokens contain `begin_of_<role>` and `end_of_<role>` substrings, but does not verify the exact format `<|begin_of_system|>` etc. The AC text specifies the exact strings, so an implementor using `<begin_of_system>` (without `|` pipes) would pass the verification but produce wrong tokens. This is minor -- any plausible implementation error would be caught by AC 1/2 which assert the actual token strings appear in rendered output.

3. **AC 16 tests only string, not None or int.** The edge case table lists `messages=None` and `messages=42` as malformed inputs, but the AC 16 verification only tests with the string `'not_a_list'`. All three would be caught by the same `isinstance(messages, list)` check, so this is acceptable as a representative test.

## New Missing Edge Cases -- anything still not covered?

None beyond the single issue noted above (missing `role` key without verification command). The edge case table (lines 297-322) is thorough -- 24 rows covering empty inputs, missing content fields, tool_calls edge cases (missing arguments, missing name, non-dict entries, nested JSON, Unicode), tool messages (with/without name), system messages (multiple, absent-with-tools), Unicode content, large inputs, nested loops, input mutation, malformed inputs, unknown roles, consecutive same-role messages, and content containing angle bracket tokens.

The M5-M10 edge cases from the previous round are all in the table. While they lack formal AC verification commands, the original feedback classified M1-M4 as "must-fix" and M5-M10 as "should-fix" -- the table coverage is appropriate for "should-fix" items.

## Verdict

**READY TO IMPLEMENT** -- with one note for the implementor:

The edge case table correctly states that a message dict missing the `role` key should raise `TypeError`, but no AC verification enforces it. The implementor should ensure the code handles `msg.get("role")` or validates key presence before AC 18's role lookup, otherwise a `{"content": "hello"}` message will crash with `KeyError` instead of the intended `TypeError`.

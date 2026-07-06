# Step 002: parse_tool_calls() — DONE

## Implementation Summary
Implemented `parse_tool_calls()` in `prompt/render.py` (lines 122-182). Uses regex `re.findall(r'<\s*tool_call\s*>(.*?)<\s*/\s*tool_call\s*>', text, re.DOTALL)` to extract tool_call blocks, then `json.loads()` each one. Validates: name is present and string, arguments is dict (or defaults to {}). Skips malformed blocks with `warnings.warn(UserWarning)`. Extra fields (like `id`) pass through. Added `import re` and `import warnings` to module imports.

## Files Changed
- `prompt/render.py`: added `import re`, `import warnings` (lines 16-17); replaced `parse_tool_calls()` stub with full implementation (lines 122-182, 61 lines)

## Deviations
None — implementation follows the agreed done-standard.md contract.

## Known Limitations
- `<tool_call>` appearing inside a string literal within a tool call's JSON arguments would break parsing. This is a fundamental limitation of regex-based extraction and is documented in the edge cases table.
- `arguments` values that are valid JSON but not dicts (strings, arrays, numbers) are rejected with a warning. This matches the contract.

# Step 001: `render_prompt()`

## Goal
Implement `render_prompt()` in `prompt/render.py` — convert structured messages + tool schemas into a single flat text string that a language model can ingest.

## Day Mapping
Day 3, resolves TODO[Day3] in `prompt/render.py` lines 46-48.

## Context
The production path uses `DeepSeekBackend.chat()` which sends messages+tool schemas via the OpenAI-native API format. `render_prompt()` is the manual path — it concatenates everything into one string with role-delimiter tokens. This is needed for:
- Understanding how tokenization and tool-call formatting actually works under the hood
- The eval/metrics module which needs to process raw model output text
- A fallback/educational path independent of API function-calling

The file already has:
- `ROLE_TOKENS` dict (line 19-24) — GLM-style tokens, may need updating for DeepSeek's actual token format
- `render_tools_block()` (line 27-37) — already implemented, renders tool schemas as text
- `render_prompt()` (line 40-49) — stub, raises NotImplementedError

## Files
- `prompt/render.py` — MODIFY: implement the `render_prompt()` function body

## Dependencies
None. Pure string manipulation.

## Constraints
- Must work with the existing `ROLE_TOKENS` dict (or update it if wrong for DeepSeek)
- Must integrate with the already-working `render_tools_block()` for tool descriptions
- Output must be a single string suitable for tokenization
- Must handle: system messages, user messages, assistant messages (with possible tool_calls), and tool/observation messages
- The format should be reasonable for any ChatML-style model (DeepSeek, GLM, etc.)

## Risks
- Wrong role tokens will produce garbled model output. DeepSeek uses a ChatML variant — verify the exact tokens.
- Messages with `tool_calls` in assistant messages need special handling (serialize the tool call JSON into the text)
- Empty content fields (e.g., assistant messages that only have tool_calls) need sensible defaults
- The tool block goes into the system message area — placement matters for model attention

## Why This Step Now
First step in the dependency chain. It's independent of all other modules (pure string ops), so it can be built and verified without waiting for anything else. Completing this unblocks Step 002 (parse_tool_calls) and the eval metrics work later.

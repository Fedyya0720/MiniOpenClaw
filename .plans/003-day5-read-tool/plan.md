# Step 003: `_read()` Tool

## Goal
Implement `_read()` in `tools/fs.py` — read a file and return its content with line numbers, truncating if over max_bytes.

## Day Mapping
Day 5, resolves TODO[Day5] in `tools/fs.py` line 7.

## Files
- `tools/fs.py` — MODIFY: implement the `_read()` function body

## Dependencies
None. Depends only on `tools/base.py` (already complete).

## Constraints
- Must prefix each line with `NNN> ` (padded line numbers)
- Must truncate at max_bytes with a clear notice like `...[truncated to {max_bytes} bytes, total {original_size} bytes]`
- Must raise FileNotFoundError for nonexistent paths
- Must handle binary files gracefully (UnicodeDecodeError → wrap in a readable error)
- Default max_bytes: 100,000

## Risks
- Binary files will cause UnicodeDecodeError — catch and return error message
- Very large files should be read in chunks or with size check before full read
- Path traversal: don't restrict paths (Day 10 adds sandbox)

# Step 004: `_write()` Tool

## Goal
Implement `_write()` in `tools/fs.py` — write content to a file, creating parent directories as needed.

## Day Mapping
Day 5, resolves TODO[Day5] in `tools/fs.py` line 12.

## Files
- `tools/fs.py` — MODIFY: implement the `_write()` function body

## Dependencies
Step 003 (_read — same file, avoid merge conflicts). Depends on `tools/base.py` (done).

## Constraints
- Create parent directories if they don't exist (`os.makedirs` or `pathlib.Path.mkdir(parents=True)`)
- Overwrite existing files (not append)
- Return confirmation message: file path + bytes written
- Handle permission errors gracefully (return error message, don't crash)
- Day 10 will add working-directory sandbox — just note in a comment

## Risks
- Writing outside the working directory (no restriction yet — Day 10)
- Path is a directory, not a file → raise IsADirectoryError or return error
- Permission denied → catch and return error string

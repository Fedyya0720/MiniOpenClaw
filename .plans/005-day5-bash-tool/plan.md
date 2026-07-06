# Step 005: `_bash()` Tool

## Goal
Implement `_bash()` in `tools/shell.py` — execute a shell command with timeout and return stdout/stderr/returncode.

## Day Mapping
Day 5, resolves TODO[Day5] in `tools/shell.py` line 7. (Line 8 is Day 10 sandbox.)

## Files
- `tools/shell.py` — MODIFY: implement the `_bash()` function body

## Dependencies
None. Depends only on `tools/base.py` (done).

## Constraints
- Use `subprocess.run()` with `shell=True`, `capture_output=True`, `text=True`
- Default timeout: 30 seconds
- Return format: stdout + stderr + returncode in a readable format
- On timeout: catch `subprocess.TimeoutExpired` and return clear error message
- Working directory: use `os.getcwd()` (or configurable)
- Day 10 will add sandbox + dangerous-command detection — just note in a comment

## Risks
- Shell injection: `shell=True` is inherently dangerous — this is by design for flexibility, Day 10 mitigates
- Very long output: should be truncated (coordinate with `truncate_observation()` in `agent/context.py`)
- Infinite loops in commands: timeout handles this
- Commands that modify system state (`rm -rf`, etc.) — Day 10 sandbox

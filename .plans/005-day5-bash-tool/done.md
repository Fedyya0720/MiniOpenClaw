# Step 005: _bash() — DONE

## Implementation Summary
Implemented `_bash()` in `tools/shell.py`. Uses `subprocess.run(shell=True, capture_output=True, text=True, timeout=timeout)`. Returns formatted output with stdout, stderr (prefixed), and [returncode: N]. Catches TimeoutExpired for clear error messages.

## Files Changed
- `tools/shell.py`: replaced `_bash()` stub (3 lines) with implementation (25 lines), added `import subprocess`

## Self-Check
All 5 ACs pass.

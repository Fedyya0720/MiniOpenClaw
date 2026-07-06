# Step 005: _bash() — Done Standard

## Acceptance Criteria
1. **Basic execution**: `_bash("echo hello")` returns stdout with "hello" and [returncode: 0]
2. **Stderr capture**: commands writing to stderr include stderr in output
3. **Nonzero exit**: `_bash("exit 1")` shows [returncode: 1]
4. **Timeout**: `_bash("sleep 5", timeout=1)` returns timeout error message
5. **Return type**: always returns str

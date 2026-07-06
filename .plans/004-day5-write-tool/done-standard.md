# Step 004: _write() — Done Standard

## Acceptance Criteria
1. **Basic write**: `_write(path, content)` creates the file with the given content → confirmation message with byte count
2. **Parent directories**: writing to `a/b/c.txt` creates `a/b/` automatically
3. **Overwrite**: writing to an existing file replaces its content
4. **Permission error**: writing to `/etc/foo` (without sudo) returns error string, no crash
5. **IsADirectoryError**: writing to a path that is a directory returns error string
6. **Return type**: always returns str

# Done Standard: Step 003 — `_read()` Tool

## Acceptance Criteria

### AC-1: Line numbers are prefixed in 6-digit padded format
- **Description**: Each output line starts with `NNNNNN> ` where the line number is right-aligned in 6 characters.
- **Verification**:
  ```bash
  python -c "
  from tools.fs import _read
  out = _read('tools/fs.py', max_bytes=2000)
  lines = out.split('\n')
  # First few lines should match pattern '     1> ...'
  import re
  for line in out.split('\n')[:5]:
      if line.strip():
          assert re.match(r'^     \d> ', line), f'Bad line format: {repr(line[:20])}'
  print('PASS: AC-1')
  "
  ```

### AC-2: Truncation at max_bytes with clear message
- **Description**: When a file exceeds `max_bytes`, output is truncated and a notice like `...[truncated to {max_bytes} bytes, total {original_size} bytes]` is appended.
- **Verification**:
  ```bash
  python -c "
  from tools.fs import _read
  import os
  out = _read('tools/fs.py', max_bytes=200)
  assert 'truncated to 200 bytes' in out, 'Missing truncation notice'
  original_size = os.path.getsize('tools/fs.py')
  assert f'total {original_size} bytes' in out, 'Missing original size in notice'
  # Content should be roughly max_bytes or less (in bytes)
  print('PASS: AC-2')
  "
  ```

### AC-3: FileNotFoundError propagates without being caught
- **Description**: Calling `_read()` on a nonexistent path raises `FileNotFoundError`.
- **Verification**:
  ```bash
  python -c "
  from tools.fs import _read
  try:
      _read('/tmp/__nonexistent_file_xyz123__.txt')
      assert False, 'Should have raised FileNotFoundError'
  except FileNotFoundError:
      print('PASS: AC-3')
  "
  ```

### AC-4: UnicodeDecodeError is caught and returns an error message string
- **Description**: Reading a binary file returns a string error message instead of crashing.
- **Verification**:
  ```bash
  python -c "
  from tools.fs import _read
  # Create a binary file with invalid UTF-8
  with open('/tmp/__binary_test.bin', 'wb') as f:
      f.write(b'\x80\x81\x82\xff\xfe')
  result = _read('/tmp/__binary_test.bin')
  assert isinstance(result, str), 'Should return string'
  assert 'Error' in result and 'UTF-8' in result, f'Bad error message: {result}'
  print('PASS: AC-4')
  "
  ```

### AC-5: Default max_bytes is 100,000
- **Description**: The `max_bytes` parameter defaults to 100,000.
- **Verification**:
  ```bash
  python -c "
  import inspect
  from tools.fs import _read
  sig = inspect.signature(_read)
  assert sig.parameters['max_bytes'].default == 100_000, f'Default is {sig.parameters[\"max_bytes\"].default}'
  print('PASS: AC-5')
  "
  ```

### AC-6: Empty file produces empty output
- **Description**: Reading an empty file returns an empty string (no line numbers, no crash).
- **Verification**:
  ```bash
  python -c "
  from tools.fs import _read
  with open('/tmp/__empty_test.txt', 'w') as f:
      pass
  result = _read('/tmp/__empty_test.txt')
  assert result == '', f'Expected empty string, got: {repr(result)}'
  print('PASS: AC-6')
  "
  ```

### AC-7: Files under max_bytes are fully returned
- **Description**: A file smaller than max_bytes returns all content with line numbers and no truncation notice.
- **Verification**:
  ```bash
  python -c "
  from tools.fs import _read
  test_content = 'line one\nline two\nline three\n'
  with open('/tmp/__small_test.txt', 'w') as f:
      f.write(test_content)
  result = _read('/tmp/__small_test.txt', max_bytes=100000)
  assert 'line one' in result
  assert 'line two' in result
  assert 'line three' in result
  assert 'truncated' not in result
  # Count lines: 3 content lines
  assert result.count('\n') == 2, f'Expected 2 newlines, got {result.count(chr(10))}'
  print('PASS: AC-7')
  "
  ```

### AC-8: read_tool is properly wired
- **Description**: The `read_tool` Tool object has correct name, description, parameters schema, and `_read` as its run function.
- **Verification**:
  ```bash
  python -c "
  from tools.fs import read_tool, _read
  assert read_tool.name == 'read', f'Bad name: {read_tool.name}'
  assert read_tool.run is _read, 'run not wired to _read'
  assert read_tool.parameters['required'] == ['path'], f'Bad required: {read_tool.parameters[\"required\"]}'
  assert 'path' in read_tool.parameters['properties']
  print('PASS: AC-8')
  "
  ```

## Edge Cases

| # | Edge Case | Expected Behavior |
|---|-----------|-------------------|
| 1 | Empty file (0 bytes) | Returns empty string `""` |
| 2 | File with no trailing newline | All lines numbered, no extra empty line |
| 3 | File with trailing newline | Final empty line after split is handled (no spurious numbered blank line) |
| 4 | Binary file (invalid UTF-8) | Returns error string mentioning UTF-8, does not crash |
| 5 | File exactly at max_bytes boundary | Full content returned, no truncation notice |
| 6 | File 1 byte over max_bytes | Content truncated, truncation notice appended |
| 7 | max_bytes=0 | Returns truncation notice with content from 0 bytes |
| 8 | Multi-byte UTF-8 char split at truncation boundary | Incomplete bytes trimmed, message still accurate |
| 9 | Nonexistent path | FileNotFoundError propagates |
| 10 | Very large file (>100MB) | Only reads max_bytes+1 bytes, efficient, no OOM |
| 11 | Single-line file | Single numbered line returned |
| 12 | File with Unicode (e.g., Chinese characters) | Correctly decoded and displayed |

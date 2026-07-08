# tools/ — Built-in Tool Set

## Architecture

Each tool is a `Tool` dataclass with `name`, `description`, `parameters` (JSON Schema), and a `run(**kwargs) -> str` callable. All tools are registered in `build_default_registry()` in [base.py](base.py).

```
tools/
├── base.py       # Tool dataclass, ToolRegistry, build_default_registry()
├── fs.py         # read, write (with Day10 write-path sandbox)
├── shell.py      # bash (with Day10 sandbox)
└── more_tools.py # edit, grep, glob, web_fetch, task_list
```

## Key Design Decisions

### 1. Tool Return Type: String

**Decision:** All tools return `str`, never structured objects.

**Why:** The tool result is injected verbatim into the LLM context as a `role="tool"` message. The model reads natural language, not JSON-RPC responses. Returning strings means no serialization layer between tool output and model input. Errors are also strings — the model sees them as natural "error: file not found" messages.

### 2. `edit` Tool: Unique-Match Strategy

**Decision:** `edit` requires `old` to be a unique substring match, failing otherwise.

**Why:** This is the simplest correct strategy. Ambiguous matches (0 or >1) reject with a clear error telling the model to use more context. Alternatives considered:
- **Line-number-based editing:** Fragile — line numbers drift after any edit.
- **Full-file rewrite:** Wasteful for large files, loses unrelated edits.
- **Diff/apply:** Too complex for a 10-day project.

Unique-match search-replace is the "just right" point on the simplicity-reliability curve.

### 3. `bash` Sandbox Architecture

**Decision:** Pattern-based blocking (not container/VM isolation).

**Why:** Container isolation (Docker, firecracker) requires root privileges and significantly more infrastructure. For a 10-day course, pattern-based blocking catches the obvious attacks while remaining simple enough for students to understand and extend. The blocking list includes: recursive deletion, filesystem formatting, raw device writes, fork bombs, permission escalation, pipe-to-shell injection, and system shutdown commands.

**Known limitations:** A determined adversary can bypass substring matching. This is acceptable for the educational context. A production agent would additionally use seccomp filters or container isolation.

### 4. `write` Path Sandbox

**Decision:** Resolve all paths relative to working directory, block escapes.

**Why:** File system writes are the most dangerous tool operation. Confining writes to the working directory prevents accidental (or malicious) modification of system files, configuration, or other projects. Protected paths (`.git`, `.env`, `.ssh`, `.gnupg`) are also blocked regardless of location.

### 5. `web_fetch` SSRF Protection

**Decision:** Block IP-address URLs in private/internal ranges before sending requests.

**Why:** An agent with network access must not be able to probe internal services. Filtering by IP range (RFC 1918, loopback, link-local, etc.) catches ~95% of SSRF vectors. DNS-based attacks (domain resolving to internal IP) are not caught — detecting those requires egress filtering or a proxy.

### 6. `grep` wraps `ripgrep`; `glob` uses `pathlib`

**Decision:** Use system `rg` for grep, Python stdlib for glob.

**Why:** `ripgrep` is fast, respects `.gitignore`, and handles large codebases. `pathlib.rglob` handles patterns natively without regex translation. Both tools truncate output at 200 results — preventing a single query from flooding context.

## Tool Schema Design

Each tool's JSON Schema `parameters` follows OpenAI function-calling conventions:
- `type: "object"` at top level
- `properties` dict with per-arg types and descriptions
- `required` list for mandatory arguments

Descriptions are in Chinese (matching the course's primary language) — the model handles mixed-language prompts well.

# skills/ — Domain Knowledge Skills

## Architecture

Skills are "domain knowledge packs" — guided workflows defined in `SKILL.md` files. Unlike tools (single function calls), skills are multi-step procedural guidance injected into the system prompt.

```
skills/
├── loader.py              # Skill loader: parse, scan, catalog
├── python-debug/
│   └── SKILL.md           # Systematic Python debugging workflow
└── example-skill/
    └── SKILL.md           # CSV statistical analysis (csv-quick-report)
```

## Skill vs. Tool

| | Tool | Skill |
|---|---|---|
| Granularity | Single function call | Multi-step workflow |
| Trigger | Explicit model tool_call | Model recognition from description |
| Context | None (stateless) | Full procedural body injected when activated |
| Example | `read`, `bash`, `grep` | `python-debug`, `csv-quick-report` |

## Key Design Decisions

### 1. YAML Frontmatter + Markdown Body

**Decision:** `SKILL.md` uses `---` YAML frontmatter for metadata, markdown for the procedural body.

**Why:** This is the same format used by Claude Code and many LLM tools. It's human-readable, easy to author, and parseable with simple split-on-`---` logic (no YAML library dependency needed). The `name` and `description` fields serve as the "recall key" — the model reads the skill catalog and decides when a skill matches the user's task.

### 2. Recall-Based Activation (Not Tool-Based)

**Decision:** Skills are activated when the model recognizes a matching task, not by explicit tool invocation.

**Why:** Skills are guidance, not actions. The model reads the catalog in the system prompt, recognizes "this looks like a Python debugging task," and follows the skill's procedural steps using the existing tool set. This is simpler than implementing a `use_skill` tool and avoids the "tool calling a tool" nesting problem.

### 3. Runtime Injection via `{skills_catalog}`

**Decision:** `skills_catalog()` renders `- name: description` lines into the system prompt's `{skills_catalog}` slot.

**Why:** The system prompt is the model's only persistent context. Injecting skill descriptions here means they're always available for recall. The `build_system_prompt()` function in `agent/prompts.py` accepts the catalog text and formats it with a section header.

### 4. Fallback Name from Directory

**Decision:** If a `SKILL.md` has no frontmatter, use the parent directory name.

**Why:** Graceful degradation. A skill at `skills/my-skill/SKILL.md` without frontmatter still gets a usable name (`my-skill`) rather than being silently ignored.

## Adding a New Skill

1. Create `skills/<skill-name>/SKILL.md`
2. Add YAML frontmatter with `name` and `description`
3. Write the procedural body (steps, notes, common pitfalls)
4. No code changes needed — `load_skills()` discovers new skills automatically

```markdown
---
name: my-skill
description: When to use this skill
---
## Steps
1. First...
2. Then...
```

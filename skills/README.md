# skills/ — Domain Knowledge Skills

## Architecture

Skills are "domain knowledge packs" — guided workflows defined in `SKILL.md` files. Unlike tools (single function calls), skills are multi-step procedural guidance loaded on demand.

```
skills/
├── loader.py              # Skill loader: parse, scan, catalog
├── codebase-guide/
│   └── SKILL.md           # Repository architecture audit workflow
├── python-debug/
│   └── SKILL.md           # Systematic Python debugging workflow
└── example-skill/
    └── SKILL.md           # CSV statistical analysis (csv-quick-report)
```

## Skill vs. Tool

| | Tool | Skill |
|---|---|---|
| Granularity | Single function call | Multi-step workflow |
| Trigger | Explicit model tool_call | Catalog recognition, then `skill(name)` |
| Context | None (stateless) | Full procedural body loaded only when activated |
| Example | `read`, `bash`, `grep` | `python-debug`, `csv-quick-report` |

## Key Design Decisions

### 1. YAML Frontmatter + Markdown Body

**Decision:** `SKILL.md` uses `---` YAML frontmatter for metadata, markdown for the procedural body.

**Why:** This is the same format used by Claude Code and many LLM tools. It's human-readable, easy to author, and parseable with simple split-on-`---` logic (no YAML library dependency needed). The `name` and `description` fields serve as the "recall key" — the model reads the skill catalog and decides when a skill matches the user's task.

### 2. Catalog Recall + On-Demand Activation

**Decision:** The system prompt contains only skill names and descriptions. When one matches the task, the model calls the read-only `skill(name)` tool before following its workflow.

**Why:** This makes activation visible in the trace and avoids paying the context cost of every skill body on every turn. The returned Markdown is still guidance; execution continues through normal tools.

### 3. Runtime Injection via `{skills_catalog}`

**Decision:** `skills_catalog()` renders `- name: description` lines into the system prompt's `{skills_catalog}` slot; `tools/skills.py` resolves and returns the selected body.

**Why:** Descriptions remain available for recall while bodies stay out of context until needed. The `build_system_prompt()` function also instructs the model to load a matching skill before domain work.

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

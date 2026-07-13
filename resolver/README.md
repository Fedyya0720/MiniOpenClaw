# resolver

Phase 1 contains dependency discovery and a small stdlib-only version matcher.

## Dependency parsing

`dep_parser.py` reads:

- `requirements.txt`, recursively following `-r` / `--requirement` includes;
- `[project].dependencies` from `pyproject.toml` via `tomllib`;
- a conservative `environment.yml`/`environment.yaml` subset containing
  top-level conda dependencies and a nested `pip:` list.

Requirement includes are resolved relative to their containing file and must
remain below the parsed project root. Missing includes, traversal attempts, and
include cycles are reported in `metadata.warnings` rather than read. Other
unsupported pip options and malformed requirement lines are reported there as
well. Each warning contains JSON-safe source, line, raw line, and reason data.

`DepSpec` preserves extras and environment markers without evaluating marker
expressions. Named direct URL/file references and VCS URLs with `#egg=name`
are retained using `direct_reference` and `non_searchable: true`, so candidate
search can skip them while installation still receives the declared reference.

`parse_project()` keeps the first dependency occurrence in discovery order,
deduplicating equal normalized name, extras, specifier, marker, and direct
reference declarations across all parsed files. The first occurrence's source
is preserved. Conda project hints (`name`, `prefix`) are returned as metadata.
This is intentionally not a complete YAML or PEP 508 implementation; later
phases can add richer parsing without adding hidden behavior here.

## Version matching

`specifier.py` supports `>=`, `<=`, `>`, `<`, `==`, `!=`, `===`, and `~=` with
comma AND semantics. `===` uses literal exact equality. `==1.2.*` and
`!=1.2.*` use numeric release-prefix semantics; wildcards with other operators
are rejected. It compares dotted numeric releases and common `dev`, alpha,
beta, release-candidate, and post-release suffixes. Unknown suffix syntax is
rejected conservatively. It does not replace `packaging.version` for arbitrary
Python ecosystem versions; the narrow behavior keeps Phase 1 dependency-free
and predictable.

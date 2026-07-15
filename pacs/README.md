# pacs/ — Parallel Adaptive Compatibility Search

PACS is MiniOpenClaw's high-level dependency environment builder. It turns the lower-level parser, solver, constraint graph, environment pool, installer, and verifier into one bounded `pacs_build` operation.

## Main flow

```text
parse project → build version catalog → solve and score candidates
       ↓
concurrent preflight → parallel isolated installation → project install → verify
       ↑                                                        ↓
parse failure → persist constraint → prune/re-score/retry    lock + report
```

`PACSBuilder.build()` caps parallelism and attempts, keeps the winning environment, and cleans up losing environments. A successful run must pass `pip check`; optional validation modules must also import. If the project has package metadata, it is installed editable after dependency resolution so project code is validated without duplicating dependency work.

## Adaptive behavior

- Version or metadata conflicts are converted into exact observed constraint edges.
- Learned edges persist in SQLite and prune later candidate combinations.
- Candidate scores combine version freshness, Python compatibility, wheel availability, cache state, and derived conflict risk.
- Preflight checks overlap, then viable candidates fill one bounded parallel install batch.
- If the first version window is exhausted, the catalog expands to older versions up to the configured limit.
- Transient network failures are classified but are not treated as package incompatibility.

## Evidence

Each run writes `result.json`, `PACS_REPORT.md`, and a frozen `requirements.lock` under `.mini-openclaw/pacs/runs/<run-id>/`. Installer logs are retained separately so failure classification remains auditable even after losing environments are cleaned up.

For the measured PACS ablation and optimized TUI results, see `docs/reports/2026-07-13-pacs-tui-ablation.md` and `docs/reports/2026-07-14-pacs-tui-optimized.md`.

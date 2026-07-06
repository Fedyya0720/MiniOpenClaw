# Plan-Execute-Verify Workfiles

Each subdirectory is one step in the implementation. See the workflow plan for details.

## Directory Format

```
NNN-short-name/
  plan.md              # Planner: high-level goal
  done-standard.md     # Executor: proposed acceptance criteria
  standard-feedback.md # Verifier: critique of ACs
  done.md              # Executor: what was built + self-check
  verify.md            # Verifier: PASS/FAIL + evidence
```

## Protocol

1. Planner → plan.md (direction)
2. Executor → done-standard.md (proposed ACs)
3. Verifier → standard-feedback.md (critique)
4. Loop 2-3 until agreed
5. Executor → done.md (implementation)
6. Verifier → verify.md (verdict)
7. PASS → commit → next step

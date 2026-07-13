#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$ROOT/demo/pacs_demo/work"

cd "$ROOT"
python demo/pacs_demo/make_fixture.py "$WORK"
python -m pacs "$WORK/project" \
  --catalog "$WORK/catalog.json" \
  --max-parallel 2 \
  --max-attempts 4 \
  --validate-import demo_core \
  --validate-import demo_plugin \
  --pip-arg=--no-index \
  --pip-arg=--find-links \
  --pip-arg="$WORK/wheelhouse"

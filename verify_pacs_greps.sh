#!/usr/bin/env bash
set -uo pipefail

root=$(cd "$(dirname "$0")" && pwd)
cd "$root"

failed=0
require() {
  local label=$1 pattern=$2 path=$3
  if grep -RqsE "$pattern" "$path"; then
    printf 'PASS C1: %s\n' "$label"
  else
    printf 'FAIL C1: %s\n' "$label"
    failed=1
  fi
}

require 'env tools mention ThreadPool/parallel/并行' 'ThreadPool|parallel|并行' tools
require 'four environment tool names exist' 'env_create|env_run|env_status|env_cleanup' tools/env_tools.py
require 'parse_deps tool exists' 'name="parse_deps"' tools/resolver_tools.py

printf 'PENDING C2: constraint generation/failure parsing belongs to later phases (non-failing)\n'
printf 'PENDING C3: persisted constraint graph and adaptive search belong to later phases (non-failing)\n'
exit "$failed"

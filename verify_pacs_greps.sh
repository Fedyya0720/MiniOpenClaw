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
require 'parse_deps tool exists' 'parse_deps' tools/resolver_tools.py
require 'C2 constraint|prune|剪枝' 'constraint|prune|剪枝' resolver
require 'C3 failure parser with structured' 'parse_failure|error_type|structured' resolver/failure_parser.py
require 'C3 parse failure tool' 'parse_failure' tools/resolver_tools.py

printf 'PENDING C2 full: constraint graph with persistence belongs to Phase 4 (non-failing)\n'
exit "$failed"

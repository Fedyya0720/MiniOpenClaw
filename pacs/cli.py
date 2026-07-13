"""Command-line entry point for the PACS builder."""
from __future__ import annotations

import argparse
import json

from .builder import PACSBuilder


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a Python environment with PACS")
    parser.add_argument("project_path")
    parser.add_argument("--python-version", default="")
    parser.add_argument("--max-parallel", type=int, default=2)
    parser.add_argument("--max-attempts", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--refresh-versions", action="store_true")
    parser.add_argument("--oldest-first", action="store_true")
    parser.add_argument("--validate-import", action="append", default=[])
    parser.add_argument("--no-install-project", action="store_true")
    args = parser.parse_args()
    result = PACSBuilder(args.project_path).build(
        python_version=args.python_version,
        max_parallel=args.max_parallel,
        max_attempts=args.max_attempts,
        timeout=args.timeout,
        refresh_versions=args.refresh_versions,
        newest_first=not args.oldest_first,
        validation_modules=args.validate_import,
        install_project=not args.no_install_project,
    )
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())

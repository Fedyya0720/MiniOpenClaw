"""Command-line entry for the high-level PACS builder."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .builder import PACSBuilder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pacs")
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("--python")
    parser.add_argument("--max-parallel", type=int, default=2)
    parser.add_argument("--max-attempts", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--catalog", help="本地 JSON 版本目录，用于离线 Demo")
    parser.add_argument("--validate-import", action="append", default=[])
    parser.add_argument("--pip-arg", action="append", default=[])
    parser.add_argument("--refresh-versions", action="store_true")
    parser.add_argument("--version-batch-size", type=int, default=5)
    parser.add_argument("--max-versions-per-package", type=int, default=20)
    parser.add_argument("--no-install-project", action="store_true")
    parser.add_argument("--backend", choices=("venv", "conda"), default="venv")
    args = parser.parse_args(argv)
    catalog = None
    if args.catalog:
        catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    result = PACSBuilder(args.project).build(
        python=args.python,
        max_parallel=args.max_parallel,
        max_attempts=args.max_attempts,
        timeout=args.timeout,
        version_catalog=catalog,
        validation_modules=args.validate_import,
        pip_args=args.pip_arg,
        refresh_versions=args.refresh_versions,
        backend=args.backend,
        version_batch_size=args.version_batch_size,
        max_versions_per_package=args.max_versions_per_package,
        install_project=not args.no_install_project,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["success"] else 2

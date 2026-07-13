"""Trusted argv-only launcher that applies limits before executing an installer."""
from __future__ import annotations

import argparse
import json
import os
import resource
from typing import Sequence

from sandbox import ResourceLimits


def apply_resource_limits(limits: ResourceLimits) -> None:
    """Apply supported POSIX resource limits in the isolated launcher process."""
    if os.name != "posix":
        return
    resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
    resource.setrlimit(resource.RLIMIT_FSIZE, (limits.file_bytes, limits.file_bytes))
    if hasattr(resource, "RLIMIT_NPROC"):
        resource.setrlimit(resource.RLIMIT_NPROC, (limits.processes, limits.processes))


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limits-json", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    parsed = parser.parse_args(argv)
    command = parsed.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("an installer argv is required after --")
    try:
        raw_limits = json.loads(parsed.limits_json)
        limits = ResourceLimits(**raw_limits)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(f"invalid resource limits: {exc}")
    apply_resource_limits(limits)
    os.execvpe(command[0], command, os.environ)


if __name__ == "__main__":
    main()

"""Trusted argv-only launcher that applies limits before executing an installer."""
from __future__ import annotations

import argparse
import json
import os
import resource
import sys
from typing import Sequence

from sandbox import ResourceLimits


def apply_resource_limits(limits: ResourceLimits) -> None:
    """Apply supported POSIX resource limits in the isolated launcher process."""
    if os.name != "posix":
        return

    def set_soft_limit(kind: int, requested: int) -> None:
        """Never try to raise a container/host hard limit."""
        _soft, hard = resource.getrlimit(kind)
        selected = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
        try:
            resource.setrlimit(kind, (selected, hard))
        except (OSError, ValueError):
            # Some kernels expose a limit constant but reject changing it
            # (notably RLIMIT_AS on macOS). Other supported limits still apply;
            # the sandbox descriptor already distinguishes rlimits-only mode.
            return

    set_soft_limit(resource.RLIMIT_CPU, limits.cpu_seconds)
    set_soft_limit(resource.RLIMIT_AS, limits.memory_bytes)
    set_soft_limit(resource.RLIMIT_FSIZE, limits.file_bytes)
    # Darwin counts RLIMIT_NPROC across every process owned by the login user,
    # not just this installer tree. Lowering it inside a child can therefore
    # make the very next `git`/compiler fork fail with EAGAIN. Linux containers
    # retain the useful per-user/process-namespace guard.
    if sys.platform != "darwin" and hasattr(resource, "RLIMIT_NPROC"):
        set_soft_limit(resource.RLIMIT_NPROC, limits.processes)


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

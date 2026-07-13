"""Rule-based pip failure log parser."""
from __future__ import annotations

import re
from typing import Any


RULES: tuple[tuple[str, str, float], ...] = (
    (r"resolutionimpossible|conflicting dependencies|dependency conflict", "dependency_conflict", .95),
    (r"requires .* but you have", "installed_version_conflict", .95),
    (r"no matching distribution found", "no_matching_distribution", .95),
    (r"could not find a version that satisfies", "version_unavailable", .95),
    (r"requires-python|python version .* is not supported", "python_version_mismatch", .95),
    (r"not a supported wheel|unsupported wheel", "wheel_incompatible", .95),
    (r"invalid wheel|wheel .* is invalid", "invalid_wheel", .9),
    (r"failed building wheel", "wheel_build_failed", .9),
    (r"metadata-generation-failed", "metadata_generation_failed", .9),
    (r"subprocess-exited-with-error", "build_subprocess_failed", .8),
    (r"microsoft visual c\+\+|gcc.*not found|clang.*not found", "compiler_missing", .95),
    (r"fatal error: .*\.h: no such file|cannot find -l", "system_library_missing", .9),
    (r"cuda.*(?:not found|mismatch|unsupported)", "cuda_incompatible", .9),
    (r"ssl: certificate_verify_failed|certificate verify failed", "certificate_error", .95),
    (r"temporary failure in name resolution|name or service not known", "network_dns_error", .9),
    (r"read timed out|connect timeout|connection timed out", "network_timeout", .9),
    (r"permission denied|operation not permitted", "permission_error", .9),
    (r"no space left on device", "disk_full", .99),
    (r"hashes are required.*do not match|hash mismatch", "hash_mismatch", .99),
    (r"externally-managed-environment", "externally_managed", .99),
)


def _parties(combo: dict[str, str]) -> tuple[str, str, str, str]:
    items = list(combo.items())
    if not items:
        return "unknown", "", "environment", ""
    if len(items) == 1:
        return items[0][0], f"=={items[0][1]}", "environment", ""
    return items[0][0], f"=={items[0][1]}", items[1][0], f"=={items[1][1]}"


def parse_failure(log_text: str, attempted_combo: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    combo = {str(k): str(v) for k, v in (attempted_combo or {}).items()}
    pkg_a, ver_a, pkg_b, ver_b = _parties(combo)
    lowered = log_text.lower()
    matches = [(kind, confidence) for pattern, kind, confidence in RULES if re.search(pattern, lowered, re.I | re.S)]
    if not matches:
        matches = [("unknown", .2)]
    return [{
        "pkg_a": pkg_a, "ver_a": ver_a, "pkg_b": pkg_b, "ver_b": ver_b,
        "error_type": kind, "confidence": confidence,
    } for kind, confidence in matches]

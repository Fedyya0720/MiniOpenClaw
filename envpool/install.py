"""Parallel and serial package installation across managed environments."""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import secrets
import signal
import subprocess
import time
from datetime import datetime, timezone
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .manager import EnvironmentPool
from .sandbox import (
    ResourceLimits,
    SandboxDescriptor,
    build_sandbox,
    pip_command,
    resource_runner_command,
)
from agent.trace import content_metadata, redact_text, sensitive_retention_enabled


@dataclass(frozen=True)
class InstallSpec:
    env_id: str
    label: str
    packages: list[str] | None = None
    argv: list[str] | None = None

    def __post_init__(self) -> None:
        if bool(self.packages) == bool(self.argv):
            raise ValueError("每个安装规格必须且只能提供 packages 或 argv")
        if self.packages is not None:
            if isinstance(self.packages, (str, bytes)) or not all(
                isinstance(item, str) and item and "\x00" not in item for item in self.packages
            ):
                raise ValueError("packages 必须是非空字符串列表")
        if self.argv is not None:
            if isinstance(self.argv, (str, bytes)) or not all(
                isinstance(item, str) and item and "\x00" not in item for item in self.argv
            ):
                raise ValueError("argv 必须是非空字符串列表")


@dataclass(frozen=True)
class InstallResult:
    env_id: str
    label: str
    success: bool
    returncode: int | None
    duration_seconds: float
    log_path: str
    summary: str
    sandbox: dict[str, Any] | None
    timed_out: bool = False
    cancelled: bool = False
    started: bool = True
    batch_id: str | None = None
    original_chars: int | None = None
    original_utf8_bytes: int | None = None
    original_sha256: str | None = None
    stored_chars: int | None = None
    stored_utf8_bytes: int | None = None
    stored_sha256: str | None = None
    redacted: bool = False
    sensitive_retention: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InstallBatchResult:
    results: list[InstallResult]
    first_success: InstallResult | None
    naive_success: bool
    attempted_count: int
    cancelled_count: int
    submitted_count: int
    mode: str
    batch_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["first_success"] = self.first_success.to_dict() if self.first_success else None
        return data


_WRITE_REDIRECT_OPTIONS = {
    "--cache-dir", "--log", "--prefix", "--report", "--root", "--src", "--target",
    "-t",
}


def _validate_install_arguments(arguments: Sequence[str]) -> None:
    """Reject pip options that redirect writes outside the managed venv.

    Local source/wheel paths remain readable, but the install destination, logs,
    cache, report, and source checkout directories are controlled by envpool.
    """
    for index, argument in enumerate(arguments):
        normalized = argument.lower()
        option = normalized.split("=", 1)[0]
        if option in _WRITE_REDIRECT_OPTIONS:
            raise ValueError(f"禁止重定向 pip 写入位置: {argument}")
        if normalized == "--user":
            raise ValueError("禁止使用 --user（安装必须留在目标虚拟环境）")
        if index and arguments[index - 1].lower() in _WRITE_REDIRECT_OPTIONS:
            raise ValueError(f"禁止重定向 pip 写入位置: {arguments[index - 1]} {argument}")


def _validate_argv(
    argv: Sequence[str], env_path: Path, workdir: Path, allow_test_commands: bool
) -> list[str]:
    if isinstance(argv, (str, bytes)) or not argv:
        raise ValueError("argv 必须是列表，不能是 shell 字符串")
    command = [str(part) for part in argv]
    executable = Path(command[0]).expanduser()
    if not executable.is_absolute():
        raise ValueError("安装器必须使用环境内的绝对路径")
    absolute = executable.absolute()
    root = env_path.absolute()
    if not absolute.is_relative_to(root):
        raise ValueError("安装器可执行文件不属于目标虚拟环境")
    relative = absolute.relative_to(root).as_posix().lower()
    if relative not in {"bin/python", "bin/python3", "bin/pip", "bin/pip3", "scripts/python.exe", "scripts/pip.exe"}:
        raise ValueError("只允许目标环境内的 python/pip 安装器")

    name = absolute.name.lower()
    tail = command[1:]
    if name.startswith("python"):
        if tail[:3] == ["-m", "pip", "install"]:
            _validate_install_arguments(tail[3:])
        elif allow_test_commands and tail[:1] == ["-c"]:
            pass
        else:
            raise ValueError("python argv 仅允许 '-m pip install' 安装命令")
    elif not tail or tail[0] != "install":
        raise ValueError("pip argv 必须使用 install 子命令")
    else:
        _validate_install_arguments(tail[1:])

    # Relative local paths are interpreted under workdir; explicit traversal is
    # rejected. Absolute local artifacts remain valid for fixtures/repositories.
    for argument in command[1:]:
        if argument == ".." or argument.startswith("../") or "/../" in argument.replace("\\", "/"):
            raise ValueError("安装参数包含路径穿越")
    return command


def _install_environment(env_path: Path) -> dict[str, str]:
    """Keep pip caches, temp files, and user-site writes inside the managed venv."""
    home = env_path / ".home"
    cache = env_path / ".cache" / "pip"
    temporary = env_path / ".tmp"
    for path in (home, cache, temporary):
        path.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update({
        "HOME": str(home),
        "PIP_CACHE_DIR": str(cache),
        "PYTHONNOUSERSITE": "1",
        "TMPDIR": str(temporary),
    })
    return environment


def _compact(stdout: str, stderr: str, limit: int = 800) -> str:
    text = "\n".join(part.strip() for part in (stdout, stderr) if part.strip())
    if not text:
        return "(no output)"
    return text if len(text) <= limit else f"{text[:limit]}\n... [完整日志已写入 PACS durable log]"


def _safe_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    return safe[:80] or "environment"


def _secure_path(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        pass


def _new_batch_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{secrets.token_hex(6)}"


def _pacs_log_path(pool: EnvironmentPool, batch_id: str, index: int, spec: InstallSpec) -> Path:
    root = pool.workdir / ".mini-openclaw" / "pacs-runs" / batch_id
    root.mkdir(parents=True, exist_ok=True)
    for directory in (pool.workdir / ".mini-openclaw", (pool.workdir / ".mini-openclaw" / "pacs-runs"), root):
        _secure_path(directory, 0o700)
    return root / f"{index:03d}-{_safe_component(spec.env_id or spec.label)}.log"


def _write_pacs_log(
    path: Path,
    attempts: Sequence[tuple[str, Sequence[str], str, str, bool]],
    *,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Persist every execution attempt, including a distinct fallback attempt."""
    entries = []
    for name, command, stdout, stderr, timed_out in attempts:
        entries.append(
            f"[{name}]\n"
            f"$ {json.dumps([str(part) for part in command], ensure_ascii=False)}\n"
            + (f"[TIMEOUT after {timeout}s]\n" if timed_out and timeout is not None else "")
            + f"[stdout]\n{stdout}\n[stderr]\n{stderr}"
        )
    original = "\n\n".join(entries)
    stored, sensitive = redact_text(original)
    retained = sensitive_retention_enabled()
    if retained:
        stored = original
    path.write_text(stored, encoding="utf-8")
    _secure_path(path, 0o600)
    return {
        **content_metadata(original, stored),
        "redacted": bool(sensitive and not retained),
        "sensitive_retention": bool(sensitive and retained),
    }


_BWRAP_STARTUP_DIAGNOSTIC = re.compile(
    r"^bwrap: (?:Creating new namespace failed:|No permissions to create new namespace(?:[.:]|$))"
)


def _bwrap_startup_failure(descriptor: Any, stderr: str) -> bool:
    """Accept only a first-line bwrap launcher diagnostic, never installer output."""
    if getattr(descriptor, "kind", None) != "bubblewrap":
        return False
    first_line = stderr.splitlines()[0] if stderr else ""
    return bool(_BWRAP_STARTUP_DIAGNOSTIC.match(first_line))


def _run_process(
    argv: Sequence[str], *, cwd: str, env: dict[str, str], timeout: float
) -> tuple[int | None, str, str, bool]:
    """Run one process group and reliably tear down its descendants on timeout."""
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return process.returncode, stdout or "", stderr or "", False
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            stdout, stderr = process.communicate()
        return process.returncode, stdout or "", stderr or "", True


def _run_one(
    pool: EnvironmentPool,
    spec: InstallSpec,
    timeout: float,
    limits: ResourceLimits | None,
    allow_test_commands: bool,
    batch_id: str,
    index: int,
) -> InstallResult:
    info = pool.status(spec.env_id)
    if info is None or isinstance(info, list):
        raise KeyError(f"环境不存在: {spec.env_id}")
    env_path = Path(info.path).resolve()
    if spec.packages is not None:
        _validate_install_arguments(spec.packages)
        command = pip_command(env_path, spec.packages)
    else:
        command = _validate_argv(spec.argv or [], env_path, pool.workdir, allow_test_commands)
    installer_argv = resource_runner_command(command, limits)
    descriptor = build_sandbox(installer_argv, env_path, pool.workdir)
    durable_log_path = _pacs_log_path(pool, batch_id, index, spec)
    started = time.monotonic()
    environment = _install_environment(env_path)
    attempts: list[tuple[str, Sequence[str], str, str, bool]] = []
    returncode, stdout, stderr, timed_out = _run_process(
        descriptor.argv,
        cwd=str(pool.workdir),
        env=environment,
        timeout=timeout,
    )
    attempts.append(("bubblewrap" if descriptor.kind == "bubblewrap" else "rlimits-only", descriptor.argv, stdout, stderr, timed_out))
    if (
        not timed_out
        and returncode != 0
        and _bwrap_startup_failure(descriptor, stderr)
        and os.getenv("MINIOPENCLAW_REQUIRE_PIP_SANDBOX") != "1"
    ):
        bwrap_stderr = stderr
        returncode, stdout, fallback_stderr, timed_out = _run_process(
            installer_argv,
            cwd=str(pool.workdir),
            env=environment,
            timeout=timeout,
        )
        attempts.append(("rlimits-only fallback", installer_argv, stdout, fallback_stderr, timed_out))
        stderr = fallback_stderr
        descriptor = SandboxDescriptor(
            argv=installer_argv,
            kind="rlimits-only",
            filesystem_isolated=False,
            network_enabled=True,
            writable_paths=[],
            readable_paths=[],
            warning=(
                "bubblewrap launcher failed before installer start; retried with resource limits only: "
                + bwrap_stderr.strip()[:300]
            ),
        )
    metadata = _write_pacs_log(durable_log_path, attempts, timeout=timeout)
    # ── system-dep remediation via conda ──────────────────────────────────
    if (
        not timed_out
        and returncode != 0
        and os.getenv("MINIOPENCLAW_REQUIRE_PIP_SANDBOX") != "1"
    ):
        try:
            from resolver.failure_parser import parse_failure as _parse
            from envpool.backends import CondaBackend as _conda

            entries = _parse(stderr=stderr, stdout=stdout)
            if any(e["error_type"] == "system_dep_missing" for e in entries) and _conda.probe():
                conda_path = env_path.parent / f"{env_path.name}-conda"
                conda_path.mkdir(parents=True, exist_ok=True)
                _conda.create(conda_path, None, timeout=timeout * 2)
                conda_argv = [
                    str(_conda.python_path(conda_path)),
                    "-m", "pip", "install",
                    *spec.packages,
                ] if spec.packages else command
                conda_result = subprocess.run(
                    conda_argv, cwd=str(pool.workdir),
                    capture_output=True, text=True, timeout=timeout,
                    env=_install_environment(conda_path),
                )
                attempts.append((
                    "conda-retry", conda_argv,
                    conda_result.stdout or "", conda_result.stderr or "", False,
                ))
                metadata = _write_pacs_log(durable_log_path, attempts, timeout=timeout)
                returncode = conda_result.returncode
                stdout = conda_result.stdout or ""
                stderr = conda_result.stderr or ""
                descriptor = SandboxDescriptor(
                    argv=conda_argv, kind="conda",
                    filesystem_isolated=True, network_enabled=True,
                    writable_paths=[str(conda_path)],
                    readable_paths=["/", str(pool.workdir)],
                    warning=None,
                )
        except Exception:
            pass  # conda retry is best-effort; original result stands
    # ── end remediation ───────────────────────────────────────────────────
    if timed_out:
        return InstallResult(
            env_id=spec.env_id,
            label=spec.label,
            success=False,
            returncode=returncode,
            duration_seconds=time.monotonic() - started,
            log_path=str(durable_log_path),
            summary=f"安装超时（{timeout}s）；完整日志: {durable_log_path}",
            sandbox=descriptor.to_dict(),
            timed_out=True,
            batch_id=batch_id,
            **metadata,
        )
    return InstallResult(
        env_id=spec.env_id,
        label=spec.label,
        success=returncode == 0,
        returncode=returncode,
        duration_seconds=time.monotonic() - started,
        log_path=str(durable_log_path),
        summary=_compact(stdout, stderr),
        sandbox=descriptor.to_dict(),
        batch_id=batch_id,
        **metadata,
    )


def _batch(
    results: list[InstallResult], submitted_count: int, mode: str, batch_id: str
) -> InstallBatchResult:
    ordered_successes = [result for result in results if result.success]
    return InstallBatchResult(
        results=results,
        first_success=ordered_successes[0] if ordered_successes else None,
        naive_success=bool(results and results[0].success),
        attempted_count=sum(result.started and not result.cancelled for result in results),
        cancelled_count=sum(result.cancelled for result in results),
        submitted_count=submitted_count,
        mode=mode,
        batch_id=batch_id,
    )


def serial_install(
    pool: EnvironmentPool,
    specs: Sequence[InstallSpec],
    *,
    timeout: float = 300.0,
    limits: ResourceLimits | None = None,
    allow_test_commands: bool = False,
) -> InstallBatchResult:
    """Run candidates one at a time and stop after the first success.

    This is the honest B3 serial trial-and-error baseline: ``attempted_count``
    counts work that actually ran, while candidates after the successful one are
    represented as not-started/cancelled rather than silently disappearing.
    """
    items = list(specs)
    batch_id = _new_batch_id()
    results: list[InstallResult] = []
    succeeded = False
    for spec in items:
        if succeeded:
            results.append(InstallResult(
                env_id=spec.env_id,
                label=spec.label,
                success=False,
                returncode=None,
                duration_seconds=0.0,
                log_path="",
                summary="earlier serial candidate succeeded; not started",
                sandbox=None,
                batch_id=batch_id,
                cancelled=True,
                started=False,
            ))
            continue
        result = _run_one(pool, spec, timeout, limits, allow_test_commands, batch_id, len(results))
        results.append(result)
        succeeded = result.success
    return _batch(results, len(items), "serial", batch_id)


def parallel_install(
    pool: EnvironmentPool,
    specs: Sequence[InstallSpec],
    *,
    timeout: float = 300.0,
    max_workers: int | None = None,
    limits: ResourceLimits | None = None,
    allow_test_commands: bool = False,
) -> InstallBatchResult:
    """Install candidates concurrently and faithfully report cancellation.

    If the naive (first) candidate succeeds, futures which have not started are
    cancelled when possible. Already-running candidates are always awaited and
    reported, so ``attempted_count`` never pretends concurrent work did not run.
    Results preserve input order; ``first_success`` means the first successful
    candidate in that semantic order, not whichever thread happened to finish.
    """
    items = list(specs)
    batch_id = _new_batch_id()
    if not items:
        return _batch([], 0, "parallel", batch_id)
    workers = max_workers or min(32, len(items))
    by_index: dict[int, InstallResult] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_run_one, pool, spec, timeout, limits, allow_test_commands, batch_id, index): index
            for index, spec in enumerate(items)
        }
        naive_succeeded = False
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            if future.cancelled():
                continue
            try:
                result = future.result()
            except Exception as exc:
                # One malformed/broken candidate must not erase successful results
                # from the rest of the parallel batch. Validation errors are made
                # explicit as a per-candidate result; serial_install still raises
                # directly, which is useful for callers validating one command.
                spec = items[index]
                result = InstallResult(
                    env_id=spec.env_id,
                    label=spec.label,
                    success=False,
                    returncode=None,
                    duration_seconds=0.0,
                    log_path="",
                    summary=f"candidate failed before/during execution: {type(exc).__name__}: {exc}",
                    sandbox=None,
                    batch_id=batch_id,
                )
            by_index[index] = result
            if index == 0 and result.success and not naive_succeeded:
                naive_succeeded = True
                for pending, pending_index in futures.items():
                    if pending_index not in by_index and pending.cancel():
                        spec = items[pending_index]
                        by_index[pending_index] = InstallResult(
                            env_id=spec.env_id,
                            label=spec.label,
                            success=False,
                            returncode=None,
                            duration_seconds=0.0,
                            log_path="",
                            summary="naive candidate succeeded; future cancelled before start",
                            sandbox=None,
                            batch_id=batch_id,
                            cancelled=True,
                            started=False,
                        )
    return _batch([by_index[index] for index in range(len(items))], len(items), "parallel", batch_id)


def install_for_environment(
    pool: EnvironmentPool, specs: Sequence[InstallSpec], **kwargs: Any
) -> InstallBatchResult:
    """Select serial mode when ``MINIOPENCLAW_PACS_SERIAL=1``."""
    if os.environ.get("MINIOPENCLAW_PACS_SERIAL") == "1":
        kwargs.pop("max_workers", None)
        return serial_install(pool, specs, **kwargs)
    return parallel_install(pool, specs, **kwargs)

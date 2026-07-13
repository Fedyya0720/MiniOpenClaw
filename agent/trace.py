"""Durable, tool-only evidence traces with redaction by default.

This module deliberately never receives conversation prose or raw backend payloads.
Trace write failures are swallowed so evidence collection cannot interrupt an agent run.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = {"api_key", "apikey", "token", "password", "secret", "authorization", "cookie"}
_AUTH_RE = re.compile(r"\b(Bearer|Basic)\s+[^\s,;]+", re.IGNORECASE)
_URL_CREDENTIALS_RE = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<credentials>[^\s/@:]+:[^\s/@]+)@", re.IGNORECASE)
_SECRET_KEY = r"(?:api[_-]?key|token|password|secret|authorization|cookie)"
# Handle JSON separately so the replacement preserves JSON quoting.  Each value
# match is bounded by a closing quote; no pattern uses nested quantifiers.
_JSON_NAMED_VALUE_RE = re.compile(
    rf'(?P<key>"{_SECRET_KEY}")(?P<sep>\s*:\s*)"(?:\\.|[^"\\])*"', re.IGNORECASE
)
# Structured/ini-like key values.  The key-name alternatives deliberately exclude
# generic words such as "error" so ordinary diagnostics remain readable.
_NAMED_VALUE_RE = re.compile(
    rf"(?im)(?P<key>\b{_SECRET_KEY}\b)(?P<sep>\s*[:=]\s*)"
    r"(?P<value>[^\s\r\n,}\]\"']+)"
)
_ENV_QUOTED_ASSIGNMENT_RE = re.compile(
    r"(?im)(?P<key>\b(?:[A-Za-z_][A-Za-z0-9_]*)?(?:KEY|TOKEN|PASSWORD|SECRET)\b)"
    r"(?P<sep>\s*=\s*)(?P<quote>[\"'])(?:\\.|[^\"'\r\n])*(?P=quote)"
)
_ENV_ASSIGNMENT_RE = re.compile(
    r"(?im)(?P<key>\b(?:[A-Za-z_][A-Za-z0-9_]*)?(?:KEY|TOKEN|PASSWORD|SECRET)\b)"
    r"(?P<sep>\s*=\s*)(?P<value>[^\s\r\n;\"']+)"
)
_FLAG_VALUE_RE = re.compile(
    rf"(?i)(?P<key>--{_SECRET_KEY})(?P<sep>\s+)(?P<value>[^\s]+)"
)


def sensitive_retention_enabled() -> bool:
    """Return the explicit forensic opt-in state; this is never enabled implicitly."""
    return os.getenv("MINIOPENCLAW_TRACE_SENSITIVE") == "1"


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return normalized in _SENSITIVE_KEY_PARTS or any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def redact_value(value: Any) -> tuple[Any, bool]:
    """Recursively redact known credential fields while preserving ordinary data."""
    if isinstance(value, dict):
        output: dict[Any, Any] = {}
        sensitive = False
        for key, item in value.items():
            if _is_sensitive_key(key):
                output[key] = _REDACTED
                sensitive = True
            else:
                output[key], found = redact_value(item)
                sensitive = sensitive or found
        return output, sensitive
    if isinstance(value, list):
        output = []
        sensitive = False
        for item in value:
            cleaned, found = redact_value(item)
            output.append(cleaned)
            sensitive = sensitive or found
        return output, sensitive
    if isinstance(value, tuple):
        cleaned, sensitive = redact_value(list(value))
        return cleaned, sensitive
    if isinstance(value, str):
        return redact_text(value)
    return value, False


def _redact_url_credentials(match: re.Match[str]) -> str:
    return f"{match.group('scheme')}{_REDACTED}@"


def redact_text(text: str) -> tuple[str, bool]:
    """Redact a conservative set of secret-bearing textual forms.

    Cheap trigger checks keep large ordinary stdout/stderr linear: regexes only
    run when their defining syntax is present. In particular, the environment
    assignment pattern must not backtrack across megabytes of unbroken text.
    """
    original = str(text)
    cleaned = original
    lowered = original.casefold()

    if "://" in original and "@" in original and ":" in original:
        cleaned = _URL_CREDENTIALS_RE.sub(_redact_url_credentials, cleaned)
    if "bearer " in lowered or "basic " in lowered:
        cleaned = _AUTH_RE.sub(lambda match: f"{match.group(1)} {_REDACTED}", cleaned)
    if any(marker in lowered for marker in (
        "api_key", "api-key", "apikey", "token", "password",
        "secret", "authorization", "cookie",
    )):
        cleaned = _JSON_NAMED_VALUE_RE.sub(
            lambda match: f'{match.group("key")}{match.group("sep")}"{_REDACTED}"', cleaned
        )
        cleaned = _NAMED_VALUE_RE.sub(
            lambda match: f"{match.group('key')}{match.group('sep')}{_REDACTED}", cleaned
        )
    if "=" in cleaned and any(marker in cleaned.upper() for marker in (
        "KEY=", "TOKEN=", "PASSWORD=", "SECRET=",
    )):
        cleaned = _ENV_QUOTED_ASSIGNMENT_RE.sub(
            lambda match: f"{match.group('key')}{match.group('sep')}{match.group('quote')}{_REDACTED}{match.group('quote')}",
            cleaned,
        )
        cleaned = _ENV_ASSIGNMENT_RE.sub(
            lambda match: f"{match.group('key')}{match.group('sep')}{_REDACTED}", cleaned
        )
    if "--" in cleaned and any(marker in lowered for marker in (
        "--api-key", "--api_key", "--token", "--password",
        "--secret", "--authorization", "--cookie",
    )):
        cleaned = _FLAG_VALUE_RE.sub(
            lambda match: f"{match.group('key')}{match.group('sep')}{_REDACTED}", cleaned
        )
    return cleaned, cleaned != original


def content_metadata(original: str, stored: str) -> dict[str, Any]:
    """Return integrity metadata for original and stored UTF-8 content."""
    original_bytes = original.encode("utf-8")
    stored_bytes = stored.encode("utf-8")
    return {
        "original_chars": len(original),
        "original_utf8_bytes": len(original_bytes),
        "original_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "stored_chars": len(stored),
        "stored_utf8_bytes": len(stored_bytes),
        "stored_sha256": hashlib.sha256(stored_bytes).hexdigest(),
    }


def _safe_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    return safe[:80] or "tool"


def _chmod(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        pass


class ToolRunTrace:
    """Best-effort append-only tool trace rooted beneath a workspace."""

    def __init__(self, workdir: str | Path, run_id: str | None = None) -> None:
        self.workdir = Path(workdir).expanduser().resolve()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.run_id = _safe_component(run_id or f"{stamp}-{secrets.token_hex(6)}")
        self.root = self.workdir / ".mini-openclaw" / "tool-runs" / self.run_id
        self.artifact_root = self.root / "artifacts"
        self.trace_path = self.root / "trace.jsonl"
        self.available = False
        try:
            self.artifact_root.mkdir(parents=True, exist_ok=True)
            # Apply restrictive modes to each trace-specific directory where supported.
            for path in (self.workdir / ".mini-openclaw", self.root, self.artifact_root):
                _chmod(path, 0o700)
            self.trace_path.touch(exist_ok=True)
            _chmod(self.trace_path, 0o600)
            self.available = True
        except OSError:
            # Tracing must never change task success/failure behavior.
            self.available = False

    def _append(self, event: dict[str, Any]) -> None:
        if not self.available:
            return
        try:
            with self.trace_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            _chmod(self.trace_path, 0o600)
        except OSError:
            self.available = False

    def record_tool_call(
        self, *, turn: int, call_index: int, name: str, tool_id: Any, arguments: Any
    ) -> None:
        try:
            redacted_arguments, sensitive = redact_value(arguments)
            retained = sensitive_retention_enabled()
            if sensitive and retained:
                stored_arguments = arguments
            else:
                stored_arguments = redacted_arguments
            original_serialized = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
            stored_serialized = json.dumps(stored_arguments, ensure_ascii=False, sort_keys=True, default=str)
            self._append({
                "event": "tool_call",
                "turn": turn,
                "call_index": call_index,
                "tool_name": str(name),
                "tool_id": tool_id,
                "arguments": stored_arguments,
                "sensitive": sensitive,
                "redacted": bool(sensitive and not retained),
                "sensitive_retention": bool(sensitive and retained),
                "sensitive_retention_warning": (
                    "Exact sensitive content retained because MINIOPENCLAW_TRACE_SENSITIVE=1"
                    if sensitive and retained else None
                ),
                **content_metadata(original_serialized, stored_serialized),
            })
        except Exception:
            # Serialization of unusual tool arguments is also non-fatal.
            return

    def record_tool_result(
        self, *, turn: int, call_index: int, name: str, tool_id: Any, result: Any, status: str
    ) -> None:
        try:
            original = str(result)
            redacted, sensitive = redact_text(original)
            retained = sensitive_retention_enabled()
            stored = original if retained else redacted
            filename = f"{turn:03d}-{call_index:03d}-{_safe_component(str(name))}.txt"
            artifact = self.artifact_root / filename
            if self.available:
                try:
                    artifact.write_text(stored, encoding="utf-8")
                    _chmod(artifact, 0o600)
                    relative_path = artifact.relative_to(self.root).as_posix()
                except OSError:
                    relative_path = None
            else:
                relative_path = None
            event = {
                "event": "tool_result",
                "turn": turn,
                "call_index": call_index,
                "tool_name": str(name),
                "tool_id": tool_id,
                "status": status if status in {"ok", "permission_denied", "error"} else "error",
                "artifact_path": relative_path,
                "redacted": bool(sensitive and not retained),
                "sensitive_retention": bool(sensitive and retained),
                "sensitive_retention_warning": (
                    "Exact sensitive content retained because MINIOPENCLAW_TRACE_SENSITIVE=1"
                    if sensitive and retained else None
                ),
                **content_metadata(original, stored),
            }
            self._append(event)
        except Exception:
            return

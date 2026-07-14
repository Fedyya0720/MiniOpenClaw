"""Lightweight developer observability for Agent runs.

This module is deliberately separate from :mod:`agent.trace`.  ``agent.trace``
is durable, tool-only evidence with full result artifacts; this tracer records
small, redacted span summaries for debugging latency and token usage.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from agent.trace import redact_text, redact_value


_PREVIEW_CHARS = 500


def _usage_from(value: Any) -> dict[str, int]:
    usage = value.get("usage") if isinstance(value, dict) else None
    if not isinstance(usage, dict):
        return {}
    cleaned: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        raw = usage.get(key)
        if isinstance(raw, (int, float)) and raw >= 0:
            cleaned[key] = int(raw)
    if "total_tokens" not in cleaned and cleaned:
        cleaned["total_tokens"] = cleaned.get("prompt_tokens", 0) + cleaned.get("completion_tokens", 0)
    return cleaned


def _preview(kind: str, value: Any) -> str:
    """Return a bounded, redacted preview without retaining model prose."""
    if kind == "llm" and isinstance(value, dict):
        calls = value.get("tool_calls") or []
        names = [str(call.get("name", "?")) for call in calls if isinstance(call, dict)]
        text = f"tool_calls={names}" if names else "final_response"
    else:
        text = str(value)
    cleaned, _ = redact_text(text)
    return cleaned[:_PREVIEW_CHARS]


class Tracer:
    """Collect ordered LLM/tool spans in memory and optionally in JSONL."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self.spans: list[dict[str, Any]] = []
        self.available = True
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.parent.chmod(0o700)
                self.path.touch(exist_ok=True)
                self.path.chmod(0o600)
            except OSError:
                # Observability must never change the outcome of an Agent run.
                self.available = False

    @classmethod
    def for_run(cls, workdir: str | Path, run_id: str) -> "Tracer":
        path = Path(workdir).resolve() / ".mini-openclaw" / "agent-runs" / run_id / "trace.jsonl"
        return cls(path)

    def _append(self, event: dict[str, Any]) -> None:
        event["seq"] = len(self.spans) + 1
        self.spans.append(event)
        if self.path is None or not self.available:
            return
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            self.path.chmod(0o600)
        except OSError:
            self.available = False

    def record(self, kind: str, name: str, output: Any, *, ok: bool = True,
               duration_ms: float = 0.0, **meta: Any) -> None:
        """Record a synthetic span, such as an unknown or denied tool call."""
        safe_meta, _ = redact_value(meta)
        event = {
            "kind": kind,
            "name": name,
            "ok": bool(ok),
            "duration_ms": round(max(duration_ms, 0.0), 3),
            "out": _preview(kind, output),
            "ts": datetime.now(timezone.utc).isoformat(),
            **safe_meta,
        }
        usage = _usage_from(output)
        if usage:
            event["usage"] = usage
            event["tokens"] = usage.get("total_tokens", 0)
        self._append(event)

    def span(self, kind: str, name: str, fn: Callable[[], Any], **meta: Any) -> Any:
        """Execute ``fn`` and record timing, output summary, usage, and errors."""
        started_wall = datetime.now(timezone.utc).isoformat()
        started = time.perf_counter()
        ok = True
        output: Any = None
        try:
            output = fn()
            return output
        except Exception as exc:
            ok = False
            output = repr(exc)
            raise
        finally:
            safe_meta, _ = redact_value(meta)
            event = {
                "kind": kind,
                "name": name,
                "ok": ok,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "out": _preview(kind, output),
                "ts": started_wall,
                **safe_meta,
            }
            usage = _usage_from(output)
            if usage:
                event["usage"] = usage
                event["tokens"] = usage.get("total_tokens", 0)
            self._append(event)


def _events(source: Tracer | str | Path | Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(source, Tracer):
        return list(source.spans)
    if isinstance(source, (str, Path)):
        events = []
        for line in Path(source).read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events
    return list(source)


def replay(source: Tracer | str | Path | Iterable[dict[str, Any]], *, emit: bool = True) -> str:
    """Render an in-memory or persisted trace as a compact step-by-step replay."""
    lines = []
    for index, event in enumerate(_events(source), 1):
        usage = event.get("usage") or {}
        tokens = usage.get("total_tokens")
        token_text = f"  {tokens}tok" if tokens is not None else ""
        flag = "" if event.get("ok", False) else "  ✗"
        lines.append(
            f"#{index:<3} {str(event.get('kind', '?')):<4} "
            f"{str(event.get('name', '?')):<18} "
            f"{float(event.get('duration_ms', 0)):>8.1f}ms{token_text}  "
            f"→ {str(event.get('out', ''))[:80]}{flag}"
        )
    rendered = "\n".join(lines)
    if emit and rendered:
        print(rendered)
    return rendered


def cost_report(
    source: Tracer | str | Path | Iterable[dict[str, Any]],
    price_per_1k: float = 0.001,
    *,
    prompt_price_per_1k: float | None = None,
    completion_price_per_1k: float | None = None,
    emit: bool = True,
) -> dict[str, Any]:
    """Calculate per-call and cumulative token cost and identify the priciest LLM span."""
    input_price = price_per_1k if prompt_price_per_1k is None else prompt_price_per_1k
    output_price = price_per_1k if completion_price_per_1k is None else completion_price_per_1k
    steps = []
    for event in _events(source):
        if event.get("kind") != "llm" or not isinstance(event.get("usage"), dict):
            continue
        usage = event["usage"]
        prompt = int(usage.get("prompt_tokens", 0) or 0)
        completion = int(usage.get("completion_tokens", 0) or 0)
        total = int(usage.get("total_tokens", prompt + completion) or 0)
        cost = prompt / 1000 * input_price + completion / 1000 * output_price
        steps.append({
            "seq": event.get("seq"),
            "name": event.get("name", "llm"),
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
            "cost": cost,
        })

    total_prompt = sum(step["prompt_tokens"] for step in steps)
    total_completion = sum(step["completion_tokens"] for step in steps)
    total_tokens = sum(step["total_tokens"] for step in steps)
    total_cost = sum(step["cost"] for step in steps)
    priciest = max(steps, key=lambda step: step["cost"], default=None)
    report = {
        "calls": steps,
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
        "total_tokens": total_tokens,
        "estimated_cost": total_cost,
        "priciest": priciest,
    }
    if emit:
        for step in steps:
            print(
                f"span #{step['seq']}: prompt={step['prompt_tokens']} "
                f"completion={step['completion_tokens']} total={step['total_tokens']} "
                f"cost=${step['cost']:.6f}"
            )
        print(f"总 token: {total_tokens}  估算成本: ${total_cost:.6f}")
        if priciest:
            print(f"最贵一步: span #{priciest['seq']} ({priciest['total_tokens']} tok)")
    return report


def build_run_summary(
    source: Tracer | str | Path | Iterable[dict[str, Any]],
    price_per_1k: float = 0.001,
    *,
    prompt_price_per_1k: float | None = None,
    completion_price_per_1k: float | None = None,
    status: str = "Completed",
) -> str:
    """Return a human-readable run summary for display after task completion.

    Unlike ``cost_report``, this produces a compact multi-line panel body
    suitable for both CLI and TUI post-run display.
    """
    input_price = price_per_1k if prompt_price_per_1k is None else prompt_price_per_1k
    output_price = price_per_1k if completion_price_per_1k is None else completion_price_per_1k

    events = _events(source)
    if not events:
        return "(no trace data)"

    llm_spans = [e for e in events if e.get("kind") == "llm"]
    tool_spans = [e for e in events if e.get("kind") == "tool"]
    errors = [e for e in events if not e.get("ok", True)]
    compaction_spans = [e for e in events if e.get("name") == "compact"]

    total_prompt = sum(int((e.get("usage") or {}).get("prompt_tokens", 0) or 0) for e in llm_spans)
    total_completion = sum(int((e.get("usage") or {}).get("completion_tokens", 0) or 0) for e in llm_spans)
    total_tokens = total_prompt + total_completion
    total_cost = total_prompt / 1000 * input_price + total_completion / 1000 * output_price

    # Find the priciest LLM span
    priciest = None
    for e in llm_spans:
        usage = e.get("usage") or {}
        p = int(usage.get("prompt_tokens", 0) or 0)
        c = int(usage.get("completion_tokens", 0) or 0)
        cost = p / 1000 * input_price + c / 1000 * output_price
        total = p + c
        if priciest is None or cost > priciest["cost"]:
            priciest = {"seq": e.get("seq"), "name": e.get("name", "?"), "total": total, "cost": cost}

    # Count distinct turns
    turns: set[int] = set()
    for e in events:
        turn = e.get("turn")
        if isinstance(turn, int):
            turns.add(turn)
    turn_count = max(turns) + 1 if turns else 0

    lines = [
        f"Turns: {turn_count}  |  LLM calls: {len(llm_spans)}  |  Tool calls: {len(tool_spans)}",
        f"Tokens: {total_prompt:,} prompt + {total_completion:,} completion = {total_tokens:,}",
        f"Cost: ~${total_cost:.6f}",
    ]
    if priciest:
        lines.append(
            f"Most expensive: span #{priciest['seq']} ({priciest['name']}, "
            f"{priciest['total']:,} tok, ${priciest['cost']:.6f})"
        )
    if compaction_spans:
        lines.append(f"Compaction: triggered {len(compaction_spans)}x")
    if errors:
        lines.append(f"Errors: {len(errors)} step(s) failed")
    status_icon = {"Completed": "✅", "Max turns": "⚠️", "Error": "❌"}.get(status, "•")
    lines.append(f"Status: {status_icon} {status}")

    return "\n".join(lines)

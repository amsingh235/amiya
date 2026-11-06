"""Hosted traces (Langfuse), exported by the harness AFTER the timed region,
so upload time never counts as pipeline latency.

Local traces always exist: every run row in runs/<pipeline>.jsonl carries its steps, and the dashboard
draws them. Langfuse is optional: set LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY in .env.
Uses the public ingestion endpoint with the standard library (no SDK). Failures are logged, never raised.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import sys
import urllib.request
import uuid

_warned = False


def enabled() -> bool:
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


def host() -> str:
    return os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")


def trace_url(trace_id: str) -> str:
    return f"{host()}/trace/{trace_id}"


def _iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def export(pipeline_id: str, case: dict, result, latency_ms: float, model: str) -> str | None:
    global _warned
    if not enabled() or not result.trace_id:
        return None
    now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    batch = [{"id": uuid.uuid4().hex, "timestamp": now, "type": "trace-create", "body": {
        "id": result.trace_id, "name": f"overkill.{pipeline_id}", "input": {"case_id": case["id"], "text": case["text"]},
        "output": {"label": result.label, "abstain_reason": result.abstain_reason},
        "metadata": {"latency_ms_harness": round(latency_ms, 1), "path": result.meta.get("path")},
        "tags": ["overkill", pipeline_id]}}]
    for s in result.meta.get("steps", []):
        if not s.get("started_at"):
            continue
        batch.append({"id": uuid.uuid4().hex, "timestamp": now, "type": "generation-create", "body": {
            "id": uuid.uuid4().hex, "traceId": result.trace_id, "name": s["node"], "model": model,
            "startTime": _iso(s["started_at"]), "endTime": _iso(s["started_at"] + (s.get("ms") or 0) / 1000),
            "output": {k: v for k, v in s.items() if k not in ("tokens_in", "tokens_out", "ms", "started_at")},
            "usage": {"input": s["tokens_in"], "output": s["tokens_out"], "unit": "TOKENS"}}})
    auth = base64.b64encode(f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()).decode()
    req = urllib.request.Request(f"{host()}/api/public/ingestion", data=json.dumps({"batch": batch}).encode(),
                                 headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
        return trace_url(result.trace_id)
    except Exception as e:  # tracing must never break a benchmark run
        if not _warned:
            print(f"[tracing] Langfuse export failed ({e}); continuing without hosted traces", file=sys.stderr)
            _warned = True
        return None

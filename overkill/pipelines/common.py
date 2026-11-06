"""Helpers shared by the LLM pipelines."""
from __future__ import annotations

from .base import CATEGORIES, Result


def to_result(completion, calls: int = 1, **meta) -> Result:
    """Validate the forced tool output. Anything outside the enum is a parse failure: counted, not hidden."""
    args = completion.tool_args or {}
    label = args.get("category")
    ok = label in CATEGORIES
    return Result(
        label=label if ok else None,
        tokens_in=completion.tokens_in, tokens_out=completion.tokens_out,
        tokens_cached=completion.tokens_cached, calls=calls,
        abstain_reason=None if ok else "parse_error",
        meta={"confidence": num(args.get("confidence")), "reason": args.get("reason"),
              "retries": completion.retries, **meta})


def num(x, default=None):
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return default


def step(node: str, completion, **out) -> dict:
    """One trace step. ms is diagnostic only (waterfall); reported latency comes from the harness."""
    return {"node": node, "tokens_in": completion.tokens_in, "tokens_out": completion.tokens_out,
            "ms": round(completion.elapsed_ms, 1), "started_at": completion.started_at, **out}

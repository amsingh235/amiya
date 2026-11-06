"""One pricing table. Cost is computed from measured tokens, never estimated from character counts.

Groq's free tier bills $0. We price every token at the paid on-demand list rate anyway, so the
comparison reflects what each architecture would cost in production, not what this build cost.
"""
from __future__ import annotations

import os

from pipelines.base import MODEL

PRICING = {
    "llama-3.3-70b-versatile": {
        "input_per_m": 0.59,
        "output_per_m": 0.79,
        "cached_input_per_m": None,  # None = no cache discount assumed; cached tokens priced as input
        "read_on": "2026-11-06",
        "source": "Groq on-demand list price ($0.59 in / $0.79 out per 1M tokens), cross-checked on "
                  "third-party price trackers (May and Aug 2026). Confirm on groq.com/pricing before quoting.",
    },
    # Only pipeline E (cascade, a labelled model-mix experiment) uses this one.
    "llama-3.1-8b-instant": {
        "input_per_m": 0.05,
        "output_per_m": 0.08,
        "cached_input_per_m": None,
        "read_on": "2026-11-06",
        "source": "Groq on-demand list price ($0.05 in / $0.08 out per 1M tokens) per third-party trackers "
                  "(May 2026). Confirm on groq.com/pricing before quoting.",
    },
}

EMBEDDING = {"model": "BAAI/bge-small-en-v1.5", "usd_per_m": 0.0,
             "basis": "runs locally on CPU via fastembed (ONNX): $0 marginal cost"}

FREE_TIER_NOTE = ("Free tier bills $0; tokens are priced at the paid on-demand rate so the comparison "
                  "reflects production cost.")


def call_cost(tokens_in: int, tokens_out: int, tokens_cached: int = 0, model: str = MODEL) -> float:
    p = PRICING[model]
    cached_rate = p["cached_input_per_m"] if p["cached_input_per_m"] is not None else p["input_per_m"]
    fresh_in = max(0, tokens_in - tokens_cached)
    return (fresh_in * p["input_per_m"] + tokens_cached * cached_rate + tokens_out * p["output_per_m"]) / 1e6


def cost_of(result) -> float:
    """Price a Result. Multi-model pipelines report usage per model; each model is priced at its own rate."""
    by_model = (result.meta or {}).get("usage_by_model")
    if by_model:
        return sum(call_cost(i, o, c, m) for m, (i, o, c) in by_model.items())
    return call_cost(result.tokens_in, result.tokens_out, result.tokens_cached)


def free_tier_limits() -> dict:
    return {k: int(os.environ.get(f"GROQ_{k}", d)) for k, d in
            (("RPM", 30), ("TPM", 12000), ("RPD", 1000), ("TPD", 100000))}


def pricing_block(model: str = MODEL) -> dict:
    return {"model": model, **PRICING[model], "embedding": EMBEDDING, "note": FREE_TIER_NOTE,
            "other_models": {m: p for m, p in PRICING.items() if m != model}}

"""Scoring: accuracy (strict: abstain = not correct), 95% Wilson interval, per-difficulty accuracy,
automation rate, confusion matrix (+ an abstain column), per-category P/R/F1, top confusions,
and retrieval attribution (did retrieval miss, or did the model ignore what it was given?).
"""
from __future__ import annotations

import math
from collections import Counter

from pipelines.base import CATEGORIES

from .data import DIFFICULTIES


def percentile(values: list[float], q: float) -> float | None:
    """Linear interpolation between closest ranks (numpy's default)."""
    if not values:
        return None
    v = sorted(values)
    pos = (len(v) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    """95% interval for a proportion. Honest at small n, unlike the normal approximation."""
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def _rate(k: int, n: int) -> float | None:
    return round(k / n, 4) if n else None


def summarize(rows: list[dict], gold: dict[str, dict]) -> dict:
    n = len(rows)
    golds = [gold[r["id"]]["label"] for r in rows]
    preds = [r["pred"] for r in rows]
    correct = sum(g == p for g, p in zip(golds, preds))
    auto = sum(p is not None for p in preds)
    auto_correct = correct  # an abstention is never correct, so every correct row is automated
    reasons = Counter(r.get("abstain_reason") for r in rows if r["pred"] is None)

    by_diff = {}
    for d in DIFFICULTIES:
        sub = [(g, p) for r, g, p in zip(rows, golds, preds) if gold[r["id"]]["difficulty"] == d]
        if sub:
            k = sum(g == p for g, p in sub)
            by_diff[d] = {"n": len(sub), "accuracy": _rate(k, len(sub)), "ci95": wilson(k, len(sub))}

    cols = CATEGORIES + ["abstain"]
    idx = {c: i for i, c in enumerate(cols)}
    matrix = [[0] * len(cols) for _ in CATEGORIES]
    for g, p in zip(golds, preds):
        matrix[idx[g]][idx[p if p is not None else "abstain"]] += 1

    per_cat = {}
    for i, c in enumerate(CATEGORIES):
        tp = matrix[i][i]
        support = sum(matrix[i])
        predicted = sum(row[i] for row in matrix)
        prec = tp / predicted if predicted else None
        rec = tp / support if support else None
        f1 = 2 * prec * rec / (prec + rec) if prec and rec else (0.0 if support else None)
        per_cat[c] = {"support": support, "precision": None if prec is None else round(prec, 4),
                      "recall": None if rec is None else round(rec, 4), "f1": None if f1 is None else round(f1, 4)}

    confusions = []
    for i, g in enumerate(CATEGORIES):
        support = sum(matrix[i])
        for j, p in enumerate(cols):
            if i != j and matrix[i][j]:
                confusions.append({"gold": g, "pred": p, "count": matrix[i][j],
                                   "share_of_gold": round(matrix[i][j] / support, 4)})
    confusions.sort(key=lambda x: (-x["count"], -x["share_of_gold"]))

    out = {
        "n": n, "correct": correct,
        "accuracy": _rate(correct, n), "ci95": wilson(correct, n),
        "accuracy_by_difficulty": by_diff,
        "automation_rate": _rate(auto, n),               # share decided without a human
        "auto_accuracy": _rate(auto_correct, auto),      # accuracy on the cases it did decide
        "human_review_rate": _rate(reasons.get("human_review", 0) + reasons.get("no_rule_matched", 0), n),
        "parse_error_rate": _rate(reasons.get("parse_error", 0), n),
        "outcomes": {"correct": correct, "wrong": auto - correct, "abstained": n - auto,
                     "abstain_reasons": dict(reasons)},
        "per_category": per_cat,
        "confusion": {"rows": CATEGORIES, "cols": cols, "matrix": matrix},
        "top_confusions": confusions[:8],
    }

    with_ret = [(r, g, p) for r, g, p in zip(rows, golds, preds) if (r.get("meta") or {}).get("retrieved")]
    if with_ret:
        hits = missed = ignored = 0
        for r, g, p in with_ret:
            hit = any(g in d.get("cats", []) for d in r["meta"]["retrieved"])
            hits += hit
            if p != g:
                if hit:
                    ignored += 1
                else:
                    missed += 1
        out["retrieval"] = {"n": len(with_ret), "hit_rate": _rate(hits, len(with_ret)),
                            "errors_retrieval_missed": missed, "errors_model_ignored": ignored,
                            "definition": "hit = a retrieved doc speaks about the gold category"}
    return out


def latency_stats(rows: list[dict]) -> dict:
    vals = [r["latency_ms"] for r in rows if not r.get("warmup")]
    if not vals:
        return {"n": 0, "p50_ms": None, "p95_ms": None, "mean_ms": None, "max_ms": None, "warmup_discarded": 0}
    return {"n": len(vals), "p50_ms": round(percentile(vals, 50), 4), "p95_ms": round(percentile(vals, 95), 4),
            "mean_ms": round(sum(vals) / len(vals), 4), "max_ms": round(max(vals), 4),
            "warmup_discarded": sum(1 for r in rows if r.get("warmup"))}


def cost_stats(rows: list[dict]) -> dict:
    n = len(rows) or 1
    tin = sum(r["tokens_in"] for r in rows)
    tout = sum(r["tokens_out"] for r in rows)
    cached = sum(r.get("tokens_cached", 0) for r in rows)
    total = sum(r["cost_usd"] for r in rows)
    return {"cost_per_case_usd": round(total / n, 8), "cost_per_1k_usd": round(1000 * total / n, 6),
            "total_usd": round(total, 6), "tokens_in_per_case": round(tin / n, 1),
            "tokens_out_per_case": round(tout / n, 1), "calls_per_case": round(sum(r["calls"] for r in rows) / n, 3),
            "cached_tokens_total": cached, "caching_used": cached > 0}

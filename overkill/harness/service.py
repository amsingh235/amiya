"""Shared service layer behind serve.py (HTTP) and mcp_server.py (MCP).

The playground is not the benchmark, but it uses the same harness-owned timing and pricing,
so a live answer is measured exactly the way results.json is.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
from pathlib import Path

from pipelines import CATEGORY_NAMES, PIPELINE_IDS, get_pipeline
from pipelines.base import ROOT
from pipelines.llm import load_env

from .cost import call_cost
from .data import load_eval
from .run import preflight, read_rows


class Service:
    def __init__(self, root: Path = ROOT):
        load_env(root / ".env")
        self.root = root
        self._pipes: dict = {}
        self._lock = threading.Lock()
        self._retriever = None
        self.cases, self.meta = load_eval(root)
        self.by_id = {c["id"]: c for c in self.cases}

    @property
    def llm_available(self) -> bool:
        return bool(os.environ.get("GROQ_API_KEY"))

    @property
    def retriever(self):
        if self._retriever is None:
            from pipelines.retrieval import Retriever
            self._retriever = Retriever()
        return self._retriever

    def pipeline(self, pid: str):
        if pid not in PIPELINE_IDS:
            raise ValueError(f"unknown pipeline {pid!r}; choose from {PIPELINE_IDS}")
        with self._lock:
            if pid not in self._pipes:
                kw = {"retriever": self.retriever} if pid in ("rag", "agents") else {}
                self._pipes[pid] = get_pipeline(pid, **kw)
            return self._pipes[pid]

    def health(self) -> dict:
        return {"live": True, "llm": self.llm_available, "eval_set": self.meta["status"], "n": self.meta["n"],
                "pipelines": {p: p == "rules" or self.llm_available for p in PIPELINE_IDS}}

    def classify(self, text: str, pipeline: str = "rules") -> dict:
        text = (text or "").strip()
        if not text:
            raise ValueError("text is empty")
        if len(text) > 4000:
            raise ValueError("text too long (max 4000 characters)")
        pipe = self.pipeline(pipeline)
        t0 = time.perf_counter()
        res = pipe.classify(text)
        latency = (time.perf_counter() - t0) * 1000  # harness-owned timing, same as run.py
        return {"pipeline": pipeline, "pred": res.label, "label_name": CATEGORY_NAMES.get(res.label),
                "abstain_reason": res.abstain_reason, "tokens_in": res.tokens_in, "tokens_out": res.tokens_out,
                "calls": res.calls, "cost_usd": round(call_cost(res.tokens_in, res.tokens_out, res.tokens_cached), 8),
                "latency_ms": round(latency, 3), "meta": res.meta}

    def search(self, query: str, k: int = 5) -> dict:
        hits = self.retriever.search(query, k=max(1, min(int(k), 10)))
        return {"mode": self.retriever.mode, "hits": hits}

    def results(self) -> dict:
        p = self.root / "results.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def results_summary(self) -> dict:
        r = self.results()
        out = {"generated_at": r.get("generated_at"), "model": r.get("model"), "eval_set": r.get("eval_set"),
               "pipelines": {}}
        for pid, e in r.get("pipelines", {}).items():
            t = e["metrics"]["test"]
            out["pipelines"][pid] = {
                "name": e["name"], "status": e["status"], "variant": e["variant"],
                "test_accuracy": t["accuracy"], "test_ci95": t["ci95"], "test_n": t["n"],
                "dev_accuracy": e["metrics"]["dev"]["accuracy"],
                "accuracy_by_difficulty": {k: v["accuracy"] for k, v in e["metrics"]["all"]["accuracy_by_difficulty"].items()},
                "automation_rate": e["metrics"]["all"]["automation_rate"],
                "cost_per_1k_usd": e["cost"]["cost_per_1k_usd"], "p50_ms": e["latency"]["p50_ms"],
                "p95_ms": e["latency"]["p95_ms"], "fixed_monthly_usd": e["fixed_monthly_usd"],
                "top_confusions": e["metrics"]["all"]["top_confusions"][:3]}
        return out

    def list_cases(self, difficulty: str | None = None, label: str | None = None, split: str | None = None,
                   limit: int = 20) -> list[dict]:
        rows = [c for c in self.cases if (not difficulty or c["difficulty"] == difficulty)
                and (not label or c["label"] == label) and (not split or c["split"] == split)]
        return [{k: c.get(k) for k in ("id", "difficulty", "label", "split", "text")} for c in rows[: max(1, int(limit))]]

    def case(self, case_id: str) -> dict:
        c = self.by_id.get(case_id)
        if not c:
            raise ValueError(f"no case {case_id!r}")
        preds = {}
        for pid, e in self.results().get("pipelines", {}).items():
            row = next((r for r in read_rows(self.root / "runs" / f"{pid}.jsonl")
                        if r["id"] == case_id and r.get("fp") == e["fingerprint"]), None)
            if row:
                preds[pid] = {"pred": row["pred"], "correct": row["pred"] == c["label"],
                              "abstain_reason": row.get("abstain_reason"), "cost_usd": row["cost_usd"],
                              "latency_ms": row["latency_ms"], "meta": row.get("meta")}
        return {**c, "predictions": preds}

    def estimate(self, pipeline: str) -> dict:
        return preflight(get_pipeline(pipeline), self.cases)

    def save_outbox(self, item: dict) -> str:
        out = self.root / "outbox"
        out.mkdir(exist_ok=True)
        path = out / f"triage-{dt.date.today().isoformat()}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return str(path.relative_to(self.root))

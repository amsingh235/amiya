"""Pipeline E (experiment): a model cascade. The small model answers first; escalate only when unsure.

  START -> small (llama-3.1-8b-instant, zero-shot) --confident--> END
                         \\--unsure--> big (llama-3.3-70b-versatile + RAG context) -> END

This is the cheapest agentic pattern there is: route by confidence, pay for the big model only on the
hard tail. It deliberately BREAKS the "one model for all pipelines" constraint, so it is NOT part of the
four-way architecture comparison: results.json marks it comparable=false and the dashboard shows it
apart from the ladder. The questions it answers: what share escalates, and does accuracy survive?

Caveat to say out loud: an 8B model's self-reported confidence is poorly calibrated. Measure the
escalation threshold on dev (CASCADE_THRESHOLD), don't trust a default.
"""
from __future__ import annotations

import os
import uuid

from .base import CATEGORIES, MODEL, LLMPipelineMixin, Pipeline, Result
from .common import num, step
from .graph import END, START, StateGraph
from .prompts import BASE_SYSTEM, RAG_SYSTEM, classify_tool

SMALL_MODEL = "llama-3.1-8b-instant"


class CascadePipeline(LLMPipelineMixin, Pipeline):
    id = "cascade"
    name = "Cascade (8B first, escalate to 70B)"
    short = "Cascade"
    uses_llm = True
    comparable = False  # different model mix: an experiment beside the ladder, never on it
    fixed_monthly_usd = 25.0
    fixed_monthly_basis = "ASSUMPTION: same managed Postgres as RAG ($25/mo) for the escalation path's retrieval."

    def __init__(self, client=None, small_client=None, retriever=None, k: int | None = None,
                 threshold: float | None = None):
        self._client = client
        self._small = small_client
        self._retriever = retriever
        self.k = int(k or os.environ.get("RAG_K", 3))
        self.threshold = float(threshold if threshold is not None else os.environ.get("CASCADE_THRESHOLD", 0.85))
        self.tool = classify_tool()
        g = StateGraph(dict)
        g.add_node("small", self.small)
        g.add_node("big", self.big)
        g.add_edge(START, "small")
        g.add_conditional_edges("small", lambda s: "confident" if s["final"] else "unsure",
                                {"confident": END, "unsure": "big"})
        g.add_edge("big", END)
        self.graph = g.compile()

    @property
    def small_client(self):
        if self._small is None:
            from .llm import GroqClient
            self._small = GroqClient(model=SMALL_MODEL)
        return self._small

    @property
    def retriever(self):
        if self._retriever is None:
            from .retrieval import Retriever
            self._retriever = Retriever()
        return self._retriever

    def config(self) -> dict:
        return {"models": [SMALL_MODEL, MODEL], "small_system": BASE_SYSTEM, "big_system": RAG_SYSTEM,
                "threshold": self.threshold, "k": self.k, "retrieval": self.retriever.describe(),
                "edges": self.graph.edges()}

    def variant(self) -> str:
        return f"τ={self.threshold} · k={self.k} · {self.retriever.mode}"

    def estimate_tokens(self, text: str) -> tuple[float, float]:
        small = (len(BASE_SYSTEM) + len(text)) / 4 + 280
        big = (len(RAG_SYSTEM) + len(text) + 520 * self.k) / 4 + 280
        return 1.4, small + 0.4 * big  # assumes ~40% escalate: revise once measured

    def small(self, s: dict) -> dict:
        c = self.small_client.chat([{"role": "system", "content": BASE_SYSTEM},
                                    {"role": "user", "content": f"Dispute:\n{s['text']}"}], tool=self.tool)
        a = c.tool_args or {}
        label = a.get("category") if a.get("category") in CATEGORIES else None
        conf = num(a.get("confidence"), 0.0)
        usage = {SMALL_MODEL: [c.tokens_in, c.tokens_out, c.tokens_cached]}
        return {"final": label if label and conf >= self.threshold else None, "small_label": label,
                "small_conf": conf, "usage": usage, "calls": 1, "path": ["small"],
                "steps": [step("small", c, model=SMALL_MODEL, label=label, confidence=conf,
                               escalate=not (label and conf >= self.threshold))]}

    def big(self, s: dict) -> dict:
        hits = self.retriever.search(s["text"], k=self.k)
        context = "\n\n".join(f"[{h['id']}] {h['text']}" for h in hits)
        c = self.client.chat([{"role": "system", "content": RAG_SYSTEM},
                              {"role": "user", "content": f"Policy excerpts:\n{context}\n\nDispute:\n{s['text']}"}],
                             tool=self.tool)
        a = c.tool_args or {}
        label = a.get("category") if a.get("category") in CATEGORIES else None
        usage = {**s["usage"], MODEL: [c.tokens_in, c.tokens_out, c.tokens_cached]}
        return {"final": label, "usage": usage, "calls": s["calls"] + 1, "path": s["path"] + ["big"],
                "retrieved": [{"id": h["id"], "cats": h["cats"], "score": h["score"]} for h in hits],
                "steps": s["steps"] + [step("big", c, model=MODEL, label=label, confidence=num(a.get("confidence")),
                                            docs=[h["id"] for h in hits])]}

    def classify(self, text: str) -> Result:
        s = self.graph.invoke({"text": text, "final": None, "usage": {}, "calls": 0, "path": [], "steps": []})
        u = s["usage"]
        return Result(
            label=s["final"], tokens_in=sum(v[0] for v in u.values()), tokens_out=sum(v[1] for v in u.values()),
            tokens_cached=sum(v[2] for v in u.values()), calls=s["calls"], trace_id=uuid.uuid4().hex,
            abstain_reason=None if s["final"] else "parse_error",
            meta={"path": s["path"], "steps": s["steps"], "escalated": "big" in s["path"],
                  "retrieved": s.get("retrieved", []), "usage_by_model": u})

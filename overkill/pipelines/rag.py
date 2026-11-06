"""Pipeline C: RAG. Retrieve top-k policy rules, put them in the prompt beside the nine categories, classify.

Tune only these, in order, measuring after each (dev split): k in {1,3,5,8}; then hybrid vs bm25/dense;
then (cut first if short on time) a cross-encoder reranker over the top 20.
Retrieval quality is logged per case so a wrong answer can be attributed to
"retrieval missed" vs "model ignored what it was given" (harness/score.py).
"""
from __future__ import annotations

import os
import uuid

from .base import MODEL, LLMPipelineMixin, Pipeline, Result
from .common import step, to_result
from .prompts import RAG_SYSTEM, classify_tool


class RagPipeline(LLMPipelineMixin, Pipeline):
    id = "rag"
    name = "RAG (policy retrieval)"
    short = "RAG"
    uses_llm = True
    fixed_monthly_usd = 25.0
    fixed_monthly_basis = ("ASSUMPTION: managed Postgres + pgvector on a paid tier (e.g. Supabase Pro, "
                           "$25/mo) once out of the free tier. This build runs on $0.")

    def __init__(self, client=None, k: int | None = None, retriever=None):
        self._client = client
        self.k = int(k or os.environ.get("RAG_K", 3))
        self._retriever = retriever
        self.tool = classify_tool()

    @property
    def retriever(self):
        if self._retriever is None:
            from .retrieval import Retriever
            self._retriever = Retriever()
        return self._retriever

    def config(self) -> dict:
        return {"model": MODEL, "system": RAG_SYSTEM, "tool": self.tool, "k": self.k,
                "retrieval": self.retriever.describe()}

    def variant(self) -> str:
        return f"k={self.k} · {self.retriever.mode}"

    def estimate_tokens(self, text: str) -> tuple[float, float]:
        return 1.0, (len(RAG_SYSTEM) + len(text) + 520 * self.k) / 4 + 220 + 60

    def classify(self, text: str) -> Result:
        hits = self.retriever.search(text, k=self.k)
        context = "\n\n".join(f"[{h['id']}] {h['text']}" for h in hits)
        c = self.client.chat([{"role": "system", "content": RAG_SYSTEM},
                              {"role": "user", "content": f"Policy excerpts:\n{context}\n\nDispute:\n{text}"}],
                             tool=self.tool)
        retrieved = [{"id": h["id"], "cats": h["cats"], "score": h["score"]} for h in hits]
        r = to_result(c, retrieved=retrieved)
        r.trace_id = uuid.uuid4().hex
        r.meta["steps"] = [{"node": "retrieve", "tokens_in": 0, "tokens_out": 0, "ms": None,
                            "docs": [h["id"] for h in hits]},
                           step("classify", c, label=r.label, confidence=r.meta.get("confidence"))]
        return r

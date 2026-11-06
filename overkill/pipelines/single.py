"""Pipeline B: one LLM call. Category definitions in the prompt, output forced through a tool schema."""
from __future__ import annotations

import uuid

from .base import MODEL, LLMPipelineMixin, Pipeline, Result
from .common import step, to_result
from .prompts import BASE_SYSTEM, classify_tool


class SinglePipeline(LLMPipelineMixin, Pipeline):
    id = "single"
    name = "Single LLM call"
    short = "Single call"
    uses_llm = True
    fixed_monthly_usd = 0.0
    fixed_monthly_basis = "Serverless API: nothing to keep running between calls."

    def __init__(self, client=None, few_shot: int = 0):
        self._client = client
        self.few_shot = few_shot  # zero-shot first; add examples later and report the delta
        self.tool = classify_tool()

    def config(self) -> dict:
        return {"model": MODEL, "system": BASE_SYSTEM, "tool": self.tool, "few_shot": self.few_shot}

    def variant(self) -> str:
        return "zero-shot" if not self.few_shot else f"{self.few_shot}-shot"

    def estimate_tokens(self, text: str) -> tuple[float, float]:
        return 1.0, (len(BASE_SYSTEM) + len(text)) / 4 + 220 + 60

    def classify(self, text: str) -> Result:
        c = self.client.chat([{"role": "system", "content": BASE_SYSTEM},
                              {"role": "user", "content": f"Dispute:\n{text}"}], tool=self.tool)
        r = to_result(c)
        r.trace_id = uuid.uuid4().hex
        r.meta["steps"] = [step("classify", c, label=r.label, confidence=r.meta.get("confidence"))]
        return r

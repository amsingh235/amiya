"""The one interface every pipeline implements.

Pipelines return a label and token counts. They never report their own cost or latency:
the harness times every call and prices every token. That is how benchmarks stay unflattered.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAXONOMY = json.loads((ROOT / "data" / "taxonomy.json").read_text(encoding="utf-8"))
CATEGORIES: list[str] = [c["id"] for c in TAXONOMY["categories"]]
CATEGORY_NAMES: dict[str, str] = {c["id"]: c["name"] for c in TAXONOMY["categories"]}
MODEL = "llama-3.3-70b-versatile"  # held constant across every pipeline. Never swap.


@dataclass
class Result:
    label: str | None                 # one of CATEGORIES, or None when the pipeline abstains
    tokens_in: int = 0                # prompt tokens, as reported by the provider
    tokens_out: int = 0               # completion tokens, as reported by the provider
    tokens_cached: int = 0            # prompt tokens served from the provider's cache (priced separately)
    calls: int = 0                    # model calls made for this case
    trace_id: str | None = None
    abstain_reason: str | None = None  # "human_review" | "no_rule_matched" | "parse_error"
    meta: dict = field(default_factory=dict)  # matched rule, retrieved docs, agent path + steps

    @property
    def abstained(self) -> bool:
        return self.label is None


class Pipeline:
    id: str = "base"
    name: str = "Base"
    short: str = "Base"
    uses_llm: bool = False
    # Infra you pay whether or not it runs. These are ASSUMPTIONS, not measurements:
    # the basis string travels into results.json so nobody mistakes one for the other.
    fixed_monthly_usd: float = 0.0
    fixed_monthly_basis: str = ""

    def classify(self, text: str) -> Result:
        raise NotImplementedError

    def config(self) -> dict:
        """Everything that changes the output. Its hash invalidates checkpoints when you tune."""
        return {}

    def variant(self) -> str:
        """Short human label for this configuration, e.g. 'k=3 · hybrid'. Shown in run history."""
        return "default"

    def fingerprint(self) -> str:
        blob = json.dumps({"id": self.id, "config": self.config()}, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:12]

    def estimate_tokens(self, text: str) -> tuple[float, float]:
        """(calls, tokens) per case: a PLANNING estimate from characters. Never used for reported cost."""
        return (0.0, 0.0)


class LLMPipelineMixin:
    """Lazy client so pipelines can be listed, fingerprinted and estimated without an API key."""
    _client = None

    @property
    def client(self):
        if self._client is None:
            from .llm import GroqClient
            self._client = GroqClient()
        return self._client

    @client.setter
    def client(self, value):
        self._client = value

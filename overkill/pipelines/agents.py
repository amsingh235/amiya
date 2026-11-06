"""Pipeline D: three agents in a state machine, not a free-roaming swarm.

  START -> classifier -> verifier --accept--> END
                    |            \\--reject--> arbiter -> END (label, or human_review)
                    \\--no parse--> END (human_review)

classifier  retrieves policy (reuses the RAG retriever), proposes a label + runner-up + confidence
verifier    fetches the policy for THAT category and checks its qualifying conditions; can reject
arbiter     runs only on rejection: compares the two candidates against policy, decides or abstains

The conditional edge into the arbiter is the whole design. An unconditional three-call chain is a
long prompt, not a multi-agent system, and costs roughly 40% more. Abstentions are a real outcome:
resolved automatically / routed to human / wrong are counted separately by the harness.
"""
from __future__ import annotations

import os
import uuid

from .base import CATEGORIES, MODEL, LLMPipelineMixin, Pipeline, Result
from .common import num, step
from .graph import END, START, StateGraph
from .prompts import (ARBITER_SYSTEM, RAG_SYSTEM, VERIFIER_SYSTEM, VERIFY_TOOL, arbitrate_tool,
                      classify_tool, policy_block)


class AgentsPipeline(LLMPipelineMixin, Pipeline):
    id = "agents"
    name = "Multi-agent (classifier, verifier, arbiter)"
    short = "Agents"
    uses_llm = True
    fixed_monthly_usd = 50.0
    fixed_monthly_basis = ("ASSUMPTION: the same managed Postgres ($25/mo) plus a hosted tracing seat "
                           "(~$25/mo): you cannot operate an agent system without traces.")

    def __init__(self, client=None, k: int | None = None, retriever=None, human_threshold: float | None = None):
        self._client = client
        self.k = int(k or os.environ.get("RAG_K", 3))
        self.human_threshold = float(human_threshold if human_threshold is not None
                                     else os.environ.get("AGENT_HUMAN_THRESHOLD", 0.6))
        self._retriever = retriever
        self.classify_tool = classify_tool(with_runner_up=True)
        self.graph = self._build()

    # ----- graph -------------------------------------------------------------------------------
    def _build(self):
        g = StateGraph(dict)
        g.add_node("classifier", self.classifier)
        g.add_node("verifier", self.verifier)
        g.add_node("arbiter", self.arbiter)
        g.add_edge(START, "classifier")
        g.add_conditional_edges("classifier", lambda s: "ok" if s["proposed"] else "unparsed",
                                {"ok": "verifier", "unparsed": END})
        g.add_conditional_edges("verifier", lambda s: s["verdict"], {"accept": END, "reject": "arbiter"})
        g.add_edge("arbiter", END)
        return g.compile()

    @property
    def retriever(self):
        if self._retriever is None:
            from .retrieval import Retriever
            self._retriever = Retriever()
        return self._retriever

    def config(self) -> dict:
        return {"model": MODEL, "classifier": RAG_SYSTEM, "verifier": VERIFIER_SYSTEM,
                "arbiter": ARBITER_SYSTEM, "k": self.k, "human_threshold": self.human_threshold,
                "retrieval": self.retriever.describe(), "edges": self.graph.edges()}

    def variant(self) -> str:
        return f"k={self.k} · τ={self.human_threshold} · {self.retriever.mode}"

    def estimate_tokens(self, text: str) -> tuple[float, float]:
        one = (len(RAG_SYSTEM) + len(text) + 520 * self.k) / 4 + 280
        return 2.35, one * 2.35  # ~35% of cases expected to reach the arbiter: revise once measured

    # ----- nodes: each returns a partial state update -------------------------------------------
    def _chat(self, s: dict, system: str, user: str, tool: dict):
        c = self.client.chat([{"role": "system", "content": system}, {"role": "user", "content": user}], tool=tool)
        acc = {"tokens_in": s["tokens_in"] + c.tokens_in, "tokens_out": s["tokens_out"] + c.tokens_out,
               "tokens_cached": s["tokens_cached"] + c.tokens_cached, "calls": s["calls"] + 1}
        return c, (c.tool_args or {}), acc

    def classifier(self, s: dict) -> dict:
        hits = self.retriever.search(s["text"], k=self.k)
        context = "\n\n".join(f"[{h['id']}] {h['text']}" for h in hits)
        c, a, acc = self._chat(s, RAG_SYSTEM, f"Policy excerpts:\n{context}\n\nDispute:\n{s['text']}",
                               self.classify_tool)
        proposed = a.get("category") if a.get("category") in CATEGORIES else None
        runner_up = a.get("runner_up") if a.get("runner_up") in CATEGORIES else None
        conf = num(a.get("confidence"), 0.0)
        return {**acc, "proposed": proposed, "runner_up": runner_up, "confidence": conf,
                "retrieved": [{"id": h["id"], "cats": h["cats"], "score": h["score"]} for h in hits],
                "path": s["path"] + ["classifier"],
                "steps": s["steps"] + [step("classifier", c, label=proposed, runner_up=runner_up,
                                            confidence=conf, reason=a.get("reason"),
                                            docs=[h["id"] for h in hits])]}

    def verifier(self, s: dict) -> dict:
        docs = self.retriever.for_category(s["proposed"], s["text"])
        user = (f"Proposed category: {s['proposed']}\n\nPolicy for {s['proposed']}:\n{policy_block(docs)}"
                f"\n\nDispute:\n{s['text']}")
        c, a, acc = self._chat(s, VERIFIER_SYSTEM, user, VERIFY_TOOL)
        verdict = a.get("verdict") if a.get("verdict") in ("accept", "reject") else "reject"  # unparsed: be safe
        suggested = a.get("suggested_category") if a.get("suggested_category") in CATEGORIES else None
        out = {**acc, "verdict": verdict, "suggested": suggested, "path": s["path"] + ["verifier"],
               "steps": s["steps"] + [step("verifier", c, verdict=verdict, suggested=suggested,
                                           failed_condition=a.get("failed_condition"),
                                           docs=[d.id for d in docs])]}
        if verdict == "accept":
            out["final"] = s["proposed"]
        return out

    def arbiter(self, s: dict) -> dict:
        second = s["suggested"] if s["suggested"] not in (None, s["proposed"]) else s["runner_up"]
        candidates = [c for c in dict.fromkeys([s["proposed"], second]) if c]
        docs = []
        for cat in candidates:
            docs += [d for d in self.retriever.for_category(cat, s["text"]) if d not in docs]
        user = (f"Candidates: {', '.join(candidates)}\nVerifier's objection: "
                f"{s['steps'][-1].get('failed_condition') or 'none given'}\n\nPolicy:\n{policy_block(docs)}"
                f"\n\nDispute:\n{s['text']}")
        c, a, acc = self._chat(s, ARBITER_SYSTEM, user, arbitrate_tool(candidates))
        decision, conf = a.get("decision"), num(a.get("confidence"), 0.0)
        final = decision if decision in candidates and conf >= self.human_threshold else None
        return {**acc, "final": final, "path": s["path"] + ["arbiter"],
                "steps": s["steps"] + [step("arbiter", c, candidates=candidates, decision=decision,
                                            confidence=conf, reason=a.get("reason"), final=final)]}

    # ----- interface ------------------------------------------------------------------------------
    def classify(self, text: str) -> Result:
        s = self.graph.invoke({"text": text, "path": [], "steps": [], "tokens_in": 0, "tokens_out": 0,
                               "tokens_cached": 0, "calls": 0, "proposed": None, "runner_up": None,
                               "verdict": None, "suggested": None, "final": None, "retrieved": []})
        final = s.get("final")
        return Result(
            label=final, tokens_in=s["tokens_in"], tokens_out=s["tokens_out"],
            tokens_cached=s["tokens_cached"], calls=s["calls"], trace_id=uuid.uuid4().hex,
            abstain_reason=None if final else ("parse_error" if not s["proposed"] else "human_review"),
            meta={"path": s["path"], "steps": s["steps"], "retrieved": s["retrieved"],
                  "proposed": s["proposed"], "verdict": s["verdict"], "confidence": s.get("confidence")})

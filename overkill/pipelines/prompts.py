"""Every prompt in the project lives here.

DRAFT: written by Claude as a starting point. You own these. Rewrite them in your own words:
an interviewer will point at any line and ask why it is there.

Design rule: single, RAG and the agent classifier share BASE_SYSTEM and the same tool schema,
so the comparison measures architecture, not prompt craft. Zero-shot first (no examples):
measure, then add few-shot and report the delta as a finding.
"""
from __future__ import annotations

from .base import CATEGORIES, TAXONOMY

CATEGORY_BLOCK = "\n".join(f"- {c['id']}: {c['definition']}" for c in TAXONOMY["categories"])

BASE_SYSTEM = f"""You classify card payment disputes into exactly one of nine categories.
Read the cardholder's message and decide what actually happened to them.

Categories (with definitions):
{CATEGORY_BLOCK}

Record your answer with the classify tool."""

RAG_SYSTEM = BASE_SYSTEM + """

You will also receive policy excerpts retrieved for this dispute. Apply them, including any
precedence rule (R1-R10) that fits the facts."""

VERIFIER_SYSTEM = """You verify a proposed category for a card payment dispute against written policy.
You get the dispute, the proposed category, and that category's policy (definition, qualifying
conditions, exclusions) plus any precedence rules that mention it.

Accept only if every qualifying condition is met by the facts in the message and no exclusion or
precedence rule sends the case to a different category. Otherwise reject, name the condition that
fails, and give the category the policy points to instead. Use the verify tool."""

ARBITER_SYSTEM = """You arbitrate a card payment dispute. A classifier and a policy verifier disagree.
You get the dispute and the policy for the two candidate categories.

Pick the candidate whose qualifying conditions the facts satisfy, applying precedence rules.
If the facts genuinely do not settle it, choose human_review: a wrong automatic decision costs
more than a human look. Use the arbitrate tool."""


def classify_tool(with_runner_up: bool = False) -> dict:
    props = {
        "category": {"type": "string", "enum": CATEGORIES},
        "confidence": {"type": "number", "description": "0 to 1. How sure you are."},
        "reason": {"type": "string", "description": "One short sentence citing the decisive fact."},
    }
    required = ["category", "confidence", "reason"]
    if with_runner_up:
        props["runner_up"] = {"type": "string", "enum": CATEGORIES,
                              "description": "The second most likely category."}
        required.append("runner_up")
    return {"type": "function", "function": {
        "name": "classify", "description": "Record the dispute category.",
        "parameters": {"type": "object", "properties": props, "required": required}}}


VERIFY_TOOL = {"type": "function", "function": {
    "name": "verify", "description": "Accept or reject the proposed category against policy.",
    "parameters": {"type": "object", "properties": {
        "verdict": {"type": "string", "enum": ["accept", "reject"]},
        "failed_condition": {"type": "string", "description": "If rejecting: the condition or rule that fails."},
        "suggested_category": {"type": "string", "enum": CATEGORIES,
                               "description": "If rejecting: the category the policy points to."},
    }, "required": ["verdict"]}}}


def arbitrate_tool(candidates: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": "arbitrate", "description": "Decide between the candidates or route to a human.",
        "parameters": {"type": "object", "properties": {
            "decision": {"type": "string", "enum": candidates + ["human_review"]},
            "confidence": {"type": "number", "description": "0 to 1."},
            "reason": {"type": "string", "description": "One sentence, citing policy."},
        }, "required": ["decision", "confidence", "reason"]}}}


def policy_block(docs) -> str:
    return "\n\n".join(f"[{d.id}] {d.text}" for d in docs)

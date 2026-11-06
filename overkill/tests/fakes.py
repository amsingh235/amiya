"""A fake Groq transport: lets tests exercise every LLM code path without a key or network."""
from __future__ import annotations

import json


def tool_response(name: str, args: dict, tokens_in: int = 500, tokens_out: int = 40) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "call_1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}],
        "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out}}


class FakeTransport:
    """script: callable(body) -> (status, headers, data). Records every request body."""

    def __init__(self, script):
        self.script = script
        self.bodies: list[dict] = []

    def __call__(self, body):
        self.bodies.append(body)
        return self.script(body)


def scripted(classify="credit_not_processed", runner_up="product_quality", verdict="accept",
             suggested=None, decision=None, confidence=0.9):
    def script(body):
        name = body["tool_choice"]["function"]["name"]
        if name == "classify":
            return 200, {}, tool_response("classify", {"category": classify, "runner_up": runner_up,
                                                       "confidence": confidence, "reason": "test"})
        if name == "verify":
            args = {"verdict": verdict, "failed_condition": "test condition"}
            if suggested:
                args["suggested_category"] = suggested
            return 200, {}, tool_response("verify", args, 700, 30)
        return 200, {}, tool_response("arbitrate", {"decision": decision or classify, "confidence": confidence,
                                                    "reason": "test"}, 900, 35)
    return script

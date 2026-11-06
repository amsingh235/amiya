"""Overkill as an MCP server: stdio transport, JSON-RPC 2.0, standard library only.

Any MCP client (Claude Desktop, Claude Code, Cursor...) can then classify disputes, search the
policy corpus, read results and inspect cases. That is how an agent with computer use, or any
assistant, can operate this benchmark as a tool.

    claude mcp add overkill -- python /absolute/path/to/overkill/mcp_server.py

Claude Desktop (claude_desktop_config.json):
    {"mcpServers": {"overkill": {"command": "python", "args": ["/absolute/path/to/overkill/mcp_server.py"]}}}

stdout carries protocol messages only; all logging goes to stderr.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness.service import Service  # noqa: E402
from pipelines import CATEGORIES, PIPELINE_IDS  # noqa: E402

SUPPORTED = ["2025-06-18", "2025-03-26", "2024-11-05"]
DIFFS = ["clear", "paraphrase", "ambiguous", "contradictory"]

TOOLS = [
    {"name": "classify_dispute",
     "description": "Classify a card payment dispute into one of 9 categories with one of the four pipelines. "
                    "Returns the label (or an abstention), tokens, cost (list price) and harness-measured latency. "
                    "'rules' needs no API key; the others need GROQ_API_KEY.",
     "inputSchema": {"type": "object", "properties": {
         "text": {"type": "string", "description": "The cardholder's message."},
         "pipeline": {"type": "string", "enum": PIPELINE_IDS, "default": "rules"}}, "required": ["text"]}},
    {"name": "search_policy",
     "description": "Retrieve the most relevant dispute-policy documents (definitions, evidence rules, "
                    "precedents, precedence rules R1-R10) for a query.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}, "k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3}},
         "required": ["query"]}},
    {"name": "get_results",
     "description": "Summary of results.json: per pipeline test accuracy with 95% CI, accuracy by difficulty, "
                    "automation rate, cost per 1k disputes, p50/p95 latency, top confusions.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "list_cases",
     "description": "List eval-set disputes, optionally filtered by difficulty tier, gold label or split.",
     "inputSchema": {"type": "object", "properties": {
         "difficulty": {"type": "string", "enum": DIFFS}, "label": {"type": "string", "enum": CATEGORIES},
         "split": {"type": "string", "enum": ["dev", "test"]},
         "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20}}}},
    {"name": "get_case",
     "description": "One dispute with its gold label and every recorded pipeline prediction (with traces).",
     "inputSchema": {"type": "object", "properties": {"case_id": {"type": "string"}}, "required": ["case_id"]}},
    {"name": "estimate_run",
     "description": "Planning estimate for running a pipeline over the whole eval set: calls, tokens, "
                    "list-price cost and how many days of Groq free-tier quota it needs.",
     "inputSchema": {"type": "object", "properties": {"pipeline": {"type": "string", "enum": PIPELINE_IDS}},
                     "required": ["pipeline"]}},
]

INSTRUCTIONS = ("Overkill benchmarks four ways to classify payment disputes (rules, single LLM call, RAG, "
                "multi-agent). Use get_results for the measured comparison, search_policy to ground answers "
                "in the written policy, and classify_dispute to run a pipeline on new text.")


def call_tool(svc: Service, name: str, a: dict):
    if name == "classify_dispute":
        return svc.classify(a.get("text", ""), a.get("pipeline", "rules"))
    if name == "search_policy":
        r = svc.search(a.get("query", ""), a.get("k", 3))
        return {"mode": r["mode"], "hits": [{k: h[k] for k in ("id", "title", "category", "score", "text")} for h in r["hits"]]}
    if name == "get_results":
        return svc.results_summary()
    if name == "list_cases":
        return svc.list_cases(a.get("difficulty"), a.get("label"), a.get("split"), a.get("limit", 20))
    if name == "get_case":
        return svc.case(a.get("case_id", ""))
    if name == "estimate_run":
        return svc.estimate(a.get("pipeline", "single"))
    raise ValueError(f"unknown tool {name!r}")


def handle(svc_factory, msg: dict) -> dict | None:
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:  # notification (e.g. notifications/initialized): never answered
        return None
    if method == "initialize":
        v = params.get("protocolVersion")
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": v if v in SUPPORTED else SUPPORTED[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "overkill", "version": "0.1.0"}, "instructions": INSTRUCTIONS}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        try:
            out = call_tool(svc_factory(), params.get("name"), params.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": json.dumps(out, indent=2, ensure_ascii=False)}], "isError": False}}
        except Exception as e:  # tool errors are results, not protocol errors
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main() -> None:
    svc = None

    def factory():
        nonlocal svc
        if svc is None:
            svc = Service()
        return svc

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            resp = handle(factory, msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

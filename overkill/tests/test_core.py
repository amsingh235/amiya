import json
import re
import shutil
from pathlib import Path

import pytest

from harness.cost import call_cost
from harness.data import load_eval, split_of
from harness.score import percentile, summarize, wilson
from pipelines import CATEGORIES, get_pipeline
from pipelines.base import ROOT
from pipelines.graph import END, START, StateGraph
from pipelines.llm import DailyLimitReached, GroqClient, _retry_after
from pipelines.retrieval import Retriever, load_policy, tokenize

from .fakes import FakeTransport, scripted, tool_response

NO_SLEEP = lambda s: None  # noqa: E731


def client(script):
    return GroqClient(transport=FakeTransport(script), sleep=NO_SLEEP)


# ---------------------------------------------------------------- scoring + cost
def test_percentile_matches_numpy_linear():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([10], 95) == 10
    assert abs(percentile(list(range(1, 101)), 95) - 95.05) < 1e-9


def test_wilson_interval_brackets_point_estimate():
    lo, hi = wilson(61, 100)
    assert lo < 0.61 < hi and 0.50 < lo and hi < 0.71
    assert wilson(0, 0) == [0.0, 0.0]


def test_cost_from_measured_tokens():
    assert call_cost(1_000_000, 0) == pytest.approx(0.59)
    assert call_cost(0, 1_000_000) == pytest.approx(0.79)
    assert call_cost(1200, 50) == pytest.approx((1200 * 0.59 + 50 * 0.79) / 1e6)


def test_summarize_counts_abstentions_as_not_correct():
    gold = {"a": {"label": "unauthorised", "difficulty": "clear"},
            "b": {"label": "duplicate_processing", "difficulty": "paraphrase"},
            "c": {"label": "unauthorised", "difficulty": "clear"}}
    rows = [{"id": "a", "pred": "unauthorised"}, {"id": "b", "pred": None, "abstain_reason": "human_review"},
            {"id": "c", "pred": "duplicate_processing"}]
    s = summarize(rows, gold)
    assert s["accuracy"] == pytest.approx(1 / 3, abs=1e-4)
    assert s["automation_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert s["auto_accuracy"] == 0.5
    assert s["human_review_rate"] == pytest.approx(1 / 3, abs=1e-4)
    m = s["confusion"]["matrix"]
    assert m[CATEGORIES.index("duplicate_processing")][-1] == 1  # abstain column


# ---------------------------------------------------------------- data integrity
def test_seed_eval_set_shape():
    cases, meta = load_eval()
    assert meta["n"] == len(cases) >= 180
    assert set(meta["label_mix"]) == set(CATEGORIES)
    mix = meta["difficulty_mix"]
    assert mix["clear"] / meta["n"] == pytest.approx(0.40, abs=0.02)
    assert mix["contradictory"] / meta["n"] == pytest.approx(0.10, abs=0.02)
    assert split_of("d0001") == split_of("d0001")  # deterministic


def test_policy_corpus_is_chunked_by_document():
    docs = load_policy()
    assert 40 <= len(docs) <= 60
    assert len({d.id for d in docs}) == len(docs)
    for d in docs:
        assert 20 <= len(d.text.split()) <= 300, d.id


def test_no_eval_text_leaks_into_policy():
    """Precedents must not copy eval cases, or RAG would be retrieving the answers."""
    def grams(text, n=7):
        w = re.findall(r"[a-z0-9]+", text.lower())
        return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}
    policy = set().union(*(grams(d.text) for d in load_policy()))
    cases, _ = load_eval()
    leaks = [c["id"] for c in cases if grams(c["text"]) & policy]
    assert not leaks, f"eval cases share 7-grams with policy docs: {leaks}"


# ---------------------------------------------------------------- pipelines
def test_rules_first_match_and_abstain():
    rules = get_pipeline("rules")
    assert rules.classify("I was charged twice for one coffee").label == "duplicate_processing"
    r = rules.classify("hello there")
    assert r.label is None and r.abstain_reason == "no_rule_matched"


def test_retriever_bm25_finds_the_relevant_rule():
    r = Retriever(mode="bm25")
    hits = r.search("paid in cash on delivery and the card was charged too", k=3)
    assert "R4" in [h["id"] for h in hits]
    assert tokenize("cancelled") == tokenize("cancel")


def test_single_forces_tool_schema_and_counts_tokens():
    t = FakeTransport(scripted(classify="product_quality"))
    p = get_pipeline("single", client=GroqClient(transport=t, sleep=NO_SLEEP))
    r = p.classify("The kettle arrived cracked.")
    assert r.label == "product_quality" and (r.tokens_in, r.tokens_out, r.calls) == (500, 40, 1)
    assert t.bodies[0]["tool_choice"]["function"]["name"] == "classify"
    assert t.bodies[0]["tools"][0]["function"]["parameters"]["properties"]["category"]["enum"] == CATEGORIES


def test_single_reports_parse_errors_instead_of_guessing():
    p = get_pipeline("single", client=client(lambda b: (200, {}, tool_response("classify", {"category": "banana"}))))
    r = p.classify("x")
    assert r.label is None and r.abstain_reason == "parse_error"


def test_rag_logs_retrieved_docs():
    p = get_pipeline("rag", client=client(scripted()), retriever=Retriever(mode="bm25"), k=3)
    r = p.classify("They accepted my return but the refund never arrived")
    assert len(r.meta["retrieved"]) == 3 and all("cats" in d for d in r.meta["retrieved"])


def test_agents_accept_path_skips_arbiter():
    t = FakeTransport(scripted(verdict="accept"))
    p = get_pipeline("agents", client=GroqClient(transport=t, sleep=NO_SLEEP), retriever=Retriever(mode="bm25"))
    r = p.classify("refund promised, never came")
    assert r.meta["path"] == ["classifier", "verifier"] and r.calls == 2 and r.label == "credit_not_processed"


def test_agents_reject_path_runs_arbiter_and_can_route_to_human():
    p = get_pipeline("agents", client=client(scripted(verdict="reject", suggested="product_quality",
                                                     decision="human_review")),
                     retriever=Retriever(mode="bm25"))
    r = p.classify("broken item, maybe refunded?")
    assert r.meta["path"] == ["classifier", "verifier", "arbiter"] and r.calls == 3
    assert r.label is None and r.abstain_reason == "human_review"
    assert r.tokens_in == 500 + 700 + 900


def test_agents_low_confidence_arbiter_abstains():
    p = get_pipeline("agents", client=client(scripted(verdict="reject", suggested="product_quality",
                                                     decision="product_quality", confidence=0.4)),
                     retriever=Retriever(mode="bm25"))
    assert p.classify("x").abstain_reason == "human_review"


def test_mini_graph_matches_langgraph_semantics():
    g = StateGraph(dict)
    g.add_node("a", lambda s: {"n": s["n"] + 1})
    g.add_node("b", lambda s: {"n": s["n"] * 10})
    g.add_edge(START, "a")
    g.add_conditional_edges("a", lambda s: "big" if s["n"] > 1 else "small", {"big": END, "small": "b"})
    g.add_edge("b", END)
    assert g.compile().invoke({"n": 0})["n"] == 10
    assert g.compile().invoke({"n": 5})["n"] == 6


# ---------------------------------------------------------------- client resilience
def test_client_backs_off_on_429_then_succeeds():
    calls = []

    def script(body):
        calls.append(1)
        if len(calls) < 3:
            return 429, {"retry-after": "1"}, {"error": {"message": "Rate limit reached ... (TPM)"}}
        return 200, {}, tool_response("classify", {"category": "unauthorised", "confidence": 1, "reason": ""})
    c = client(script).chat([{"role": "user", "content": "x"}],
                            tool={"type": "function", "function": {"name": "classify"}})
    assert len(calls) == 3 and c.retries == 2


def test_client_stops_on_daily_cap():
    msg = "Rate limit reached for model on tokens per day (TPD): Limit 100000. Please try again in 7m12.5s."
    with pytest.raises(DailyLimitReached):
        client(lambda b: (429, {}, {"error": {"message": msg}})).chat([{"role": "user", "content": "x"}])
    assert _retry_after({}, msg) == pytest.approx(432.5)


# ---------------------------------------------------------------- harness end to end
def test_harness_checkpoints_and_resumes(tmp_path: Path):
    for sub in ("data", "pipelines"):
        shutil.copytree(ROOT / sub, tmp_path / sub, ignore=shutil.ignore_patterns("labels"))
    (tmp_path / "data" / "labels").mkdir()
    from harness.run import run_pipeline
    t = FakeTransport(scripted(classify="unauthorised"))
    mk = lambda: get_pipeline("single", client=GroqClient(transport=t, sleep=NO_SLEEP))  # noqa: E731
    e1 = run_pipeline("single", limit=12, yes=True, pipeline=mk(), root=tmp_path, log=lambda *a: None)
    assert e1["status"] == "partial" and e1["n_scored"] == 12 and len(t.bodies) == 12
    e2 = run_pipeline("single", limit=3, yes=True, pipeline=mk(), root=tmp_path, log=lambda *a: None)
    assert e2["n_scored"] == 15 and len(t.bodies) == 15  # the first 12 were not re-run
    res = json.loads((tmp_path / "results.json").read_text())
    assert res["generated_by"] == "harness/run.py"
    assert res["pipelines"]["single"]["latency"]["warmup_discarded"] == 8  # first 5 of session 1 + all 3 of session 2
    assert (tmp_path / "web" / "runs" / "single.json").exists()


# ---------------------------------------------------------------- MCP server + JS parity
def test_mcp_stdio_handshake_and_tool_call():
    import subprocess
    import sys
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18",
             "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "classify_dispute",
             "arguments": {"text": "I was charged twice for one order", "pipeline": "rules"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "search_policy",
             "arguments": {"query": "paid in cash and also charged", "k": 2}}}]
    p = subprocess.run([sys.executable, str(ROOT / "mcp_server.py")], input="\n".join(json.dumps(m) for m in msgs),
                       capture_output=True, text=True, timeout=60, env={"RAG_RETRIEVAL": "bm25", "PATH": ""})
    out = [json.loads(l) for l in p.stdout.splitlines()]
    assert [o["id"] for o in out] == [1, 2, 3, 4]  # notification got no reply
    assert out[0]["result"]["protocolVersion"] == "2025-06-18"
    assert {t["name"] for t in out[1]["result"]["tools"]} >= {"classify_dispute", "search_policy", "get_results"}
    assert json.loads(out[2]["result"]["content"][0]["text"])["pred"] == "duplicate_processing"
    assert "R4" in out[3]["result"]["content"][0]["text"]


def test_browser_rules_engine_matches_python():
    """The dashboard runs rules.toml in JS; it must agree with the Python engine on every case."""
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not installed")
    import tomllib
    rules = tomllib.loads((ROOT / "pipelines" / "rules.toml").read_text())
    cases, _ = load_eval()
    js = ("const R=" + json.dumps(rules) + ",C=" + json.dumps([c["text"] for c in cases]) + ";"
          "const rs=R.rule.map(r=>({l:r.label,p:r.patterns.map(p=>new RegExp(p,'i'))}));"
          "console.log(JSON.stringify(C.map(t=>{for(const r of rs)for(const p of r.p)if(p.test(t))return r.l;return null})))")
    js_preds = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    py = get_pipeline("rules")
    assert js_preds == [py.classify(c["text"]).label for c in cases]

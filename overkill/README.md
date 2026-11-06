# Overkill

**Rules, one LLM call, RAG, or a multi-agent graph: where does the next step of sophistication pay for itself?**

> DRAFT README. Structure by design; every number and sentence must end up in the owner's own words.
> Numbers below come from `results.json`, never typed by hand.

## The question
Payment disputes have to be sorted into one of nine categories (card-network reason codes) before
anyone can fight them. Four architectures can do it. Which is worth its cost, and at what volume?

## The method
- One task, one eval set, one scoring harness, one model held constant (`llama-3.3-70b-versatile` via Groq).
- Eval set built **before** any pipeline: synthetic-but-grounded disputes in four difficulty tiers
  (clear · paraphrase · policy conflict · stated reason wrong). *Current status: 180-case seed drafted and
  labelled by Claude; blind human relabel pending.*
- Tune on a dev split, report a held-out test split, with 95% Wilson intervals.
- Pipelines return token counts only; the harness times every call and prices every token at list price.

## The four approaches

| | Approach | Test accuracy | Cost / 1k disputes | p95 latency | Automated |
|---|---|---|---|---|---|
| A | Rules engine (v0, untuned) | **49.6%** (41–58%) | $0 | 0.11 ms | 65% |
| B | Single LLM call | not run yet | | | |
| C | RAG (BM25 + pgvector hybrid) | not run yet | | | |
| D | Classifier → verifier → arbiter | not run yet | | | |

Rules by tier: clear 81% · paraphrase 29% · policy conflict 44% · stated-reason-wrong 17%.

## The finding
*(Owner writes this in two sentences once all four have run.)*

## What I would do differently
*(Owner writes this.)*

---

**Run it:** `python run_eval.py -p rules` · `python serve.py` → http://localhost:8000 · `python -m pytest -q`
**Learn it:** [LEARN.md](LEARN.md) · **Why it's built this way:** [DECISIONS.md](DECISIONS.md) · **Rules for AI assistants:** [CLAUDE.md](CLAUDE.md)

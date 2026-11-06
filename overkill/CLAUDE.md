# Overkill

Four pipelines classify payment disputes into 9 categories.
The deliverable is the comparison, not the pipelines.

## Hard constraints
- One model for all pipelines: llama-3.3-70b-versatile via Groq. Never swap.
- One vector store: pgvector. Do not add another. (The in-memory cosine search in
  `pipelines/retrieval.py` is an offline test double with the same interface, not a second store.)
- Pipelines return token counts only. The harness owns timing and pricing.
- Never edit data/eval.jsonl. Labels are frozen. Only `tools/label.py freeze` may create it.
  `data/eval.seed.jsonl` is a Claude-drafted seed; it is used only until eval.jsonl exists.
- Never write numbers into results.json by hand. Only `harness/run.py` writes it.
- Free tiers only. Flag anything that would incur cost.
- Tune on the dev split only (`--split dev`). Report the test split.

## Style
- Standard library first. Justify every new dependency in DECISIONS.md.
- No framework where 30 lines would do.

## Ownership — who must be able to defend it in an interview
Owner writes (Claude may draft, marked DRAFT, owner rewrites):
eval labels, the nine category definitions, `pipelines/rules.toml`, every prompt in
`pipelines/prompts.py`, the agent graph's nodes + conditional edge, every number and
sentence in README.md.

Delegate freely: clients, retries, backoff, file IO, cost table maths, scoring,
pgvector setup, dashboard wiring, tests, refactors.

## Working rules
- One pipeline per session: "read CLAUDE.md and results.json, then build pipeline C only."
- One pipeline per run: `python run_eval.py --pipeline rules`
- After every real choice, add one line to DECISIONS.md.
- Run `python -m pytest -q` before committing.

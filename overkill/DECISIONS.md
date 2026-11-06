# Decisions

One line per real choice. ✍ = a judgement call the owner must revisit and own before an interview.

## Method
- Eval seed: 180 cases (20/category) at 40/35/15/10 clear/paraphrase/conflict/contradictory. ✍ Extend to 420 and relabel blind; below 200, differences stop meaning much.
- Dev/test split by sha256(id), 30% dev. Tune on dev, report test. Deterministic, no file to maintain.
- Accuracy is strict: an abstention is never correct. Automation rate and accuracy-when-automated are reported separately.
- 95% intervals are Wilson score intervals: honest at n≈130, where the normal approximation isn't.
- Latency: first 5 measured calls of each session discarded as warm-up; p50/p95 by linear interpolation.
- Tokens priced at Groq list price ($0.59/$0.79 per 1M, read 2026-11-06) although the free tier bills $0: compare production cost, not build cost.
- Per-case checkpoint keyed by (pipeline fingerprint, text hash): a crash costs nothing; an unchanged pipeline re-runs free; history of every variant kept.
- Fixed monthly costs are labelled assumptions with a basis string: rules $400 (maintenance), single $0, rag $25 (managed Postgres), agents $50 (+ tracing). ✍

## Pipelines
- Rules in TOML, not YAML: tomllib is stdlib in 3.11, zero dependency, same "someone edits this forever" argument.
- Rules v0 written from definitions, not tuned on the eval set; unmatched → human queue (abstain). v0 = 49.6% test. ✍ Tune on dev to plateau.
- Rules order by estimated precision: recurring > duplicate > credit > processing > unauthorised > amount > service > not-received > quality. ✍
- Single/RAG/agent-classifier share one system prompt + tool schema, so the comparison measures architecture, not prompt craft. ✍ Prompts are drafts.
- Output forced via tool_choice + enum; anything else is a counted parse_error, not a guess. One retry on Groq's tool_use_failed.
- Zero-shot first; few-shot later as a measured delta.
- Policy chunked by document (one `##` section = one rule, 60–150 words); never by token count.
- Hybrid retrieval = BM25 + dense fused by RRF (k=60). Embeddings: bge-small-en-v1.5 via fastembed (local, $0, no torch). Never swap the embedding model.
- pgvector with no ANN index: 46 rows, exact scan is exact and faster. HNSW past ~10k rows.
- In-memory cosine scan is a test double for offline dev, not a second vector store; results.json records which store ran.
- No psycopg pgvector adapter: vectors passed as text literals cast to ::vector.
- Agents: classifier → verifier → arbiter only on reject. Arbiter abstains below τ=0.6. Verifier parse failure = reject (safe side). ✍
- Own 40-line StateGraph mirroring LangGraph's API instead of the dependency: one-import swap when checkpointing/streaming is needed. ✍
- Retrieval attribution: hit = any retrieved doc speaks about the gold category; errors split into retrieval-missed vs model-ignored.

## Infra
- Groq client on urllib, not the SDK: the SDK retries silently, hiding retries from measurement. Backoff honours retry-after; TPD/RPD 429 stops the run cleanly.
- Client-side sliding-window limiter (RPM/TPM) instead of collecting 429s.
- Langfuse via its public ingestion API (stdlib), exported after the timed region; failures never break a run. Untested against a live account.
- MCP server hand-written on stdio JSON-RPC (stdlib): readable, no SDK version drift.
- serve.py binds 127.0.0.1 only: it spends the owner's API quota.

## Dashboard
- Static site reading results.json; harness copies data into web/ after every run, so Vercel needs no backend.
- Pipelines A→D encoded as one-hue ordinal ramp (light→dark = cheap→sophisticated), validated with the dataviz validator in both modes. 4-hue categorical failed the all-pairs gate for the scatter.
- Rules engine also runs in-browser from the same rules.toml; a test asserts JS/Python parity on every case.
- Autopilot drives the real UI (cursor, typing, clicks, outbox filing) with live or recorded results; it never fabricates a lane result. Docks as a sidebar ≥1200px.
- Cost model uses measured wrong/abstain rates on the test split; error and review costs are user inputs; INR uses lakh/crore ticks.

## v0.2
- Cascade (E) added as a labelled model-mix experiment (8B → 70B+RAG on low confidence), comparable=false, off the ladder; per-model pricing via usage_by_model. ✍ Threshold 0.85 is a placeholder: tune on dev.
- Critic section computes its checks from results.json (no hand-written verdicts); score = pass 1, note 0.5, warn/fail 0.
- Red-team rewrites are deterministic string transforms (no model), so the attack itself costs $0 and is reproducible; rewrites that leave the text unchanged and the "ten words" truncation are not counted.
- Themes restyle chrome only; series colours stay on the ramp validated for the theme's mode.

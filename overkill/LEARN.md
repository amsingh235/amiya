# Overkill: the learning guide

> Read this top to bottom once. Then keep it open while you build. Every section ends with the
> sentence you should be able to say in an interview. If you can't say it yet, that's the part to study.

---

## 0. What is this project, in plain English?

Companies get **payment disputes**: a customer emails "I was charged twice", "my refund never came",
"I don't recognise this charge". Someone has to read each one and put it in the right bucket
(card networks like Visa and Mastercard define these buckets as *reason codes*). Wrong bucket means
wrong evidence and a lost case.

You can automate that sorting four ways, each more sophisticated and more expensive than the last:

| Rung | Approach | Plain English |
|---|---|---|
| A | **Rules engine** | A list of keyword patterns. "charged twice" → Duplicate. No AI. |
| B | **Single LLM call** | Send the message + the 9 definitions to an AI model, get one answer. |
| C | **RAG** | Same, but first *look up* the most relevant policy rules and give them to the model. |
| D | **Multi-agent** | Three AI steps: propose an answer, verify it against policy, arbitrate if they disagree. |

**Overkill measures all four on the same test set** and asks: *is each step up worth what it costs?*
That's the whole project. The pipelines aren't the deliverable. **The comparison is.**

The sentence this project lets you say:

> "I'd start with the cheapest thing that could work, measure it against a labelled set, and only
> escalate where the error cost justifies it. I have the numbers from doing exactly that on dispute triage."

---

## 1. The map: how the pieces fit

```
 data/eval.seed.jsonl ──┐  (180 disputes; becomes data/eval.jsonl after YOU relabel them)
 data/taxonomy.json  ───┤  the 9 categories + definitions
 data/policy/*.md  ─────┤  46 policy documents (RAG reads these)
                        ▼
 pipelines/  rules.py  single.py  rag.py  agents.py      ← four implementations, ONE interface (base.py)
             llm.py (Groq client)  retrieval.py (BM25 + vectors)  graph.py (state machine)  prompts.py
                        │ each returns: label + token counts. Never cost or time.
                        ▼
 harness/    run.py   times every call · prices every token (cost.py) · scores (score.py)
                        │ checkpoints each case to runs/<pipeline>.jsonl
                        ▼
 results.json  ───────► web/  (the dashboard, a static site you deploy on Vercel)
                        ▲
 serve.py      local server: dashboard + live API (try any text against the real pipelines)
 mcp_server.py the same tools for Claude Desktop / Claude Code / any MCP client
 tools/label.py  blind double-pass labelling → data/eval.jsonl
```

**Why one interface?** If every pipeline implements the same `classify(text) -> Result`, no
pipeline can quietly get an easier job. **Why does the harness own timing and pricing?** A pipeline
that reports its own latency can flatter itself. Ours can't: `harness/run.py` wraps every call in
`time.perf_counter()` and prices the tokens the provider *reported*.

> Interview line: "Pipelines return token counts only; the harness owns timing and pricing.
> That's how I kept the benchmark from flattering any one approach."

---

## 2. Run it in five minutes

```bash
cd overkill
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt                          # pytest; fastembed/psycopg are optional

python run_eval.py --pipeline rules      # no key needed, takes a second, writes results.json
python serve.py                          # open http://localhost:8000
python -m pytest -q                      # 21 tests, all offline
```

Then the AI pipelines:

1. Create a free Groq key (no card): https://console.groq.com/keys
2. `cp .env.example .env` and paste the key into `GROQ_API_KEY=`
3. Always estimate first: `python run_eval.py -p single --estimate`
4. Run: `python run_eval.py -p single --yes`

### ⚠ The free-tier reality (read before you start)

Groq's free tier for `llama-3.3-70b-versatile` allows about **100,000 tokens per day** (TPD) and
1,000 requests per day (check yours at console.groq.com/settings/limits). Our estimates for the 180-case seed:

| Pipeline | Calls | Tokens | Days on free tier | Cost at list price |
|---|---|---|---|---|
| Single | 180 | ~143k | **~1.4 days** | ~$0.09 |
| RAG (k=3) | 180 | ~219k | **~2.2 days** | ~$0.13 |
| Agents | ~423 | ~516k | **~5.2 days** | ~$0.31 |

At 420 cases, multiply by 2.3. That's about two weeks of free quota for everything.
The harness handles this for you. It **stops cleanly** at the daily cap, **checkpoints** every case,
and **resumes** next time you run the same command. Your options:

- **Stay free:** run each pipeline a little every day. Fine, because the harness resumes.
- **Pay about $1:** Groq's paid tier would finish every run in under an hour. ⚠ This incurs cost
  (CLAUDE.md says free tiers only), so it's your call, not mine.

> Interview line: "The infra layer I built was the most useful part: backoff that honours
> retry-after, a client-side rate limiter, daily-cap detection, and per-case checkpointing. A crash at
> case 380 costs nothing, and re-running an unchanged pipeline costs nothing."

---

## 3. What's real right now (measured, not typed)

Rules engine **v0** (untuned, written from the definitions only), on the seed set:

| | Value |
|---|---|
| Test accuracy (n=133) | **49.6%** (95% CI 41.3%–58.0%) |
| Dev accuracy (n=47), the split you tune on | 53.2% |
| By tier | clear **80.6%** · paraphrase **28.6%** · policy conflict 44.4% · stated reason wrong 16.7% |
| Automated (a rule fired) | 65%. Accuracy when it fires: 77.8% |
| Latency | p50 0.06 ms · p95 0.11 ms |
| Biggest failure | no pattern fired at all (cancelled-recurring and service-not-rendered paraphrases) |

That is already the story the runbook predicted: **rules match words; disputes are paraphrase.**
Your job is to tune `pipelines/rules.toml` on the **dev split only** until adding patterns stops helping
(the runbook expects a plateau near 60%), then write the plateau down in DECISIONS.md.

B, C and D are built and tested with a fake Groq server (`tests/fakes.py`), but have **not been run
against Groq yet**: this build environment can't reach api.groq.com. Their cards on the dashboard say
"not run" until you run them. No number is ever invented.

---

## 4. The concepts, one at a time

### 4.1 The eval set comes first, and it's labelled blind

**What:** `data/eval.seed.jsonl` holds 180 disputes: 20 per category, mixed 40% clear / 35% paraphrase /
15% policy conflict / 10% stated-reason-wrong (exactly the runbook's mix).

**Honest status:** Claude drafted *and labelled* these as a seed. They're grounded in public
card-network reason codes (Visa 10.4/12.x/13.x, Mastercard 48xx), but the labels are not yours yet.
The dashboard shows a yellow "seed" banner until you fix that.

**Your job (the non-negotiable part):**
1. Rewrite `data/taxonomy.json` definitions in your own words. Lock them.
2. Read, edit and extend the disputes toward 420. Write new ones from consumer-complaint forums and
   network docs. Don't copy precedents from `data/policy/` (a test checks for leakage).
3. `python tools/label.py pass1` labels every case **blind** (you see text only).
4. **A day later:** `python tools/label.py pass2` (different order, blind to pass 1).
5. `python tools/label.py agree` gives your **self-agreement** and Cohen's kappa.
6. `python tools/label.py resolve` settles each disagreement, or drops genuinely ambiguous cases.
7. `python tools/label.py freeze` writes `data/eval.jsonl`. From then on it's frozen and the harness uses it.
8. Re-run every pipeline (fingerprints change, so old rows are ignored automatically).

**Why blind and twice:** if you label after building pipelines you unconsciously write cases your
pipelines pass, and the eval becomes a certificate instead of a measurement. Your self-agreement
(say 96%) is the **ceiling**. No pipeline can meaningfully beat the consistency of its own labels.
The dashboard draws it as a dashed line.

**Dev/test split:** each case is assigned dev (30%) or test (70%) by a hash of its id
(`harness/data.py`). You **tune** rules, prompts and k on dev, and **report** test. Tuning on the
numbers you report is overfitting, and an interviewer will ask.

**Confidence intervals:** with ~130 test cases, a 95% Wilson interval is about ±8 points.
So "RAG 86% vs single 84%" is **noise**, not a finding. Say that before they do.

> Interview line: "I labelled before any pipeline existed, twice, a day apart. My self-agreement was X%,
> which is the ceiling. Differences under about 8 points on my test split are within the interval, so I don't claim them."

### 4.2 The difficulty tiers explain *why* each approach fails

| Tier | Example | Who should win |
|---|---|---|
| clear | "I was charged twice for the same order" | everyone |
| paraphrase | "the café's ₹340 shows up two times, same timestamp" | rules die here (no keyword) |
| policy conflict | "concert cancelled, organiser promised a refund, nothing came" (service? or credit?) | **RAG**: precedence rule R2 decides |
| stated reason wrong | "Duplicate charge! My gym billed me again after I cancelled" | **agents**: the verifier checks facts vs stated reason |

The 10 precedence rules in `data/policy/precedence.md` (R1–R10) are what make "policy conflict" cases
decidable. Read them; you'll be asked to defend them.

### 4.3 Rung A: the rules engine (`pipelines/rules.py`, `rules.toml`)

- Patterns are **regular expressions** per category, matched case-insensitively. **First match wins**,
  so order matters: most precise categories first.
- **No match → human queue** (an abstention). It counts as *not correct* for accuracy, and lowers
  the **automation rate**. That's what a real rules engine does.
- Patterns live in **TOML**, not Python. Python 3.11 reads TOML with the standard library (`tomllib`),
  so there's no YAML dependency. The file *is* the maintenance argument: someone edits it forever.
  That's why its fixed monthly cost ($400, an **assumption**) is the highest of the four.
- The dashboard runs the **same rules.toml in your browser** (a test checks that JS and Python give
  identical labels on all 180 cases).

> Interview line: "I tuned the rules properly, not as a straw man, on dev only, until it plateaued at X%.
> Rules match words; disputes are paraphrase. That's the ceiling, not lack of effort."

### 4.4 Rung B: one LLM call (`pipelines/single.py`, `prompts.py`)

Three things decide whether this lands near 87% or near 70%:
1. **Forced output format:** we pass a *tool schema* whose `category` field is an **enum** of the 9 ids,
   and set `tool_choice` so the model *must* call it. No free-text parsing.
   Anything outside the enum is recorded as `parse_error`: **counted, never hidden or guessed**.
2. **Definitions in the prompt**, not just names. The model can't tell "service not rendered" from
   "product not received" without them.
3. **Zero-shot first.** Measure, then add few-shot examples and report the delta. The harness keeps
   every configuration in `history` (the "Tuning record" on the dashboard), so before/after is on record.

**The gap between A and B is the most valuable number in the project.** It tells a client whether AI
is worth starting at all. **Week-2 checkpoint:** if the gap is under 10 points, your eval set is too easy.
Add harder paraphrase cases before building anything else. The dashboard warns you automatically.

### 4.5 Tokens, cost and latency (`harness/cost.py`, `harness/score.py`)

- **Tokens:** the provider reports `prompt_tokens` and `completion_tokens` for every call. We sum them
  per case. The tool schema also counts as prompt tokens, which is why prompts look "bigger" than their text.
- **Price:** $0.59 per 1M input tokens and $0.79 per 1M output tokens (read 2026-11-06; confirm on
  groq.com/pricing). The free tier bills $0, but we **price at list price** so the comparison shows
  production cost.
- **Cost per 1k disputes** = average cost per case × 1,000. Small numbers, big volumes.
- **Latency:** p50 (median) and **p95** (95% of calls are faster than this). The first 5 calls of each
  session are discarded as warm-up.

> Interview line: "Mean latency hides the tail, and the tail is what breaks an SLA."

### 4.6 Rung C: RAG (`pipelines/rag.py`, `retrieval.py`)

**RAG = Retrieval-Augmented Generation:** search a document store for the most relevant passages,
put them in the prompt, then generate.

- **Corpus:** 46 short documents: per category a definition with qualifying conditions, an evidence
  and exclusions doc, and two worked precedents, plus the 10 precedence rules. A thin corpus makes RAG
  score the same as a single call. That's a failed *corpus*, not a failed pipeline.
- **Chunk by document, not by token count.** Each `## section` is one coherent rule (60–150 words).
  Fixed 512-token chunks would cut conditions away from the rule they qualify. *Say why you didn't
  chunk by token count; that answer distinguishes you.*
- **BM25** is classic keyword scoring (term frequency × rarity, with length normalisation). Written
  in about 30 lines of Python, it catches exact terms like "chargeback", amounts and merchant names.
- **Embeddings** turn text into vectors; similar meaning → nearby vectors (cosine similarity). We use
  `BAAI/bge-small-en-v1.5` locally via `fastembed` (free, CPU, no torch). Don't swap embedding models;
  it's a rabbit hole with small returns.
- **pgvector** is a Postgres extension that stores vectors and searches them with SQL (`<=>` is the cosine
  distance operator). Setup: create a free Supabase project, enable the `vector` extension, put
  `DATABASE_URL` in `.env`, then run `python tools/ingest_pgvector.py`. No index on purpose: at 46 rows an
  exact scan is exact and faster (add HNSW past ~10k rows).
- **Hybrid search** = run both, combine with **Reciprocal Rank Fusion**: `score = Σ 1/(60 + rank)`.
  Without fastembed installed, RAG runs BM25-only and **results.json records that**.
- **Tune in this order, on dev, measuring after each:** k ∈ {1, 3, 5, 8} (there's a peak, then more
  context distracts) → hybrid vs BM25-only → reranking (cut first if short on time).
  Set k with `RAG_K=5 python run_eval.py -p rag --split dev`.
- **Retrieval attribution:** for every wrong answer we check whether any retrieved doc spoke about the
  correct category. *Retrieval missed* (fix: search) vs *model ignored good context* (fix: prompt).
  The dashboard shows both counts. Almost nobody separates these.

### 4.7 Rung D: multi-agent (`pipelines/agents.py`, `graph.py`)

```
START → classifier ─ok→ verifier ─accept→ END
            │                └─reject→ arbiter → END (label, or human_review)
            └─unparsed→ END (human_review)
```

- **Classifier:** RAG plus a `runner_up` and a confidence.
- **Verifier:** fetches the policy *for the proposed category only* and checks its qualifying
  conditions. It can **reject**, naming the failed condition and the category policy points to.
- **Arbiter:** runs **only when the verifier rejects**. That conditional edge is the whole design.
  An unconditional three-call chain is a long prompt, not a multi-agent system, and costs roughly 40% more.
- **Human review is a real outcome.** If the arbiter can't decide, or its confidence is below
  τ=0.6 (`AGENT_HUMAN_THRESHOLD`), the case goes to a human. We count **resolved automatically /
  routed to human / wrong** separately. *Automation rate* is the number an operations leader cares about.
- **Why our own 40-line graph instead of LangGraph?** Three nodes and one conditional edge don't need
  a framework (CLAUDE.md rule). `graph.py` mirrors LangGraph's API exactly (`add_node`, `add_edge`,
  `add_conditional_edges`, `compile`, `invoke`), so switching is one import:
  `from langgraph.graph import StateGraph, START, END`. Being able to explain both is the senior answer.
- **Verbalised confidence is poorly calibrated.** That's why the verifier exists: it checks *facts*,
  not the model's opinion of itself.
- **Tracing:** every step (node, tokens, verdict, docs) is stored in `runs/agents.jsonl` and drawn on the
  dashboard. Add `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` to `.env` for hosted waterfalls in Langfuse Cloud
  (free). Export happens *after* the timed region, so upload time never counts as latency.
  ⚠ The Langfuse exporter uses their public ingestion API and is untested against a live account; check one trace after your first run.

> The finding to expect (and say plainly): "Agents bought ~1–2 points over RAG for several times the
> token spend and roughly 4× the latency. Here is the volume and error-cost combination where that's worth it."

### 4.8 The cost model: where the money conversation happens

Section "What it costs to be right" on the dashboard:

```
monthly cost = fixed infra + volume × (token cost per case
                                       + wrong-rate × cost of a wrong auto-decision
                                       + abstain-rate × cost of a human review)
```

Accuracy, abstention and tokens are **measured**. Fixed infra is an **assumption** (each pipeline
states its basis; change them in the pipeline classes). Error and review costs are **the client's
numbers**. Move the sliders, switch to ₹ (lakh/crore ticks), read the break-even points.
At high error cost, accuracy wins. At low volume, fixed cost wins. That's the trade-off you sell.

### 4.9 Autopilot: the "computer use" button

Flip **Autopilot** in the top bar and the agent takes the mouse. A cursor moves across the console:
it opens disputes from the inbox, types them into the workbench, **finds** relevant policy (BM25 in the
browser), runs all four pipelines, follows the agent graph's path, decides, and **files** each case
into the Outbox (auto-resolved / human review / mismatch). Then you export the triage as CSV or JSON.
With `serve.py` running, filed cases are also written to `outbox/triage-<date>.jsonl` on disk.

Two missions: **triage the inbox** (one case per difficulty tier) and **hunt failure modes** (finds
cases where pipelines disagree with the label or with each other, and explains which rule fired).
Esc or the toggle gives control back. On wide screens the log docks on the right so it never covers
what the agent is clicking.

**What it is and isn't:** it operates *this console*, using real pipelines (live via `serve.py` + key)
or their recorded runs. It doesn't control your operating system. For true desktop computer use,
connect `mcp_server.py` to an agent that has computer-use tools (next section). Then that agent can
call `classify_dispute`, `search_policy`, `get_results` and `get_case` as tools.

### 4.10 MCP: plugging Overkill into any AI assistant

**MCP (Model Context Protocol)** is a standard way for AI apps to call external tools. Our
`mcp_server.py` speaks it over stdin/stdout as JSON-RPC 2.0 (`initialize` → `tools/list` →
`tools/call`), using only the standard library, so you can read every line of the protocol.

```bash
claude mcp add overkill -- python /absolute/path/to/overkill/mcp_server.py      # Claude Code
```
Claude Desktop → `claude_desktop_config.json`:
```json
{"mcpServers": {"overkill": {"command": "python", "args": ["/absolute/path/to/overkill/mcp_server.py"]}}}
```
Then ask: *"Use overkill to classify: 'I paid the plumber by transfer and he charged my card too'"* or
*"Summarise the overkill results and tell me which pipeline a 50k/month client should use."*

---

## 4.11 New in v0.2: critic, red team, cascade, themes, tutorial

- **The skeptical reviewer** (dashboard section *Critic*): every check an interviewer would run, computed live
  from results.json, with an interview-readiness score. Seed labels = FAIL; overlapping intervals = "inside the
  noise"; tiny tiers, dev≫test, partial/stale runs, parse errors, stale prices. Fix the reds before quoting numbers.
- **⚡ Red-team it** (console): attacks the current dispute with 8 rewrites (typo storm, Hinglish code-mix,
  keyword-free rewording, SMS-speak, ALL-CAPS rage, buried in small talk, wrong stated reason, ten words) and
  shows which pipeline breaks. Rules run in-browser; with `serve.py` + key the single call is attacked too.
  **Export as eval drafts** downloads the rewrites *unlabelled*: label them blind before adding them to the set.
  Autopilot red-teams one paraphrase case per mission.
- **E · Cascade** (`pipelines/cascade.py`): `llama-3.1-8b-instant` answers first; below `CASCADE_THRESHOLD`
  confidence it escalates to the 70B + RAG. This is the cheapest agentic routing pattern. It mixes models, so it
  is marked `comparable=false` and shown *beside* the ladder, never on it (the CLAUDE.md exception).
  Each model is priced at its own rate ($0.05/$0.08 per 1M for the 8B). Tune the threshold on dev: small-model
  confidence is poorly calibrated. The question it answers: what share escalates, and does accuracy survive?
- **Five themes:** Daylight, Midnight, Aurora, Terminal, Paper (press **T** to cycle). Data colours keep the
  validated ramp of the theme's light/dark mode; themes only restyle surfaces, ink and type.
- **Tutorial** (`web/tutorial.html`): eight chapters with commands, "check yourself" questions and saved progress.

## 5. What YOU must write by hand

The project's value is your ability to defend decisions. Claude drafted the following; each is marked
DRAFT in the file. **Rewrite them yourself:**

- [ ] `data/taxonomy.json` definitions, in your words, then lock them
- [ ] The eval set: edit, extend to 420, label blind twice (`tools/label.py`)
- [ ] `pipelines/rules.toml`: tune on dev until it plateaus; record the plateau
- [ ] `pipelines/prompts.py`: every prompt, every line
- [ ] `pipelines/agents.py`: the node structure and the conditional edge (you may keep them; you must be able to redraw them from memory)
- [ ] `data/policy/precedence.md`: R1–R10 are policy choices. Agree with each or change it.
- [ ] Fixed monthly cost assumptions (`fixed_monthly_usd` in each pipeline)
- [ ] Every number and sentence in README.md

Delegate freely (Claude is fine here): clients, retries, file IO, scoring maths, pgvector setup,
dashboard code, tests, refactors.

**Habit:** after each pipeline runs, ask Claude Code to explain its retrieval or routing decisions
back to you, then argue with it. Where you can't follow the argument is where the interviewer will find the hole.

---

## 6. Your next five weeks

| Week | Do this | Done when |
|---|---|---|
| 1 | Rewrite definitions · extend + relabel the eval set blind (pass1, then pass2 a day later) · freeze | `data/eval.jsonl` exists, self-agreement measured |
| 2 | Tune rules on dev · get a Groq key · run `single` (spread over 2 days on free tier) | Two numbers and the gap written in DECISIONS.md (gap < 10 pts → harder cases) |
| 3 | Supabase + `ingest_pgvector.py` · run `rag` at k=1,3,5,8 on dev · pick k · run test | k chosen with evidence, retrieval attribution read |
| 4 | Langfuse keys · run `agents` · read 10 traces · screenshot one waterfall | automation rate + cost ratio vs RAG known |
| 5 | Pick 4 replay cases · write README · deploy · post | dashboard live, README carries the argument |

**Already done for you:** repo, harness, all four pipelines, client and infra, scoring, dashboard,
Autopilot, MCP server, labelling tool, 21 tests, one real measured pipeline.

**Deploy (Vercel, free):** import the GitHub repo into Vercel → set **Root Directory** to `overkill/web`
→ Framework: *Other* → Deploy. `run_eval.py` re-publishes `web/` after every run, so commit and push
to update the live page. It's static, so it's never "down" when a recruiter opens it.

---

## 7. Interview questions you will get (fill in your numbers)

1. **Why test rules first?** Cheapest thing that could work; it sets the floor that gives every other number meaning.
2. **How do I know your labels are right?** Blind, twice, a day apart, self-agreement X%; disagreements resolved by policy or dropped.
3. **Did you tune on your test set?** No: a hash-based dev/test split; tuning on dev, reporting test.
4. **Is 86 vs 84 a real difference?** At n≈130 the 95% interval is about ±8 pts; no. Here's what *is* significant…
5. **Why chunk by document?** Each rule is a coherent unit; token chunks split conditions from their rule.
6. **Why hybrid search?** Disputes contain exact terms (amounts, "chargeback") that BM25 catches and embeddings blur.
7. **When RAG was wrong, why?** Retrieval missed N times, model ignored good context M times: different fixes.
8. **Why not Qdrant or Pinecone?** One vector store; pgvector lives in the Postgres I already have. A second store adds a logo and subtracts credibility.
9. **Is your multi-agent system just a chain?** No: the arbiter only runs on rejection (conditional edge); that's ~40% cheaper than an unconditional chain.
10. **Why not LangGraph?** Three nodes don't need a framework; my graph mirrors its API, so it's a one-line swap when I need checkpointing.
11. **How did you handle rate limits?** Client-side limiter, backoff honouring retry-after, daily-cap detection, checkpoint/resume.
12. **What would you build for us?** The sentence in section 0, plus the cost model with *their* volume and error cost.

---

## 8. Turning this into money (an *AI Build Decision Review*)

Sell **the method, not the tool**. Nobody buys a dispute benchmark. People pay for the answer to
*"are we about to overspend on AI, and how would we know?"* Overkill is your proof you can answer it.

**How this repo becomes a client deliverable (2 weeks):**
1. Replace `data/taxonomy.json` + `data/policy/` with *their* categories and policy (support tickets, KYC flags, lead routing: any classification task).
2. Build 100–200 labelled cases with their team using `tools/label.py` (their people label blind, so self-agreement is measured on *their* data).
3. Run the rungs cheapest-first with `run_eval.py`.
4. Set the cost model to their volume, error cost and review cost (₹ toggle), and read the break-even.
5. Deploy their dashboard (Vercel, free) as the live artifact for their CFO. Add a one-page recommendation.

**Pricing anchors (from your runbook; test them, don't trust them):** first two engagements
₹20k–30k for a named testimonial; after two case studies ₹60k–1.2L per review; optional oversight
₹25k–40k/month, capped at 3 months. Anchor the price against the overbuild you prevent, not your hours.

**Before taking money:** read your internship agreement's outside-work and IP clauses (you said
you've checked; keep it in writing). Keep Overkill free of any employer data, code or time.
In every engagement note, state plainly that you measure and recommend; you don't guarantee production accuracy.

---

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| Dashboard says "couldn't load data files" | You opened `index.html` as a file. Run `python serve.py`. |
| `GROQ_API_KEY is not set` | `cp .env.example .env`, paste the key |
| Run stops with "daily limit reached" | Expected on the free tier. Run the same command tomorrow; it resumes. |
| RAG says `mode: bm25` | `pip install fastembed` for hybrid (first run downloads ~70 MB of model) |
| `results.json` shows "stale" | You changed the eval set. Re-run each pipeline. |
| Tests fail after editing policy docs | A precedent may share 7+ words with an eval case (leakage test). Reword it. |
| Want to re-run from scratch | `--fresh` ignores checkpoints (costs tokens again) |

## 10. Glossary

**Abstain:** the system declines to decide and routes to a human. **Automation rate:** share decided
without a human. **BM25:** keyword relevance scoring. **Checkpoint:** saving progress per case.
**Confusion matrix:** true category (rows) vs predicted (columns). **Embedding:** a vector representing
meaning. **Fingerprint:** hash of a pipeline's config; changes invalidate old results. **Few-shot:**
examples in the prompt. **MCP:** Model Context Protocol, a standard for AI tool calling. **p95:** the
latency 95% of calls beat. **pgvector:** vectors inside Postgres. **RAG:** retrieve, then generate.
**RRF:** Reciprocal Rank Fusion. **Self-agreement:** how often your two blind labelling passes agree.
**TPD/RPD/TPM/RPM:** tokens/requests per day/minute. **Wilson interval:** an honest confidence
interval for a proportion at small n.

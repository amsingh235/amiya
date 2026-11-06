"""The harness: loads the eval set, runs ONE pipeline, times every call, prices every token, scores,
and writes results.json. Nothing else is allowed to write results.json.

Resilience (free tiers WILL rate-limit you):
  * checkpoint: every case is appended to runs/<pipeline>.jsonl the moment it finishes
  * resume: re-running skips cases already done with the same pipeline fingerprint + same text,
    so a crash at case 380 costs nothing and an unchanged pipeline re-runs for free
  * daily caps: on a TPD/RPD 429 the run stops cleanly; run the same command tomorrow
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import time
import uuid
from pathlib import Path

from pipelines import CATEGORY_NAMES, MODEL, PIPELINE_IDS, get_pipeline
from pipelines.base import ROOT, TAXONOMY
from pipelines.llm import DailyLimitReached, MissingKey, load_env

from . import tracing
from .cost import call_cost, cost_of, free_tier_limits, pricing_block
from .data import load_eval
from .score import cost_stats, latency_stats, summarize

WARMUP = 5  # discard the first five measured calls of each session from latency stats


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a half-written last line after a crash
    return rows


def current_rows(path: Path, fingerprint: str, cases: list[dict]) -> dict[str, dict]:
    shas = {c["id"]: text_sha(c["text"]) for c in cases}
    done = {}
    for r in read_rows(path):
        if r.get("fp") == fingerprint and shas.get(r["id"]) == r.get("text_sha"):
            done[r["id"]] = r
    return done


def preflight(pipe, todo: list[dict]) -> dict:
    """Planning estimate from characters (chars/4). Reported cost always uses measured tokens."""
    calls = tokens = 0.0
    for c in todo:
        k, t = pipe.estimate_tokens(c["text"])
        calls += k
        tokens += t
    lim = free_tier_limits()
    out_tokens = 60 * calls
    return {"cases": len(todo), "calls": round(calls), "tokens": round(tokens),
            "est_cost_usd_at_list_price": round(call_cost(int(tokens - out_tokens), int(out_tokens)), 4),
            "minutes_at_rpm_tpm": round(max(calls / lim["RPM"], tokens / lim["TPM"]), 1),
            "days_at_free_tier": round(max(calls / lim["RPD"], tokens / lim["TPD"]), 2), "limits": lim}


def history(path: Path, cases: list[dict]) -> list[dict]:
    """Accuracy per configuration ever run (k=1 vs k=3, zero-shot vs few-shot...): your tuning record."""
    gold = {c["id"]: c for c in cases}
    shas = {c["id"]: text_sha(c["text"]) for c in cases}
    by_fp: dict[str, dict] = {}
    for r in read_rows(path):
        if shas.get(r["id"]) != r.get("text_sha"):
            continue
        h = by_fp.setdefault(r["fp"], {"fingerprint": r["fp"], "variant": r.get("variant"), "rows": {},
                                       "first_run": r.get("ts")})
        h["rows"][r["id"]] = r
    out = []
    for h in by_fp.values():
        rows = list(h.pop("rows").values())
        dev = [r for r in rows if gold[r["id"]]["split"] == "dev"]
        test = [r for r in rows if gold[r["id"]]["split"] == "test"]
        h.update({"n": len(rows),
                  "dev_accuracy": summarize(dev, gold)["accuracy"] if dev else None,
                  "test_accuracy": summarize(test, gold)["accuracy"] if test else None,
                  "cost_per_1k_usd": cost_stats(rows)["cost_per_1k_usd"]})
        out.append(h)
    return out


def build_entry(pipe, rows: list[dict], cases: list[dict], meta: dict, path: Path) -> dict:
    gold = {c["id"]: c for c in cases}
    by_split = {s: [r for r in rows if gold[r["id"]]["split"] == s] for s in ("dev", "test")}
    cfg = pipe.config()
    summary_cfg = {k: v for k, v in cfg.items() if k in ("k", "few_shot", "retrieval", "human_threshold", "edges")}
    if pipe.id == "rules":
        summary_cfg["patterns"] = sum(len(p) for _, p in pipe.rules)
    trace = next((r.get("trace_url") for r in rows if r.get("trace_url")), None)
    return {
        "id": pipe.id, "name": pipe.name, "short": pipe.short, "uses_llm": pipe.uses_llm,
        "status": "complete" if len(rows) == len(cases) else "partial",
        "n_scored": len(rows), "n_total": len(cases), "eval_sha": meta["sha"],
        "fingerprint": pipe.fingerprint(), "variant": pipe.variant(), "run_at": now_iso(),
        "model": " + ".join(cfg["models"]) if "models" in cfg else (MODEL if pipe.uses_llm else None),
        "comparable": getattr(pipe, "comparable", True),
        "escalation_rate": (round(sum(1 for r in rows if (r.get("meta") or {}).get("escalated")) / len(rows), 4)
                            if any("escalated" in (r.get("meta") or {}) for r in rows) else None),
        "headline_split": "test",
        "metrics": {"all": summarize(rows, gold), "test": summarize(by_split["test"], gold),
                    "dev": summarize(by_split["dev"], gold)},
        "latency": latency_stats(rows),
        "cost": cost_stats(rows),
        "fixed_monthly_usd": pipe.fixed_monthly_usd,
        "fixed_monthly_basis": pipe.fixed_monthly_basis,
        "config": summary_cfg,
        "history": history(path, cases),
        "langfuse_trace": trace,
    }


def write_results(entry: dict, meta: dict, root: Path = ROOT) -> dict:
    path = root / "results.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    data.update({"schema": 1, "generated_at": now_iso(), "generated_by": "harness/run.py",
                 "model": MODEL, "pricing": pricing_block(), "eval_set": meta,
                 "taxonomy": [{"id": c["id"], "name": c["name"]} for c in TAXONOMY["categories"]]})
    pipes = data.setdefault("pipelines", {})
    pipes[entry["id"]] = entry
    data["pipelines"] = {pid: pipes[pid] for pid in PIPELINE_IDS if pid in pipes}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def publish(root: Path = ROOT) -> None:
    """Copy everything the static dashboard needs into web/, so Vercel never needs a backend."""
    web = root / "web"
    (web / "data").mkdir(parents=True, exist_ok=True)
    (web / "runs").mkdir(parents=True, exist_ok=True)
    results = root / "results.json"
    if results.exists():
        shutil.copyfile(results, web / "results.json")
        data = json.loads(results.read_text())
        for pid, entry in data.get("pipelines", {}).items():
            rows = {r["id"]: r for r in read_rows(root / "runs" / f"{pid}.jsonl") if r.get("fp") == entry["fingerprint"]}
            slim = {i: {k: r.get(k) for k in ("pred", "abstain_reason", "tokens_in", "tokens_out", "calls",
                                               "cost_usd", "latency_ms", "meta")} for i, r in rows.items()}
            (web / "runs" / f"{pid}.json").write_text(json.dumps(slim, ensure_ascii=False), encoding="utf-8")
    cases, meta = load_eval(root)
    keep = ("id", "text", "label", "difficulty", "split", "notes")
    (web / "data" / "cases.json").write_text(json.dumps(
        {"meta": meta, "cases": [{k: c.get(k) for k in keep} for c in cases]}, ensure_ascii=False), encoding="utf-8")
    from pipelines.retrieval import load_policy
    (web / "data" / "policy.json").write_text(json.dumps(
        [d.__dict__ for d in load_policy(root / "data" / "policy")], ensure_ascii=False), encoding="utf-8")
    import tomllib
    rules = tomllib.loads((root / "pipelines" / "rules.toml").read_text(encoding="utf-8"))
    (web / "data" / "rules.json").write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
    (web / "data" / "taxonomy.json").write_text(json.dumps(TAXONOMY, ensure_ascii=False), encoding="utf-8")
    (web / "data" / "kb.json").write_text(json.dumps(kb_from_markdown(root / "LEARN.md"), ensure_ascii=False), encoding="utf-8")


def kb_from_markdown(path: Path) -> list[dict]:
    """Split the guide into small retrievable blocks for Nyay: one paragraph, bullet, table row
    (with its header) or command block per doc, titled by its section."""
    import re
    if not path.exists():
        return []
    docs: list[dict] = []
    section, block, header, in_code, code = "Overview", [], None, False, []

    def emit(text: str) -> None:
        text = " ".join(text.split())
        if section.lower() == "glossary" and text.count("**") > 2:  # one definition per doc
            for part in re.split(r"(?=\*\*[^*]+:\*\*)", text):
                if part.strip():
                    docs.append({"id": f"glossary-{len(docs)}", "title": "Glossary", "text": part.strip()})
            return
        if len(text) >= 40:
            slug = re.sub(r"[^a-z0-9]+", "-", section.lower()).strip("-")
            docs.append({"id": f"{slug}-{len(docs)}", "title": section, "text": text[:900]})

    def flush() -> None:
        nonlocal block
        if block:
            emit(" ".join(block))
        block = []

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            if in_code:
                emit("Commands: " + " ; ".join(c for c in code if c.strip()))
                code = []
            in_code = not in_code
            continue
        if in_code:
            code.append(line.strip())
            continue
        m = re.match(r"^#{2,3}\s+(.*)", line)
        if m:
            flush()
            section, header = re.sub(r"^[\d.]+\s*", "", m.group(1)).strip(), None
            continue
        if line.strip().startswith("|"):
            flush()
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c):
                continue
            if header is None:
                header = cells
            else:
                emit(" · ".join(f"{h}: {c}" if h else c for h, c in zip(header, cells)))
            continue
        if not line.strip():
            header = None
            flush()
            continue
        if line.strip() == "---":
            flush()
            continue
        if re.match(r"^\s*([-*]|\d+\.)\s+", line):
            flush()
            line = re.sub(r"^\s*([-*]|\d+\.)\s+(\[ \]\s*)?", "", line)
        block.append(line.strip().lstrip("> "))
    flush()
    return docs


def run_pipeline(pid: str, *, split: str = "all", limit: int | None = None, fresh: bool = False,
                 yes: bool = False, pipeline=None, root: Path = ROOT, log=print) -> dict:
    load_env(root / ".env")
    cases, meta = load_eval(root)
    pipe = pipeline or get_pipeline(pid)
    fp, variant = pipe.fingerprint(), pipe.variant()
    runs_path = root / "runs" / f"{pid}.jsonl"
    runs_path.parent.mkdir(exist_ok=True)
    done = {} if fresh else current_rows(runs_path, fp, cases)
    todo = [c for c in cases if c["id"] not in done and split in ("all", c["split"])]
    if limit:
        todo = todo[:limit]

    log(f"\n▶ {pipe.name}  [{variant}]  fingerprint {fp}")
    log(f"  eval set: {meta['file']} ({meta['status']}, n={meta['n']})  ·  cached: {len(done)}  ·  to run: {len(todo)}")
    if pipe.uses_llm and todo:
        plan = preflight(pipe, todo)
        log(f"  plan: ~{plan['calls']} calls, ~{plan['tokens']:,} tokens, ≈${plan['est_cost_usd_at_list_price']} at list price "
            f"(free tier: $0) · ≥{plan['minutes_at_rpm_tpm']} min at RPM/TPM · {plan['days_at_free_tier']} days of free-tier daily cap")
        if plan["days_at_free_tier"] > 1 and not yes:
            log("  ⚠ more than one day of free-tier quota. Re-run with --yes to proceed; it will stop at the cap "
                "and resume where it left off next time.")
            return {}
        pipe.client  # fail fast with a clear message if GROQ_API_KEY is missing

    session, measured, stopped = uuid.uuid4().hex[:8], 0, None
    t_start = time.perf_counter()
    with runs_path.open("a", encoding="utf-8") as f:
        for i, case in enumerate(todo, 1):
            t0 = time.perf_counter()
            try:
                res = pipe.classify(case["text"])
            except DailyLimitReached as e:
                stopped = f"daily limit reached ({e}). Progress is checkpointed; run the same command later."
                break
            except MissingKey:
                raise
            except Exception as e:  # stop rather than score an infrastructure failure as a wrong answer
                stopped = f"stopped on {type(e).__name__}: {e}. Progress is checkpointed; re-run to resume."
                break
            latency_ms = (time.perf_counter() - t0) * 1000  # harness-owned timing
            row = {"id": case["id"], "text_sha": text_sha(case["text"]), "fp": fp, "variant": variant,
                   "pred": res.label, "abstain_reason": res.abstain_reason,
                   "tokens_in": res.tokens_in, "tokens_out": res.tokens_out, "tokens_cached": res.tokens_cached,
                   "calls": res.calls, "cost_usd": round(cost_of(res), 8),
                   "latency_ms": round(latency_ms, 4), "warmup": measured < WARMUP, "session": session,
                   "trace_id": res.trace_id, "meta": res.meta, "ts": now_iso()}
            measured += 1
            url = tracing.export(pid, case, res, latency_ms, MODEL)  # after the timed region
            if url:
                row["trace_url"] = url
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            done[case["id"]] = row
            if pipe.uses_llm and (i % 10 == 0 or i == len(todo)):
                ok = sum(1 for c in todo[:i] if done[c["id"]]["pred"] == c["label"])
                log(f"  {i}/{len(todo)}  running accuracy {ok / i:.1%}  ·  {time.perf_counter() - t_start:.0f}s")

    if stopped:
        log(f"  ■ {stopped}")
    rows = [done[c["id"]] for c in cases if c["id"] in done]
    if not rows:
        log("  nothing scored yet; results.json unchanged")
        return {}
    entry = build_entry(pipe, rows, cases, meta, runs_path)
    write_results(entry, meta, root)
    publish(root)
    _report(entry, log)
    return entry


def _report(e: dict, log=print) -> None:
    t, d = e["metrics"]["test"], e["metrics"]["dev"]
    log(f"\n  {e['name']} · {e['status']} ({e['n_scored']}/{e['n_total']})")
    log(f"  accuracy  test {fmt(t['accuracy'])}  95% CI {fmt(t['ci95'][0])}–{fmt(t['ci95'][1])}  (n={t['n']})"
        f"   ·  dev {fmt(d['accuracy'])} (n={d['n']}, tune on this)")
    log("  by tier   " + "  ".join(f"{k} {fmt(v['accuracy'])}" for k, v in e["metrics"]["all"]["accuracy_by_difficulty"].items()))
    log(f"  automated {fmt(e['metrics']['all']['automation_rate'])} of cases  ·  accuracy when automated "
        f"{fmt(e['metrics']['all']['auto_accuracy'])}")
    lat, cost = e["latency"], e["cost"]
    log(f"  latency   p50 {lat['p50_ms']} ms  p95 {lat['p95_ms']} ms   ·  cost ${cost['cost_per_1k_usd']}/1k disputes"
        f"  ·  fixed ${e['fixed_monthly_usd']:.0f}/mo (assumption)")
    for c in e["metrics"]["all"]["top_confusions"][:3]:
        log(f"  confuses  {CATEGORY_NAMES.get(c['gold'], c['gold'])} → {CATEGORY_NAMES.get(c['pred'], c['pred'])} ×{c['count']}")
    log("  wrote results.json and published web/\n")


def fmt(x) -> str:
    return "—" if x is None else f"{x:.1%}"


__all__ = ["run_pipeline", "publish", "preflight", "read_rows", "WARMUP"]

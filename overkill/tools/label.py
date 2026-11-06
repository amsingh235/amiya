"""Blind double-pass labelling: the step that makes every later number trustworthy.

    python tools/label.py pass1      label every dispute blind (text only), shuffled
    python tools/label.py pass2      a DAY later: again, different order, blind to pass 1
    python tools/label.py agree      self-agreement + Cohen's kappa; disagreements listed
    python tools/label.py resolve    settle each disagreement: pick one, or drop the case
    python tools/label.py freeze     write data/eval.jsonl (refuses to overwrite: labels are frozen)

Resumable: press q to stop, run the same command later. Where your two passes disagree the case is
genuinely ambiguous: sharpen the policy rule that resolves it, or drop it. Your self-agreement rate is
the ceiling no pipeline can meaningfully beat; the dashboard draws it as a line.

To add your own disputes: append {"id": "d0181", "text": "..."} lines to the source file
(default data/eval.seed.jsonl; label and difficulty are optional there, and never shown to you here).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
import textwrap
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipelines.base import CATEGORIES, TAXONOMY  # noqa: E402

LABELS = ROOT / "data" / "labels"
DIFF_KEYS = {"c": "clear", "p": "paraphrase", "a": "ambiguous", "x": "contradictory"}


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def by_id(p: Path) -> dict[str, dict]:
    return {r["id"]: r for r in read_jsonl(p)}


def ask(prompt: str, valid) -> str:
    while True:
        v = input(prompt).strip().lower()
        if v in valid:
            return v
        print("  ?", ", ".join(sorted(valid)))


def label_pass(n: int, source: Path) -> None:
    cases = read_jsonl(source)
    out = LABELS / f"pass{n}.jsonl"
    done = by_id(out)
    order = [c for c in cases if c["id"] not in done]
    random.Random(n * 7919).shuffle(order)
    menu = "\n".join(f"  {i}  {c['name']:<22} {c['signal']}" for i, c in enumerate(TAXONOMY["categories"], 1))
    LABELS.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        for i, c in enumerate(order, 1):
            print("\033[2J\033[H" + f"Pass {n} · {len(done) + i}/{len(cases)} · blind\n")
            print(textwrap.fill(c["text"], 88) + "\n")
            print(menu)
            k = ask("\ncategory 1-9 (s skip, q quit): ", {str(x) for x in range(1, 10)} | {"s", "q"})
            if k == "q":
                break
            if k == "s":
                continue
            d = ask("difficulty  c clear · p paraphrase · a ambiguous · x contradictory: ", set(DIFF_KEYS))
            f.write(json.dumps({"id": c["id"], "label": CATEGORIES[int(k) - 1], "difficulty": DIFF_KEYS[d],
                                "ts": dt.datetime.now().isoformat(timespec="seconds")}) + "\n")
            f.flush()
    print(f"saved to {out.relative_to(ROOT)}")


def kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(a) | set(b)) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def agree(source: Path) -> None:
    p1, p2 = by_id(LABELS / "pass1.jsonl"), by_id(LABELS / "pass2.jsonl")
    ids = sorted(set(p1) & set(p2))
    if not ids:
        sys.exit("need both passes first")
    a, b = [p1[i]["label"] for i in ids], [p2[i]["label"] for i in ids]
    rate = sum(x == y for x, y in zip(a, b)) / len(ids)
    seed = {c["id"]: c.get("label") for c in read_jsonl(source)}
    vs_draft = [i for i in ids if p1[i]["label"] == p2[i]["label"] and seed.get(i)]
    res = {"self_agreement": round(rate, 4), "kappa": round(kappa(a, b), 4), "n": len(ids),
           "agreement_with_claude_draft": round(sum(seed[i] == p1[i]["label"] for i in vs_draft) / len(vs_draft), 4) if vs_draft else None,
           "computed_on": dt.date.today().isoformat()}
    (LABELS / "agreement.json").write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))
    dis = [i for i in ids if p1[i]["label"] != p2[i]["label"]]
    print(f"\n{len(dis)} disagreements (run `resolve`):")
    for i in dis:
        print(f"  {i}: {p1[i]['label']} vs {p2[i]['label']}")


def resolve(source: Path) -> None:
    texts = {c["id"]: c["text"] for c in read_jsonl(source)}
    p1, p2 = by_id(LABELS / "pass1.jsonl"), by_id(LABELS / "pass2.jsonl")
    out = LABELS / "resolved.jsonl"
    done = by_id(out)
    todo = [i for i in sorted(set(p1) & set(p2)) if p1[i]["label"] != p2[i]["label"] and i not in done]
    with out.open("a", encoding="utf-8") as f:
        for i in todo:
            print("\033[2J\033[H" + textwrap.fill(texts.get(i, "?"), 88))
            print(f"\n  1  pass 1: {p1[i]['label']}\n  2  pass 2: {p2[i]['label']}\n  d  drop the case (too ambiguous)\n  o  other category")
            k = ask("choice (q quit): ", {"1", "2", "d", "o", "q"})
            if k == "q":
                break
            label = {"1": p1[i]["label"], "2": p2[i]["label"], "d": None}.get(k)
            if k == "o":
                label = CATEGORIES[int(ask("category 1-9: ", {str(x) for x in range(1, 10)})) - 1]
            note = input("which policy rule settles it? (optional) ").strip()
            f.write(json.dumps({"id": i, "label": label, "dropped": label is None, "rule": note}) + "\n")


def freeze(source: Path) -> None:
    dest = ROOT / "data" / "eval.jsonl"
    if dest.exists():
        sys.exit(f"{dest.relative_to(ROOT)} exists. Labels are frozen; delete it yourself only if you mean to relabel.")
    p1, p2, rs = by_id(LABELS / "pass1.jsonl"), by_id(LABELS / "pass2.jsonl"), by_id(LABELS / "resolved.jsonl")
    rows, missing, dropped = [], [], 0
    for c in read_jsonl(source):
        i = c["id"]
        if i not in p1 or i not in p2:
            missing.append(i)
            continue
        if p1[i]["label"] == p2[i]["label"]:
            label = p1[i]["label"]
        elif i in rs:
            if rs[i]["dropped"]:
                dropped += 1
                continue
            label = rs[i]["label"]
        else:
            missing.append(i)
            continue
        diff = p2[i]["difficulty"] if p1[i]["difficulty"] != p2[i]["difficulty"] else p1[i]["difficulty"]
        rows.append({"id": i, "text": c["text"], "label": label, "difficulty": diff, "notes": c.get("notes", ""),
                     "labeler": "human-2pass"})
    if missing:
        sys.exit(f"{len(missing)} cases not fully labelled/resolved yet, e.g. {missing[:5]}")
    dest.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"froze {len(rows)} cases ({dropped} dropped) into {dest.relative_to(ROOT)}. Re-run every pipeline.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["pass1", "pass2", "agree", "resolve", "freeze"])
    ap.add_argument("--source", type=Path, default=ROOT / "data" / "eval.seed.jsonl")
    a = ap.parse_args()
    {"pass1": lambda: label_pass(1, a.source), "pass2": lambda: label_pass(2, a.source),
     "agree": lambda: agree(a.source), "resolve": lambda: resolve(a.source), "freeze": lambda: freeze(a.source)}[a.cmd]()


if __name__ == "__main__":
    main()

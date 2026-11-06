"""Load the eval set. data/eval.jsonl (human-labelled, frozen) wins; the Claude-drafted seed is a fallback.

Every case gets a deterministic dev/test split from a hash of its id (30% dev). Tune on dev, report test:
tuning rules, prompts or k on the cases you report is how a benchmark quietly becomes a certificate.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from pipelines.base import CATEGORIES, ROOT

DIFFICULTIES = ["clear", "paraphrase", "ambiguous", "contradictory"]
DEV_PCT = 30


def split_of(case_id: str) -> str:
    return "dev" if int(hashlib.sha256(case_id.encode()).hexdigest()[:8], 16) % 100 < DEV_PCT else "test"


def eval_path(root: Path = ROOT) -> Path:
    frozen = root / "data" / "eval.jsonl"
    return frozen if frozen.exists() else root / "data" / "eval.seed.jsonl"


def load_eval(root: Path = ROOT) -> tuple[list[dict], dict]:
    path = eval_path(root)
    raw = path.read_bytes()
    cases = []
    for i, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        c = json.loads(line)
        if c["label"] not in CATEGORIES:
            raise ValueError(f"{path.name}:{i}: unknown label {c['label']!r}")
        if c.get("difficulty") not in DIFFICULTIES:
            raise ValueError(f"{path.name}:{i}: unknown difficulty {c.get('difficulty')!r}")
        c["split"] = split_of(c["id"])
        cases.append(c)
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path.name}: duplicate ids")

    agreement = None
    agree_file = root / "data" / "labels" / "agreement.json"
    if agree_file.exists():
        agreement = json.loads(agree_file.read_text()).get("self_agreement")
    frozen = path.name == "eval.jsonl"
    meta = {
        "file": str(path.relative_to(root)),
        "sha": hashlib.sha256(raw).hexdigest()[:12],
        "status": "frozen-human" if frozen else "seed-draft",
        "status_note": ("Hand-labelled twice, a day apart; labels frozen." if frozen else
                        "SEED: synthetic-but-grounded disputes drafted and labelled by Claude. "
                        "Not yet blind-relabelled by a human: run tools/label.py."),
        "n": len(cases),
        "categories": len(CATEGORIES),
        "self_agreement": agreement if frozen else None,
        "difficulty_mix": dict(Counter(c["difficulty"] for c in cases)),
        "label_mix": dict(Counter(c["label"] for c in cases)),
        "splits": dict(Counter(c["split"] for c in cases)),
    }
    return cases, meta

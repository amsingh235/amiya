"""Pipeline A: rules engine. Keyword/regex per category, first match wins. No model, no API call.

Unmatched disputes go to a human queue (abstain), which is what a real rules engine does.
They count as wrong for accuracy and as not-automated for automation rate.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

from .base import CATEGORIES, Pipeline, Result

RULES_PATH = Path(__file__).with_name("rules.toml")


class RulesPipeline(Pipeline):
    id = "rules"
    name = "Rules engine"
    short = "Rules"
    fixed_monthly_usd = 400.0
    fixed_monthly_basis = ("ASSUMPTION: ~4 h/month of pattern maintenance at $100/h. "
                           "Someone edits rules.toml forever as wording drifts.")

    def __init__(self, path: Path = RULES_PATH):
        self.path = Path(path)
        self.raw = self.path.read_text(encoding="utf-8")
        cfg = tomllib.loads(self.raw)
        self.version = cfg.get("version", "?")
        self.rules = []
        for rule in cfg["rule"]:
            if rule["label"] not in CATEGORIES:
                raise ValueError(f"rules.toml: unknown label {rule['label']!r}")
            self.rules.append((rule["label"], [re.compile(p, re.IGNORECASE) for p in rule["patterns"]]))

    def config(self) -> dict:
        return {"rules_toml": self.raw}

    def variant(self) -> str:
        return f"{self.version} · {sum(len(p) for _, p in self.rules)} patterns"

    def classify(self, text: str) -> Result:
        for label, patterns in self.rules:
            for pattern in patterns:
                m = pattern.search(text)
                if m:
                    return Result(label=label, meta={"rule": label, "pattern": pattern.pattern,
                                                     "match": m.group(0)[:80]})
        return Result(label=None, abstain_reason="no_rule_matched", meta={"rule": None})

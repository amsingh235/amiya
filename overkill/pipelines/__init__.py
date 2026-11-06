"""Pipeline registry. Import lazily so listing pipelines never needs an API key or fastembed."""
from __future__ import annotations

from .base import CATEGORIES, CATEGORY_NAMES, MODEL, Pipeline, Result

PIPELINE_IDS = ["rules", "single", "rag", "agents"]


def get_pipeline(pid: str, **kwargs) -> Pipeline:
    if pid == "rules":
        from .rules import RulesPipeline
        return RulesPipeline(**kwargs)
    if pid == "single":
        from .single import SinglePipeline
        return SinglePipeline(**kwargs)
    if pid == "rag":
        from .rag import RagPipeline
        return RagPipeline(**kwargs)
    if pid == "agents":
        from .agents import AgentsPipeline
        return AgentsPipeline(**kwargs)
    raise KeyError(f"unknown pipeline {pid!r}; choose from {PIPELINE_IDS}")


__all__ = ["CATEGORIES", "CATEGORY_NAMES", "MODEL", "PIPELINE_IDS", "Pipeline", "Result", "get_pipeline"]

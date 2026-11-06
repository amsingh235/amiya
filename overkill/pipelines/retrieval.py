"""Policy retrieval for pipelines C and D.

Corpus: data/policy/*.md, chunked BY DOCUMENT: every '## ' section is one rule of 60-150 words.
Fixed-size token chunking would cut qualifying conditions away from the rule they qualify.

Search modes (results.json records which one actually ran):
  bm25    keyword scoring, pure Python. Always available. Catches exact terms embeddings blur.
  dense   cosine similarity over embeddings (fastembed, BAAI/bge-small-en-v1.5).
          Store: pgvector when DATABASE_URL is set; otherwise an in-memory brute-force double
          (same interface, for offline dev; at ~50 docs an exact scan is what pgvector does anyway).
  hybrid  both, fused with Reciprocal Rank Fusion (k=60). Default when dense is available.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .base import CATEGORIES, ROOT

POLICY_DIR = ROOT / "data" / "policy"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
CACHE_DIR = ROOT / ".cache"


@dataclass
class Doc:
    id: str
    category: str          # owning category, or "precedence" for cross-category rules
    title: str
    text: str
    cats: list[str]        # categories this doc speaks about (used for retrieval-quality logging)


def load_policy(policy_dir: Path = POLICY_DIR) -> list[Doc]:
    docs = []
    for path in sorted(policy_dir.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        m = re.search(r"^category:\s*(\S+)", raw, re.M)
        owner = m.group(1) if m else path.stem
        raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
        for section in re.split(r"^## ", raw, flags=re.M)[1:]:
            head, _, body = section.partition("\n")
            head, body = head.strip(), " ".join(body.split())
            doc_id = head.split()[0] if re.match(r"R\d+\b", head) else head
            mentioned = [c for c in CATEGORIES if c in body or c.replace("_", " ") in body.lower()]
            cats = [owner] if owner in CATEGORIES else mentioned
            docs.append(Doc(doc_id, owner, head, body, cats))
    return docs


STOP = set("""a an the and or but if of to in on at for from by with is are was were be been it its this
that these those i me my we our you your they them their he she his her as so do did does have has had
there here what which who whom will would can could just than then too very s t""".split())


def stem(t: str) -> str:
    for suffix in ("ations", "ation", "ings", "ing", "edly", "ed", "es", "ly", "s", "e"):
        if t.endswith(suffix) and len(t) - len(suffix) >= 3:
            t = t[: -len(suffix)]
            break
    if len(t) > 4 and t[-1] == t[-2] and t[-1] not in "aeiou":
        t = t[:-1]  # cancell -> cancel
    return t


def tokenize(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1]


class BM25:
    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in corpus]
        self.len = [len(d) for d in corpus]
        self.avgdl = sum(self.len) / max(1, len(corpus))
        n = len(corpus)
        df = Counter(t for d in corpus for t in set(d))
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for tf, dl in zip(self.tf, self.len):
            s = 0.0
            for t in query:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            out.append(s)
        return out


class Embedder:
    def __init__(self, model: str = EMBED_MODEL):
        from fastembed import TextEmbedding  # optional dependency
        self.model_name = model
        self.m = TextEmbedding(model_name=model)

    def passages(self, texts: list[str]) -> list[list[float]]:
        fn = getattr(self.m, "passage_embed", self.m.embed)
        return [[float(x) for x in v] for v in fn(texts)]

    def query(self, text: str) -> list[float]:
        fn = getattr(self.m, "query_embed", self.m.embed)
        return [float(x) for x in next(iter(fn([text])))]


class MemoryVectorStore:
    """Offline test double for pgvector: exact cosine scan. Not a second vector store."""
    name = "memory"

    def __init__(self, ids: list[str], vectors: list[list[float]]):
        self.ids = ids
        self.vecs = [self._norm(v) for v in vectors]

    @staticmethod
    def _norm(v):
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def search(self, vec: list[float], k: int) -> list[tuple[str, float]]:
        q = self._norm(vec)
        scored = [(i, sum(a * b for a, b in zip(q, v))) for i, v in zip(self.ids, self.vecs)]
        return sorted(scored, key=lambda x: -x[1])[:k]


class PgVectorStore:
    """pgvector via psycopg. Vectors travel as text literals cast to ::vector, so no pgvector package."""
    name = "pgvector"

    def __init__(self, url: str):
        import psycopg  # optional dependency
        self.conn = psycopg.connect(url, autocommit=True)

    def search(self, vec: list[float], k: int) -> list[tuple[str, float]]:
        lit = "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
        rows = self.conn.execute(
            "select id, 1 - (embedding <=> %s::vector) as score from policy_docs "
            "order by embedding <=> %s::vector limit %s", (lit, lit, k)).fetchall()
        return [(r[0], float(r[1])) for r in rows]


def _cached_doc_vectors(embedder: Embedder, docs: list[Doc]) -> list[list[float]]:
    key = hashlib.sha256((embedder.model_name + "".join(d.id + d.text for d in docs)).encode()).hexdigest()[:16]
    path = CACHE_DIR / f"policy-emb-{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    vecs = embedder.passages([f"{d.title}. {d.text}" for d in docs])
    CACHE_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(vecs))
    return vecs


class Retriever:
    def __init__(self, mode: str | None = None, docs: list[Doc] | None = None, pool: int = 20):
        self.docs = docs or load_policy()
        self.by_id = {d.id: d for d in self.docs}
        self.pool = pool
        self.bm25 = BM25([tokenize(f"{d.title} {d.text}") for d in self.docs])
        self.requested = (mode or os.environ.get("RAG_RETRIEVAL", "auto")).lower()
        self.embedder = self.store = None
        if self.requested in ("auto", "dense", "hybrid"):
            try:
                self.embedder = Embedder()
                url = os.environ.get("DATABASE_URL")
                if url:
                    self.store = PgVectorStore(url)
                else:
                    self.store = MemoryVectorStore([d.id for d in self.docs],
                                                   _cached_doc_vectors(self.embedder, self.docs))
            except Exception as e:  # fastembed/psycopg missing or model download blocked
                if self.requested != "auto":
                    raise RuntimeError(f"dense retrieval unavailable ({e}). pip install fastembed") from e
                self.embedder = self.store = None
        if self.store is None:
            self.mode = "bm25"
        else:
            self.mode = "dense" if self.requested == "dense" else "hybrid"

    def describe(self) -> dict:
        return {"mode": self.mode, "embedding_model": EMBED_MODEL if self.store else None,
                "vector_store": self.store.name if self.store else None, "docs": len(self.docs),
                "chunking": "by document (one ## section = one rule)"}

    def _bm25_ranked(self, query: str) -> list[tuple[str, float]]:
        scores = self.bm25.scores(tokenize(query))
        ranked = sorted(zip((d.id for d in self.docs), scores), key=lambda x: -x[1])
        return [r for r in ranked if r[1] > 0][: self.pool]

    def search(self, query: str, k: int = 3) -> list[dict]:
        if self.mode == "bm25":
            ranked = self._bm25_ranked(query)[:k]
        else:
            dense = self.store.search(self.embedder.query(query), self.pool)
            if self.mode == "dense":
                ranked = dense[:k]
            else:  # Reciprocal Rank Fusion: score = sum over lists of 1 / (60 + rank)
                fused: dict[str, float] = {}
                for lst in (self._bm25_ranked(query), dense):
                    for rank, (doc_id, _) in enumerate(lst, 1):
                        fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (60 + rank)
                ranked = sorted(fused.items(), key=lambda x: -x[1])[:k]
        return [{"id": i, "score": round(s, 4), "category": self.by_id[i].category,
                 "cats": self.by_id[i].cats, "title": self.by_id[i].title, "text": self.by_id[i].text}
                for i, s in ranked]

    def for_category(self, category: str, query: str, n_rules: int = 3) -> list[Doc]:
        """The verifier's view: one category's own docs + the precedence rules most relevant to this case."""
        own = [d for d in self.docs if d.category == category and "precedent" not in d.id]
        rules = [d for d in self.docs if d.category == "precedence" and category in d.cats]
        if rules:
            scores = dict(zip((d.id for d in self.docs), self.bm25.scores(tokenize(query))))
            rules = sorted(rules, key=lambda d: -scores.get(d.id, 0))[:n_rules]
        return own + rules

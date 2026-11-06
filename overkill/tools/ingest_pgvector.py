"""Embed data/policy into pgvector (Supabase or Neon free Postgres).

    pip install fastembed "psycopg[binary]"
    # put DATABASE_URL in .env (Supabase: Project Settings -> Database -> connection string)
    python tools/ingest_pgvector.py

Re-run after editing any policy document. After this, RAG and agents use pgvector for the dense half
of hybrid search automatically (results.json records vector_store="pgvector").
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipelines.llm import load_env  # noqa: E402
from pipelines.retrieval import EMBED_MODEL, Embedder, load_policy  # noqa: E402


def main() -> None:
    load_env()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set in .env")
    import psycopg

    docs = load_policy()
    vecs = Embedder().passages([f"{d.title}. {d.text}" for d in docs])
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute((ROOT / "db" / "schema.sql").read_text())
        conn.execute("delete from policy_docs")
        for d, v in zip(docs, vecs):
            conn.execute(
                "insert into policy_docs (id, category, title, body, cats, embedding, embedding_model) "
                "values (%s, %s, %s, %s, %s, %s::vector, %s)",
                (d.id, d.category, d.title, d.text, d.cats, "[" + ",".join(f"{x:.6f}" for x in v) + "]", EMBED_MODEL))
        n = conn.execute("select count(*) from policy_docs").fetchone()[0]
    print(f"upserted {n} policy documents ({EMBED_MODEL}, {len(vecs[0])} dims) into pgvector")


if __name__ == "__main__":
    main()

-- One vector store: pgvector inside the Postgres you already have.
create extension if not exists vector;

create table if not exists policy_docs (
  id              text primary key,          -- e.g. 'R4' or 'credit_not_processed-definition'
  category        text not null,             -- owning category, or 'precedence'
  title           text not null,
  body            text not null,             -- one whole rule: chunked by document, never by token count
  cats            text[] not null default '{}',  -- categories the doc speaks about (retrieval-quality logging)
  embedding       vector(384) not null,      -- BAAI/bge-small-en-v1.5
  embedding_model text not null,
  updated_at      timestamptz not null default now()
);

-- No ANN index on purpose: ~50 rows, so an exact scan is both exact and faster.
-- Past ~10k rows, add:  create index on policy_docs using hnsw (embedding vector_cosine_ops);

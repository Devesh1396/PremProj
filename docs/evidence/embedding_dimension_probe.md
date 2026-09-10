# Embedding dimensionality — measured, 2026-09-10

Evidence for the `EMBEDDING_DIM` decision. Everything here was **measured**
against the configured provider and against pgvector, not recalled. Web
search and `ai.google.dev` are both blocked by this environment's egress
proxy, so the provider questions were answered by calling the API.

Fourteen embedding calls in total. `config/model_prices.json` has no
embedding rate configured, so these record as UNPRICED.

## 1. Are truncated vectors returned normalised?

The hazard: with Matryoshka truncation, asking for fewer dimensions than
the model's native output can return a vector that is no longer unit
length. Measured L2 norm of the returned vector:

| model | asked | got | L2 norm | normalised? |
|---|---|---|---|---|
| `gemini-embedding-001` | (default) | 3072 | 1.000000 | yes |
| `gemini-embedding-001` | 3072 | 3072 | 1.000000 | yes |
| `gemini-embedding-001` | **1536** | 1536 | **0.702191** | **NO** |
| `gemini-embedding-001` | 768 | 768 | 0.590418 | NO |
| `gemini-embedding-2` | (default) | 3072 | 1.000000 | yes |
| `gemini-embedding-2` | 3072 | 3072 | 1.000000 | yes |
| `gemini-embedding-2` | **1536** | 1536 | **1.000000** | **yes** |
| `gemini-embedding-2` | 768 | 768 | 1.000000 | yes |

**A newer model does auto-normalise truncated output.** The provider
offers `gemini-embedding-001`, `gemini-embedding-2-preview` and
`gemini-embedding-2`; the last returns unit-length vectors at every
supported dimensionality, so the manual-normalisation step disappears.

## 2. What does truncation cost in retrieval quality?

One query against six documents, ranked at 3072 and at 1536.

| model | ranking identical | top-3 identical |
|---|---|---|
| `gemini-embedding-001` | yes | yes |
| `gemini-embedding-2` | no | no |

The `gemini-embedding-2` difference is a swap of ranks **3 and 4** between
two near-tied documents (0.659 vs 0.655) — noise at a tie boundary, not
degradation. Top-2 identical in both models. This is one probe, not a
benchmark; it is enough to say truncation is not obviously harmful and not
enough to say it is free.

## 3. Can pgvector index 3072 dimensions?

```
create table _dimtest (v vector(3072));                       -- CREATE TABLE
create index on _dimtest using hnsw (v vector_cosine_ops);
ERROR:  column cannot have more than 2000 dimensions for hnsw index
```

**No, not on this pgvector.** 3072 stores fine and `<=>` computes fine —
only the *index* is refused. Without an index every similarity query is a
sequential scan.

| | |
|---|---|
| pgvector available here | **0.6.0** (`halfvec` does not exist; it arrives in 0.7.0) |
| HNSW / IVFFlat dimension limit | **2000** |
| pgvector on the VPS | **UNKNOWN — must be checked before 3072 is considered** |

## 4. Is unnormalised actually "quietly wrong" for cosine?

Same direction, one scaled to 0.7 of the other:

| operator | used by | result | norm-sensitive? |
|---|---|---|---|
| `<=>` cosine | **all four HNSW indexes here** | 1.8e-08 (≈ 0) | **no** |
| `<->` L2 | — | 1.1224973 | yes |
| `<#>` inner product | — | -9.80 vs -14 for unit/unit | yes |

So cosine **ranking** survives unnormalised vectors: pgvector divides by
the norms. The hazard is narrower than "cosine is quietly wrong" — it bites
on `<->` or `<#>`, and on any column holding a mix of normalised and
unnormalised rows where magnitudes are ever compared. Real, but not the
failure mode for the operator this schema actually uses.

## 5. What is already embedded

| table | embedded | rows |
|---|---|---|
| `knowledge_chunks` | 0 | 0 |
| `concepts` | 0 | 0 |
| `concept_aliases` | 0 | 0 |
| `strategies` | 0 | 0 |
| `implementation_patterns` | 0 | 0 |

**Nothing. Anywhere.** Five `vector(1536)` columns and four HNSW indexes,
all empty. There is no re-embed to pay for under any option chosen now.

## 6. A loose end found while measuring

`EMBEDDING_DIM=1536` is in `.env.example` and is **read by no code**. The
real value is a `dim int := 1536` literal in `002_concepts.sql` and again
in `003_knowledge.sql`, each with a comment saying it must match the other
two. Three copies, no enforcement.

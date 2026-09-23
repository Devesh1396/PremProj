#!/usr/bin/env python3
"""K14 — hybrid retrieval. Metadata filter -> full text -> vector -> dedupe -> rerank.

BUILD_GUIDE step 17. DECISIONS.md D8, D15, D34; Engine 7 §35, A3.

    python3 scripts/retrieval.py --query "insulin resistance in a vegetarian"
    python3 scripts/retrieval.py --concepts INSULIN_SENSITIVITY,SLEEP_QUALITY
    python3 scripts/retrieval.py --explain          # channels and why

### The acceptance criterion is about BREADTH, and breadth is a mechanism

BUILD_GUIDE step 17: *"the cross-domain case retrieves across insulin
sensitivity, hepatic fat, triglycerides, muscle, appetite, sleep,
vegetarian implementation, exercise and behaviour — not three disease
folders."*

Text similarity alone cannot do that. A case note about insulin resistance
is lexically close to insulin-resistance material and lexically far from
sleep material, so a pure text or pure vector search returns the disease
folder however good the embeddings are. Two mechanisms here produce the
breadth instead:

1. **The concept spine is a retrieval channel, not just a filter.** The
   case's NORMALIZED CONCEPTS are an input (`concept_ids`), and
   `strategy_concepts` pulls in everything linked to any of them --
   including the sleep and behaviour concepts Engine 1 raised, which no
   amount of lexical similarity to the presenting complaint would surface.
2. **A per-bucket cap in the rerank.** A library with forty insulin
   strategies and two sleep strategies returns forty insulin strategies at
   limit 40 unless something stops it. `per_bucket_cap` stops it: each
   query concept may fill at most that many slots before the rest of the
   page is offered to other concepts. Leftover capacity is then filled
   from the deferred results, so the cap costs no recall -- it only
   changes the ORDER in which breadth and depth are spent.

### Channels are additive and every result says which found it

A row found by text, vector and the spine is ONE result carrying three
channels, not three results. That is the dedupe step, and the channel list
is what makes a retrieval explainable afterwards -- "why did this appear?"
has an answer in the row.

### Without pgvector this degrades LOUDLY (D15)

The vector channel is skipped, `diagnostics["vector"]` says why, and the
other channels run. It never silently returns worse results while claiming
to be hybrid.

### A3: held-out material is the answer key, not a source

Chunks belonging to a held-out `source_items` row are excluded by default.
Evaluation passes `include_held_out=True` deliberately -- that is the whole
point of the held-out set. Production retrieval must never see it, or the
measurement it exists for is measuring itself.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import psycopg

import embedding

DEFAULT_LIMIT = int(os.environ.get("RETRIEVAL_LIMIT", "20"))

# `per_bucket_cap` is DERIVED, not a constant, unless a caller states one.
#
# A fixed cap only produces breadth at one particular page size. Cap 3 with
# a page of 12 lets three disease folders take nine of the twelve slots and
# the acceptance criterion fails at the DEFAULT setting -- which would mean
# the breadth was a knob a test set, not a property the system has. The cap
# that spreads a page of `limit` across `n` query concepts is limit // n.
def derive_cap(limit: int, n_buckets: int) -> int:
    return max(1, limit // max(1, n_buckets))

# How much each channel is worth once its scores are normalized to [0,1].
# Weights are renormalized over the channels that actually ran, so a
# database with no pgvector does not score every result 30% lower than the
# same database with it -- the ranking is comparable, the recall is not,
# and only the second of those is a real degradation.
CHANNEL_WEIGHTS = {"concept": 0.40, "fts": 0.30, "vector": 0.30}

KINDS = ("strategy", "curated_strategy", "chunk", "pattern", "concept")


def dsn() -> str:
    return os.environ["DATABASE_URL"]


def vector_available(conn) -> bool:
    return conn.execute("select embedding_dim()").fetchone()[0] is not None


def has_vectors(conn, table: str) -> bool:
    """Whether this table has any embedding at all. A column with no
    vectors in it is not a usable channel, and saying so is more useful
    than returning an empty vector result set that looks like a miss."""
    if not vector_available(conn):
        return False
    return bool(conn.execute(
        f"select exists (select 1 from {table} where embedding is not null)"
    ).fetchone()[0])


def resolve_concepts(conn, keys: list[str]) -> list[str]:
    """Canonical keys -> concept ids. Live concepts only.

    D8: a PROPOSED concept is not a retrieval anchor. Linking to one to
    make a count look right is exactly the shortcut K11 is forbidden.
    """
    if not keys:
        return []
    rows = conn.execute(
        "select concept_id::text from concepts "
        " where canonical_key = any(%s) and status in ('SEEDED','ACTIVE')",
        (keys,)).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------
# Channel 1: the concept spine
# ---------------------------------------------------------------------

def by_concept(conn, concept_ids: list[str], include_held_out: bool) -> list[dict]:
    """Strategies and patterns reachable from the case's concepts.

    `strategy_concepts` is the retrieval spine (003): Engine 1's prose is
    normalized to concepts and joined here. Without this channel retrieval
    collapses to disease-name matching, which is the failure the step 17
    acceptance criterion names.

    The link `weight` is the score, so a PRIMARY link outranks a
    peripheral mention of the same concept.
    """
    if not concept_ids:
        return []
    rows = conn.execute(
        """select s.strategy_id::text, s.name, sc.concept_id::text,
                  max(sc.weight)::float as w
             from strategies s
             join strategy_concepts sc on sc.strategy_id = s.strategy_id
            where sc.concept_id = any(%s::uuid[])
              and s.knowledge_status <> 'DEPRECATED'
            group by 1, 2, 3""",
        (concept_ids,)).fetchall()
    out = []
    for sid, name, cid, weight in rows:
        out.append({"kind": "strategy", "id": sid, "label": name,
                    "bucket": cid, "channel": "concept", "raw": float(weight)})

    patterns = conn.execute(
        """select p.pattern_id::text,
                  coalesce(p.intervention, p.practical_method, 'pattern'),
                  sc.concept_id::text, max(sc.weight)::float
             from implementation_patterns p
             join strategy_concepts sc on sc.strategy_id = p.strategy_id
             join strategies s on s.strategy_id = p.strategy_id
            where sc.concept_id = any(%s::uuid[])
              and s.knowledge_status <> 'DEPRECATED'
            group by 1, 2, 3""",
        (concept_ids,)).fetchall()
    for pid, label, cid, weight in patterns:
        out.append({"kind": "pattern", "id": pid, "label": label,
                    "bucket": cid, "channel": "concept", "raw": float(weight)})

    # THE THIRD ROW SOURCE: preserved curated practitioner knowledge (D52).
    #
    # It is here, inside the same function, rather than in a pipeline of
    # its own, and that is the whole mitigation for the risk this design
    # accepted. `curated_strategies` is a second place a retrievable thing
    # lives, so two sources CAN diverge -- but sharing this function means
    # they cannot diverge in channel, in score normalization, in the merge
    # or in the rerank, which is where a divergence would actually hurt.
    # `implementation_patterns` above is the same pattern, already proven.
    #
    # The alternative was to copy `curated_fields.text_value` into
    # `strategies` and have one source. That undoes GATE 1: two copies of
    # the practitioner's words, and the one retrieval returns is the copy
    # with no span, no per-field provenance and no verbatim guarantee.
    curated = conn.execute(
        """select s.curated_id::text, s.name, l.concept_id::text,
                  max(l.weight)::float
             from curated_strategies s
             join curated_strategy_concepts l on l.curated_id = s.curated_id
            where l.concept_id = any(%s::uuid[])
            group by 1, 2, 3""",
        (concept_ids,)).fetchall()
    for cur_id, name, cid, weight in curated:
        out.append({"kind": "curated_strategy", "id": cur_id, "label": name,
                    "bucket": cid, "channel": "concept", "raw": float(weight)})
    return out


# ---------------------------------------------------------------------
# Channel 2: full text
# ---------------------------------------------------------------------

def tsquery_for(conn, query: str) -> str | None:
    """The query as an OR of its lexemes, or None if it has none.

    **Not `websearch_to_tsquery` and not `plainto_tsquery`: both AND every
    term.** `'insulin resistance with hepatic fat'` becomes
    `'insulin' & 'resist' & 'hepat' & 'fat'`, and a document must contain
    ALL of them -- so a realistic clinical query, which is a paragraph,
    matches nothing at all. Step 18 layer A scored 0.00 on all fourteen
    domain tests for exactly this reason and nothing else (bug 63).

    Ranking is what separates a document matching six terms from one
    matching one, and `ts_rank_cd` already does that. ANDing is not a
    relevance strategy, it is a filter that removes everything.

    The lexemes come from `to_tsvector` -- the parser's own output, quoted
    with `quote_literal` -- so nothing a practitioner pastes can reach
    `to_tsquery` as syntax.
    """
    if not query or not query.strip():
        return None
    row = conn.execute(
        "select string_agg(quote_literal(lexeme), ' | ') "
        "  from unnest(to_tsvector('english', %s))", (query,)).fetchone()
    return row[0] if row and row[0] else None


def by_fts(conn, query: str, include_held_out: bool) -> list[dict]:
    """`ts_rank_cd` over exactly the expressions the GIN indexes cover."""
    tsq = tsquery_for(conn, query)
    if tsq is None:
        return []
    out = []
    rows = conn.execute(
        """select s.strategy_id::text, s.name,
                  ts_rank_cd(to_tsvector('english',
                      s.name || ' ' || coalesce(s.summary,'') || ' '
                      || coalesce(s.mechanism,'')),
                      to_tsquery('english', %s))::float as rank,
                  (select sc.concept_id::text from strategy_concepts sc
                    where sc.strategy_id = s.strategy_id
                    order by sc.weight desc, sc.concept_id limit 1)
             from strategies s
            where s.knowledge_status <> 'DEPRECATED'
              and to_tsvector('english',
                      s.name || ' ' || coalesce(s.summary,'') || ' '
                      || coalesce(s.mechanism,''))
                  @@ to_tsquery('english', %s)""",
        (tsq, tsq)).fetchall()
    for sid, name, rank, bucket in rows:
        out.append({"kind": "strategy", "id": sid, "label": name,
                    "bucket": bucket, "channel": "fts", "raw": float(rank)})

    held_out_clause = "" if include_held_out else " and not i.held_out"
    rows = conn.execute(
        f"""select c.chunk_id::text, left(c.text, 120), d.item_id::text,
                   ts_rank_cd(to_tsvector('english', c.text),
                       to_tsquery('english', %s))::float
              from knowledge_chunks c
              join source_documents d on d.document_id = c.document_id
              join source_items i on i.item_id = d.item_id
             where to_tsvector('english', c.text)
                   @@ to_tsquery('english', %s){held_out_clause}""",
        (tsq, tsq)).fetchall()
    for chunk_id, snippet, item_id, rank in rows:
        out.append({"kind": "chunk", "id": chunk_id, "label": snippet,
                    "bucket": item_id, "channel": "fts", "raw": float(rank)})

    rows = conn.execute(
        """select concept_id::text, canonical_name,
                  ts_rank_cd(to_tsvector('english', search_text),
                      to_tsquery('english', %s))::float
             from concepts
            where status in ('SEEDED','ACTIVE')
              and to_tsvector('english', search_text)
                  @@ to_tsquery('english', %s)""",
        (tsq, tsq)).fetchall()
    for cid, name, rank in rows:
        out.append({"kind": "concept", "id": cid, "label": name,
                    "bucket": cid, "channel": "fts", "raw": float(rank)})

    # Curated cards are ranked as ONE DOCUMENT -- name plus every
    # preserved field -- exactly as a `strategies` row is ranked as name
    # plus summary plus mechanism. Ranking each field separately and
    # taking the best would let a card matching six terms across three
    # fields lose to one matching two terms in a single field, which is
    # the opposite of what `ts_rank_cd` is for.
    #
    # THE TEXT IS READ WHERE IT LIVES. Nothing is copied into a search
    # column, so the words ranked here are the same characters
    # `curated_fields` preserved, at the spans it recorded.
    #
    # `client_decision_logic` IS PART OF THAT DOCUMENT, so the routing
    # intelligence influences what comes back and not only what a reader
    # sees afterwards. The alternative -- an allowlist of "descriptive"
    # fields -- would be a per-field weighting nobody could justify from
    # the source. The cost is stated in D52: full text has no notion of
    # negation, so a card saying "this is LOW priority when X" matches a
    # query about X exactly as a card saying "prioritize when X" does.
    # Distinguishing them is E1 Pass B's job, not retrieval's.
    rows = conn.execute(
        """with doc as (
             select s.curated_id, s.name,
                    s.name || ' ' || coalesce(
                      string_agg(f.text_value, ' ' order by f.source_start), '')
                    as body
               from curated_strategies s
               left join curated_fields f on f.curated_id = s.curated_id
              group by s.curated_id, s.name)
           select d.curated_id::text, d.name,
                  ts_rank_cd(to_tsvector('english', d.body),
                      to_tsquery('english', %s))::float,
                  (select l.concept_id::text from curated_strategy_concepts l
                    where l.curated_id = d.curated_id
                    order by l.weight desc, l.concept_id limit 1)
             from doc d
            where to_tsvector('english', d.body)
                  @@ to_tsquery('english', %s)""",
        (tsq, tsq)).fetchall()
    for cur_id, name, rank, bucket in rows:
        out.append({"kind": "curated_strategy", "id": cur_id, "label": name,
                    "bucket": bucket, "channel": "fts", "raw": float(rank)})
    return out


# ---------------------------------------------------------------------
# Channel 3: vector
# ---------------------------------------------------------------------

def by_vector(conn, query: str, include_held_out: bool,
              embed_call=None) -> tuple[list[dict], str]:
    """Cosine similarity over whatever is embedded. Returns (hits, note).

    The query is embedded through `embedding.embed()` -- the one boundary
    (D38) -- so a query is checked for text-ness, unit norm and dimension
    exactly as stored content is. A query that somehow arrived as media is
    refused here rather than priced as text.

    `1 - (embedding <=> q)` is cosine similarity. It is already in [0,1]
    for unit vectors with non-negative similarity, and negative
    similarities are clamped at 0 rather than dropped: a result that is
    merely irrelevant should score zero, not sort below one that another
    channel found.
    """
    if not query or not query.strip():
        return [], "no query text"
    if not vector_available(conn):
        return [], "pgvector absent (D15): metadata + full text only"

    # The embedding model is optional CONFIGURATION, and its absence is a
    # supported state -- it is deliberately unset on the VPS, where nothing
    # is allowed to make a paid call yet. Retrieval degrades to metadata +
    # full text and SAYS SO; it does not raise. `embedding.embed()` still
    # refuses, correctly, because asking it to embed with no model pinned
    # IS an error (D34) -- but a query is not asking it to.
    if not os.environ.get("MODEL_EMBEDDING", "").strip():
        return [], ("MODEL_EMBEDDING is not set: the query cannot be embedded, "
                    "so the vector channel is skipped (metadata + full text only)")

    # THE SAME GUARD `_tier_semantic` CARRIES, and for the same reason
    # (V3). `MODEL_EMBEDDING` says which model; `LLM_API_KEY` says whether
    # a call may be made at all, and they are configured independently.
    # Without this, a suite with a model configured and no credential
    # reached the live endpoint from inside retrieval and got a 404 --
    # an exception where a named degradation belongs. Found by the GATE 3
    # bridge test, which queries full text on a database that has both a
    # model name and no key. An injected `embed_call` is its own
    # transport and needs no credential.
    if embed_call is None and not os.environ.get("LLM_API_KEY", "").strip():
        return [], ("LLM_API_KEY is not set: no provider call may be made, so "
                    "the vector channel is skipped (metadata + full text only)")

    tables = [t for t in ("strategies", "knowledge_chunks", "concepts")
              if has_vectors(conn, t)]
    if not tables:
        return [], "no embeddings stored yet: run scripts/embed_library.py"

    vector, _model, _dims = embedding.embed(
        conn, query, entity_type="retrieval_query", call=embed_call)
    q = str(vector)

    out = []
    if "strategies" in tables:
        rows = conn.execute(
            """select s.strategy_id::text, s.name,
                      (1 - (s.embedding <=> %s::vector))::float,
                      (select sc.concept_id::text from strategy_concepts sc
                        where sc.strategy_id = s.strategy_id
                        order by sc.weight desc, sc.concept_id limit 1)
                 from strategies s
                where s.embedding is not null
                  and s.knowledge_status <> 'DEPRECATED'
                order by s.embedding <=> %s::vector
                limit 100""", (q, q)).fetchall()
        for sid, name, sim, bucket in rows:
            out.append({"kind": "strategy", "id": sid, "label": name,
                        "bucket": bucket, "channel": "vector",
                        "raw": max(0.0, float(sim))})

    if "knowledge_chunks" in tables:
        held_out_clause = "" if include_held_out else " and not i.held_out"
        rows = conn.execute(
            f"""select c.chunk_id::text, left(c.text, 120), d.item_id::text,
                       (1 - (c.embedding <=> %s::vector))::float
                  from knowledge_chunks c
                  join source_documents d on d.document_id = c.document_id
                  join source_items i on i.item_id = d.item_id
                 where c.embedding is not null{held_out_clause}
                 order by c.embedding <=> %s::vector
                 limit 100""", (q, q)).fetchall()
        for chunk_id, snippet, item_id, sim in rows:
            out.append({"kind": "chunk", "id": chunk_id, "label": snippet,
                        "bucket": item_id, "channel": "vector",
                        "raw": max(0.0, float(sim))})

    if "concepts" in tables:
        rows = conn.execute(
            """select concept_id::text, canonical_name,
                      (1 - (embedding <=> %s::vector))::float
                 from concepts
                where embedding is not null and status in ('SEEDED','ACTIVE')
                order by embedding <=> %s::vector
                limit 50""", (q, q)).fetchall()
        for cid, name, sim in rows:
            out.append({"kind": "concept", "id": cid, "label": name,
                        "bucket": cid, "channel": "vector",
                        "raw": max(0.0, float(sim))})
    return out, f"embedded query against {', '.join(tables)}"


# ---------------------------------------------------------------------
# Dedupe and rerank
# ---------------------------------------------------------------------

def normalize_scores(hits: list[dict]) -> None:
    """Scale each channel's raw scores to [0,1] IN PLACE.

    `ts_rank_cd` and cosine similarity are not on the same scale and never
    will be -- one is unbounded and corpus-dependent, the other is a
    bounded angle. Blending them raw would let whichever happens to be
    larger dominate the ranking for reasons that have nothing to do with
    relevance, so each channel is normalized against its own best hit
    before any weight is applied.
    """
    for channel in {h["channel"] for h in hits}:
        subset = [h for h in hits if h["channel"] == channel]
        top = max(h["raw"] for h in subset)
        for h in subset:
            h["score"] = (h["raw"] / top) if top > 0 else 0.0


def merge(hits: list[dict], weights: dict) -> list[dict]:
    """One row per (kind, id), carrying every channel that found it."""
    merged: dict[tuple[str, str], dict] = {}
    for h in hits:
        key = (h["kind"], h["id"])
        row = merged.get(key)
        if row is None:
            row = merged[key] = {
                "kind": h["kind"], "id": h["id"], "label": h["label"],
                "buckets": set(), "channels": {}, "score": 0.0}
        if h.get("bucket"):
            row["buckets"].add(h["bucket"])
        # A channel may find the same row through several concepts; the
        # strongest link is the one that speaks for it.
        row["channels"][h["channel"]] = max(
            row["channels"].get(h["channel"], 0.0), h["score"])
    for row in merged.values():
        row["score"] = sum(weights[c] * s for c, s in row["channels"].items())
        row["buckets"] = sorted(row["buckets"])
    return list(merged.values())


def rerank(rows: list[dict], limit: int, per_bucket_cap: int) -> list[dict]:
    """Score order, with a per-bucket cap so one concept cannot fill the page.

    Two passes, deliberately. The first spends the page on breadth: no
    bucket may take more than `per_bucket_cap` slots. The second fills
    whatever is left with the best of what the first pass deferred, so the
    cap never costs recall -- it changes the ORDER in which breadth and
    depth are spent, which is exactly the difference between a
    cross-domain retrieval and three disease folders.

    Ties break on (kind, id) so the same library and the same query always
    return the same page. A retrieval that reshuffles between runs cannot
    be evaluated, and step 18 is an evaluation layer.
    """
    ordered = sorted(rows, key=lambda r: (-r["score"], r["kind"], r["id"]))
    used: dict[str, int] = {}
    chosen, deferred = [], []
    for row in ordered:
        if len(chosen) >= limit:
            break
        buckets = row["buckets"] or ["_none"]
        # A row is capped only if EVERY bucket it belongs to is full: a
        # strategy linked to both insulin sensitivity and sleep still
        # counts as breadth while sleep has room.
        if all(used.get(b, 0) >= per_bucket_cap for b in buckets):
            deferred.append(row)
            continue
        for b in buckets:
            used[b] = used.get(b, 0) + 1
        row["capped"] = False
        chosen.append(row)
    for row in deferred:
        if len(chosen) >= limit:
            break
        row["capped"] = True
        chosen.append(row)
    return chosen[:limit]


# ---------------------------------------------------------------------
# Traceability: a retrieved curated strategy back to the source bytes
# ---------------------------------------------------------------------

def curated_trace(conn, curated_id: str) -> dict:
    """query -> concept -> curated strategy -> field -> byte range -> text.

    D52. If what a practitioner sees cannot be traced back to the words
    they wrote, GATE 1 bought nothing -- so a retrieved `curated_strategy`
    result resolves to its card, its concept links with the exact span
    each one came from, its preserved fields with theirs, and the
    `raw_location` of the untouched original.

    The last hop, reading the file and slicing it, is deliberately NOT
    done here. The check that matters is against the ORIGINAL document,
    and a verifier that compares the database against the database has
    constructed both halves of its own comparison (V2).
    """
    # STRUCTURAL PROVENANCE TRAVELS WITH THE STRUCTURE (D57). `heading_path`
    # is structure, and a consumer handed a path with nothing saying where
    # it came from cannot tell a grammar-derived container name from an
    # authored hierarchy. The card's block carries it; so does each field's.
    card = conn.execute(
        """select s.curated_id::text, s.ordinal, s.name, s.heading_path,
                  s.source_start, s.source_end, e.envelope_id::text,
                  e.raw_location, e.source_title,
                  b.structural_provenance::text
             from curated_strategies s
             join source_envelopes e on e.envelope_id = s.envelope_id
             left join curated_blocks b
                    on b.envelope_id = s.envelope_id and b.ordinal = s.ordinal
            where s.curated_id = %s""", (curated_id,)).fetchone()
    if card is None:
        return {}
    links = conn.execute(
        """select canonical_key, canonical_name, concept_type, field_name,
                  source_phrase, source_start, source_end, rule_id,
                  resolution_tier, resolution_score
             from v_curated_concept_trace
            where curated_id = %s
            order by source_start""", (curated_id,)).fetchall()
    fields = conn.execute(
        """select f.field_name, f.provenance::text, f.source_start,
                  f.source_end, f.text_value, f.heading_path,
                  b.structural_provenance::text
             from curated_fields f
             left join curated_blocks b on b.block_id = f.block_id
            where f.curated_id = %s
            order by f.source_start""", (curated_id,)).fetchall()
    keys = ("curated_id", "ordinal", "name", "heading_path",
            "source_start", "source_end", "envelope_id", "raw_location",
            "source_title", "structural_provenance")
    return {
        **dict(zip(keys, card)),
        "concept_links": [dict(zip(
            ("canonical_key", "canonical_name", "concept_type", "field_name",
             "source_phrase", "source_start", "source_end", "rule_id",
             "tier", "score"), r)) for r in links],
        "fields": [dict(zip(
            ("field_name", "provenance", "source_start", "source_end",
             "text_value", "heading_path", "structural_provenance"), r))
            for r in fields],
    }


# ---------------------------------------------------------------------
# The CASE block: what a client pipeline actually hands Engine 7
# ---------------------------------------------------------------------
#
# GATE 3 made curated cards retrievable and nothing in the runtime
# retrieved them: `client_new.py` went E1 Pass A -> normalize -> E7 with
# NORMALIZED_CONCEPTS and no knowledge at all, and `retrieval.py` was
# imported by no script outside the suites. A bridge nothing crosses is
# not a bridge (D52a).

# CASE RETRIEVAL ASKS FOR KNOWLEDGE OBJECTS, EXPLICITLY.
#
# `KINDS` defaults to a MIXED set that includes `concept` -- ontology
# vocabulary, which is the right answer for an ontology query and the
# wrong one for a case. The GATE 3 first run measured what happens when a
# caller takes the default: 82 of 124 merged results were concepts, each
# in its own bucket so the per-bucket cap could not restrain them, and
# they took 27 of 30 places. A case pipeline states what it wants rather
# than inheriting a default that was never chosen for it.
CASE_KINDS = ("strategy", "curated_strategy", "pattern")


def curated_expansion(conn, curated_id: str) -> dict:
    """A curated card for an engine payload, WITHOUT flattening it.

    `client_decision_logic` stays its own field, with its provenance and
    its byte range, exactly as `curated_fields` holds it. Collapsing the
    fields into a `summary`/`mechanism` pair would rebuild the legacy
    strategy shape GATE 1 refused to write (D50) -- the routing
    intelligence would arrive as prose in a summary, which is how K09 lost
    it in the first place (D49).
    """
    tr = curated_trace(conn, curated_id)
    if not tr:
        return {}
    return {
        "card_name": tr["name"],
        "heading_path": tr["heading_path"],
        # Where the path's structure came from. Never AUTHORED for any
        # source ingested today: the canonical document states no heading
        # level, so the path names the container the grammar recognised and
        # nothing more.
        "structural_provenance": tr["structural_provenance"],
        "source_title": tr["source_title"],
        "raw_location": tr["raw_location"],
        "card_source_start": tr["source_start"],
        "card_source_end": tr["source_end"],
        # Every field the practitioner wrote, each with the provenance and
        # the span that make it checkable against the original.
        "fields": [{"field_name": f["field_name"],
                    "provenance": f["provenance"],
                    "structural_provenance": f["structural_provenance"],
                    "heading_path": f["heading_path"],
                    "source_start": f["source_start"],
                    "source_end": f["source_end"],
                    "text": f["text_value"]}
                   for f in tr["fields"]],
        "concept_links": [{"canonical_key": l["canonical_key"],
                           "field_name": l["field_name"],
                           "source_phrase": l["source_phrase"],
                           "source_start": l["source_start"],
                           "source_end": l["source_end"],
                           "tier": l["tier"],
                           "score": float(l["score"]) if l["score"] is not None else None}
                          for l in tr["concept_links"]],
    }


def _library_expansion(conn, kind: str, row_id: str) -> dict:
    if kind == "strategy":
        row = conn.execute(
            "select name, summary, mechanism, knowledge_status::text "
            "  from strategies where strategy_id=%s", (row_id,)).fetchone()
        keys = ("name", "summary", "mechanism", "knowledge_status")
    else:
        row = conn.execute(
            "select intervention, practical_method, context_notes "
            "  from implementation_patterns where pattern_id=%s",
            (row_id,)).fetchone()
        keys = ("intervention", "practical_method", "context_notes")
    return dict(zip(keys, row)) if row else {}


def case_knowledge(conn, *, query: str | None, concept_ids: list[str],
                   limit: int = DEFAULT_LIMIT, embed_call=None,
                   telemetry: bool = True) -> dict:
    """The `RETRIEVED_KNOWLEDGE` block a case pipeline hands to an engine.

    RETRIEVAL SUPPLIES RELEVANT KNOWLEDGE. IT DOES NOT DECIDE PRIORITY.
    `RANKING_BASIS` is a FIELD on the block, not a caption in a comment
    (D43): every consumer reads `RELEVANCE_ONLY` and knows the order is
    lexical and concept-spine relevance. Which strategy the client should
    start with is E1 Pass B's decision over E7's reasoning, and nothing
    here computes it -- the GATE 3 answer key is explicit that
    PRIMARY/SECONDARY/LOW mean retrieval prominence, not a treatment
    ranking.

    The diagnostics travel with the block on purpose. A thin result from a
    young library and a thin result from an unembedded one look identical
    in the items and different in the diagnostics, and an engine reasoning
    over four strategies should be able to tell which it is looking at.
    """
    result = retrieve(conn, query=query, concept_ids=concept_ids,
                      kinds=CASE_KINDS, limit=limit, embed_call=embed_call,
                      telemetry=telemetry)
    items = []
    for rank, row in enumerate(result["results"], 1):
        item = {
            "rank": rank,
            "kind": row["kind"],
            "id": row["id"],
            "label": row["label"],
            "score": round(float(row["score"]), 6),
            "channels": {c: round(float(v), 6)
                         for c, v in sorted(row["channels"].items())},
            "matched_concept_ids": row["buckets"],
        }
        if row["kind"] == "curated_strategy":
            item["curated"] = curated_expansion(conn, row["id"])
        else:
            item[row["kind"]] = _library_expansion(conn, row["kind"], row["id"])
        items.append(item)
    return {
        "RANKING_BASIS": "RELEVANCE_ONLY",
        "KINDS_REQUESTED": list(CASE_KINDS),
        "ITEMS": items,
        "DIAGNOSTICS": result["diagnostics"],
    }


def record_hits(conn, rows: list[dict], concept_ids: list[str]) -> None:
    """Concept usage telemetry (002): concepts never hit by retrieval are
    review candidates; concepts hit constantly are worth deepening."""
    touched = set(concept_ids)
    for row in rows:
        touched.update(row["buckets"])
        if row["kind"] == "concept":
            touched.add(row["id"])
    ids = [t for t in touched if len(t) == 36]
    if not ids:
        return
    conn.execute(
        "update concepts set retrieval_hits = retrieval_hits + 1, "
        "last_retrieved = now() where concept_id = any(%s::uuid[])", (ids,))


# ---------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------

def retrieve(conn, *, query: str | None = None,
             concept_ids: list[str] | None = None,
             concept_keys: list[str] | None = None,
             kinds: tuple[str, ...] = KINDS,
             limit: int = DEFAULT_LIMIT,
             per_bucket_cap: int | None = None,
             include_held_out: bool = False,
             embed_call=None,
             telemetry: bool = True) -> dict:
    """Metadata filter -> full text -> vector -> dedupe -> rerank.

    Returns {"results": [...], "diagnostics": {...}}. The diagnostics are
    not decoration: which channels ran, and why one did not, is the
    difference between a thin result set that is expected (a young library)
    and one that is a fault (an unembedded library nobody noticed).
    """
    concept_ids = list(concept_ids or [])
    if concept_keys:
        concept_ids += resolve_concepts(conn, concept_keys)
    concept_ids = sorted(set(concept_ids))

    diagnostics: dict = {"concepts_in": len(concept_ids),
                         "held_out_included": include_held_out}

    hits: list[dict] = []
    spine = by_concept(conn, concept_ids, include_held_out)
    hits += spine
    diagnostics["concept"] = f"{len(spine)} via strategy_concepts"

    text_hits = by_fts(conn, query or "", include_held_out)
    hits += text_hits
    diagnostics["fts"] = f"{len(text_hits)} via ts_rank_cd" if query \
        else "no query text"

    vector_hits, note = by_vector(conn, query or "", include_held_out, embed_call)
    hits += vector_hits
    diagnostics["vector"] = f"{len(vector_hits)} hits: {note}" if vector_hits \
        else note
    # STATED, NOT ASSUMED. `curated_strategies` has no embedding column, so
    # a curated card reaches a page through the concept spine and full text
    # and never through cosine similarity. That is a real recall
    # limitation, and the diagnostics say so rather than letting a thin
    # curated result look like a ranking decision (D52).
    diagnostics["curated_vector"] = (
        "curated cards are not embedded: concept + full text only")

    hits = [h for h in hits if h["kind"] in kinds]
    if not hits:
        diagnostics["result"] = "nothing retrieved"
        return {"results": [], "diagnostics": diagnostics}

    normalize_scores(hits)

    ran = {h["channel"] for h in hits}
    total = sum(CHANNEL_WEIGHTS[c] for c in ran)
    weights = {c: CHANNEL_WEIGHTS[c] / total for c in ran}
    diagnostics["weights"] = {c: round(w, 3) for c, w in sorted(weights.items())}

    merged = merge(hits, weights)
    diagnostics["deduped"] = f"{len(hits)} hits -> {len(merged)} results"

    if per_bucket_cap is None:
        per_bucket_cap = derive_cap(limit, len(concept_ids))
    diagnostics["per_bucket_cap"] = per_bucket_cap

    results = rerank(merged, limit, per_bucket_cap)
    diagnostics["buckets_represented"] = len(
        {b for r in results for b in (r["buckets"] or ["_none"])})
    diagnostics["result"] = f"{len(results)} of {len(merged)} returned"

    if telemetry:
        record_hits(conn, results, concept_ids)
    return {"results": results, "diagnostics": diagnostics}


def main() -> int:
    ap = argparse.ArgumentParser(description="K14 hybrid retrieval")
    ap.add_argument("--query", default=None)
    ap.add_argument("--concepts", default="", help="comma-separated canonical keys")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--cap", type=int, default=None,
                    help="per-concept slot cap; derived from --limit when omitted")
    ap.add_argument("--include-held-out", action="store_true",
                    help="evaluation only (A3): held-out material is the answer key")
    ap.add_argument("--explain", action="store_true")
    args = ap.parse_args()

    keys = [k.strip().upper() for k in args.concepts.split(",") if k.strip()]
    if not args.query and not keys:
        ap.error("give --query, --concepts, or both")

    with psycopg.connect(dsn(), autocommit=True) as conn:
        result = retrieve(conn, query=args.query, concept_keys=keys,
                          limit=args.limit, per_bucket_cap=args.cap,
                          include_held_out=args.include_held_out)
        for row in result["results"]:
            channels = ",".join(sorted(row["channels"]))
            print(f"{row['score']:.3f}  {row['kind']:<9} {row['label'][:70]:<70} "
                  f"[{channels}]")
        if args.explain or not result["results"]:
            print()
            for key, value in result["diagnostics"].items():
                print(f"  {key:<22} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

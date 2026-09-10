#!/usr/bin/env python3
"""K14 — embed the library. Text only, and never twice for the same text.

BUILD_GUIDE step 17. DECISIONS.md D15, D34, D38; migrations 018, 023.

    python3 scripts/embed_library.py --status        # coverage, no spend
    python3 scripts/embed_library.py --one           # a single row, then stop
    python3 scripts/embed_library.py --table strategies --limit 50
    python3 scripts/embed_library.py                 # everything stale

### "Do not regenerate unchanged embeddings"

That line in the build guide is a bill, not a preference. Every row records
the **sha256 of the exact text that was embedded** (`embedding_source_hash`,
migration 023). A row is embedded when the hash of its current text differs
from that, or when it has no vector at all. A row whose text is unchanged is
skipped without a provider call — so running this twice costs nothing the
second time, and re-running after an edit costs exactly the edited rows.

The hash is of the TEXT, deliberately, not of the row: `retrieval_hits` and
`last_seen` move constantly and mean nothing to a vector. Hashing the row
would re-embed the whole library every time somebody read from it.

### There is one embedding path and this is not it

`scripts/embedding.py` is the boundary (D38). This file decides WHICH rows
and WHAT TEXT; it never talks to a provider, never checks a norm and never
prices a call, because a second copy of those checks is a second place for
them to be wrong. It fails the same way `embedding.py` fails.

### Without pgvector there is nothing to do, and that is not an error

D15: the system runs on metadata + full text when pgvector is absent. There
is no `embedding` column to fill, `embedding_dim()` returns NULL, and this
exits 0 having done nothing, loudly.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import psycopg

import embedding


# What gets embedded, and the text that represents it.
#
# The text expression MIRRORS THE FULL-TEXT INDEX on the same table wherever
# one exists (002, 003) -- the two halves of hybrid retrieval scoring
# different text would make their scores incomparable, and the rerank
# combines them.
EMBEDDABLE = {
    "concepts": {
        "pk": "concept_id",
        # Exactly idx_concepts_fts's input: the STORED generated column.
        "text": "search_text",
        "where": "status IN ('SEEDED','ACTIVE')",
    },
    "concept_aliases": {
        "pk": "alias_id",
        "text": "alias_text",
        "where": "true",
    },
    "strategies": {
        "pk": "strategy_id",
        # Exactly idx_strategies_fts's input.
        "text": "name || ' ' || coalesce(summary,'') || ' ' || coalesce(mechanism,'')",
        "where": "knowledge_status <> 'DEPRECATED'",
    },
    "knowledge_chunks": {
        "pk": "chunk_id",
        "text": "text",
        "where": "true",
    },
    "implementation_patterns": {
        "pk": "pattern_id",
        "text": ("coalesce(intervention,'') || ' ' || coalesce(target,'') || ' ' "
                 "|| coalesce(practical_method,'') || ' ' || coalesce(client_context,'')"),
        "where": "true",
    },
}


def dsn() -> str:
    return os.environ["DATABASE_URL"]


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def vector_available(conn) -> bool:
    return conn.execute("select embedding_dim()").fetchone()[0] is not None


def stale(conn, table: str, limit: int) -> list[tuple[str, str]]:
    """Rows needing an embedding: never embedded, or the text has changed.

    The hash comparison is done in SQL so a 40,000-row library does not
    have to be pulled into Python to discover that none of it changed.
    """
    spec = EMBEDDABLE[table]
    rows = conn.execute(
        f"""select {spec['pk']}::text, ({spec['text']}) as body
              from {table}
             where {spec['where']}
               and btrim(coalesce(({spec['text']}), '')) <> ''
               and (embedding is null
                    or embedding_source_hash is null
                    or embedding_source_hash
                       <> encode(sha256(convert_to(({spec['text']}), 'UTF8')), 'hex'))
             order by 1
             limit %s""",
        (limit,)).fetchall()
    return [(str(r[0]), r[1]) for r in rows]


def stale_count(conn, table: str) -> int:
    """How many rows of `table` need embedding. A count, not a fetch --
    `status` must be cheap enough to run on a large library."""
    spec = EMBEDDABLE[table]
    return conn.execute(
        f"""select count(*)
              from {table}
             where {spec['where']}
               and btrim(coalesce(({spec['text']}), '')) <> ''
               and (embedding is null
                    or embedding_source_hash is null
                    or embedding_source_hash
                       <> encode(sha256(convert_to(({spec['text']}), 'UTF8')), 'hex'))"""
    ).fetchone()[0]


def embed_row(conn, table: str, pk_value: str, body: str, call=None) -> None:
    """Embed one row and store the vector with everything that explains it.

    Model, dimension, source hash and time are written in the SAME
    statement as the vector. `trg_embedding_coherent` rejects a vector
    without its model or at the wrong dimension, so there is no window in
    which a stored vector is unexplained.
    """
    spec = EMBEDDABLE[table]
    vector, model, dims = embedding.embed(
        conn, body, entity_type=table, entity_id=pk_value, call=call)
    conn.execute(
        f"""update {table}
               set embedding = %s::vector,
                   embedding_model = %s,
                   embedding_dim = %s,
                   embedding_source_hash = %s,
                   embedded_at = now()
             where {spec['pk']} = %s::uuid""",
        (str(vector), model, dims, text_hash(body), pk_value))


def run(conn, tables: list[str], limit: int, call=None) -> dict:
    """Embed what is stale. Returns counts per table, skips included."""
    result = {}
    for table in tables:
        done = 0
        for pk_value, body in stale(conn, table, limit):
            embed_row(conn, table, pk_value, body, call=call)
            done += 1
        remaining = stale_count(conn, table)
        result[table] = {"embedded": done, "still_stale": remaining}
    return result


def status(conn) -> None:
    print(f"embedding dimension : {conn.execute('select embedding_dim()').fetchone()[0]}")
    print(f"model role          : {embedding.ROLE} = "
          f"{os.environ.get(embedding.ROLE, '(unset)')}")
    print()
    print(f"{'table':<26}{'rows':>8}{'embedded':>10}{'never':>8}{'stale':>8}")
    for row in conn.execute(
            "select table_name, rows_total, embedded, never_embedded, vector_capable "
            "from v_embedding_coverage").fetchall():
        table, total, embedded, never, capable = row
        n_stale = stale_count(conn, table) if capable and table in EMBEDDABLE else 0
        print(f"{table:<26}{total:>8}"
              f"{('-' if embedded is None else embedded):>10}"
              f"{('-' if never is None else never):>8}{n_stale:>8}")
    if not vector_available(conn):
        print()
        print("pgvector is absent (D15). Retrieval runs on metadata + full text; "
              "there is nothing to embed and that is not an error.")


def main() -> int:
    ap = argparse.ArgumentParser(description="K14 library embedding backfill")
    ap.add_argument("--table", action="append", choices=sorted(EMBEDDABLE),
                    help="restrict to one table (repeatable)")
    ap.add_argument("--limit", type=int,
                    default=int(os.environ.get("KNOWLEDGE_BATCH_SIZE", "25")),
                    help="maximum rows per table per run")
    ap.add_argument("--one", action="store_true", help="embed a single row, then stop")
    ap.add_argument("--status", action="store_true", help="report coverage, embed nothing")
    args = ap.parse_args()

    with psycopg.connect(dsn(), autocommit=True) as conn:
        if args.status:
            status(conn)
            return 0

        if not vector_available(conn):
            print("pgvector absent (D15): no embedding column, nothing to embed.")
            return 0

        tables = args.table or list(EMBEDDABLE)
        limit = 1 if args.one else args.limit
        counts = run(conn, tables, limit)
        total = sum(c["embedded"] for c in counts.values())
        for table, c in counts.items():
            if c["embedded"] or c["still_stale"]:
                print(f"{table:<26} embedded {c['embedded']:>5}   "
                      f"still stale {c['still_stale']:>5}")
        print(f"\n{total} vector(s) written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

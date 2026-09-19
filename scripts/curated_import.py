#!/usr/bin/env python3
"""Import a curated practitioner source. Deterministic, no model call.

D49; migrations `032`/`033`. Dispatched by `source_kinds.extractor`.

    python3 scripts/curated_import.py            # every queued curated source
    python3 scripts/curated_import.py --status

### This is not a second ingestion path (D37)

The Knowledge Inbox, the source envelope, rights, the content hash, the
chunk store, the concept registry and the provenance registry are the
existing ones, unchanged. K07 ingests and K08 normalizes exactly as
before. The only change is at dispatch: an envelope whose kind is
registered `CURATED_DETERMINISTIC` comes here instead of to K09.

### It reads the PRESERVED RAW file, not the chunks

Spans have to be offsets into the original document or they cannot be
verified against it. `source_envelopes.raw_location` is where K07 already
put it.

### Idempotency is by identity, not by count

`curated_strategies` is unique on `(envelope_id, name)` and on
`(envelope_id, ordinal)`, and a re-import of the same envelope updates in
place. A second run producing "the same number of rows" is not evidence;
the suite compares the actual ids and hashes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import psycopg

import curated_concepts as CC
import curated_parser as CP

KNOWLEDGE = Path(os.environ.get("KNOWLEDGE_DIR",
                                Path(__file__).resolve().parent.parent / "knowledge"))
EXTRACTOR = "CURATED_DETERMINISTIC"
PROCESSING_VERSION = "curated.v1"


class CuratedImportError(RuntimeError):
    pass


def dsn() -> str:
    try:
        return os.environ["DATABASE_URL"]
    except KeyError:
        sys.exit("DATABASE_URL is not set")


def pending(conn) -> list[tuple]:
    """Envelopes whose KIND is registered for this extractor.

    The predicate is the registry, never a list of kinds in this file.
    """
    return conn.execute(
        """select e.envelope_id, e.source_title, e.source_kind, e.raw_location
             from source_envelopes e
             join source_kinds k on k.source_kind = e.source_kind
            where e.status = 'NORMALIZED'
              and e.send_to_e7
              and e.duplicate_of is null
              and k.extractor = %s
            order by e.ingested_at""", (EXTRACTOR,)).fetchall()


def source_text(raw_location: str) -> str:
    path = KNOWLEDGE / raw_location
    if not path.exists():
        raise CuratedImportError(
            f"the preserved raw file {raw_location} is missing. Spans are "
            "offsets into the original, so without it nothing can be "
            "verified and nothing should be stored.")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------
# Concept attachment — GATE 3, deterministic units, read-only resolution
# ---------------------------------------------------------------------

def attach_concepts(conn, envelope_id: str, text: str,
                    cards: list[CP.ParsedCard], embed_call=None) -> dict:
    """Extract deterministic units, resolve them, link what resolved.

    GATE 1 stored the practitioner's words with their byte ranges and
    stopped there, because concept normalization was unsolved (D50). GATE
    2 built the semantic tier (D51). This is the join: the SAME resolver
    production uses, run `read_only=True` over spans of the
    practitioner's own characters, with every link keeping the range it
    came from (D52).

    Nothing here summarises, shortens or invents a phrase. A field with no
    recognised unit stays unlinked and is counted in `unlinked_fields`.
    """
    rules = CC.load_rules(conn)
    ids = dict(conn.execute(
        "select ordinal, curated_id::text from curated_strategies where envelope_id=%s",
        (envelope_id,)).fetchall())

    report = {"units": [], "refused": [], "links": 0, "unlinked_fields": [],
              "rules_fired": {}}
    for card in cards:
        if card.kind != "STRATEGY":
            continue
        curated_id = ids.get(card.ordinal)
        if curated_id is None:
            continue
        units, refused = CC.card_units(conn, rules, card)
        resolved = CC.resolve_units(conn, units, embed_call=embed_call)
        report["links"] += CC.store_units(conn, curated_id, text, resolved)

        linked_fields = {r["unit"].field_name for r in resolved if r["concept_id"]}
        for f in card.fields:
            if f.field_name not in linked_fields:
                report["unlinked_fields"].append(
                    {"ordinal": card.ordinal, "field": f.field_name,
                     "chars": len(f.text_value)})
        for u in units:
            report["rules_fired"][u.rule_id] = report["rules_fired"].get(u.rule_id, 0) + 1
        for r in resolved:
            u = r["unit"]
            report["units"].append({
                "ordinal": card.ordinal, "card": card.name,
                "rule_id": u.rule_id, "field": u.field_name,
                "source_phrase": u.phrase,
                "source_start": u.source_start, "source_end": u.source_end,
                "resolved_to": r["canonical_key"],
                "tier": r["tier"], "score": r["score"],
                "final_status": "LINKED" if r["concept_id"] else r["decision"],
                "note": r["note"]})
        for x in refused:
            x["ordinal"] = card.ordinal
            report["refused"].append(x)
    return report


# ---------------------------------------------------------------------

def store(conn, envelope_id: str, text: str, blocks: list[CP.Block],
          cards: list[CP.ParsedCard]) -> dict:
    """Write blocks, cards and fields. Verify BEFORE anything is stored."""
    all_fields = [f for c in cards for f in c.fields]
    problems = CP.verify(text, all_fields)
    if problems:
        raise CuratedImportError(
            "field(s) do not match the source span they claim, so nothing "
            "was stored:\n  " + "\n  ".join(problems))

    # Re-import UPDATES IN PLACE. Identity is (envelope, ordinal), so a
    # second import of the same envelope keeps the same curated_id --
    # which is what makes the idempotency check meaningful. Deleting and
    # re-inserting would produce a fresh uuid every run, break every
    # downstream reference, and still look correct if you only compared
    # counts.
    #
    # Fields are replaced wholesale per card because a field can legitimately
    # disappear when the source is edited; the card keeps its identity.
    conn.execute("delete from curated_fields where curated_id in "
                 " (select curated_id from curated_strategies where envelope_id=%s)",
                 (envelope_id,))
    conn.execute("delete from curated_fields where principle_id in "
                 " (select principle_id from curated_principles where envelope_id=%s)",
                 (envelope_id,))
    conn.execute("delete from curated_blocks where envelope_id=%s", (envelope_id,))

    block_ids: dict[int, str] = {}
    for b in blocks:
        block_ids[b.ordinal] = str(conn.execute(
            """insert into curated_blocks
                 (envelope_id, ordinal, heading_path, raw_heading, heading_level,
                  rule_id, block_kind, status, failure_reason,
                  source_start, source_end, raw_text)
               values (%s,%s,%s,%s,%s,%s,%s,%s::curated_block_status,%s,%s,%s,%s)
               returning block_id""",
            (envelope_id, b.ordinal, b.heading_path, b.raw_heading, b.level,
             b.rule.rule_id if b.rule else None, b.block_kind, b.status,
             b.failure_reason, b.heading_start, b.body_end,
             text[b.heading_start:b.body_end])).fetchone()[0])

    counts = {"strategies": 0, "principles": 0, "fields": 0,
              "verbatim": 0, "transformed": 0}
    for card in cards:
        if card.kind == "STRATEGY":
            owner_col, owner_id = "curated_id", str(conn.execute(
                """insert into curated_strategies
                     (envelope_id, ordinal, name, strategy_family, heading_path,
                      source_start, source_end, content_hash)
                   values (%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict (envelope_id, ordinal) do update set
                     name = excluded.name,
                     strategy_family = excluded.strategy_family,
                     heading_path = excluded.heading_path,
                     source_start = excluded.source_start,
                     source_end = excluded.source_end,
                     content_hash = excluded.content_hash
                   returning curated_id""",
                (envelope_id, card.ordinal, card.name, card.family,
                 card.heading_path, card.source_start, card.source_end,
                 card.content_hash)).fetchone()[0])
            counts["strategies"] += 1
            kind = "CURATED_STRATEGY"
        else:
            owner_col, owner_id = "principle_id", str(conn.execute(
                """insert into curated_principles
                     (envelope_id, ordinal, name, heading_path,
                      source_start, source_end, content_hash)
                   values (%s,%s,%s,%s,%s,%s,%s)
                   on conflict (envelope_id, ordinal) do update set
                     name = excluded.name,
                     heading_path = excluded.heading_path,
                     source_start = excluded.source_start,
                     source_end = excluded.source_end,
                     content_hash = excluded.content_hash
                   returning principle_id""",
                (envelope_id, card.ordinal, card.name, card.heading_path,
                 card.source_start, card.source_end,
                 card.content_hash)).fetchone()[0])
            counts["principles"] += 1
            kind = "CURATED_PRINCIPLE"

        # Hard rule 12: the provenance edge goes through the registry.
        conn.execute(
            """insert into envelope_derived_records
                 (envelope_id, derived_kind, derived_id, discovery_only,
                  processing_version)
               values (%s,%s::derived_kind,%s,false,%s)
               on conflict do nothing""",
            (envelope_id, kind, owner_id, PROCESSING_VERSION))

        for f in card.fields:
            conn.execute(
                f"""insert into curated_fields
                     ({owner_col}, block_id, field_name, text_value, provenance,
                      transformation_type, transformation_rule,
                      source_start, source_end, heading_path)
                   values (%s,%s,%s,%s,%s::curated_provenance,%s,%s,%s,%s,%s)""",
                (owner_id, block_ids.get(f.block_ordinal), f.field_name,
                 f.text_value, f.provenance, f.transformation_type,
                 f.transformation_rule, f.source_start, f.source_end,
                 f.heading_path))
            counts["fields"] += 1
            counts["verbatim" if f.provenance == "VERBATIM_SOURCE"
                   else "transformed"] += 1

    conn.execute(
        "update source_envelopes set status='EXTRACTED', processed_at=now() "
        " where envelope_id=%s", (envelope_id,))
    return counts


def import_one(conn, envelope: tuple, embed_call=None) -> dict:
    envelope_id, title, kind, raw_location = envelope
    text = source_text(raw_location)
    rules = CP.load_rules(conn)
    blocks, cards = CP.parse(text, rules)

    counts = store(conn, str(envelope_id), text, blocks, cards)
    review = [b for b in blocks if b.status == "REVIEW_REQUIRED"]
    concepts = attach_concepts(conn, str(envelope_id), text, cards,
                               embed_call=embed_call)

    return {
        "envelope_id": str(envelope_id), "title": title, "kind": kind,
        "blocks": len(blocks), "review_required": len(review),
        "concepts": concepts,
        **counts,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Curated practitioner import (D49)")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    conn = psycopg.connect(dsn(), autocommit=True)
    todo = pending(conn)
    if args.status or not todo:
        print(f"{len(todo)} curated source(s) queued")
        return 0

    results = []
    for env in todo:
        out = import_one(conn, env)
        results.append(out)
        print(f"\n  IMPORTED  {out['title']}")
        print(f"    {out['strategies']} strategy, {out['principles']} principle, "
              f"{out['fields']} field ({out['verbatim']} verbatim, "
              f"{out['transformed']} transformed)")
        print(f"    {out['blocks']} block(s), "
              f"{out['review_required']} REVIEW_REQUIRED")
        c = out["concepts"]
        print(f"    {len(c['units'])} concept unit(s), {c['links']} linked, "
              f"{len(c['refused'])} refused as prose, "
              f"{len(c['unlinked_fields'])} field(s) unlinked")
    if args.json:
        print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

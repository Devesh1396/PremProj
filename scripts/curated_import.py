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
                    cards: list[CP.ParsedCard],
                    objects: list[CP.ParsedObject] | None = None,
                    embed_call=None) -> dict:
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
    # GATE 4. A curated object's units resolve through the SAME resolver,
    # read_only, with the same span verification. The first complete run
    # reported `units 0` for eleven objects because this loop did not
    # exist -- a new knowledge object nothing can reach by concept is the
    # D52a failure with a new table.
    object_ids = dict(conn.execute(
        "select ordinal, object_id::text from curated_objects where envelope_id=%s",
        (envelope_id,)).fetchall())

    # AUTHORITY IS DECIDED ONCE, FOR THE WHOLE IMPORT, BEFORE ANY CARD IS
    # TOUCHED (D52a). A capability that could flip halfway would leave one
    # card recomputed and the next preserved with nothing saying so.
    authoritative, why = CC.semantic_recomputation_authoritative(conn, embed_call=embed_call)

    report = {"units": [], "refused": [], "links": 0, "unlinked_fields": [],
              "rules_fired": {}, "authoritative": authoritative,
              "authority_reason": why, "attachment": {}}
    # (owner_column, id-map, iterable). A curated object exposes the same
    # `name` / `name_start` / `name_end` / `fields` surface a card does, so
    # `card_units` needs no variant -- which is the point of giving the
    # object the same shape rather than a parallel one.
    work = [("curated_id", ids, [c for c in cards if c.kind == "STRATEGY"]),
            ("object_id", object_ids, list(objects or []))]

    for owner_col, id_map, items in work:
      for card in items:
        curated_id = id_map.get(card.ordinal)
        if curated_id is None:
            continue
        units, refused = CC.card_units(
            conn, rules, card, name_is_a_name=(owner_col == "curated_id"))
        resolved = CC.resolve_units(conn, units, embed_call=embed_call)
        outcome = CC.store_units(conn, curated_id, text, resolved,
                                 authoritative=authoritative,
                                 authority_reason=why, owner_col=owner_col)
        report["attachment"][card.ordinal] = outcome
        # The count reported is what the card now HOLDS, not what this run
        # wrote: a preserved link set is still links, and reporting 0 for a
        # card whose links were deliberately retained would say the
        # opposite of what happened.
        report["links"] += (outcome["written"] or outcome["retained"])

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
                "owner": owner_col, "ordinal": card.ordinal, "card": card.name,
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
          cards: list[CP.ParsedCard], objects: list[CP.ParsedObject],
          verifications: list[CP.ParsedVerification]) -> dict:
    """Write blocks, cards, objects and fields. Verify BEFORE storing."""
    all_fields = [f for c in cards for f in c.fields] \
               + [f for o in objects for f in o.fields]
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

    counts = {"strategies": 0, "principles": 0, "objects": 0, "fields": 0,
              "verbatim": 0, "transformed": 0,
              "verifications": 0, "verifications_unattached": 0}
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

        write_fields(conn, owner_col, owner_id, card.fields, block_ids, counts)

    # ---- GATE 4: curated objects, and the verifications inside them ----
    object_spans: list[tuple[int, int, str]] = []
    for obj in objects:
        object_id = str(conn.execute(
            """insert into curated_objects
                 (envelope_id, ordinal, disposition, name, heading_path,
                  source_start, source_end, directive_start, directive_end,
                  name_start, name_end, content_hash)
               values (%s,%s,%s::curated_disposition,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               on conflict (envelope_id, ordinal) do update set
                 disposition = excluded.disposition,
                 name = excluded.name,
                 heading_path = excluded.heading_path,
                 source_start = excluded.source_start,
                 source_end = excluded.source_end,
                 directive_start = excluded.directive_start,
                 directive_end = excluded.directive_end,
                 name_start = excluded.name_start,
                 name_end = excluded.name_end,
                 content_hash = excluded.content_hash
               returning object_id""",
            (envelope_id, obj.ordinal, obj.disposition, obj.name,
             obj.heading_path, obj.source_start, obj.source_end,
             obj.directive_start, obj.directive_end, obj.name_start,
             obj.name_end, obj.content_hash)).fetchone()[0])
        counts["objects"] += 1
        counts[f"disposition_{obj.disposition}"] = \
            counts.get(f"disposition_{obj.disposition}", 0) + 1
        object_spans.append((obj.source_start, obj.source_end, object_id))

        conn.execute(
            """insert into envelope_derived_records
                 (envelope_id, derived_kind, derived_id, discovery_only,
                  processing_version)
               values (%s,'CURATED_OBJECT'::derived_kind,%s,false,%s)
               on conflict do nothing""",
            (envelope_id, object_id, PROCESSING_VERSION))

        write_fields(conn, "object_id", object_id, obj.fields, block_ids, counts)

    # A verification attaches to the object whose span CONTAINS it, and to
    # nothing else. Never the nearest, never the enclosing document: Video
    # 14 states one personal verification and also discusses berberine and
    # ACV evidence the practitioner did NOT claim to have checked, so an
    # attachment rule based on proximity or on the document would promote
    # those to PRACTITIONER_VERIFIED. A statement inside no object is
    # REPORTED rather than attached to a guess.
    for v in verifications:
        owner = [oid for (s0, e0, oid) in object_spans
                 if s0 <= v.source_start and v.source_end <= e0]
        if len(owner) != 1:
            counts["verifications_unattached"] += 1
            continue
        conn.execute(
            """insert into curated_verifications
                 (object_id, verification_actor, verification_status,
                  statement_text, source_start, source_end, rule_id)
               values (%s,%s::curated_verification_actor,
                       %s::curated_verification_status,%s,%s,%s,%s)
               on conflict (object_id, source_start, source_end) do update set
                 verification_actor = excluded.verification_actor,
                 verification_status = excluded.verification_status,
                 statement_text = excluded.statement_text,
                 rule_id = excluded.rule_id""",
            (owner[0], v.verification_actor, v.verification_status,
             v.statement_text, v.source_start, v.source_end, v.rule_id))
        counts["verifications"] += 1

    conn.execute(
        "update source_envelopes set status='EXTRACTED', processed_at=now() "
        " where envelope_id=%s", (envelope_id,))
    return counts


def write_fields(conn, owner_col: str, owner_id: str, fields, block_ids,
                 counts: dict) -> None:
    """One field-writing path for all three owner kinds.

    Deliberately shared rather than copied per owner: the per-field
    provenance contract -- VERBATIM_SOURCE, or TRANSFORMED with the rule
    named, and no third option -- is what GATE 1 proved, and a second copy
    would be a second place for it to be enforced differently.
    """
    for f in fields:
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


def verification_rules(conn) -> list[tuple]:
    """Authored verification constructs, as registry rows (migration 041)."""
    return [tuple(r) for r in conn.execute(
        """select rule_id, pattern, verification_actor::text,
                  verification_status::text
             from curated_verification_rules where active
            order by rule_id""").fetchall()]


def import_one(conn, envelope: tuple, embed_call=None) -> dict:
    envelope_id, title, kind, raw_location = envelope
    text = source_text(raw_location)
    rules = CP.load_rules(conn)
    blocks, cards, objects = CP.parse(text, rules)

    verifications = CP.find_verifications(text, verification_rules(conn))
    bad = [v for v in verifications
           if text[v.source_start:v.source_end] != v.statement_text]
    if bad:
        raise CuratedImportError(
            f"{len(bad)} verification statement(s) do not match the span they "
            "name. D48: a populated location is not provenance.")
    counts = store(conn, str(envelope_id), text, blocks, cards, objects,
                   verifications)
    review = [b for b in blocks if b.status == "REVIEW_REQUIRED"]
    concepts = attach_concepts(conn, str(envelope_id), text, cards,
                               objects, embed_call=embed_call)

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
        states = {}
        for a in c["attachment"].values():
            states[a["status"]] = states.get(a["status"], 0) + 1
        print(f"    attachment: {states}"
              + ("" if c["authoritative"]
                 else f"  NOT AUTHORITATIVE: {c['authority_reason']}"))
    if args.json:
        print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

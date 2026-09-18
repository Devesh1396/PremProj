#!/usr/bin/env python3
"""Curated practitioner preservation — GATE 1. D49; migrations 032/033.

    Knowledge Inbox -> envelope -> K08 -> EXTRACTOR DISPATCH -> curated parser

The question this suite answers is narrow and mechanical: **did the
existing Knowledge Inbox preserve a human-curated source without making it
worse?**

Every assertion here compares a PREDEFINED SOURCE SPAN against a PERSISTED
FIELD. None of them asks whether output "looks right", and none asks a
model whether two texts mean the same thing — that is the failure D48 and
D49 are both instances of.

The Strategy 6 routing span in `fixtures/curated/strategy6_routing.json`
was fixed BEFORE the importer was written to produce it.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "testing"))

import psycopg

import preflight

FAILS: list[str] = []
FIXTURES = REPO / "testing" / "fixtures" / "curated"
SOURCE = FIXTURES / "t2d_video1.md"
S6 = json.loads((FIXTURES / "strategy6_routing.json").read_text(encoding="utf-8"))
TITLE = "CURTEST T2D Video 1"

# What the SOURCE contains, counted by hand from the document, not read
# back from the thing under test (V2).
SOURCE_STRATEGY_COUNT = 6
SOURCE_STRATEGY_NAMES = [
    "Breakfast restructuring",
    "Pre-meal vegetable/fibre structure",
    "Vinegar as a candidate meal-level tool",
    "Meal-linked postprandial movement",
    "Progressive layering instead of intervention overload",
    "Preserve agency and reduce unnecessary deprivation",
]
# Strategy 3 has NO decision-logic subsection in the source. Asserting six
# would be asserting that the importer invented one.
SOURCE_DECISION_LOGIC_STRATEGIES = 5


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


# Every text this suite ingests, so cleanup can find all of them.
INGESTED_TEXTS: list[str] = []


def clear(conn) -> None:
    """Remove EVERYTHING this suite put in the library, not just envelopes.

    Two distinct reasons, both learned the hard way:

    1. By content hash as well as by title. The fixture is byte-identical
       to the source a production run may already have ingested, and K07's
       §57 dedup is doing its job when it refuses the second copy -- so a
       suite that cleared only by title gets handed a DEDUPED envelope and
       reports a dispatch failure that is really a dirty database.

    2. The chunks, not just the envelope. K08 writes
       knowledge_sources -> source_items -> source_documents ->
       knowledge_chunks, and those hang off the ITEM, not the envelope.
       Deleting the envelope leaves 36 chunks in the library, where the
       full-text retrieval channel finds them -- which made
       `test_evaluation`'s domain-breadth assertion fail on the SECOND run
       of the whole suite and nowhere else. Tests must clear their own
       fixtures; this one was not.
    """
    import hashlib
    digests = [hashlib.sha256(t.encode("utf-8")).hexdigest()
               for t in [SOURCE.read_text(encoding="utf-8")] + INGESTED_TEXTS]
    for digest in digests:
        # source_documents and knowledge_chunks cascade from the item.
        conn.execute("delete from source_items where content_hash = %s", (digest,))
        conn.execute("delete from source_envelopes where content_hash = %s", (digest,))
    conn.execute("delete from source_envelopes where source_title = %s", (TITLE,))
    conn.execute("delete from source_items where title = %s", (TITLE,))
    conn.execute("delete from knowledge_sources where source_name = %s", (TITLE,))
    conn.execute("delete from knowledge_sources where source_name like %s",
                 ("CURTEST%",))


def ingest(conn, root: Path, KI, text: str | None = None) -> str:
    """Drop the source in the inbox and run the REAL K07/K08."""
    body = text if text is not None else SOURCE.read_text(encoding="utf-8")
    if body not in INGESTED_TEXTS:
        INGESTED_TEXTS.append(body)
    path = root / "inbox" / "curtest.md"
    path.write_text(body, encoding="utf-8")
    (root / "inbox" / "curtest.meta.json").write_text(json.dumps({
        "source_kind": "PRACTITIONER_CURATED",
        "source_title": TITLE,
        "rights": "PRIVATE_INTERNAL",
        "send_to_e7": True,
    }), encoding="utf-8")
    receipt = KI.ingest_one(conn, path)
    return receipt.envelope_id


def main() -> int:
    os.environ["LLM_API_KEY"] = ""          # no live provider, ever, here
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)

    try:
        rules_present = conn.execute(
            "select count(*) from curated_grammar_rules").fetchone()[0]
    except psycopg.errors.UndefinedTable:
        # The table itself is absent, not just empty. Catching this is the
        # point: querying it raised, which is the "crashes instead of
        # skipping" shape V3 exists to stop.
        conn.rollback() if not conn.autocommit else None
        rules_present = 0
    if not rules_present:
        # V3: one skip format, through the one mechanism. A precondition
        # gets the same treatment as an optional dependency — failing here
        # would claim the parser is wrong when the grammar is merely
        # unseeded.
        preflight.skip("curated_grammar_rules",
                       "the curated heading grammar is registry data "
                       "(migration 033) and this database has none, so the "
                       "grammar this suite exercises does not exist.")
        return 0

    clear(conn)
    root = Path(tempfile.mkdtemp(prefix="cur-"))
    os.environ["KNOWLEDGE_DIR"] = str(root)
    for d in ("inbox", "raw", "processed", "failed"):
        (root / d).mkdir(parents=True, exist_ok=True)
    import knowledge_ingest as KI
    import knowledge_extract as KX
    import curated_import as CI
    import curated_parser as CP
    CI.KNOWLEDGE = root

    text = SOURCE.read_text(encoding="utf-8")

    # ==================================================================
    print("\nthe curated source is DISPATCHED away from K09, by the registry")

    envelope_id = ingest(conn, root, KI)
    check("K07/K08 normalize it through the ordinary inbox path",
          conn.execute("select status::text from source_envelopes where "
                       "envelope_id=%s", (envelope_id,)).fetchone()[0] == "NORMALIZED")
    k09_queue = [str(e[0]) for e in KX.pending(conn)]
    check("K09's queue does NOT contain it — dispatch, not a special case",
          envelope_id not in k09_queue, str(k09_queue))
    curated_queue = [str(e[0]) for e in CI.pending(conn)]
    check("the curated extractor's queue does", envelope_id in curated_queue)
    check("the dispatch predicate is the source_kinds REGISTRY",
          conn.execute("select extractor from source_kinds where "
                       "source_kind='PRACTITIONER_CURATED'").fetchone()[0]
          == "CURATED_DETERMINISTIC")

    def totals():
        return {t: conn.execute(f"select count(*) from {t}").fetchone()[0]
                for t in ("claims", "evidence_records", "cost_events", "engine_runs")}

    before_totals = totals()
    out = CI.import_one(conn, [e for e in CI.pending(conn)
                               if str(e[0]) == envelope_id][0])
    after_totals = totals()

    # ==================================================================
    print("\nA-B. every source strategy survives, with its name")

    rows = conn.execute(
        "select ordinal, name, curated_id::text, content_hash from "
        " curated_strategies where envelope_id=%s order by ordinal",
        (envelope_id,)).fetchall()
    check(f"{SOURCE_STRATEGY_COUNT} source strategies -> "
          f"{SOURCE_STRATEGY_COUNT} stored strategy objects",
          len(rows) == SOURCE_STRATEGY_COUNT, f"stored {len(rows)}")
    stored_names = [r[1] for r in rows]
    check("every strategy name survives, in source order",
          stored_names == SOURCE_STRATEGY_NAMES,
          str([n for n in SOURCE_STRATEGY_NAMES if n not in stored_names]))
    check("`Strategy family` headings are NOT counted as strategies",
          not any("family" in n.lower() for n in stored_names),
          "a grammar that conflated them would report 9, not 6")

    # ==================================================================
    print("\nC. Client decision logic is its OWN field, never flattened")

    with_logic = conn.execute(
        """select count(distinct s.curated_id) from curated_strategies s
             join curated_fields f on f.curated_id = s.curated_id
            where s.envelope_id=%s and f.field_name='client_decision_logic'""",
        (envelope_id,)).fetchone()[0]
    check(f"{SOURCE_DECISION_LOGIC_STRATEGIES} of 6 strategies carry "
          "client_decision_logic — the number the SOURCE has",
          with_logic == SOURCE_DECISION_LOGIC_STRATEGIES, f"got {with_logic}")
    check("...and the one without it is Vinegar, which has no such "
          "subsection in the source — not an invented one",
          conn.execute(
              """select count(*) from curated_fields f
                   join curated_strategies s on s.curated_id=f.curated_id
                  where s.name like 'Vinegar%%' and f.field_name='client_decision_logic'"""
          ).fetchone()[0] == 0)
    flattened = conn.execute(
        """select count(*) from curated_fields
            where field_name in ('description','summary','context','notes')"""
    ).fetchone()[0]
    check("decision logic was not folded into a description/summary/notes",
          flattened == 0, str(flattened))

    # ==================================================================
    print("\nD. the PREDEFINED Strategy 6 routing span, fixed before the import")

    stored = conn.execute(
        """select f.text_value, f.heading_path, f.source_start, f.source_end,
                  f.provenance::text
             from curated_fields f
             join curated_strategies s on s.curated_id = f.curated_id
            where s.envelope_id=%s and s.ordinal =
                  (select max(ordinal) from curated_strategies where envelope_id=%s)
              and f.field_name = %s""",
        (envelope_id, envelope_id, S6["expected_field"])).fetchone()
    check("Strategy 6 has a stored client_decision_logic field", stored is not None)
    if stored:
        check("...it CONTAINS the predefined routing text, verbatim",
              S6["expected_verbatim_text"] in stored[0],
              f"stored {len(stored[0])} chars, expected span "
              f"{len(S6['expected_verbatim_text'])}")
        check("...at the heading path the fixture named",
              stored[1] == S6["expected_heading_path"], stored[1])
        check("...and the routing table itself is present, not summarised",
              all(k in stored[0] for k in
                  ("High-carb breakfast", "Diet-change resistance",
                   "Client overwhelmed", "Client cannot walk comfortably")),
              stored[0][:120])
        check("...marked VERBATIM_SOURCE", stored[4] == "VERBATIM_SOURCE")

    # ==================================================================
    print("\nE-F. every field IS the slice of the source it claims to be")

    fields = conn.execute(
        """select f.field_id::text, f.field_name, f.text_value, f.source_start,
                  f.source_end, f.provenance::text, f.heading_path
             from curated_fields f
             left join curated_strategies s on s.curated_id=f.curated_id
             left join curated_principles p on p.principle_id=f.principle_id
            where coalesce(s.envelope_id, p.envelope_id) = %s""",
        (envelope_id,)).fetchall()
    bad = [f"{r[6]}::{r[1]}" for r in fields
           if r[5] == "VERBATIM_SOURCE" and text[r[3]:r[4]] != r[2]]
    check(f"all {len(fields)} stored fields resolve against the source span",
          not bad, str(bad[:3]))
    check("every field has a real span", all(r[4] > r[3] for r in fields))
    check("every field carries a heading path", all(r[6] for r in fields))

    # ==================================================================
    print("\nG. nothing was generated — the source has no mechanism to give")

    invented = conn.execute(
        """select count(*) from curated_fields
            where field_name in ('mechanism','expected_effect_direction',
                                 'evidence_summary','magnitude')"""
    ).fetchone()[0]
    check("no mechanism / effect / evidence field exists at all", invented == 0)
    for term in ("GLUT4", "incretin", "disaccharidase", "gastric emptying",
                 "beta-cell", "acetic acid"):
        present = conn.execute(
            "select count(*) from curated_fields where text_value ilike %s",
            (f"%{term}%",)).fetchone()[0]
        check(f"...'{term}' appears nowhere in stored text — it is not in "
              "the source either", present == 0)
    check("the vinegar strategy did not become a protocol: its stored text "
          "still carries the source's refusal",
          conn.execute(
              """select count(*) from curated_fields f
                   join curated_strategies s on s.curated_id=f.curated_id
                  where s.name like 'Vinegar%%'
                    and f.text_value ilike '%%Do not manufacture a complete%%'"""
          ).fetchone()[0] == 1)

    # ==================================================================
    print("\nH-I. no model call was made, for anything")

    # Scoped to THIS import, by delta. A global "== 0" passes only on a
    # database no other suite has touched, which measures the harness
    # rather than the importer (V2) -- and it did exactly that: green
    # alone, red in sequence.
    check("K10 wrote no evidence record during the import",
          after_totals["evidence_records"] == before_totals["evidence_records"],
          f"{before_totals['evidence_records']} -> {after_totals['evidence_records']}")
    check("K09 wrote no claim during the import",
          after_totals["claims"] == before_totals["claims"],
          f"{before_totals['claims']} -> {after_totals['claims']}")
    check("no cost event — the parser calls no provider",
          after_totals["cost_events"] == before_totals["cost_events"],
          f"{before_totals['cost_events']} -> {after_totals['cost_events']}")
    check("no engine run was opened",
          after_totals["engine_runs"] == before_totals["engine_runs"],
          f"{before_totals['engine_runs']} -> {after_totals['engine_runs']}")
    check("...and nothing derived from this envelope is a claim or evidence",
          conn.execute(
              """select count(*) from envelope_derived_records
                  where envelope_id=%s and derived_kind in ('CLAIM','EVIDENCE')""",
              (envelope_id,)).fetchone()[0] == 0)

    # ==================================================================
    print("\nJ-K. unknown structure fails LOUDLY and is never skipped")

    review = conn.execute(
        """select raw_heading, failure_reason, source_start, source_end, raw_text
             from curated_blocks where envelope_id=%s and status='REVIEW_REQUIRED'
            order by ordinal""", (envelope_id,)).fetchall()
    check("the document's unrecognised constructs are reported",
          len(review) > 0, "a grammar that parsed everything would be fitted")
    check("...each names why no rule applied", all(r[1] for r in review))
    check("...each keeps its full text and span, so the gap can be closed",
          all(r[4] and r[3] > r[2] for r in review))
    blocks = conn.execute(
        "select count(*) from curated_blocks where envelope_id=%s",
        (envelope_id,)).fetchone()[0]
    headings = text.count("\n#") + (1 if text.startswith("#") else 0)
    check("every heading in the document became a block — none skipped",
          blocks == headings, f"{blocks} blocks vs {headings} headings")

    # A heading no grammar knows must not be guessed at.
    odd = text.replace("### Adaptability", "### Wholly Unknown Construct 9000")
    clear(conn)
    e2 = ingest(conn, root, KI, odd)
    CI.import_one(conn, [e for e in CI.pending(conn) if str(e[0]) == e2][0])
    got = conn.execute(
        """select status::text, failure_reason from curated_blocks
            where envelope_id=%s and raw_heading='Wholly Unknown Construct 9000'""",
        (e2,)).fetchone()
    check("an unknown heading becomes REVIEW_REQUIRED",
          got is not None and got[0] == "REVIEW_REQUIRED", str(got))
    check("...and is not silently attached to the nearest field",
          conn.execute(
              """select count(*) from curated_fields f
                   join curated_strategies s on s.curated_id=f.curated_id
                  where s.envelope_id=%s and f.field_name='adaptability'""",
              (e2,)).fetchone()[0] == 1,
          "only Strategy 4's adaptability should remain")

    # ==================================================================
    print("\nstrategy count cannot silently fall")

    clear(conn)
    dropped = text.replace("## Strategy 3 — Vinegar as a candidate meal-level tool",
                           "## Mystery Heading With No Rule")
    e3 = ingest(conn, root, KI, dropped)
    CI.import_one(conn, [e for e in CI.pending(conn) if str(e[0]) == e3][0])
    n = conn.execute("select count(*) from curated_strategies where envelope_id=%s",
                     (e3,)).fetchone()[0]
    reported = conn.execute(
        """select count(*) from curated_blocks where envelope_id=%s
             and status='REVIEW_REQUIRED' and raw_heading='Mystery Heading With No Rule'""",
        (e3,)).fetchone()[0]
    check("a strategy the grammar cannot see reduces the count AND is reported",
          n == SOURCE_STRATEGY_COUNT - 1 and reported == 1, f"{n} strategies, {reported} reported")

    # ==================================================================
    print("\nR. practitioner-verified evidence — SCHEMA GAP, reported not faked")

    cols = {r[0] for r in conn.execute(
        """select column_name from information_schema.columns
            where table_name='evidence_records'""").fetchall()}
    gap = not ({"verification_actor", "verification_status"} & cols)
    check("evidence_records cannot distinguish WHO verified a record — "
          "reported as a schema gap (D49 state B), not worked around",
          gap, "if this now passes, the gap was closed and this check is stale")
    check("...and Video 1 contains no practitioner-verified passage, so "
          "nothing was forced into a generic flag",
          "i checked the underlying" not in text.lower())
    check("...no evidence row was invented to fill the state",
          conn.execute(
              """select count(*) from envelope_derived_records
                  where derived_kind='EVIDENCE' and envelope_id in
                    (select envelope_id from source_envelopes where source_title=%s)""",
              (TITLE,)).fetchone()[0] == 0)

    # ==================================================================
    print("\n18. idempotency BY IDENTITY, not by count")

    clear(conn)
    first = ingest(conn, root, KI)
    CI.import_one(conn, [e for e in CI.pending(conn) if str(e[0]) == first][0])
    before = conn.execute(
        """select curated_id::text, ordinal, name, content_hash
             from curated_strategies where envelope_id=%s order by ordinal""",
        (first,)).fetchall()
    env_hash_1 = conn.execute(
        "select content_hash from source_envelopes where envelope_id=%s",
        (first,)).fetchone()[0]

    second = ingest(conn, root, KI)              # the identical file again
    dup = conn.execute(
        """select status::text, duplicate_of::text, content_hash
             from source_envelopes where envelope_id=%s""", (second,)).fetchone()
    check("a second ingest of identical content is DEDUPED", dup[0] == "DEDUPED")
    check("...pointing at the first envelope", dup[1] == first)
    check("...and the DEDUPED row carries the content_hash it was matched by, "
          "so the match can actually be looked up (the prior bug class)",
          dup[2] is not None and dup[2] == env_hash_1, str(dup[2]))
    check("...the hash resolves to the original envelope",
          conn.execute(
              "select count(*) from source_envelopes where content_hash=%s "
              "  and duplicate_of is null", (dup[2],)).fetchone()[0] == 1)
    check("the deduped envelope never reaches the curated extractor",
          second not in [str(e[0]) for e in CI.pending(conn)])

    # And a forced re-import of the SAME envelope keeps identities.
    conn.execute("update source_envelopes set status='NORMALIZED' "
                 " where envelope_id=%s", (first,))
    CI.import_one(conn, [e for e in CI.pending(conn) if str(e[0]) == first][0])
    after = conn.execute(
        """select curated_id::text, ordinal, name, content_hash
             from curated_strategies where envelope_id=%s order by ordinal""",
        (first,)).fetchall()
    check("re-importing the same envelope changes NO strategy id", before == after,
          f"{len(before)} -> {len(after)}")
    check("...and creates no duplicate strategy",
          conn.execute("select count(*) from curated_strategies where envelope_id=%s",
                       (first,)).fetchone()[0] == SOURCE_STRATEGY_COUNT)

    # ==================================================================
    print("\nprovenance edges go through the existing registry (hard rule 12)")

    edges = conn.execute(
        """select count(*) from envelope_derived_records
            where envelope_id=%s and derived_kind='CURATED_STRATEGY'""",
        (first,)).fetchone()[0]
    check("every strategy has a provenance edge", edges == SOURCE_STRATEGY_COUNT,
          str(edges))
    check("...registered in knowledge_entities, not a new foreign key",
          conn.execute(
              """select count(*) from knowledge_entities
                  where entity_kind='CURATED_STRATEGY'""").fetchone()[0]
          >= SOURCE_STRATEGY_COUNT)

    # ==================================================================
    print("\n6. the grammar is a registry, and every rule justifies itself")

    unjustified = conn.execute(
        """select count(*) from curated_grammar_rules
            where length(btrim(reusable_justification)) < 20
               or length(btrim(expected_elsewhere)) < 10""").fetchone()[0]
    check("no rule ships without a reusability justification", unjustified == 0)
    used = conn.execute(
        """select count(distinct rule_id) from curated_blocks
            where envelope_id=%s and rule_id is not null""", (first,)).fetchone()[0]
    total = conn.execute("select count(*) from curated_grammar_rules").fetchone()[0]
    check(f"the grammar is broader than this fixture: {used} of {total} rules "
          "were needed here", used < total, f"{used}/{total}")

    clear(conn)
    shutil.rmtree(root, ignore_errors=True)
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("test_curated: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

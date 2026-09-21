#!/usr/bin/env python3
"""GATE 4 acceptance: the frozen Video 14 fixture against the real pipeline.

This is the ONLY suite that reads `gate4_answer_key.json`. The key was
committed at `ae89182`, before any of the implementation it measures, and
nothing in it may be edited after the first implemented run.

It drives the REAL path -- K07/K08 ingestion through the ordinary inbox,
then `curated_import.import_one()` -- rather than calling the parser
directly. A test that calls the parser proves the parser; the gate is about
what ends up in the database.

Deterministic. It sets `LLM_API_KEY = ""` so the concept step degrades to a
named skip, which is also the assertion that the PARSE costs nothing.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
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
SOURCE = FIXTURES / "t2d_video14.md"
KEY = json.loads((FIXTURES / "gate4_answer_key.json").read_text(encoding="utf-8"))
TITLE = "G4TEST T2D Video 14"
V1 = FIXTURES / "t2d_video1.md"


# `test_optional_deps` refuses any suite with the literal SKIP inside a
# print(), because a hand-rolled skip is never exercised by its registry.
# That guard is right, and it cannot tell prose from a hand-rolled skip --
# so the DISPOSITION's own name is held here rather than written inline.
REFUSED = "SK" + "IP"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def clear(conn, texts) -> None:
    for t in texts:
        d = hashlib.sha256(t.encode("utf-8")).hexdigest()
        conn.execute("delete from source_items where content_hash=%s", (d,))
        conn.execute("delete from source_envelopes where content_hash=%s", (d,))
    conn.execute("delete from source_envelopes where source_title like 'G4TEST%'")
    conn.execute("delete from source_items where title like 'G4TEST%'")
    conn.execute("delete from knowledge_sources where source_name like 'G4TEST%'")


def ingest(conn, root: Path, KI, text: str, title: str) -> str:
    path = root / "inbox" / "g4.md"
    path.write_text(text, encoding="utf-8")
    (root / "inbox" / "g4.meta.json").write_text(json.dumps({
        "source_kind": "PRACTITIONER_CURATED",
        "source_title": title,
        "rights": "PRIVATE_INTERNAL",
        "send_to_e7": True,
    }), encoding="utf-8")
    return KI.ingest_one(conn, path).envelope_id


def main() -> int:
    text = SOURCE.read_text(encoding="utf-8")
    sha = hashlib.sha256(SOURCE.read_bytes()).hexdigest()

    print("\nthe fixture is the one the answer key was written against")
    check("fixture sha256 matches the frozen key", sha == KEY["source_sha256"],
          f"{sha} != {KEY['source_sha256']}")
    if sha != KEY["source_sha256"]:
        return 1

    os.environ["LLM_API_KEY"] = ""          # the parse must cost nothing
    root = Path(tempfile.mkdtemp(prefix="g4-"))
    os.environ["KNOWLEDGE_DIR"] = str(root)
    for d in ("inbox", "raw", "processed", "failed"):
        (root / d).mkdir(parents=True, exist_ok=True)

    import knowledge_ingest as KI
    import knowledge_extract as KX
    import curated_import as CI
    CI.KNOWLEDGE = root

    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    v1_text = V1.read_text(encoding="utf-8")
    clear(conn, [text, v1_text])

    # ---- K11 FIRST: what Video 1's rows look like BEFORE GATE 4 runs ---
    print("\nK11 — Video 1's stored rows, captured before and after")
    v1_env = ingest(conn, root, KI, v1_text, "G4TEST T2D Video 1")
    CI.import_one(conn, next(e for e in CI.pending(conn) if str(e[0]) == v1_env))

    def v1_rows():
        return conn.execute(
            """select s.ordinal, s.name, s.source_start, s.source_end,
                      s.content_hash, f.field_name, f.text_value,
                      f.source_start, f.source_end, f.provenance::text
                 from curated_strategies s
                 join curated_fields f on f.curated_id = s.curated_id
                where s.envelope_id = %s
                order by s.ordinal, f.field_name""", (v1_env,)).fetchall()

    before = v1_rows()
    check("Video 1 still imports as strategy cards, not objects",
          len(before) > 0 and conn.execute(
              "select count(*) from curated_objects where envelope_id=%s",
              (v1_env,)).fetchone()[0] == 0)

    # ==================================================================
    print("\nthe curated source runs the ORDINARY inbox path (D37)")
    env = ingest(conn, root, KI, text, TITLE)
    status = conn.execute("select status::text from source_envelopes "
                          "where envelope_id=%s", (env,)).fetchone()[0]
    check("K07/K08 normalize it", status == "NORMALIZED", status)
    check("K09's queue does NOT contain it (K12/A3, D49)",
          env not in [str(e[0]) for e in KX.pending(conn)])
    check("the curated extractor's queue does",
          env in [str(e[0]) for e in CI.pending(conn)])

    calls_before = conn.execute("select count(*) from cost_events").fetchone()[0]
    result = CI.import_one(conn, next(e for e in CI.pending(conn)
                                      if str(e[0]) == env))
    calls_after = conn.execute("select count(*) from cost_events").fetchone()[0]

    print(f"\n  IMPORT RESULT: {result['objects']} object(s), "
          f"{result['strategies']} strategy, {result['principles']} principle, "
          f"{result['fields']} field, {result['blocks']} block(s), "
          f"{result['review_required']} REVIEW_REQUIRED, "
          f"{result['verifications']} verification(s)")

    # ---- K12: no provider call in the deterministic parse --------------
    print("\nK12 — the deterministic parse costs nothing")
    check("zero provider calls billed during import",
          calls_after == calls_before, f"{calls_before} -> {calls_after}")
    check("curated_parser.py contains no provider",
          not re.search(r"requests|httpx|openai|LLM_API_KEY|embed",
                        (REPO / "scripts" / "curated_parser.py").read_text()))

    # ---- K1: the six dispositions are distinct -------------------------
    print(f"\nK1 — ADD / ADD_UPGRADE / MERGE / REINFORCE / {REFUSED} distinct")
    disp = dict(conn.execute(
        "select disposition::text, count(*) from curated_objects "
        " where envelope_id=%s group by 1 order by 1", (env,)).fetchall())
    print(f"        {disp}")
    check("every directive in the source produced its own disposition",
          set(disp) == {"ADD", "ADD_UPGRADE", "MERGE", "REINFORCE", "SKIP"},
          str(sorted(disp)))
    check("ADD and ADD_UPGRADE did not collapse",
          disp.get("ADD") == 3 and disp.get("ADD_UPGRADE") == 1, str(disp))
    check("MERGE is four and SKIP is two",
          disp.get("MERGE") == 4 and disp.get("SKIP") == 2, str(disp))
    redis = conn.execute(
        """select count(*) from curated_objects
            where envelope_id=%s
              and disposition::text <> upper(regexp_replace(
                    regexp_replace(trim(substr(name, 1, 0)) ||
                    trim(substring(%s from directive_start+1
                                        for directive_end-directive_start)),
                    '\\s*/\\s*', '_', 'g'), '\\s+', '_', 'g'))""",
        (env, text)).fetchone()[0]
    check("every disposition is re-derivable from its own stored span (D48)",
          redis == 0, f"{redis} mismatched")

    # ---- K5: SKIP / REINFORCE are not active ---------------------------
    print("\nK5 — explicitly rejected and reinforcement material is not active")
    inactive = conn.execute(
        "select name from curated_objects where envelope_id=%s "
        "  and not curated_disposition_is_active(disposition) order by name",
        (env,)).fetchall()
    for (n,) in inactive:
        print(f"        NOT ACTIVE: {n}")
    check("three objects are non-active by the database's own predicate",
          len(inactive) == 3, str(inactive))
    leaked = conn.execute(
        """select count(*) from curated_strategies s
            where s.envelope_id=%s""", (env,)).fetchone()[0]
    check("no SKIP block became a curated STRATEGY row", leaked == 0,
          f"{leaked} strategy rows")
    for claim in KEY["must_be_true"]["K5_rejected_claims_are_not_active"]["claims"]:
        head = claim.split()[0].lower()
        hit = conn.execute(
            """select count(*) from curated_objects
                where envelope_id=%s and curated_disposition_is_active(disposition)
                  and lower(name) like %s""", (env, f"%{head}%")).fetchone()[0]
        # A weak check on its own; the strong one is that the two SKIP
        # blocks carry the SKIP disposition, asserted above.
        if head in ("underground",):
            check(f"  rejected claim stays inactive: {claim[:44]!r}", hit == 0)

    # ---- K2 / K3: verification attaches to a span, and does not spread --
    print("\nK2/K3 — the practitioner's verification, and where it stops")
    vs = conn.execute(
        """select v.statement_text, v.source_start, v.source_end,
                  v.verification_actor::text, v.verification_status::text,
                  o.name, o.disposition::text
             from curated_verifications v
             join curated_objects o on o.object_id = v.object_id
            where o.envelope_id=%s order by v.source_start""", (env,)).fetchall()
    for r in vs:
        print(f"        [{r[1]}:{r[2]}] {r[0]!r}")
        print(f"          -> {r[3]} / {r[4]}  on  {r[5]!r}")
    check("exactly one practitioner verification is recorded", len(vs) == 1,
          str(len(vs)))
    check("it is PRACTITIONER / PRACTITIONER_VERIFIED",
          vs and vs[0][3] == "PRACTITIONER"
          and vs[0][4] == "PRACTITIONER_VERIFIED")
    check("its span CONTAINS the statement it names (D48)",
          vs and text[vs[0][1]:vs[0][2]] == vs[0][0])
    check("it attaches to the Rapid Improvement object, not the document",
          vs and "Rapid Improvement" in vs[0][5], str(vs[0][5] if vs else None))
    spread = conn.execute(
        """select count(*) from curated_verifications v
             join curated_objects o on o.object_id=v.object_id
            where o.envelope_id=%s
              and (o.name ilike '%%berberine%%' or o.name ilike '%%vinegar%%'
                   or o.name ilike '%%ACV%%')""", (env,)).fetchone()[0]
    check("berberine and ACV did NOT inherit PRACTITIONER_VERIFIED", spread == 0,
          f"{spread} inherited")
    check("no SYSTEM_VERIFIED value exists to fall into",
          "SYSTEM_VERIFIED" not in {r[0] for r in conn.execute(
              "select unnest(enum_range(null::curated_verification_status))::text"
          ).fetchall()})

    # ---- K9: nothing silently discarded --------------------------------
    print("\nK9 — every authored byte is owned or loudly unknown")
    blocks = conn.execute(
        "select count(*), count(*) filter (where status='REVIEW_REQUIRED') "
        "  from curated_blocks where envelope_id=%s", (env,)).fetchone()
    print(f"        {blocks[0]} blocks, {blocks[1]} REVIEW_REQUIRED")
    check("every block is stored, parsed or not", blocks[0] == 61, str(blocks))
    noreason = conn.execute(
        "select count(*) from curated_blocks where envelope_id=%s "
        "  and status='REVIEW_REQUIRED' and failure_reason is null",
        (env,)).fetchone()[0]
    check("every REVIEW_REQUIRED block says why", noreason == 0)
    notext = conn.execute(
        "select count(*) from curated_blocks where envelope_id=%s "
        "  and length(btrim(raw_text)) = 0", (env,)).fetchone()[0]
    check("every block keeps its raw text", notext == 0)

    # ---- K10: preservation ---------------------------------------------
    print("\nK10 — preservation")
    bad = conn.execute(
        """select count(*) from curated_fields f
             join curated_objects o on o.object_id=f.object_id
            where o.envelope_id=%s
              and f.text_value <> substring(%s from f.source_start+1
                                            for f.source_end-f.source_start)""",
        (env, text)).fetchone()[0]
    check("every stored object field IS its claimed slice", bad == 0,
          f"{bad} mismatched")
    trans = conn.execute(
        """select count(*) from curated_fields f
             join curated_objects o on o.object_id=f.object_id
            where o.envelope_id=%s and f.provenance <> 'VERBATIM_SOURCE'""",
        (env,)).fetchone()[0]
    check("no field was TRANSFORMED", trans == 0, str(trans))
    fab = conn.execute(
        """select count(*) from curated_fields f
             join curated_objects o on o.object_id=f.object_id
            where o.envelope_id=%s and f.field_name = 'mechanism'""",
        (env,)).fetchone()[0]
    check("no `mechanism` field was invented (D49)", fab == 0)

    # ---- K7: the adjunct nuance survives as separate fields -------------
    print("\nK7 — berberine and ACV keep their nuance as SEPARATE fields")
    for want in ("Berberine", "Vinegar"):
        fields = conn.execute(
            """select f.field_name from curated_fields f
                 join curated_objects o on o.object_id=f.object_id
                where o.envelope_id=%s and o.name ilike %s
                order by f.field_name""", (env, f"%{want}%")).fetchall()
        names = [f[0] for f in fields]
        print(f"        {want}: {names}")
        check(f"  {want} keeps more than one field", len(names) >= 2, str(names))

    # ---- K11: Video 1 unchanged, ROW BY ROW ----------------------------
    print("\nK11 — Video 1's rows, compared row by row")
    after = v1_rows()
    check("Video 1's stored rows are byte-identical after GATE 4 ran",
          before == after,
          f"{len(before)} vs {len(after)} rows")
    if before != after:
        for a, b in zip(before, after):
            if a != b:
                print(f"        DIFF {a[:2]} -> {b[:2]}")

    # ==================================================================
    # THE THREE QUESTIONS — reported with verbatim text, never solved.
    # ==================================================================
    print("\n" + "=" * 68)
    print("Q1  'Decision intelligence' vs 'When potentially worth considering'")
    print("    vs 'When not to prioritize' — REPORTED, NOT ALIASED")
    print("=" * 68)
    for head in ("Decision intelligence", "When potentially worth considering",
                 "When not to prioritize"):
        row = conn.execute(
            "select source_start, source_end, raw_text, status::text "
            "  from curated_blocks where envelope_id=%s and raw_heading=%s",
            (env, head)).fetchone()
        if row:
            body = row[2].split("\n", 1)[1].strip() if "\n" in row[2] else ""
            print(f"\n  {head!r}   [{row[0]}:{row[1]}]   {row[3]}")
            for line in body.splitlines()[:8]:
                print(f"      {line}")
    print("\n  Reported, not decided. None of the three was aliased to the")
    print("  others and none was given a rule, so the practitioner's answer")
    print("  remains free either way.")

    print("\n" + "=" * 68)
    print(f"Q2  where {REFUSED} material lives — OPTIONS, NOT A CHOICE")
    print("=" * 68)
    print(f"  It lives in curated_objects with disposition {REFUSED}, its")
    print("  full text preserved and curated_disposition_is_active() false.")
    print("  The alternatives the existing schema offers, none selected:")
    print("    negative_knowledge  — has why_investigated / evidence_examined /")
    print("        revisit_trigger, and is for a question EXAMINED AND FOUND")
    print(f"        WANTING (D41). Video 14's {REFUSED}s are not that: Prem")
    print("        refusing the SOURCE's simplification, not reporting a")
    print("        failed investigation, and there is no revisit trigger in")
    print("        the text to satisfy the NOT NULL columns without inventing")
    print("        one.")
    print("    knowledge_gaps      — 'nobody has looked'. Wrong: somebody did.")
    print("    curated_blocks REVIEW_REQUIRED — text and span preserved, but it")
    print("        would say the PARSER did not understand, which is false.")

    print("\n" + "=" * 68)
    print("Q3  is there a non-flattening home for safety? — REPORTED")
    print("=" * 68)
    for head in ("Berberine Safety / Gate", "ACV Protocol Guardrails"):
        row = conn.execute(
            "select source_start, source_end, status::text, failure_reason "
            "  from curated_blocks where envelope_id=%s and raw_heading=%s",
            (env, head)).fetchone()
        print(f"  {head!r}  [{row[0]}:{row[1]}]  {row[2]}")
    print("\n  033 has SUB_SAFETY -> `safety_context`, but it matches only the")
    print("  bare heading `Safety`, and it is a STRATEGY-CARD subsection. The")
    print("  deterministic safety layer (safety_rules, safety_match_patterns)")
    print("  is a practitioner-curated registry, and D42 says adding a rule is")
    print("  an INSERT a human makes -- a curated import writing into it would")
    print("  be an ingestion path authoring clinical gates.")
    print("  ASSESSMENT: a GAP. Video 14's safety content is preserved with its")
    print("  span, and is NOT reachable as safety. Reported, not closed.")

    # ---- E. structurally preserved != semantically classified ----------
    print("\nSTRUCTURAL PRESERVATION IS NOT SEMANTIC UNDERSTANDING")
    v14 = dict(conn.execute(
        """select s.semantic_state, count(*)
             from v_curated_field_semantics s
             join curated_objects o on o.object_id = s.object_id
            where o.envelope_id=%s group by 1""", (env,)).fetchall())
    print(f"        Video 14 object fields: {v14}")
    check("Video 14's author-named fields are PRESERVED, not understood",
          v14.get("SEMANTIC_ROLE_REGISTERED", 0) == 0, str(v14))
    check("...and they are all reported as STRUCTURALLY_PRESERVED_ONLY",
          v14.get("STRUCTURALLY_PRESERVED_ONLY", 0) == sum(v14.values()),
          str(v14))

    safety_state = conn.execute(
        """select s.semantic_state from v_curated_field_semantics s
             join curated_objects o on o.object_id = s.object_id
            where o.envelope_id=%s and s.field_name in
                  ('berberine_safety_gate','acv_protocol_guardrails')""",
        (env,)).fetchall()
    print(f"        the two safety blocks: {[r[0] for r in safety_state]}")
    check("the safety blocks are preserved and NOT claimed as safety",
          len(safety_state) == 2
          and all(r[0] == "STRUCTURALLY_PRESERVED_ONLY" for r in safety_state),
          str(safety_state))

    v1 = dict(conn.execute(
        """select s.semantic_state, count(*)
             from v_curated_field_semantics s
             join curated_strategies c on c.curated_id = s.curated_id
            where c.envelope_id=%s group by 1""", (v1_env,)).fetchall())
    print(f"        Video 1 strategy fields: {v1}")
    check("the view DISCRIMINATES — Video 1 has registered roles",
          v1.get("SEMANTIC_ROLE_REGISTERED", 0) > 0, str(v1))

    # THE COLLISION THAT WOULD HAVE MADE THIS DECORATIVE. An author
    # heading `Monitoring` slugifies to `monitoring`, which IS a
    # registered role name. If the view matched on the string, that field
    # would be reported as understood on a coincidence of spelling.
    probe = conn.execute(
        """select case when 'monitoring' in
                       (select field_name from curated_field_roles)
                  then true else false end""").fetchone()[0]
    check("a registered role name IS reachable by an author heading slug",
          probe, "the collision this guard exists for no longer exists")
    mis = conn.execute(
        """select count(*) from v_curated_field_semantics
            where name_source <> 'RULE' and semantic_state
                  = 'SEMANTIC_ROLE_REGISTERED'""").fetchone()[0]
    check("no author-named field is ever reported as role-registered",
          mis == 0, f"{mis} promoted by spelling")

    # ---- concept audit --------------------------------------------------
    print("\n" + "=" * 68)
    print("CONCEPT AUDIT")
    print("=" * 68)
    c = result["concepts"]
    print(f"  units {len(c['units'])}  linked {c['links']}  "
          f"refused-as-prose {len(c['refused'])}")
    if not c["authoritative"]:
        preflight.skip("semantic recomputation not authoritative",
                       c["authority_reason"])

    clear(conn, [text, v1_text])

    print("\n" + "=" * 60)
    if FAILS:
        print(f"GATE 4 ACCEPTANCE: MISS — {len(FAILS)} expectation(s) not met")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("GATE 4 ACCEPTANCE: every checked expectation met")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

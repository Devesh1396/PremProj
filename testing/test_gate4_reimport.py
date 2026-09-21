#!/usr/bin/env python3
"""GATE 4 — re-importing the SAME curated envelope, and stale derived state.

Two regressions, both driving the REAL importer.

REGRESSION 1 — identical re-import. The same envelope, requeued through
the supported lifecycle and imported again. Asserted by IDENTITY AND
STATE, never by counts: object ids, ordinals, dispositions, names, content
hashes, every object-owned field with its text, span, provenance and block
relationship, every verification with its owner, actor, status, statement
and span, and the concept links.

Before the fix this raised

    UniqueViolation: duplicate key value violates unique constraint
                     "uq_curated_field_object"

leaving 30 object fields orphaned with `block_id` NULL, because
`curated_fields.block_id` was ON DELETE SET NULL and `store()` had no
delete for the third owner GATE 4 introduced.

REGRESSION 2 — stale derived state. Derived rows must not become
immortal. A synthetic source produces an authored field and a
practitioner verification; the deterministic RULE CONDITION is then
changed so the next import no longer produces them; the obsolete rows must
be gone, and the parent object must keep its identity.

Deterministic. `LLM_API_KEY` is cleared, so no provider call is made and
the semantic tier is inert by configuration (V3) -- which is also the
"less capable second environment" regression 1 needs.
"""
from __future__ import annotations

import hashlib
import json
import os
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
TITLE = "G4RI T2D Video 14"
SYNTH_TITLE = "G4RI synthetic stale"


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
    conn.execute("delete from source_envelopes where source_title like 'G4RI%'")
    conn.execute("delete from source_items where title like 'G4RI%'")
    conn.execute("delete from knowledge_sources where source_name like 'G4RI%'")


def ingest(conn, root: Path, KI, text: str, title: str, name: str) -> str:
    path = root / "inbox" / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    (root / "inbox" / f"{name}.meta.json").write_text(json.dumps({
        "source_kind": "PRACTITIONER_CURATED",
        "source_title": title,
        "rights": "PRIVATE_INTERNAL",
        "send_to_e7": True,
    }), encoding="utf-8")
    return KI.ingest_one(conn, path).envelope_id


def requeue(conn, envelope_id: str) -> None:
    """Put the envelope back on the extractor's queue, as the queue defines it.

    `pending()` selects status NORMALIZED, so that is what 'requeue' means.
    Deliberately NOT a second envelope: a fresh envelope with the same text
    would test dedup, not re-import, and would pass with the bug present.
    """
    conn.execute(
        "update source_envelopes set status='NORMALIZED', processed_at=null "
        " where envelope_id=%s", (envelope_id,))


def run_import(conn, CI, envelope_id: str):
    todo = [e for e in CI.pending(conn) if str(e[0]) == envelope_id]
    if len(todo) != 1:
        raise RuntimeError(
            f"envelope {envelope_id} is not queued exactly once: {len(todo)}")
    return CI.import_one(conn, todo[0])


# ---- the state that must survive a re-import unchanged ----------------

def objects_state(conn, env: str):
    return conn.execute(
        """select object_id::text, ordinal, disposition::text, name,
                  content_hash, source_start, source_end,
                  directive_start, directive_end, name_start, name_end
             from curated_objects where envelope_id=%s
            order by ordinal""", (env,)).fetchall()


def object_fields_state(conn, env: str):
    return conn.execute(
        """select o.ordinal, f.field_name, f.text_value, f.source_start,
                  f.source_end, f.provenance::text,
                  b.raw_heading, b.ordinal
             from curated_fields f
             join curated_objects o on o.object_id = f.object_id
             left join curated_blocks b on b.block_id = f.block_id
            where o.envelope_id=%s
            order by o.ordinal, f.field_name""", (env,)).fetchall()


def verifications_state(conn, env: str):
    return conn.execute(
        """select o.ordinal, v.verification_actor::text,
                  v.verification_status::text, v.statement_text,
                  v.source_start, v.source_end, v.rule_id
             from curated_verifications v
             join curated_objects o on o.object_id = v.object_id
            where o.envelope_id=%s
            order by v.source_start""", (env,)).fetchall()


def links_state(conn, env: str):
    return conn.execute(
        """select o.ordinal, l.concept_id::text, l.source_phrase,
                  l.source_start, l.source_end, l.field_name, l.rule_id
             from curated_strategy_concepts l
             join curated_objects o on o.object_id = l.object_id
            where o.envelope_id=%s
            order by o.ordinal, l.source_start""", (env,)).fetchall()


# ----------------------------------------------------------------------
# Regression 2's synthetic source. `ADIPOKINES` is a name the K1 seed
# already holds, so the object name resolves through the EXACT tier with
# no provider and no pgvector -- which is how this suite gets a real
# concept link to protect without fabricating one (V2).
# ----------------------------------------------------------------------
SYNTH = """# Synthetic — Engine 7 Update

## ADD — adipokines

An object whose name the seed already knows.

I checked the underlying published study.

### Escalation logic

This subsection exists only so that a rule can stop producing it.
"""


def main() -> int:
    os.environ["LLM_API_KEY"] = ""
    root = Path(tempfile.mkdtemp(prefix="g4ri-"))
    os.environ["KNOWLEDGE_DIR"] = str(root)
    for d in ("inbox", "raw", "processed", "failed"):
        (root / d).mkdir(parents=True, exist_ok=True)

    import knowledge_ingest as KI
    import curated_import as CI
    CI.KNOWLEDGE = root

    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    text = SOURCE.read_text(encoding="utf-8")
    clear(conn, [text, SYNTH])

    # ==================================================================
    print("\nREGRESSION 1 — the SAME envelope, imported twice")
    env = ingest(conn, root, KI, text, TITLE, "v14")
    first = run_import(conn, CI, env)
    print(f"        first: {first['objects']} objects, {first['fields']} fields, "
          f"{first['verifications']} verification(s)")

    o1, f1, v1, l1 = (objects_state(conn, env), object_fields_state(conn, env),
                      verifications_state(conn, env), links_state(conn, env))
    check("the first import produced objects to compare", len(o1) > 0)
    check("...and object-owned fields", len(f1) > 0)
    check("...and a practitioner verification", len(v1) > 0)

    requeue(conn, env)
    check("the SAME envelope is queued again, not a new one",
          conn.execute("select count(*) from source_envelopes where "
                       "envelope_id=%s", (env,)).fetchone()[0] == 1)

    failed = None
    try:
        second = run_import(conn, CI, env)
    except Exception as exc:                       # noqa: BLE001
        failed = exc
        second = None
    check("a second identical import does not raise", failed is None,
          f"{type(failed).__name__}: {failed}" if failed else "")

    if second is not None:
        o2, f2, v2, l2 = (objects_state(conn, env),
                          object_fields_state(conn, env),
                          verifications_state(conn, env), links_state(conn, env))

        check("object IDENTITIES survive — same object_ids, not just as many",
              [r[0] for r in o1] == [r[0] for r in o2],
              f"{[r[0] for r in o1][:2]} vs {[r[0] for r in o2][:2]}")
        check("ordinals, dispositions, names, hashes and spans are identical",
              o1 == o2)
        check("no duplicate objects", len({r[0] for r in o2}) == len(o2))

        check("every object-owned field is identical", f1 == f2,
              f"{len(f1)} vs {len(f2)} rows")
        check("no duplicate (object, field_name)",
              len({(r[0], r[1]) for r in f2}) == len(f2))
        check("NO object field is left orphaned with a NULL block",
              all(r[6] is not None for r in f2),
              f"{sum(1 for r in f2 if r[6] is None)} orphan(s)")

        check("verification state is identical", v1 == v2)
        check("no duplicate verification rows",
              len({(r[0], r[4], r[5]) for r in v2}) == len(v2))

        check("concept links are not destroyed by the second import",
              l1 == l2, f"{len(l1)} -> {len(l2)}")

        states = {a["status"] for a in second["concepts"]["attachment"].values()}
        print(f"        recomputation states, run 2: {sorted(states)}")
        check("the recomputation contract still decides, and says which",
              states.issubset({"RECOMPUTED", "FIRST_ATTACHMENT",
                               "NOT_RECOMPUTED", "FAILED_CLOSED"}),
              str(states))
        check("...and nothing was FAILED_CLOSED on an unchanged source",
              "FAILED_CLOSED" not in states, str(states))

    # ==================================================================
    print("\nREGRESSION 2 — derived state must not become immortal")
    senv = ingest(conn, root, KI, SYNTH, SYNTH_TITLE, "synth")
    s_first = run_import(conn, CI, senv)
    print(f"        first: {s_first['objects']} object(s), "
          f"{s_first['fields']} field(s), "
          f"{s_first['verifications']} verification(s)")

    def synth_fields():
        return {r[1] for r in object_fields_state(conn, senv)}

    def synth_verifs():
        return verifications_state(conn, senv)

    before_ids = [r[0] for r in objects_state(conn, senv)]
    check("the synthetic object exists", len(before_ids) == 1, str(before_ids))
    check("an AUTHORED field was produced", "escalation_logic" in synth_fields(),
          str(sorted(synth_fields())))
    check("a practitioner verification was produced", len(synth_verifs()) == 1)

    linked = links_state(conn, senv)
    if linked:
        print(f"        concept link(s): {[(r[2], r[5]) for r in linked]}")
    else:
        preflight.skip(
            "a K1 concept resolvable by a deterministic tier",
            "the synthetic object name did not resolve through the exact, "
            "alias or trigram tier, so there is no real link to protect and "
            "the link-survival half of this regression cannot run. It is not "
            "asserted vacuously.")

    # Change ONLY the deterministic rule condition. The rules are registry
    # rows, so deactivating one is the supported way to stop a construct
    # being produced -- no source edit, no second envelope, no new
    # ingestion path.
    restored = False
    try:
        conn.execute("update curated_grammar_rules set active=false "
                     " where rule_id='SUB_AUTHORED_SUBHEAD'")
        conn.execute("update curated_verification_rules set active=false "
                     " where rule_id='PRACTITIONER_CHECKED_SOURCE'")

        requeue(conn, senv)
        run_import(conn, CI, senv)

        after_ids = [r[0] for r in objects_state(conn, senv)]
        now_fields = synth_fields()
        now_verifs = synth_verifs()

        check("the obsolete AUTHORED field is GONE, not immortal",
              "escalation_logic" not in now_fields, str(sorted(now_fields)))
        check("the obsolete VERIFICATION is GONE, not immortal",
              now_verifs == [], str(now_verifs))
        check("the parent object KEPT its identity — not delete-and-recreate",
              after_ids == before_ids, f"{before_ids} -> {after_ids}")
        check("current source-derived state survives",
              "opening_statement" in now_fields, str(sorted(now_fields)))
    finally:
        conn.execute("update curated_grammar_rules set active=true "
                     " where rule_id='SUB_AUTHORED_SUBHEAD'")
        conn.execute("update curated_verification_rules set active=true "
                     " where rule_id='PRACTITIONER_CHECKED_SOURCE'")
        restored = True
    check("the rule registry is restored, so the suite is idempotent",
          restored and conn.execute(
              "select active from curated_grammar_rules where "
              "rule_id='SUB_AUTHORED_SUBHEAD'").fetchone()[0])

    # A third import, with the rules back, must put the field and the
    # verification back -- proving the removal was RECONCILIATION against
    # the current source, not a one-way delete.
    requeue(conn, senv)
    run_import(conn, CI, senv)
    check("restoring the rule restores the field — reconciliation, not deletion",
          "escalation_logic" in synth_fields(), str(sorted(synth_fields())))
    check("...and the verification", len(synth_verifs()) == 1)
    check("...with the object's identity still unchanged",
          [r[0] for r in objects_state(conn, senv)] == before_ids)

    # ------------------------------------------------------------------
    # A stale OBJECT, not just a stale field. The upsert can only add or
    # update; nothing in it notices that an ordinal stopped being produced.
    print("\nan object the source no longer yields is removed too")
    try:
        conn.execute("update curated_grammar_rules set active=false "
                     " where rule_id='CURATION_DIRECTIVE'")
        requeue(conn, senv)
        run_import(conn, CI, senv)
        check("the object is gone once its construct stops being parsed",
              objects_state(conn, senv) == [],
              str(objects_state(conn, senv)))
        check("...and its fields went with it",
              object_fields_state(conn, senv) == [])
        check("...and its verification went with it",
              verifications_state(conn, senv) == [])
        check("...and its concept links went with it",
              links_state(conn, senv) == [])
    finally:
        conn.execute("update curated_grammar_rules set active=true "
                     " where rule_id='CURATION_DIRECTIVE'")

    # ------------------------------------------------------------------
    # F. Curated objects are deliberately OUTSIDE runtime retrieval, and
    # that is checked rather than asserted in prose.
    #
    # WHEN THIS CHECK IS CHANGED, THE REPLACEMENT MUST DRIVE THE REAL
    # RETRIEVAL PATH WITH A **SKIP** OBJECT PRESENT AND PROVE IT IS NOT
    # RETURNED. `test_gate4_acceptance`'s K5 proves
    # `curated_disposition_is_active()` classifies SKIP as inactive -- it
    # tests the predicate in isolation, and NOTHING CONSULTS THAT
    # PREDICATE TODAY because nothing retrieves from the table. A widening
    # that forgot to call it would put a rejected claim in front of a
    # practitioner and K5 would stay green.
    print("\ncurated objects are OUTSIDE runtime retrieval (GATE 4 scope)")
    requeue(conn, senv)
    run_import(conn, CI, senv)
    import retrieval as RET
    src = (REPO / "scripts" / "retrieval.py").read_text(encoding="utf-8")
    check("no retrieval channel reads curated_objects",
          "curated_objects" not in src,
          "retrieval.py now mentions curated_objects -- if that is "
          "deliberate, this check must be REPLACED by one that drives the "
          "real retrieval path with a SKIP object and asserts it is absent")
    check("`curated_object` is not an offered retrieval kind",
          "curated_object" not in [k for k in RET.KINDS],
          str(RET.KINDS))

    clear(conn, [text, SYNTH])

    print("\n" + "=" * 60)
    if FAILS:
        print(f"FAILURES: {len(FAILS)}")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("test_gate4_reimport: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

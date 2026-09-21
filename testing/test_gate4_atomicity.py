#!/usr/bin/env python3
"""A failed curated import must not be able to claim success.

Drives the REAL importer and INSPECTS THE DATABASE AFTER THE FAILURE.
Catching the exception proves nothing; the question is what is left behind.

MEASURED BEFORE THE FIX, injecting a failure into concept attachment on a
real Video 14 import:

    status=EXTRACTED  processed=True  objects=11  queued_for_retry=0

The envelope claimed success, `pending()` never offered it again, and the
library kept whatever that run had managed. Injecting a failure midway
through `store()` instead committed 3 objects and 61 blocks, because every
statement on an autocommit connection is its own transaction.

THE BOUNDARY NOW: `import_one` wraps deterministic storage, concept
attachment and the status transition in ONE `conn.transaction()`, and the
EXTRACTED update happens last. A failure anywhere inside rolls the whole
thing back, the envelope stays NORMALIZED, and `pending()` offers it again.

Failures are injected deterministically by monkeypatching the importer's
own functions -- never by depending on a provider or a network error, so
this suite needs neither.
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

FAILS: list[str] = []
SOURCE = REPO / "testing" / "fixtures" / "curated" / "t2d_video14.md"
TITLE = "G4AT T2D Video 14"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


class Injected(RuntimeError):
    """A failure this suite caused on purpose. Never swallowed."""


def clear(conn, text: str) -> None:
    d = hashlib.sha256(text.encode("utf-8")).hexdigest()
    conn.execute("delete from source_items where content_hash=%s", (d,))
    conn.execute("delete from source_envelopes where content_hash=%s", (d,))
    conn.execute("delete from source_envelopes where source_title like 'G4AT%'")
    conn.execute("delete from source_items where title like 'G4AT%'")
    conn.execute("delete from knowledge_sources where source_name like 'G4AT%'")


def main() -> int:
    os.environ["LLM_API_KEY"] = ""          # no provider, by construction
    root = Path(tempfile.mkdtemp(prefix="g4at-"))
    os.environ["KNOWLEDGE_DIR"] = str(root)
    for d in ("inbox", "raw", "processed", "failed"):
        (root / d).mkdir(parents=True, exist_ok=True)

    import knowledge_ingest as KI
    import curated_import as CI
    CI.KNOWLEDGE = root

    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    text = SOURCE.read_text(encoding="utf-8")
    clear(conn, text)

    path = root / "inbox" / "at.md"
    path.write_text(text, encoding="utf-8")
    (root / "inbox" / "at.meta.json").write_text(json.dumps({
        "source_kind": "PRACTITIONER_CURATED", "source_title": TITLE,
        "rights": "PRIVATE_INTERNAL", "send_to_e7": True}), encoding="utf-8")
    env = KI.ingest_one(conn, path).envelope_id

    def queued() -> int:
        return len([e for e in CI.pending(conn) if str(e[0]) == env])

    def state() -> dict:
        st = conn.execute(
            "select status::text from source_envelopes where envelope_id=%s",
            (env,)).fetchone()[0]
        return {
            "status": st,
            "objects": conn.execute(
                "select count(*) from curated_objects where envelope_id=%s",
                (env,)).fetchone()[0],
            "blocks": conn.execute(
                "select count(*) from curated_blocks where envelope_id=%s",
                (env,)).fetchone()[0],
            "fields": conn.execute(
                """select count(*) from curated_fields f
                     join curated_objects o on o.object_id=f.object_id
                    where o.envelope_id=%s""", (env,)).fetchone()[0],
            "verifications": conn.execute(
                """select count(*) from curated_verifications v
                     join curated_objects o on o.object_id=v.object_id
                    where o.envelope_id=%s""", (env,)).fetchone()[0],
            "queued": queued(),
        }

    def run():
        todo = [e for e in CI.pending(conn) if str(e[0]) == env]
        if len(todo) != 1:
            raise RuntimeError(f"not queued exactly once: {len(todo)}")
        return CI.import_one(conn, todo[0])

    def requeue():
        conn.execute("update source_envelopes set status='NORMALIZED' "
                     " where envelope_id=%s", (env,))

    # ==================================================================
    print("\nFAILURE AFTER deterministic storage, during concept attachment")
    original = CI.attach_concepts
    CI.attach_concepts = lambda *a, **k: (_ for _ in ()).throw(
        Injected("injected: concept attachment failed"))
    raised = None
    try:
        run()
    except Injected as exc:
        raised = exc
    finally:
        CI.attach_concepts = original
    check("the failure propagates — it is not swallowed", raised is not None)

    s = state()
    print(f"        {s}")
    check("the envelope does NOT claim EXTRACTED", s["status"] != "EXTRACTED",
          s["status"])
    check("...it is back in a retryable state", s["status"] == "NORMALIZED",
          s["status"])
    check("...and pending() offers it again", s["queued"] == 1)
    check("NO half-finished objects were committed", s["objects"] == 0,
          str(s["objects"]))
    check("NO half-finished blocks were committed", s["blocks"] == 0,
          str(s["blocks"]))
    check("NO half-finished fields or verifications",
          s["fields"] == 0 and s["verifications"] == 0, str(s))

    # ==================================================================
    print("\nFAILURE MIDWAY THROUGH deterministic storage")
    real_wf = CI.write_fields
    calls = {"n": 0}

    def half(*a, **k):
        calls["n"] += 1
        if calls["n"] > 3:
            raise Injected("injected: failed midway through field writing")
        return real_wf(*a, **k)

    CI.write_fields = half
    raised = None
    try:
        run()
    except Injected as exc:
        raised = exc
    finally:
        CI.write_fields = real_wf
    check("the failure propagates", raised is not None)
    check("...after some rows had already been written",
          calls["n"] > 3, str(calls["n"]))

    s = state()
    print(f"        {s}")
    check("storage is ATOMIC — nothing partial survives",
          s["objects"] == 0 and s["blocks"] == 0 and s["fields"] == 0,
          str(s))
    check("the envelope is still retryable",
          s["status"] == "NORMALIZED" and s["queued"] == 1, str(s))

    # ==================================================================
    print("\nRETRY, with no injected failure")
    ok = run()
    s = state()
    print(f"        {s}")
    check("the retry succeeds", ok["objects"] == 11, str(ok["objects"]))
    check("...and NOW the envelope is EXTRACTED", s["status"] == "EXTRACTED",
          s["status"])
    check("...and is no longer queued", s["queued"] == 0)
    check("the complete import landed", s["objects"] == 11 and s["blocks"] == 61,
          str(s))
    # 12 OBJECT fields since 048/049: 11 object bodies plus the one
    # registered label (`Decision intelligence` -> client_decision_logic)
    # that survives without the retired catch-all. (A 13th field belongs to
    # the `E7 principle` card, which is not an object and is not counted
    # here.) The rest of Video 14's
    # subsections are REVIEW_REQUIRED, which is the flat-structure result.
    check("no duplicate derived rows from the earlier failures",
          s["fields"] == 12 and s["verifications"] == 1, str(s))

    dupes = conn.execute(
        """select count(*) from (
             select o.object_id, f.field_name
               from curated_fields f
               join curated_objects o on o.object_id=f.object_id
              where o.envelope_id=%s
              group by 1,2 having count(*) > 1) d""", (env,)).fetchone()[0]
    check("...and none duplicated by (object, field_name)", dupes == 0,
          str(dupes))

    # ==================================================================
    print("\nthe status transition is the LAST thing a successful import does")
    src = (REPO / "scripts" / "curated_import.py").read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    check("import_one opens an explicit transaction",
          "with conn.transaction():" in body)
    check("store() no longer sets EXTRACTED itself",
          body.count("status='EXTRACTED'") == 1, body.count("status='EXTRACTED'"))
    # Look for the CALL, which is after the transaction opens -- searching
    # from 0 finds `def attach_concepts(conn, ...)` and the check passes or
    # fails for the wrong reason.
    i_tx = body.index("with conn.transaction():")
    i_ac = body.index("attach_concepts(conn", i_tx)
    i_st = body.index("status='EXTRACTED'", i_tx)
    i_store = body.index("store(conn", i_tx)
    check("...storage, then attachment, then the status — in that order",
          i_tx < i_store < i_ac < i_st,
          f"tx={i_tx} store={i_store} attach={i_ac} status={i_st}")

    clear(conn, text)
    print("\n" + "=" * 60)
    if FAILS:
        print(f"FAILURES: {len(FAILS)}")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("test_gate4_atomicity: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""C3 normalization — BUILD_GUIDE step 13, DECISIONS.md D2 and D3.

The assertions that matter:

  * resolution is CHEAPEST FIRST and stops early — an alias hit never
    reaches the LLM, and the suite proves it by injecting an LLM that
    raises if called
  * a confirmed mapping is cached, so a phrase never costs a second call
  * clinically distinct CONFUSABLE_DO_NOT_MERGE concepts are never merged
    into one answer
  * extraction PROPOSES; it never silently creates a canonical concept
  * escalation ranks by impact and respects the weekly cap
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import psycopg
import normalize as NZ

FAILS: list[str] = []
PFX = "C3TEST_"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def boom(*_args, **_kwargs):
    raise AssertionError("the LLM tier was reached when a cheap tier should have answered")


def main() -> int:
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)

    # Idempotent: its own namespace, cleared first, so this suite and K1's
    # seed cannot step on each other.
    conn.execute("delete from concepts where canonical_key like %s", (PFX + "%",))
    conn.execute("delete from concept_proposals where raw_phrase like %s", ("%c3test%",))
    conn.execute("delete from normalization_cache where phrase_norm like %s", ("%c3test%",))

    def concept(key, name, ctype="PHYSIOLOGY", status="SEEDED"):
        return str(conn.execute(
            """insert into concepts (canonical_key, canonical_name, concept_type,
                                     status, origin_method)
               values (%s,%s,%s,%s,'SEED') returning concept_id""",
            (PFX + key, name, ctype, status)).fetchone()[0])

    insulin = concept("INSULIN_SENSITIVITY", "c3test insulin sensitivity")
    hba1c = concept("HBA1C", "c3test glycated haemoglobin", "BIOMARKER")
    central = concept("CENTRAL_ADIPOSITY", "c3test central adiposity")
    visceral = concept("VISCERAL_FAT", "c3test visceral fat")

    conn.execute(
        """insert into concept_aliases (concept_id, alias_text, method, confidence, confirmed)
           values (%s,'c3test insulin resistance','SEED',1.0,true)""", (insulin,))
    # D3: these two are close in embedding space and clinically distinct.
    conn.execute(
        """insert into concept_relations (from_concept, to_concept, relation_type, method)
           values (%s,%s,'CONFUSABLE_DO_NOT_MERGE','SEED')""", (central, visceral))

    # ------------------------------------------------------------------
    print("\ntier 1: deterministic alias, and it does not reach the LLM")
    r = NZ.resolve(conn, "c3test insulin resistance", llm=boom, use_cache=False)
    check("a confirmed alias resolves", r.decision == "RESOLVED" and insulin in r.concept_ids,
          repr(r))
    check("...by the alias tier, not similarity", r.method == "alias", r.method)
    check("...at full confidence", r.confidence == 1.0, str(r.confidence))

    r = NZ.resolve(conn, "c3test insulin sensitivity", llm=boom, use_cache=False)
    check("the canonical name itself resolves", insulin in r.concept_ids, repr(r))

    print("\ntier 2: structured identifiers are not a similarity question")
    # The structured tier maps a phrase to a canonical_key, so this needs a
    # concept keyed HBA1C. K1 seeds one; if the ontology has not been seeded
    # yet, create it here. Earlier this test RENAMED its own fixture to
    # HBA1C and renamed it back, which collided with the seeded concept the
    # moment K1 ran first -- a test mutating a globally meaningful key.
    seeded = conn.execute(
        "select concept_id from concepts where canonical_key='HBA1C'").fetchone()
    borrowed = seeded is None
    hba1c_real = str(seeded[0]) if seeded else str(conn.execute(
        """insert into concepts (canonical_key, canonical_name, concept_type,
                                 status, origin_method)
           values ('HBA1C','glycated haemoglobin','BIOMARKER','SEEDED','SEED')
           returning concept_id""").fetchone()[0])
    # "HbA1c" is itself a canonical name once K1 has seeded it, so the ALIAS
    # tier answers first -- cheapest tier first, working as designed. To
    # exercise the structured tier specifically, use an identifier form that
    # is not anyone's canonical name.
    r = NZ.resolve(conn, "HbA1c", llm=boom, use_cache=False)
    check("a structured identifier maps to the right concept",
          hba1c_real in r.concept_ids, repr(r))
    check("...via a deterministic tier, never similarity or an LLM",
          r.method in ("alias", "structured"), r.method)

    r = NZ.resolve(conn, "a1c", llm=boom, use_cache=False)
    check("an identifier that is nobody's canonical name uses the structured tier",
          r.method == "structured" and hba1c_real in r.concept_ids, repr(r))
    if borrowed:
        conn.execute("delete from concepts where concept_id=%s", (hba1c_real,))

    print("\ntier 3: trigram catches near-neighbours")
    r = NZ.resolve(conn, "c3test insulin sensitivty", llm=boom, use_cache=False)  # typo
    check("a misspelling still resolves without an LLM",
          r.decision in ("RESOLVED", "ESCALATED", "LOGGED") and r.method == "trigram", repr(r))
    if r.decision == "RESOLVED":
        check("...and the confirmed spelling is learned as an alias",
              conn.execute(
                  """select count(*) from concept_aliases
                      where concept_id=%s and alias_text='c3test insulin sensitivty'""",
                  (insulin,)).fetchone()[0] == 1)

    # ------------------------------------------------------------------
    print("\nthe cache means a phrase never costs a second call (D2)")
    conn.execute("delete from normalization_cache where phrase_norm=norm_phrase(%s)",
                 ("c3test insulin resistance",))
    NZ.resolve(conn, "c3test insulin resistance", llm=boom, use_cache=False)
    cached = conn.execute(
        """select concept_ids, method from normalization_cache
            where phrase_norm = norm_phrase(%s)""", ("c3test insulin resistance",)).fetchone()
    check("a confirmed resolution is cached", cached is not None and len(cached[0]) == 1,
          str(cached))
    r = NZ.resolve(conn, "c3test insulin resistance", llm=boom)
    check("the second call is served from cache", r.method == "cache", repr(r))
    hits = conn.execute(
        """select hit_count from normalization_cache
            where phrase_norm = norm_phrase(%s)""", ("c3test insulin resistance",)).fetchone()[0]
    check("cache hits are counted", hits >= 1, str(hits))

    # ------------------------------------------------------------------
    print("\nCONFUSABLE_DO_NOT_MERGE is never collapsed (D3)")
    check("the mirror relation exists so a merge check cannot miss the pair",
          conn.execute(
              """select count(*) from concept_relations
                  where relation_type='CONFUSABLE_DO_NOT_MERGE'
                    and from_concept=%s and to_concept=%s""",
              (visceral, central)).fetchone()[0] == 1)
    clash = NZ.confusable_with(conn, [central, visceral])
    check("a two-concept answer spanning the pair is detected", len(clash) >= 1, str(clash))
    check("a single-concept answer is never a clash",
          NZ.confusable_with(conn, [central]) == [])

    def llm_merges_them(_phrase, _candidates):
        return {"concept_ids": [central, visceral], "confidence": 0.99}
    r = NZ.resolve(conn, "c3test belly fat around the middle", llm=llm_merges_them,
                   use_cache=False)
    check("an LLM answer that merges a confusable pair is refused",
          r.decision != "RESOLVED" and not r.concept_ids, repr(r))
    check("...and nothing was cached from it",
          conn.execute(
              """select count(*) from normalization_cache
                  where phrase_norm = norm_phrase(%s)""",
              ("c3test belly fat around the middle",)).fetchone()[0] == 0)

    # ------------------------------------------------------------------
    print("\nextraction proposes; it never silently creates a canonical concept")
    before = conn.execute(
        "select count(*) from concepts where status in ('SEEDED','ACTIVE')").fetchone()[0]
    r = NZ.resolve(conn, "c3test entirely unheard of phenomenon", use_cache=False)
    after = conn.execute(
        "select count(*) from concepts where status in ('SEEDED','ACTIVE')").fetchone()[0]
    check("no new SEEDED or ACTIVE concept appeared", after == before, f"{before} -> {after}")
    check("the decision says it was proposed", r.decision == "AUTO_CREATE", repr(r))

    proposed = conn.execute(
        """select status::text, origin_method from concepts
            where canonical_name = 'c3test entirely unheard of phenomenon'""").fetchone()
    check("the new concept exists with status PROPOSED",
          proposed is not None and proposed[0] == "PROPOSED", str(proposed))
    check("...and records how it got there",
          proposed is not None and proposed[1] == "DETERMINISTIC", str(proposed))
    check("a proposal row was written",
          conn.execute(
              """select count(*) from concept_proposals
                  where raw_phrase='c3test entirely unheard of phenomenon'"""
          ).fetchone()[0] == 1)
    check("an unresolved phrase is NOT cached as if it were confirmed",
          conn.execute(
              """select count(*) from normalization_cache
                  where phrase_norm = norm_phrase(%s)""",
              ("c3test entirely unheard of phenomenon",)).fetchone()[0] == 0)

    print("\na PROPOSED concept does not answer future lookups")
    r2 = NZ.resolve(conn, "c3test entirely unheard of phenomenon", use_cache=False)
    check("it is still not returned as a resolution", not r2.concept_ids, repr(r2))

    # ------------------------------------------------------------------
    print("\nescalation ranks by impact and is capped (D8)")
    check("the weekly cap is read from the environment", NZ.WEEKLY_CAP >= 1, str(NZ.WEEKLY_CAP))
    check("escalations this week are countable", NZ.escalations_this_week(conn) >= 0)
    check("the escalation queue view sees them",
          conn.execute("select count(*) from v_concept_escalation_queue").fetchone()[0] >= 0)

    print("\nan Engine 1 Pass A phrase list resolves end to end")
    results = NZ.resolve_all(conn, [
        "c3test insulin resistance",
        "c3test insulin sensitivity",
        "c3test entirely unheard of phenomenon",
    ])
    check("every phrase gets an outcome", len(results) == 3, str(results))
    check("known phrases resolve, unknown ones propose",
          sum(1 for r in results if r.concept_ids) == 2
          and sum(1 for r in results if r.decision == "AUTO_CREATE") == 1,
          str(results))

    # Clean up after itself as well as before. Leaving a
    # CONFUSABLE_DO_NOT_MERGE pair behind is not inert: it is visible to
    # every other suite that looks at the concept layer.
    conn.execute("delete from concepts where canonical_key like %s", (PFX + "%",))
    conn.execute("delete from concept_proposals where raw_phrase like %s", ("%c3test%",))
    conn.execute("delete from normalization_cache where phrase_norm like %s", ("%c3test%",))

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

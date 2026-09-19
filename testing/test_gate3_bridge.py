#!/usr/bin/env python3
"""GATE 3 bridge — deterministic regression, no provider, ordinary CI.

D52, D52a. This is NOT the acceptance test.
`testing/test_gate3_acceptance.py` runs the frozen synthetic client
against a live embedding provider and skips wherever that is not
configured — which, measured, is every `run_all.sh`. So the bridge it
proves could be broken by a future retrieval change with the full suite
staying green.

### THE SPLIT OF RESPONSIBILITY IS THE WHOLE DESIGN

    GATE 2 owns   phrase -> canonical concept, and its calibration.
    GATE 3 owns   established concept -> curated knowledge, retrieved,
                  ranked, traceable.

So this suite RECEIVES canonical concept ids that already exist in the K1
seed and asserts what retrieval does with them. **It manufactures no
semantic corpus.** Fabricating vectors so a phrase resolves would be
inventing GATE 2's answer and then testing it, which proves nothing about
either gate and would quietly become the evidence that 0.82 works. Nothing
here says anything about a threshold.

The links this suite establishes are written through the REAL write path
(`curated_concepts.store_units`) with the REAL spans the REAL parser
produced. Only the phrase -> concept step is supplied, because that step
is the other gate's.

### What is deterministic here and what is not

Everything. No embedding, no model, no provider: `LLM_API_KEY` is cleared,
the concept channel runs off ids this suite supplies, and the full-text
channel runs off `ts_rank_cd` over text already in the database. It runs
on every floor, and it SKIPS by name on none of them except the one where
the K1 seed itself is absent.
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
sys.path.insert(0, str(REPO / "testing" / "fixtures"))

import psycopg

import preflight

FAILS: list[str] = []
SOURCE = REPO / "testing" / "fixtures" / "curated" / "t2d_video1.md"
TITLE = "GATE3BRIDGE T2D Video 1"

# The six cards, in document order, counted by hand from the source and
# not read back from the thing under test (V2).
CARD_COUNT = 6
BREAKFAST = "Breakfast restructuring"
VINEGAR = "Vinegar as a candidate meal-level tool"
MOVEMENT = "Meal-linked postprandial movement"
AGENCY = "Preserve agency and reduce unnecessary deprivation"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def clear(conn) -> None:
    conn.execute("delete from source_envelopes where source_title=%s", (TITLE,))
    conn.execute("delete from source_items where title=%s", (TITLE,))


def ingest(conn, root: Path, KI) -> str:
    path = root / "inbox" / "g3b.md"
    path.write_text(SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
    (root / "inbox" / "g3b.meta.json").write_text(json.dumps({
        "source_kind": "PRACTITIONER_CURATED",
        "source_title": TITLE,
        "rights": "PRIVATE_INTERNAL",
        "send_to_e7": True,
    }), encoding="utf-8")
    return KI.ingest_one(conn, path).envelope_id


def main() -> int:
    # No provider, ever. The semantic tier is inert here BY DESIGN: this
    # suite is about what happens after a concept is established, and
    # making it depend on an embedding call would give it the acceptance
    # suite's skip and defeat the point of writing it.
    os.environ["LLM_API_KEY"] = ""
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)

    if conn.execute("select to_regclass('curated_concept_rules')").fetchone()[0] is None:
        preflight.skip("curated_concept_rules",
                       "migration 039 has not been applied, so the GATE 3 "
                       "concept-unit rules do not exist.")
        return 0

    live = conn.execute(
        """select canonical_key, concept_id::text from concepts
            where status in ('SEEDED','ACTIVE') order by canonical_key""").fetchall()
    if not preflight.have(
            len(live) >= 2, "the K1 ontology seed",
            "fewer than two live concepts exist, so there is nothing to "
            "anchor a curated link to and the concept channel cannot be "
            "exercised. Run scripts/seed_ontology.py."):
        return 0

    root = Path(tempfile.mkdtemp(prefix="g3b-"))
    os.environ["KNOWLEDGE_DIR"] = str(root)
    for d in ("inbox", "raw", "processed", "failed"):
        (root / d).mkdir(parents=True, exist_ok=True)

    import knowledge_ingest as KI
    import curated_concepts as CC
    import curated_import as CI
    import curated_parser as CP
    import retrieval as R
    CI.KNOWLEDGE = root

    clear(conn)
    envelope_id = str(ingest(conn, root, KI))
    env = [e for e in CI.pending(conn) if str(e[0]) == envelope_id][0]
    imported = CI.import_one(conn, env)
    text = SOURCE.read_text(encoding="utf-8")

    cards = conn.execute(
        """select curated_id::text, ordinal, name from curated_strategies
            where envelope_id=%s order by ordinal""", (envelope_id,)).fetchall()
    by_name = {r[2]: r[0] for r in cards}
    check(f"the source's {CARD_COUNT} cards are preserved",
          len(cards) == CARD_COUNT, str(len(cards)))

    # ==================================================================
    print("\n1. a degraded run is NOT AUTHORITATIVE, and says so")

    # The semantic tier cannot run here, so every card's attachment must
    # be reported as such rather than silently written as a result.
    check("the import reports that it could not authoritatively attach",
          imported["concepts"]["authoritative"] is False,
          str(imported["concepts"]["authority_reason"]))
    states = {a["status"] for a in imported["concepts"]["attachment"].values()}
    check("...and every card is FIRST_ATTACHMENT, not a silent recompute",
          states == {CC.FIRST_ATTACHMENT}, str(states))

    # ==================================================================
    print("\n2. established concepts, linked through the REAL write path")

    # GATE 2's step is SUPPLIED, not simulated: these ids already exist.
    # Everything else -- the units, their spans, the verification, the
    # insert -- is the production path.
    rules = CC.load_rules(conn)
    _, parsed, _objs = CP.parse(text, CP.load_rules(conn))
    by_ordinal = {c.ordinal: c for c in parsed if c.kind == "STRATEGY"}

    anchor_a, anchor_b = live[0][1], live[1][1]
    key_a, key_b = live[0][0], live[1][0]

    def link_card(name: str, concept_id: str) -> dict:
        curated_id = by_name[name]
        ordinal = next(r[1] for r in cards if r[0] == curated_id)
        units, _ = CC.card_units(conn, rules, by_ordinal[ordinal])
        unit = next(u for u in units if u.unit_kind == "CARD_NAME")
        resolved = [{"unit": unit, "concept_id": concept_id,
                     "canonical_key": None, "tier": "supplied",
                     "score": 1.0, "decision": "RESOLVED", "note": ""}]
        return CC.store_units(conn, curated_id, text, resolved,
                              authoritative=True)

    out_m = link_card(MOVEMENT, anchor_a)
    out_g = link_card(AGENCY, anchor_b)
    check("an authoritative write reports RECOMPUTED",
          out_m["status"] == CC.RECOMPUTED and out_g["status"] == CC.RECOMPUTED,
          f"{out_m['status']}/{out_g['status']}")
    check("...and the span it stored IS the card name in the source",
          all(text[l["source_start"]:l["source_end"]] == l["source_phrase"]
              for cid in (by_name[MOVEMENT], by_name[AGENCY])
              for l in CC.prior_links(conn, cid)))

    # ==================================================================
    print("\n3. concept -> curated knowledge, and only through the link")

    page = R.case_knowledge(conn, query=None, concept_ids=[anchor_a],
                            limit=30, telemetry=False)
    ids = [i["id"] for i in page["ITEMS"]]
    check(f"a card linked to {key_a} is retrieved by that concept",
          by_name[MOVEMENT] in ids, str(page["DIAGNOSTICS"]))
    check("...and a card linked to a DIFFERENT concept is not",
          by_name[AGENCY] not in ids)
    check("...nor is an unlinked card",
          by_name[VINEGAR] not in ids)

    conn.execute("delete from curated_strategy_concepts where curated_id=%s",
                 (by_name[MOVEMENT],))
    gone = R.case_knowledge(conn, query=None, concept_ids=[anchor_a],
                            limit=30, telemetry=False)
    check("removing the link removes the card: the LINK carries it, not a "
          "name match", by_name[MOVEMENT] not in [i["id"] for i in gone["ITEMS"]])
    link_card(MOVEMENT, anchor_a)

    # ==================================================================
    print("\n4. the CASE block asks for knowledge objects, not vocabulary")

    check("CASE_KINDS excludes ontology `concept` rows",
          "concept" not in R.CASE_KINDS and "curated_strategy" in R.CASE_KINDS,
          str(R.CASE_KINDS))
    mixed = R.retrieve(conn, query="breakfast protein fibre glucose",
                       concept_ids=[anchor_a], limit=40, telemetry=False)
    check("...and the DEFAULT kinds do return them, so the filter is doing "
          "the work rather than the corpus",
          any(r["kind"] == "concept" for r in mixed["results"]))
    block = R.case_knowledge(conn, query="breakfast protein fibre glucose",
                             concept_ids=[anchor_a], limit=40, telemetry=False)
    check("...so no ontology row reaches the case block",
          all(i["kind"] in R.CASE_KINDS for i in block["ITEMS"]),
          str({i["kind"] for i in block["ITEMS"]}))
    check("the block labels its ranking basis as a FIELD",
          block["RANKING_BASIS"] == "RELEVANCE_ONLY")

    # ==================================================================
    print("\n5. rank is relevance, and the negative control is measurable")

    # A query drawn from ONE card's own subject must rank that card above
    # a card about something else. If the mechanism under test were
    # deleted -- if `by_fts` stopped reading `curated_fields` -- every card
    # would score identically and this could not distinguish them (V2).
    ranked = R.case_knowledge(
        conn, query="breakfast is refined carbohydrate with minimal protein "
                    "and fibre, and changing one repetitive meal may simplify "
                    "adherence",
        concept_ids=[], limit=30, telemetry=False)
    order = {i["label"]: i["rank"] for i in ranked["ITEMS"]}
    check("the negative control is ON the page and therefore measurable",
          VINEGAR in order, f"absent from {sorted(order)}")
    check("a breakfast query ranks the breakfast card above the vinegar card",
          BREAKFAST in order and VINEGAR in order
          and order[BREAKFAST] < order[VINEGAR],
          f"{order.get(BREAKFAST)} vs {order.get(VINEGAR)}")
    scores = {i["label"]: i["score"] for i in ranked["ITEMS"]}
    check("...and they do not merely tie, which a tie-break would decide",
          BREAKFAST in scores and VINEGAR in scores
          and scores[BREAKFAST] > scores[VINEGAR],
          f"{scores.get(BREAKFAST)} vs {scores.get(VINEGAR)}")

    # ==================================================================
    print("\n6. a curated card is EXPANDED, never flattened")

    card = next(i for i in ranked["ITEMS"] if i["label"] == AGENCY)
    fields = {f["field_name"]: f for f in card["curated"]["fields"]}
    check("client_decision_logic survives as its OWN field",
          "client_decision_logic" in fields, str(sorted(fields)))
    check("...VERBATIM_SOURCE, with its own byte range",
          fields.get("client_decision_logic", {}).get("provenance")
          == "VERBATIM_SOURCE")
    check("...and it is not folded into a summary/mechanism pair",
          "summary" not in card and "mechanism" not in card
          and "strategy" not in card)
    raw = conn.execute(
        "select raw_location from source_envelopes where envelope_id=%s",
        (envelope_id,)).fetchone()[0]
    original = (root / raw).read_text(encoding="utf-8")
    dl = fields.get("client_decision_logic")
    check("...and the text IS the slice of the ORIGINAL file it names",
          dl is not None
          and original[dl["source_start"]:dl["source_end"]] == dl["text"])
    check("the routing table K09 lost is in that field",
          dl is not None and "bottleneck" in dl["text"])

    # ==================================================================
    print("\n7. query -> concept -> link -> card -> field -> byte span")

    traced = next(i for i in page["ITEMS"] if i["id"] == by_name[MOVEMENT])
    link = traced["curated"]["concept_links"][0]
    check("the retrieved item names the concept that matched it",
          anchor_a in traced["matched_concept_ids"])
    check("...the link names the field and the span its phrase came from",
          link["field_name"] == CC.CARD_NAME_FIELD
          and original[link["source_start"]:link["source_end"]]
          == link["source_phrase"])
    check("...the card names the preserved raw file",
          traced["curated"]["raw_location"] == raw)
    check("...and every field it carries is verbatim at its own span",
          all(original[f["source_start"]:f["source_end"]] == f["text"]
              for f in traced["curated"]["fields"]))

    # ==================================================================
    print("\n8. a less capable re-import does NOT erase established links")

    before = {(l["concept_id"], l["source_start"], l["source_end"])
              for cid in by_name.values() for l in CC.prior_links(conn, cid)}
    check("there are links to lose", len(before) == 2, str(len(before)))

    conn.execute("update source_envelopes set status='NORMALIZED', "
                 " processed_at=null where envelope_id=%s", (envelope_id,))
    again = CI.import_one(
        conn, [e for e in CI.pending(conn) if str(e[0]) == envelope_id][0])
    after = {(l["concept_id"], l["source_start"], l["source_end"])
             for cid in by_name.values() for l in CC.prior_links(conn, cid)}
    check("a degraded re-import preserves every link, identity and span",
          after == before, f"{len(before)} -> {len(after)}")
    linked_states = {o: a["status"] for o, a in again["concepts"]["attachment"].items()}
    check("...and reports NOT_RECOMPUTED for the cards that had links",
          all(linked_states[o] == CC.NOT_RECOMPUTED for o in
              [next(r[1] for r in cards if r[0] == by_name[n])
               for n in (MOVEMENT, AGENCY)]),
          str(linked_states))
    check("...with a reason naming what was unavailable",
          all("MODEL_EMBEDDING" in a["reason"] or "LLM_API_KEY" in a["reason"]
              or "pgvector" in a["reason"] or "embedded" in a["reason"]
              for o, a in again["concepts"]["attachment"].items()
              if a["status"] == CC.NOT_RECOMPUTED))
    check("...and the card is still retrievable afterwards",
          by_name[MOVEMENT] in [i["id"] for i in R.case_knowledge(
              conn, query=None, concept_ids=[anchor_a], limit=30,
              telemetry=False)["ITEMS"]])

    # ==================================================================
    print("\n9. an AUTHORITATIVE re-run CAN remove a link that no longer resolves")

    # The other half, and without it section 8 would pass on a store that
    # simply never deletes anything.
    curated_id = by_name[MOVEMENT]
    out = CC.store_units(conn, curated_id, text, [], authoritative=True)
    check("an authoritative run with nothing resolved removes the link",
          out["status"] == CC.RECOMPUTED and out["written"] == 0
          and out["removed"] == 1, str(out))
    check("...and the card stops being retrievable by that concept",
          curated_id not in [i["id"] for i in R.case_knowledge(
              conn, query=None, concept_ids=[anchor_a], limit=30,
              telemetry=False)["ITEMS"]])

    # ==================================================================
    print("\n10. a stale span is FAILED CLOSED, never retained")

    link_card(AGENCY, anchor_b)      # re-establish one to make stale
    conn.execute(
        "update curated_strategy_concepts set source_start=source_start+7, "
        " source_end=source_end+7 where curated_id=%s", (by_name[AGENCY],))
    stale_out = CC.store_units(conn, by_name[AGENCY], text, [],
                               authoritative=False,
                               authority_reason="test: tier unavailable")
    check("a link that no longer sits on the text it names is DELETED, not "
          "kept, when it cannot be recomputed",
          stale_out["status"] == CC.FAILED_CLOSED
          and stale_out["removed"] == 1
          and CC.prior_links(conn, by_name[AGENCY]) == [],
          str(stale_out))

    # ==================================================================
    print("\n10b. AVAILABILITY IS NOT AUTHORITY: partial embedding coverage")

    # The bug this closes: `semantic_tier_available()` is TRUE with ONE
    # embedded concept, and partial coverage is an ordinary supported
    # state here (`embed_library` batches 25 and reports `still_stale`).
    # So a run whose resolver simply could not SEE a concept could mark
    # itself authoritative and delete the link an earlier complete run
    # established.
    #
    # Everything below drives the REAL predicates. Nothing simulates them.
    import normalize as NZ
    import embed_library as EL

    if not preflight.have_capability(
            conn, "vector",
            "pgvector is absent (D15), so there is no embedding column, "
            "`semantic_tier_available` is already False for the right "
            "reason, and the availability/authority gap this section exists "
            "to test cannot be constructed."):
        pass
    else:
        live_ids = [r[1] for r in live]
        saved = conn.execute(
            """select concept_id::text, embedding::text, embedding_model,
                      embedding_dim, embedding_source_hash
                 from concepts where embedding is not null""").fetchall()

        def restore():
            for cid, vec, model, dim, h in saved:
                conn.execute(
                    "update concepts set embedding=%s::vector, "
                    " embedding_model=%s, embedding_dim=%s, "
                    " embedding_source_hash=%s where concept_id=%s",
                    (vec, model, dim, h, cid))

        try:
            if not preflight.have(
                    bool(saved), "an embedded ontology",
                    "no live concept carries a vector, so full coverage "
                    "cannot be established and neither half of the "
                    "availability/authority comparison can be built. Run "
                    "scripts/embed_library.py --table concepts."):
                pass
            else:
                os.environ["LLM_API_KEY"] = "gate3-bridge-authority-probe"
                full_ok, full_why = CC.semantic_recomputation_authoritative(conn)
                check("with FULL, FRESH coverage a recomputation is "
                      "authoritative", full_ok, full_why)
                check("...and `stale_count` agrees there is nothing to embed",
                      EL.stale_count(conn, "concepts") == 0)

                # ONE concept's vector removed. Availability is untouched;
                # authority must not be.
                victim = saved[0][0]
                conn.execute(
                    "update concepts set embedding=null, "
                    " embedding_source_hash=null where concept_id=%s",
                    (victim,))
                avail_ok, _ = NZ.semantic_tier_available(conn)
                auth_ok, auth_why = CC.semantic_recomputation_authoritative(conn)
                check("ONE missing vector still leaves the semantic tier "
                      "AVAILABLE -- Gate 2 semantics are unchanged", avail_ok)
                check("...but the recomputation is NOT authoritative",
                      not auth_ok, auth_why)
                check("...and the reason names partial coverage",
                      "PARTIAL" in auth_why or "partial" in auth_why, auth_why)
                restore()

                # A STALE vector -- present, but for text that has changed.
                # `embedding is not null` would call this covered; the
                # source hash is what tells the difference.
                conn.execute(
                    "update concepts set embedding_source_hash=%s "
                    " where concept_id=%s", ("0" * 64, victim))
                stale_ok, stale_why = CC.semantic_recomputation_authoritative(conn)
                check("a STALE vector is not coverage either: present but "
                      "for different text", not stale_ok, stale_why)
                check("...and the semantic tier is still available, so the "
                      "two predicates are genuinely different",
                      NZ.semantic_tier_available(conn)[0])
                restore()

                # ...and the whole point: a re-import under partial coverage
                # must not delete an established link.
                link_card(MOVEMENT, anchor_a)
                established = CC.prior_links(conn, by_name[MOVEMENT])
                check("a link is established under full coverage",
                      len(established) == 1)
                conn.execute(
                    "update concepts set embedding=null, "
                    " embedding_source_hash=null where concept_id=%s",
                    (victim,))
                auth, reason = CC.semantic_recomputation_authoritative(conn)
                partial = CC.store_units(conn, by_name[MOVEMENT], text, [],
                                         authoritative=auth,
                                         authority_reason=reason)
                check("a re-import under PARTIAL coverage preserves it",
                      partial["status"] == CC.NOT_RECOMPUTED
                      and CC.prior_links(conn, by_name[MOVEMENT]) == established,
                      str(partial))
                restore()
        finally:
            os.environ["LLM_API_KEY"] = ""
            restore()

    # ==================================================================
    print("\n11. RUNTIME: a real CLIENT_NEW case actually receives a curated card")

    # A test that calls `retrieval.py` is not proof of runtime integration.
    # This runs the REAL `client_new.run_new_client()` end to end on the
    # fixture provider and reads WHAT WAS ACTUALLY SENT to each engine, by
    # capturing the user prompt at the provider boundary -- the request is
    # not persisted (it is client data), so the boundary is the only honest
    # place to look.
    #
    # The curated cards reach this case through FULL TEXT, not the concept
    # spine: the fixture's Pass A phrases do not resolve to K1 concepts
    # without the semantic tier, which is inert here. That is the point --
    # the bridge has two channels and this proves the one that works with
    # no provider at all.
    import client_new as CN
    import intake as IN
    import run_engine as RE
    import synthetic_intake as SI

    link_card(MOVEMENT, anchor_a)
    sent: dict[str, str] = {}
    original_provider = RE.select_provider

    def capturing():
        call, name = original_provider()

        def wrapped(system, user, params):
            label = params.get("engine", "?")
            if label == "E1":
                label += "_PASS_" + str(params.get("pass_label"))
            sent[label] = user
            return call(system, user, params)
        return wrapped, name

    SI.clear(conn)
    RE.select_provider = capturing
    try:
        client_id = SI.load_client(conn, SI.EXTERNAL_REF_COMPLETE)
        submission = IN.submit(conn, client_id, SI.COMPLETE_INTAKE)
        outcome = CN.run_new_client(conn, submission)
    finally:
        RE.select_provider = original_provider

    check("the pipeline reached the review queue",
          outcome.status == "AWAITING_REVIEW",
          outcome.stopped_because or outcome.status)
    step_names = [st.name for st in outcome.steps]
    check("RETRIEVE runs between NORMALIZE and E7 in the real pipeline",
          "RETRIEVE" in step_names
          and step_names.index("NORMALIZE") < step_names.index("RETRIEVE")
          < step_names.index("E7"), str(step_names))

    e7_sent = sent.get("E7", "")
    check("E7 was sent a RETRIEVED_KNOWLEDGE block", '"RETRIEVED_KNOWLEDGE"' in e7_sent)
    check("...labelled RELEVANCE_ONLY", '"RANKING_BASIS": "RELEVANCE_ONLY"' in e7_sent)
    check("...that asked for knowledge objects, not vocabulary",
          '"curated_strategy"' in e7_sent and '"KINDS_REQUESTED"' in e7_sent)
    check("...carrying a curated Video 1 card BY NAME",
          AGENCY in e7_sent or BREAKFAST in e7_sent or MOVEMENT in e7_sent,
          "no curated card reached E7")
    check("...with client_decision_logic as its own named field, not prose "
          "in a summary",
          '"field_name": "client_decision_logic"' in e7_sent)
    check("...and the practitioner's own words inside it",
          "actual bottleneck" in e7_sent or "Prioritize this strategy when"
          in e7_sent)
    check("...traceable to the preserved raw file",
          '"raw_location"' in e7_sent and '"source_start"' in e7_sent)

    pass_b = sent.get("E1_PASS_B", "")
    # The SENTINEL, not merely the key. `SENT-E7-CASE-STRATEGY` exists in
    # exactly one handoff block and nowhere else, so its presence is proof
    # that Engine 7's reasoning reached Pass B -- `"E7_HANDOFF": {}` being
    # present is not.
    check("Pass B receives E7's REASONING over that retrieval",
          RE.sentinel("E7", "CASE", "STRATEGY") in pass_b,
          "E7's handoff content did not reach Pass B")
    check("...and the retrieval block beside it, so a curated field's "
          "survival does not depend on an engine repeating it",
          '"RETRIEVED_KNOWLEDGE"' in pass_b)

    pass_a = sent.get("E1_PASS_A", "")
    check("Pass A is NOT given the retrieval: it is what decides what to "
          "retrieve", '"RETRIEVED_KNOWLEDGE"' not in pass_a)
    check("E2 and E3 reason over E1's decision, not over the library",
          '"RETRIEVED_KNOWLEDGE"' not in sent.get("E2", "")
          and '"RETRIEVED_KNOWLEDGE"' not in sent.get("E3", ""))

    SI.clear(conn)

    clear(conn)
    shutil.rmtree(root, ignore_errors=True)
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("test_gate3_bridge: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

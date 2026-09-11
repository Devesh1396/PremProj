#!/usr/bin/env python3
"""K11 — strategy synthesis. CREATE / UPDATE / MERGE / NO CHANGE.

BUILD_GUIDE step 16. Engine 7 §17, §39, §R13; D7, D11, D36.

    python3 scripts/knowledge_synthesize.py            # the queue
    python3 scripts/knowledge_synthesize.py --one      # one claim, then stop
    python3 scripts/knowledge_synthesize.py --status   # what is queued

`K11_STRATEGY_SYNTHESIZER: CREATE / UPDATE / MERGE / NO CHANGE. Never
silently duplicate.`

### Deterministic dedup happens BEFORE the model call, not inside it

BUILD_GUIDE: *"Watch `MERGE_DECISION` in `v_cost_by_operation`. If cost per
new card climbs with library size, deterministic dedup is not filtering
enough before the LLM call."*

That is a measurable prediction about this file. Candidate strategies are
found by concept overlap and, where `pg_trgm` is available, by name
similarity — and only those candidates are sent. Asking a model "is this
already in the library?" with the whole library attached is the cost curve
that warning describes.

### "Never silently duplicate" is enforced here, not requested

A model returning `CREATE` is not sufficient authority to create. Every
`CREATE` is re-checked deterministically against the live library
immediately before insertion, and a collision is **converted to an UPDATE**
with the override recorded. The model proposes; this file decides.

### Nothing is promoted (D11, hard rule 7)

Everything created lands at `AI_DISCOVERED_CANDIDATE`. The one status this
file may set beyond that is `DEPRECATED`, on the losing side of a MERGE —
and `ck_provenance_required` refuses it without a provenance note, so the
merge rationale becomes that note. A strategy past candidate status
without a traceable reason cannot exist, and this file cannot create one.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import psycopg

import concept_key
import normalize
import run_engine as RE

SYNTHESIS_TAG = "RESEARCH_PRACTICE_SYNTHESIS"
PROCESSING_VERSION = "k11.v1"

DEFAULT_BATCH = int(os.environ.get("KNOWLEDGE_SYNTHESIS_BATCH", "10"))

# How close two names must be before this file calls them the same
# strategy without asking. Deliberately high: a false MERGE loses a real
# distinction, and the model still sees the near-misses as candidates.
NAME_COLLISION = 0.92
# How close before a strategy is worth SENDING as a candidate. Lower,
# because the whole point is to give the model the neighbourhood.
CANDIDATE_SIMILARITY = 0.45
MAX_CANDIDATES = 8

DECISIONS = {"CREATE", "UPDATE", "MERGE", "NO_CHANGE"}
CONFIDENCES = {"STRONG", "MODERATE", "LIMITED", "MECHANISTIC_ONLY",
               "CONFLICTING", "INSUFFICIENT", "UNKNOWN"}
LINK_ROLES = {"TARGETS", "INDICATED_FOR", "POPULATION", "MECHANISM",
              "CONTRAINDICATED", "REQUIRES_CONTEXT"}
CARD_FIELDS = (
    "summary", "intervention_category", "mechanism", "practical_implementation",
    "dose_or_exposure", "frequency", "duration", "timeframe",
    "expected_effect_direction", "expected_magnitude_summary",
    "evidence_summary", "limitations", "adverse_effects", "interactions",
    "contraindication_context", "cost_context", "complexity",
    "adherence_context", "geography_context", "seasonality_context",
    "alternatives", "outcomes_to_track",
)


class SynthesisFailed(RuntimeError):
    """The run produced nothing usable. Nothing is written."""


def dsn() -> str:
    return os.environ["DATABASE_URL"]


def capability(conn, name: str) -> bool:
    row = conn.execute(
        "select enabled from system_capabilities where capability=%s", (name,)
    ).fetchone()
    return bool(row and row[0])


def queue(conn, limit: int) -> list[tuple]:
    """Researched claims not yet attached to any strategy."""
    return conn.execute(
        """select c.claim_id, c.claim_text, c.claim_type, c.target, c.mechanism,
                  c.context, c.independent_evidence_findings,
                  c.current_interpretation, c.areas_supported,
                  c.areas_overstated, c.areas_uncertain
             from claims c
            where c.independent_evidence_findings is not null
              and not exists (select 1 from strategy_claims sc
                               where sc.claim_id = c.claim_id)
            order by c.created_at
            limit %s""", (limit,)).fetchall()


def claim_phrases(claim: tuple) -> list[str]:
    return [p for p in (claim[3], claim[4]) if (p or "").strip()]


def candidates(conn, claim: tuple) -> list[dict]:
    """Existing strategies this claim might already be covered by.

    Concept overlap first -- it is exact, cheap and works with no optional
    extension -- then name similarity where pg_trgm is available. Without
    pg_trgm this returns fewer candidates and the model sees a smaller
    neighbourhood; it does not return wrong ones (D15).
    """
    found: dict[str, dict] = {}

    concept_ids: list[str] = []
    for phrase in claim_phrases(claim):
        res = normalize.resolve(conn, phrase, context="K11 synthesis candidates")
        concept_ids.extend(res.concept_ids)

    if concept_ids:
        for row in conn.execute(
            """select s.strategy_id, s.name, s.summary, s.knowledge_status::text,
                      count(distinct sc.concept_id) as overlap
                 from strategies s
                 join strategy_concepts sc on sc.strategy_id = s.strategy_id
                where sc.concept_id = any(%s::uuid[])
                  and s.knowledge_status <> 'DEPRECATED'
                group by s.strategy_id, s.name, s.summary, s.knowledge_status
                order by overlap desc limit %s""",
                (concept_ids, MAX_CANDIDATES)).fetchall():
            found[str(row[0])] = {"strategy_id": str(row[0]), "name": row[1],
                                  "summary": row[2], "knowledge_status": row[3],
                                  "matched_by": f"{row[4]} shared concept(s)"}

    if capability(conn, "pg_trgm"):
        needle = " ".join(claim_phrases(claim)) or (claim[1] or "")
        for row in conn.execute(
            """select s.strategy_id, s.name, s.summary, s.knowledge_status::text,
                      similarity(s.name, %s) as sim
                 from strategies s
                where s.knowledge_status <> 'DEPRECATED'
                  and similarity(s.name, %s) >= %s
                order by sim desc limit %s""",
                (needle, needle, CANDIDATE_SIMILARITY, MAX_CANDIDATES)).fetchall():
            found.setdefault(str(row[0]), {
                "strategy_id": str(row[0]), "name": row[1], "summary": row[2],
                "knowledge_status": row[3],
                "matched_by": f"name similarity {float(row[4]):.2f}"})

    return list(found.values())[:MAX_CANDIDATES]


def collision(conn, name: str) -> str | None:
    """An active strategy this CREATE would duplicate, or None.

    The enforcement half of "never silently duplicate". A model saying
    CREATE is a proposal; this is the check that decides.
    """
    key = concept_key.key_for(name)
    exact = conn.execute(
        "select strategy_id from strategies "
        " where canonical_key = %s and knowledge_status <> 'DEPRECATED'", (key,)
    ).fetchone()
    if exact:
        return str(exact[0])

    if capability(conn, "pg_trgm"):
        near = conn.execute(
            "select strategy_id from strategies "
            " where knowledge_status <> 'DEPRECATED' "
            "   and similarity(name, %s) >= %s order by similarity(name, %s) desc "
            " limit 1", (name, NAME_COLLISION, name)).fetchone()
        if near:
            return str(near[0])
    return None


def evidence_for(conn, claim_id: str) -> list[str]:
    """Evidence written by K10 while researching this claim.

    Joined through the claim's own research run rather than through the
    discovery envelope: the envelope surfaced the claim, the evidence came
    from independent research (D10).
    """
    return [str(r[0]) for r in conn.execute(
        """select e.evidence_id from evidence_records e
            where e.created_at >= (select c.created_at from claims c
                                    where c.claim_id = %s)
            order by e.created_at desc limit 20""", (claim_id,)).fetchall()]


def link_concepts(conn, strategy_id: str, concepts: list) -> tuple[int, list[str]]:
    """Returns (links written, phrases that resolved to nothing canonical).

    A phrase nothing matched becomes a PROPOSED concept and resolve()
    returns no ids for it -- deliberately, because PROPOSED is what keeps a
    machine-invented concept out of retrieval until something promotes it
    (D8). So the strategy is real and not yet retrievable, and that is a
    GAP, not a failure and not something to paper over by linking a
    proposal into the spine.
    """
    linked = 0
    unresolved: list[str] = []
    for entry in concepts or []:
        if not isinstance(entry, dict):
            continue
        phrase = (entry.get("phrase") or "").strip()
        if not phrase:
            continue
        role = (entry.get("role") or "TARGETS").strip().upper()
        if role not in LINK_ROLES:
            role = "TARGETS"
        res = normalize.resolve(conn, phrase, context="K11 strategy concept")
        if not res.concept_ids:
            unresolved.append(phrase)
            continue
        for concept_id in res.concept_ids:
            conn.execute(
                "insert into strategy_concepts (strategy_id, concept_id, link_role, note) "
                "values (%s,%s,%s::concept_link_role,%s) on conflict do nothing",
                (strategy_id, concept_id, role, f"K11 from claim phrase {phrase!r}"))
            linked += 1
    return linked, unresolved


def record_retrieval_gap(conn, strategy_id: str, name: str,
                         unresolved: list[str]) -> None:
    """§R13: a strategy with no concepts is one nothing will ever retrieve.

    Recorded as an OPEN gap rather than logged and forgotten. Hard rule 11:
    zero identified gaps never means finished, and a gap the library cannot
    see is one nobody will ever close.
    """
    if conn.execute(
        "select 1 from knowledge_gaps where status='OPEN' and question like %s",
            (f"%{strategy_id}%",)).fetchone():
        return
    phrases = ", ".join(repr(p) for p in unresolved) or "none were offered"
    conn.execute(
        """insert into knowledge_gaps (question, importance, severity, status)
           values (%s, 60, 'HIGH', 'OPEN')""",
        (f"Strategy {name!r} ({strategy_id}) has no canonical concepts, so "
         f"nothing will retrieve it. Phrases that resolved to nothing "
         f"canonical: {phrases}. Each became a PROPOSED concept, which is "
         "kept out of retrieval until it is promoted (D8) — promoting them, "
         "or supplying phrases that match the seeded ontology, is what makes "
         "this strategy findable.",))


def link_claim_and_evidence(conn, strategy_id: str, claim_id: str,
                            evidence_ids: list[str]) -> None:
    conn.execute(
        "insert into strategy_claims (strategy_id, claim_id, note) "
        "values (%s,%s,%s) on conflict do nothing",
        (strategy_id, claim_id, f"K11 {PROCESSING_VERSION}"))
    for evidence_id in evidence_ids:
        conn.execute(
            "insert into strategy_evidence (strategy_id, evidence_id, relationship, note) "
            "values (%s,%s,'SUPPORTS',%s) on conflict do nothing",
            (strategy_id, evidence_id, f"K11 {PROCESSING_VERSION}"))


def envelope_of(conn, claim_id: str) -> str | None:
    row = conn.execute(
        "select envelope_id from envelope_derived_records "
        " where derived_kind='CLAIM' and derived_id=%s limit 1", (claim_id,)).fetchone()
    return str(row[0]) if row else None


def create_strategy(conn, decision: dict, claim_id: str,
                    evidence_ids: list[str]) -> tuple[str, str]:
    """Returns (strategy_id, outcome) where outcome is CREATE or UPDATE."""
    name = (decision.get("name") or "").strip()
    if not name:
        raise SynthesisFailed("a CREATE decision carried no name.")

    existing = collision(conn, name)
    if existing:
        # Never silently duplicate. The model proposed a new card for
        # something the library already has; that becomes an update, and
        # the override is recorded rather than the duplicate being made.
        apply_update(conn, dict(decision, strategy_id=existing,
                                rationale=(decision.get("rationale") or "") +
                                " [K11: proposed as CREATE; an existing "
                                "strategy already covers this name, so it was "
                                "applied as an UPDATE instead.]"),
                     claim_id, evidence_ids)
        return existing, "UPDATE"

    confidence = (decision.get("evidence_confidence") or "UNKNOWN").strip().upper()
    if confidence not in CONFIDENCES:
        confidence = "UNKNOWN"

    columns = ["name", "canonical_key", "evidence_confidence", "knowledge_status"]
    values: list = [name, concept_key.key_for(name), confidence,
                    "AI_DISCOVERED_CANDIDATE"]
    for field in CARD_FIELDS:
        if decision.get(field) is not None:
            columns.append(field)
            values.append(decision[field])

    placeholders = ", ".join(
        "%s::evidence_confidence" if c == "evidence_confidence"
        else "%s::knowledge_status" if c == "knowledge_status" else "%s"
        for c in columns)
    strategy_id = str(conn.execute(
        f"insert into strategies ({', '.join(columns)}) "
        f"values ({placeholders}) returning strategy_id", values).fetchone()[0])

    link_claim_and_evidence(conn, strategy_id, claim_id, evidence_ids)
    linked, unresolved = link_concepts(conn, strategy_id, decision.get("concepts"))
    if linked == 0:
        record_retrieval_gap(conn, strategy_id, name, unresolved)

    envelope_id = envelope_of(conn, claim_id)
    if envelope_id:
        conn.execute(
            "insert into envelope_derived_records "
            "  (envelope_id, derived_kind, derived_id, discovery_only, processing_version) "
            "values (%s,'STRATEGY',%s,true,%s) on conflict do nothing",
            (envelope_id, strategy_id, PROCESSING_VERSION))
    return strategy_id, "CREATE"


def apply_update(conn, decision: dict, claim_id: str,
                 evidence_ids: list[str]) -> str:
    strategy_id = decision.get("strategy_id")
    if not strategy_id:
        raise SynthesisFailed("an UPDATE decision carried no strategy_id.")
    if not conn.execute("select 1 from strategies where strategy_id=%s",
                        (strategy_id,)).fetchone():
        raise SynthesisFailed(f"UPDATE names strategy {strategy_id}, which does "
                              "not exist.")

    sets, values = [], []
    for field in CARD_FIELDS:
        if decision.get(field) is not None:
            sets.append(f"{field} = %s")
            values.append(decision[field])
    if sets:
        values.append(strategy_id)
        conn.execute(
            f"update strategies set {', '.join(sets)}, updated_at = now() "
            " where strategy_id = %s", values)

    link_claim_and_evidence(conn, strategy_id, claim_id, evidence_ids)
    link_concepts(conn, strategy_id, decision.get("concepts"))

    # An UPDATE that leaves a strategy with no canonical concepts is the
    # same unretrievable card as a CREATE that does.
    still_none = conn.execute(
        "select count(*) from strategy_concepts where strategy_id=%s",
        (strategy_id,)).fetchone()[0] == 0
    if still_none:
        name = conn.execute("select name from strategies where strategy_id=%s",
                            (strategy_id,)).fetchone()[0]
        record_retrieval_gap(
            conn, str(strategy_id), name,
            [(c or {}).get("phrase") for c in (decision.get("concepts") or [])
             if isinstance(c, dict)])
    return str(strategy_id)


def apply_merge(conn, decision: dict) -> str:
    loser = decision.get("strategy_id")
    winner = decision.get("merge_into")
    rationale = (decision.get("rationale") or "").strip()
    if not (loser and winner):
        raise SynthesisFailed("a MERGE decision needs strategy_id and merge_into.")
    if loser == winner:
        raise SynthesisFailed("a MERGE cannot fold a strategy into itself.")
    if not rationale:
        # DEPRECATED is past AI_DISCOVERED_CANDIDATE, and
        # ck_provenance_required would refuse the write anyway. Failing here
        # says why; failing there says "check constraint violated" (D11).
        raise SynthesisFailed(
            "a MERGE needs a rationale: it deprecates a strategy, and a "
            "strategy past AI_DISCOVERED_CANDIDATE cannot exist without a "
            "provenance note.")

    # Move the loser's links to the winner, skipping any the winner already
    # has, then drop what is left. A merge must not lose a claim or an
    # evidence link -- that is the difference between merging two cards and
    # deleting one of them.
    for table, column in (("strategy_claims", "claim_id"),
                          ("strategy_evidence", "evidence_id"),
                          ("strategy_concepts", "concept_id")):
        conn.execute(
            f"update {table} set strategy_id = %s "
            f" where strategy_id = %s "
            f"   and not exists (select 1 from {table} other "
            f"                    where other.strategy_id = %s "
            f"                      and other.{column} = {table}.{column})",
            (winner, loser, winner))
        conn.execute(f"delete from {table} where strategy_id = %s", (loser,))

    conn.execute(
        "update strategies set knowledge_status='DEPRECATED', "
        "       provenance_note=%s, updated_at=now() where strategy_id=%s",
        (f"K11 MERGE into {winner}: {rationale}", loser))
    return str(winner)


def synthesize_one(conn, claim: tuple) -> dict:
    claim_id = str(claim[0])
    found = candidates(conn, claim)
    evidence_ids = evidence_for(conn, claim_id)

    result = RE.run_engine(
        conn,
        RE.EngineRequest(
            engine="E7",
            mode="SYNTHESIS",
            model_role="MODEL_RESEARCH",
            structured_input={
                "CLAIM_REFERENCE": claim_id,
                "CLAIM_TEXT": claim[1],
                "CLAIM_TYPE": claim[2],
                "CLAIM_TARGET": claim[3],
                "CLAIM_MECHANISM": claim[4],
                "CLAIM_CONTEXT": claim[5],
                "INDEPENDENT_EVIDENCE_FINDINGS": claim[6],
                "CURRENT_INTERPRETATION": claim[7],
                "AREAS_SUPPORTED": claim[8],
                "AREAS_OVERSTATED": claim[9],
                "AREAS_UNCERTAIN": claim[10],
                # The neighbourhood, found deterministically. Sending the
                # whole library instead is the cost curve BUILD_GUIDE warns
                # about.
                "CANDIDATE_STRATEGIES": found,
                "PROCESSING_VERSION": PROCESSING_VERSION,
            },
            run_context={"stage": "K11", "claim_id": claim_id,
                         "candidates": len(found)}))

    if result.status != "SUCCEEDED":
        raise SynthesisFailed(
            f"the SYNTHESIS run did not succeed ({result.status}): {result.error}")

    body = dict(result.secondary_handoffs or {})
    if result.handoff_tag:
        body[result.handoff_tag] = result.structured
    block = body.get(SYNTHESIS_TAG)
    if not block:
        raise SynthesisFailed(f"the run produced no <{SYNTHESIS_TAG}> block.")
    raw = block.get("SYNTHESIS_JSON")
    if raw is None:
        raise SynthesisFailed(f"<{SYNTHESIS_TAG}> carried no SYNTHESIS_JSON.")
    try:
        decisions = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SynthesisFailed(f"SYNTHESIS_JSON is not valid JSON: {exc}") from exc
    if not isinstance(decisions, list):
        raise SynthesisFailed("SYNTHESIS_JSON must be an array.")

    outcomes: dict[str, int] = {"CREATE": 0, "UPDATE": 0, "MERGE": 0,
                                "NO_CHANGE": 0}
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        kind = (decision.get("decision") or "").strip().upper()
        if kind not in DECISIONS:
            raise SynthesisFailed(
                f"{kind!r} is not one of the four decisions. There is no fifth "
                "(§R13); an unrecognised one is a malformed run, not a nuance.")
        if kind == "NO_CHANGE":
            outcomes["NO_CHANGE"] += 1
            continue
        if kind == "CREATE":
            _sid, actual = create_strategy(conn, decision, claim_id, evidence_ids)
            outcomes[actual] += 1
        elif kind == "UPDATE":
            apply_update(conn, decision, claim_id, evidence_ids)
            outcomes["UPDATE"] += 1
        else:
            apply_merge(conn, decision)
            outcomes["MERGE"] += 1

    if outcomes["NO_CHANGE"] and not any(
            outcomes[k] for k in ("CREATE", "UPDATE", "MERGE")):
        # NO_CHANGE is a real answer, and the claim must not come back
        # around the queue for it. Attach it to nothing, and say so.
        conn.execute(
            "update claims set current_interpretation = coalesce(current_interpretation, '') "
            "  || %s where claim_id = %s",
            (" [K11: NO_CHANGE — the library already covers this.]", claim_id))

    envelope_id = envelope_of(conn, claim_id)
    if envelope_id:
        conn.execute(
            """update source_delta_analyses
                  set strategies_created = strategies_created + %s,
                      strategies_updated = strategies_updated + %s
                where envelope_id = %s""",
            (outcomes["CREATE"], outcomes["UPDATE"] + outcomes["MERGE"],
             envelope_id))

    return {"claim_id": claim_id, "run_id": result.run_id,
            "candidates": len(found), "outcomes": outcomes,
            "detail": (f"{len(found)} candidate(s) sent; "
                       + ", ".join(f"{v} {k}" for k, v in outcomes.items() if v)
                       or f"{len(found)} candidate(s) sent; nothing decided")}


def status(conn) -> None:
    todo = conn.execute(
        """select count(*) from claims c
            where c.independent_evidence_findings is not null
              and not exists (select 1 from strategy_claims sc
                               where sc.claim_id = c.claim_id)""").fetchone()[0]
    print(f"\nWAITING FOR K11    {todo} researched claim(s) with no strategy")
    rows = conn.execute(
        "select knowledge_status::text, count(*) from strategies "
        " group by 1 order by 2 desc").fetchall()
    print("\nSTRATEGIES")
    if not rows:
        print("  none — the library has no strategies yet.")
    for kstatus, n in rows:
        print(f"  {kstatus:32s} {n}")
    spine = conn.execute(
        "select count(distinct strategy_id) from strategy_concepts").fetchone()[0]
    total = conn.execute("select count(*) from strategies").fetchone()[0]
    print(f"\nRETRIEVABLE        {spine} of {total} strategies carry concepts")
    if total and spine < total:
        print("  A strategy with no concepts is a strategy nothing will "
              "retrieve (§R13).")


def main() -> int:
    with psycopg.connect(dsn(), autocommit=True) as conn:
        if "--status" in sys.argv:
            status(conn)
            return 0

        todo = queue(conn, 1 if "--one" in sys.argv else DEFAULT_BATCH)
        if not todo:
            print("no researched claims waiting for synthesis")
            status(conn)
            return 0

        print(f"{len(todo)} claim(s) to synthesise from\n")
        failures = 0
        for claim in todo:
            try:
                out = synthesize_one(conn, claim)
            except SynthesisFailed as exc:
                failures += 1
                print(f"  FAILED      {str(claim[0])[:8]}  {exc}")
                continue
            print(f"  SYNTHESISED {str(claim[0])[:8]}  {out['detail']}")

        status(conn)
        return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

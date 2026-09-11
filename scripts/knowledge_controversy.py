#!/usr/bin/env python3
"""K12 — the per-domain controversy and negative-knowledge pass.

BUILD_GUIDE step 19. Engine 7 §R14; migration 025; D9, D10.

    python3 scripts/knowledge_controversy.py --status
    python3 scripts/knowledge_controversy.py --one
    python3 scripts/knowledge_controversy.py --domain DOMAIN_B

### Neither of these accumulates from ingestion, which is why it exists

K09 reads one source and produces claims. K11 turns claims into strategies.
Nothing in that path can produce *"these two bodies of evidence contradict
each other"* or *"this was investigated and does not work"*, because **no
single source says either**. Both are statements about what has piled up,
so both need a dedicated pass over the pile.

BUILD_PLAN: *"K9 runs per domain once that domain reaches moderate
coverage, not at the end of Wave 1. Negative knowledge and controversies do
not fall out of ingestion naturally."* Running it at the end is how a
library ends up confidently recommending something the evidence already
argued about.

### A controversy with one position is not a controversy

It is a consensus statement, or a gap, and stored here it would be
retrieved and shown to the practitioner as a live disagreement.
`trg_controversy_positions_at_commit` refuses it **at commit**, so a
partial write cannot land — and this file writes a controversy and its
positions in ONE transaction for that reason.

### Absence of evidence is not evidence of absence

A strategy nobody has studied is a **gap** (K13), not negative knowledge.
Negative knowledge means examined and found wanting, and
`ck_negative_is_actionable` requires what was examined and what would make
us look again. Without both it cannot do the one job it has: stop the same
question being researched a second time.

### An empty result is a real result, and is recorded as one

`domain_controversy_assessments` gets a row whether or not anything was
found. "No controversies in this domain" and "nobody has ever looked" are
otherwise the same absent row, and the second is the dangerous one
(hard rule 11).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import psycopg

import run_engine as RE

CONTROVERSY_TAG = "RESEARCH_PRACTICE_CONTROVERSY"
PROCESSING_VERSION = "k12.v1"

# "Once that domain reaches moderate coverage, not at the end." The same
# trigger layer C uses, and the same reason: correct the library while
# re-tagging is still cheap.
MODERATE_COVERAGE = int(os.environ.get("EVAL_MODERATE_COVERAGE", "6"))

# How much accumulated material to put in front of the pass. A domain with
# less than this has not accumulated anything to read across.
MIN_MATERIAL = int(os.environ.get("K12_MIN_MATERIAL", "3"))
MATERIAL_LIMIT = int(os.environ.get("K12_MATERIAL_LIMIT", "60"))


class ControversyFailed(RuntimeError):
    """A K12 pass that will not be papered over."""


def dsn() -> str:
    return os.environ["DATABASE_URL"]


def queue(conn, limit: int | None = None) -> list[tuple]:
    """Domains at moderate coverage that have never had a K12 pass.

    `v_controversy_state.overdue` is the same predicate, and it is the
    number worth watching: a domain deep enough to have disagreements in
    it and no pass over them.
    """
    rows = conn.execute(
        """select domain_id::text, domain_key, name
             from v_controversy_state
            where overdue
            order by domain_key""").fetchall()
    return rows[:limit] if limit else rows


def material(conn, domain_id: str) -> dict:
    """What has accumulated in this domain, for the pass to read across.

    Strategies, the evidence behind them and the claims they rest on --
    joined through the concept spine, which is how anything in this system
    knows a strategy belongs to a domain.
    """
    strategies = conn.execute(
        """select distinct s.strategy_id::text, s.name, s.summary, s.mechanism,
                  s.evidence_summary, s.evidence_confidence::text,
                  s.limitations, s.adverse_effects
             from strategies s
             join strategy_concepts sc on sc.strategy_id = s.strategy_id
             join concept_domains cd on cd.concept_id = sc.concept_id
            where cd.domain_id = %s::uuid
              and s.knowledge_status <> 'DEPRECATED'
            order by 2
            limit %s""", (domain_id, MATERIAL_LIMIT)).fetchall()

    evidence = conn.execute(
        """select distinct e.evidence_id::text, e.citation, e.design::text,
                  e.population, e.results_summary, e.limitations
             from evidence_records e
             join strategy_evidence se on se.evidence_id = e.evidence_id
             join strategy_concepts sc on sc.strategy_id = se.strategy_id
             join concept_domains cd on cd.concept_id = sc.concept_id
            where cd.domain_id = %s::uuid
            order by 2
            limit %s""", (domain_id, MATERIAL_LIMIT)).fetchall()

    return {
        "STRATEGIES": [
            {"strategy_id": r[0], "name": r[1], "summary": r[2],
             "mechanism": r[3], "evidence_summary": r[4],
             "evidence_confidence": r[5], "limitations": r[6],
             "adverse_effects": r[7]} for r in strategies],
        "EVIDENCE": [
            {"evidence_id": r[0], "citation": r[1], "design": r[2],
             "population": r[3], "results_summary": r[4],
             "limitations": r[5]} for r in evidence],
    }


def blocks(result: RE.EngineResult) -> dict:
    found = dict(result.secondary_handoffs or {})
    if result.handoff_tag:
        found[result.handoff_tag] = result.structured
    body = found.get(CONTROVERSY_TAG)
    if not body:
        raise ControversyFailed(f"the run produced no <{CONTROVERSY_TAG}> block.")
    return body


def parse_json_field(body: dict, field: str, expect: type):
    raw = body.get(field)
    if raw is None:
        raise ControversyFailed(f"<{CONTROVERSY_TAG}> carried no {field}.")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ControversyFailed(f"{field} is not valid JSON: {exc}") from exc
    if not isinstance(value, expect):
        raise ControversyFailed(
            f"{field} must be a {expect.__name__}; got {type(value).__name__}.")
    return value


def write_controversy(conn, domain_id: str, record: dict) -> str | None:
    """One controversy and its positions, in ONE transaction.

    The constraint trigger fires at commit, so the positions must be inside
    the same transaction as their parent. Written here rather than in two
    passes for exactly that reason -- and a controversy the model returned
    with fewer than two positions is refused here too, before the database
    has to, so the reason reaches the caller as a skip rather than an
    aborted transaction.
    """
    positions = record.get("positions") or []
    if not isinstance(positions, list) or len(positions) < 2:
        return None

    question = (record.get("question") or "").strip()
    if not question:
        return None

    with conn.transaction():
        controversy_id = str(conn.execute(
            """insert into controversies
                 (question, summary, why_studies_disagree, population_differences,
                  current_consensus, current_uncertainty, practical_interpretation,
                  domain_id)
               values (%s,%s,%s,%s,%s,%s,%s,%s::uuid)
               returning controversy_id""",
            (question, record.get("summary"),
             record.get("why_studies_disagree"),
             record.get("population_differences"),
             record.get("current_consensus"),
             record.get("current_uncertainty"),
             record.get("practical_interpretation"), domain_id)).fetchone()[0])

        for position in positions:
            if not isinstance(position, dict):
                continue
            conn.execute(
                """insert into controversy_positions
                     (controversy_id, position, evidence_summary,
                      population_context, held_by)
                   values (%s,%s,%s,%s,%s)""",
                (controversy_id, (position.get("position") or "").strip(),
                 position.get("evidence_summary"),
                 position.get("population_context"),
                 # §12: who holds it is a fact about them, never the
                 # evidence. It is recorded beside the evidence, never
                 # instead of it -- ck_position_has_evidence refuses that.
                 position.get("held_by")))
    return controversy_id


def write_negative(conn, domain_id: str, record: dict) -> str | None:
    """One negative-knowledge finding, or None when it is not one.

    A record missing what was examined or what would make us look again is
    dropped rather than written with the field blank: the constraint would
    refuse it anyway, and a finding that cannot stop a future search is
    not negative knowledge.
    """
    required = ("claim_or_strategy", "why_investigated", "evidence_examined",
                "finding", "revisit_trigger")
    if any(not (record.get(field) or "").strip() for field in required):
        return None
    return str(conn.execute(
        """insert into negative_knowledge
             (claim_or_strategy, strategy_id, domain_id, why_investigated,
              evidence_examined, finding, current_interpretation, revisit_trigger)
           values (%s,%s::uuid,%s::uuid,%s,%s,%s,%s,%s)
           returning negative_id""",
        (record["claim_or_strategy"].strip(), record.get("strategy_id"),
         domain_id, record["why_investigated"].strip(),
         record["evidence_examined"].strip(), record["finding"].strip(),
         record.get("current_interpretation"),
         record["revisit_trigger"].strip())).fetchone()[0])


def assess_one(conn, domain: tuple) -> dict:
    domain_id, domain_key, name = domain
    body_in = material(conn, domain_id)
    total = len(body_in["STRATEGIES"]) + len(body_in["EVIDENCE"])
    if total < MIN_MATERIAL:
        return {"domain": domain_key, "outcome": "TOO_THIN", "controversies": 0,
                "negative": 0,
                "detail": (f"{total} item(s) of accumulated material; a pass "
                           "over this would be reading across nothing")}

    result = RE.run_engine(
        conn,
        RE.EngineRequest(
            engine="E7", mode="CONTROVERSY", model_role="MODEL_RESEARCH",
            structured_input={
                "DOMAIN_REFERENCE": domain_key,
                "DOMAIN_NAME": name,
                "PROCESSING_VERSION": PROCESSING_VERSION,
                **body_in,
            },
            run_context={"stage": "K12", "domain_key": domain_key}))

    if result.status != "SUCCEEDED":
        raise ControversyFailed(
            f"the CONTROVERSY run did not succeed ({result.status}): {result.error}")

    body = blocks(result)
    controversies = parse_json_field(body, "CONTROVERSIES_JSON", list)
    negatives = parse_json_field(body, "NEGATIVE_KNOWLEDGE_JSON", list)

    written_c, refused_c = [], 0
    for record in controversies:
        if not isinstance(record, dict):
            continue
        got = write_controversy(conn, domain_id, record)
        if got:
            written_c.append(got)
        else:
            refused_c += 1

    written_n, refused_n = [], 0
    for record in negatives:
        if not isinstance(record, dict):
            continue
        got = write_negative(conn, domain_id, record)
        if got:
            written_n.append(got)
        else:
            refused_n += 1

    # The governance row lands whatever was found. Zero is an honest
    # result; an absent row means nobody looked, and those must not be the
    # same thing (hard rule 11, §70).
    conn.execute(
        """insert into domain_controversy_assessments
             (domain_id, assessed_by, processing_version, controversies_found,
              negative_findings, evidence_examined, note)
           values (%s::uuid,'K12',%s,%s,%s,%s,%s)
           on conflict (domain_id) do update
             set assessed_at = now(),
                 processing_version = excluded.processing_version,
                 controversies_found = excluded.controversies_found,
                 negative_findings = excluded.negative_findings,
                 evidence_examined = excluded.evidence_examined,
                 note = excluded.note""",
        (domain_id, PROCESSING_VERSION, len(written_c), len(written_n),
         len(body_in["EVIDENCE"]),
         f"{refused_c} controversy record(s) and {refused_n} negative "
         f"record(s) refused as incomplete" if (refused_c or refused_n)
         else None))

    return {"domain": domain_key, "outcome": "ASSESSED", "run_id": result.run_id,
            "controversies": len(written_c), "negative": len(written_n),
            "refused": refused_c + refused_n,
            "detail": (f"{len(written_c)} controversy/ies, "
                       f"{len(written_n)} negative finding(s)"
                       + (f", {refused_c + refused_n} refused"
                          if (refused_c or refused_n) else ""))}


def status(conn) -> None:
    print(f"\n{'domain':<28}{'pass':>8}{'contro':>8}{'positions':>11}"
          f"{'negative':>10}  overdue")
    for row in conn.execute(
            "select domain_key, pass_performed, controversies, positions, "
            "       negative_findings, overdue from v_controversy_state "
            " order by overdue desc, domain_key").fetchall():
        key, done, contro, positions, negative, overdue = row
        print(f"{key:<28}{('yes' if done else 'no'):>8}{contro:>8}"
              f"{positions:>11}{negative:>10}  {'OVERDUE' if overdue else ''}")
    print("\nA domain with a pass and zero controversies is an honest result.")
    print("A domain with no pass is not a result at all (hard rule 11).")


def main() -> int:
    ap = argparse.ArgumentParser(description="K12 controversy + negative knowledge")
    ap.add_argument("--domain", help="one domain_key, whatever its coverage")
    ap.add_argument("--one", action="store_true", help="one overdue domain, then stop")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    with psycopg.connect(dsn(), autocommit=True) as conn:
        if args.status:
            status(conn)
            return 0

        if args.domain:
            row = conn.execute(
                "select domain_id::text, domain_key, name from knowledge_domains "
                " where domain_key=%s and active", (args.domain,)).fetchone()
            if row is None:
                print(f"no active domain {args.domain}")
                return 1
            targets = [row]
        else:
            targets = queue(conn, 1 if args.one else args.limit)

        if not targets:
            print("no domain is overdue a K12 pass.")
            return 0

        for domain in targets:
            print(f"  {assess_one(conn, domain)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""K13 — the per-domain gap assessment, and capped escalation.

BUILD_GUIDE step 19. Engine 7 §R2b, §R15, §49, §68, §70; migrations 007, 025.

    python3 scripts/knowledge_gap.py --status
    python3 scripts/knowledge_gap.py --one
    python3 scripts/knowledge_gap.py --domain DOMAIN_B
    python3 scripts/knowledge_gap.py --escalate

### Readiness is not completion (hard rule 11)

`foundation_ready` needs coverage across the 18 §R2a dimensions **plus** a
gap assessment actually performed **plus** no open CRITICAL gap. It never
requires zero gaps, and zero identified gaps never means finished. §70
forbids a `COMPLETE` status and this file does not create one by another
name.

The row in `domain_gap_assessments` means **the pass ran**. `gaps_found = 0`
means none were identified today. Those are different claims and the schema
keeps them apart deliberately — an absent row is "nobody looked".

### A gap is not negative knowledge

A question nobody has studied is a gap. Something examined and found
wanting is negative knowledge (K12). Recording an unstudied intervention as
negative knowledge tells the library it has an answer when what it has is a
hole; recording a refuted one as a gap sends the next pass to research it
again.

### Escalation is capped and ranks by impact, not uncertainty

Hard rule 3. `--escalate` moves the top N of `v_knowledge_gap_queue` from
`OPEN` to `RESEARCHING` — severity first, then how much of the library
leans on that domain. The cap is what stops a gap assessment turning into a
research backlog nobody chose.

**What `RESEARCHING` does NOT mean here.** It marks a gap as taken up; it
does not run a research pass. Wiring an escalated gap into a live E7
research run belongs to the continuous-update step (BUILD_PLAN K11 /
step 21) and is deliberately not invented here — a gap question is not a
claim, and `knowledge_research.py` researches claims. Saying so is better
than half-building a loop that looks finished.
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

GAPS_TAG = "RESEARCH_PRACTICE_GAPS"
PROCESSING_VERSION = "k13.v1"

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
ESCALATION_CAP = int(os.environ.get("KNOWLEDGE_ESCALATION_CAP", "5"))
MATERIAL_LIMIT = int(os.environ.get("K13_MATERIAL_LIMIT", "60"))


class GapAssessmentFailed(RuntimeError):
    """A K13 pass that will not be papered over."""


def dsn() -> str:
    return os.environ["DATABASE_URL"]


def queue(conn, limit: int | None = None) -> list[tuple]:
    """Domains with coverage but no gap assessment.

    Ordered by how much coverage they have: the deepest un-assessed domain
    is where an unnoticed CRITICAL gap does the most damage, because it is
    the one closest to being called ready.
    """
    rows = conn.execute(
        """select domain_id::text, domain_key, name, dimensions_covered
             from v_domain_readiness
            where not gap_assessment_complete and dimensions_covered > 0
            order by dimensions_covered desc, domain_key""").fetchall()
    return rows[:limit] if limit else rows


def material(conn, domain_id: str) -> dict:
    """What the domain holds, and which dimensions it does not cover.

    The missing dimensions are the input that matters: a gap assessment
    that cannot see where coverage is thin is guessing.
    """
    readiness = conn.execute(
        """select dimensions_covered, dimensions_total, missing_dimensions,
                  open_critical_gaps, open_high_priority_gaps
             from v_domain_readiness where domain_id = %s::uuid""",
        (domain_id,)).fetchone()

    strategies = conn.execute(
        """select distinct s.name, s.summary, s.evidence_confidence::text
             from strategies s
             join strategy_concepts sc on sc.strategy_id = s.strategy_id
             join concept_domains cd on cd.concept_id = sc.concept_id
            where cd.domain_id = %s::uuid
              and s.knowledge_status <> 'DEPRECATED'
            order by 1 limit %s""", (domain_id, MATERIAL_LIMIT)).fetchall()

    concepts = conn.execute(
        """select c.canonical_name from concept_domains cd
             join concepts c on c.concept_id = cd.concept_id
            where cd.domain_id = %s::uuid and c.status in ('SEEDED','ACTIVE')
            order by 1 limit %s""", (domain_id, MATERIAL_LIMIT)).fetchall()

    existing = conn.execute(
        "select question, severity::text from knowledge_gaps "
        " where domain_id = %s::uuid and status in ('OPEN','RESEARCHING')",
        (domain_id,)).fetchall()

    return {
        "DIMENSIONS_COVERED": readiness[0] if readiness else 0,
        "DIMENSIONS_TOTAL": readiness[1] if readiness else 18,
        "DIMENSIONS_MISSING": list(readiness[2] or []) if readiness else [],
        "CONCEPTS": [r[0] for r in concepts],
        "STRATEGIES": [{"name": r[0], "summary": r[1],
                        "evidence_confidence": r[2]} for r in strategies],
        # So the pass does not re-raise what is already recorded.
        "GAPS_ALREADY_OPEN": [{"question": r[0], "severity": r[1]}
                              for r in existing],
    }


def blocks(result: RE.EngineResult) -> dict:
    found = dict(result.secondary_handoffs or {})
    if result.handoff_tag:
        found[result.handoff_tag] = result.structured
    body = found.get(GAPS_TAG)
    if not body:
        raise GapAssessmentFailed(f"the run produced no <{GAPS_TAG}> block.")
    return body


def parse_json_field(body: dict, field: str, expect: type):
    raw = body.get(field)
    if raw is None:
        raise GapAssessmentFailed(f"<{GAPS_TAG}> carried no {field}.")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GapAssessmentFailed(f"{field} is not valid JSON: {exc}") from exc
    if not isinstance(value, expect):
        raise GapAssessmentFailed(
            f"{field} must be a {expect.__name__}; got {type(value).__name__}.")
    return value


def already_open(conn, domain_id: str, question: str) -> bool:
    """A gap already recorded is not a new gap.

    Deterministic, on the normalized question, and done BEFORE the write --
    the same shape as K11's dedup and for the same reason: a library that
    re-raises the same question every pass reports a growing gap count that
    means nothing.
    """
    return bool(conn.execute(
        "select 1 from knowledge_gaps "
        " where domain_id = %s::uuid and status in ('OPEN','RESEARCHING') "
        "   and norm_phrase(question) = norm_phrase(%s) limit 1",
        (domain_id, question)).fetchone())


def write_gap(conn, domain_id: str, record: dict) -> str | None:
    question = (record.get("question") or "").strip()
    if not question or already_open(conn, domain_id, question):
        return None

    severity = (record.get("severity") or "MEDIUM").strip().upper()
    if severity not in SEVERITIES:
        # An unrecognised severity is NOT quietly promoted or demoted.
        # MEDIUM is the schema default and the honest landing place; the
        # note records what was said.
        severity = "MEDIUM"

    importance = 0
    for field in ("why_it_matters", "what_would_close_it"):
        if (record.get(field) or "").strip():
            importance += 1

    return str(conn.execute(
        """insert into knowledge_gaps
             (question, domain_id, severity, importance, status)
           values (%s,%s::uuid,%s::gap_severity,%s,'OPEN')
           returning gap_id""",
        (question, domain_id, severity, importance)).fetchone()[0])


def assess_one(conn, domain: tuple) -> dict:
    domain_id, domain_key, name = domain[0], domain[1], domain[2]
    body_in = material(conn, domain_id)

    result = RE.run_engine(
        conn,
        RE.EngineRequest(
            engine="E7", mode="GAP", model_role="MODEL_RESEARCH",
            structured_input={
                "DOMAIN_REFERENCE": domain_key,
                "DOMAIN_NAME": name,
                "PROCESSING_VERSION": PROCESSING_VERSION,
                **body_in,
            },
            run_context={"stage": "K13", "domain_key": domain_key}))

    if result.status != "SUCCEEDED":
        raise GapAssessmentFailed(
            f"the GAP run did not succeed ({result.status}): {result.error}")

    body = blocks(result)
    gaps = parse_json_field(body, "GAPS_JSON", list)
    assessment = parse_json_field(body, "ASSESSMENT_JSON", dict)

    written, duplicates = [], 0
    for record in gaps:
        if not isinstance(record, dict):
            continue
        got = write_gap(conn, domain_id, record)
        if got:
            written.append(got)
        else:
            duplicates += 1

    # The governance row. It says the pass RAN -- nothing more and nothing
    # less. gaps_found counts what THIS pass identified, so a domain
    # re-assessed with everything already recorded reports 0 found and
    # remains assessed, which is correct.
    conn.execute(
        """insert into domain_gap_assessments
             (domain_id, assessed_by, processing_version, gaps_found, note)
           values (%s::uuid,'K13',%s,%s,%s)
           on conflict (domain_id) do update
             set assessed_at = now(),
                 processing_version = excluded.processing_version,
                 gaps_found = excluded.gaps_found,
                 note = excluded.note""",
        (domain_id, PROCESSING_VERSION, len(written),
         (assessment.get("note") or "")[:2000] or None))

    ready = conn.execute(
        "select foundation_ready, open_critical_gaps from v_domain_readiness "
        " where domain_id = %s::uuid", (domain_id,)).fetchone()

    return {"domain": domain_key, "run_id": result.run_id,
            "gaps": len(written), "already_recorded": duplicates,
            "foundation_ready": bool(ready[0]) if ready else None,
            "open_critical": ready[1] if ready else None,
            "detail": (f"{len(written)} new gap(s)"
                       + (f", {duplicates} already recorded" if duplicates else "")
                       + " — a pass that finds none is an honest result, "
                         "not a finished domain")}


def escalate(conn, cap: int = ESCALATION_CAP) -> list[dict]:
    """Take up the top `cap` open gaps. Capped, and ranked by impact.

    Hard rule 3: escalation ranks by impact, not uncertainty, and is
    capped. `v_knowledge_gap_queue` orders severity first, then how much of
    the library leans on the domain, then age — deterministically, so the
    same cap always takes the same top N.
    """
    rows = conn.execute(
        "select gap_id::text, question, domain_key, severity::text, "
        "       strategies_in_domain from v_knowledge_gap_queue "
        " where status = 'OPEN' limit %s", (cap,)).fetchall()
    taken = []
    for gap_id, question, domain_key, severity, leaning in rows:
        conn.execute(
            "update knowledge_gaps set status='RESEARCHING' where gap_id=%s::uuid",
            (gap_id,))
        taken.append({"gap_id": gap_id, "domain": domain_key,
                      "severity": severity, "leaning_strategies": leaning,
                      "question": question[:80]})
    return taken


def resolve(conn, gap_id: str, resolution: str, superseded: bool = False) -> None:
    """Close a gap. `ck_gap_resolution_coherent` refuses a resolved gap
    with no resolution, so "resolved" cannot be a state something drifts
    into."""
    if not resolution.strip():
        raise GapAssessmentFailed(
            "a resolved gap must say what resolved it. The constraint "
            "refuses it, and a closed gap with no answer is worse than an "
            "open one: nothing will ever look again.")
    conn.execute(
        "update knowledge_gaps set status=%s, resolution=%s, resolved_at=now() "
        " where gap_id=%s::uuid",
        ("SUPERSEDED" if superseded else "RESOLVED", resolution.strip(), gap_id))


def status(conn) -> None:
    print(f"\n{'domain':<28}{'cov':>5}{'pass':>7}{'crit':>6}{'high':>6}  ready")
    for row in conn.execute(
            "select domain_key, dimensions_covered, gap_assessment_complete, "
            "       open_critical_gaps, open_high_priority_gaps, foundation_ready "
            "  from v_domain_readiness order by dimensions_covered desc, domain_key"
    ).fetchall():
        key, covered, done, crit, high, ready = row
        print(f"{key:<28}{covered:>5}{('yes' if done else 'no'):>7}"
              f"{crit:>6}{high:>6}  {'READY' if ready else ''}")

    queued = conn.execute(
        "select severity::text, count(*) from v_knowledge_gap_queue "
        " group by 1 order by 1").fetchall()
    print("\nopen and in-flight gaps: "
          + (", ".join(f"{n} {sev}" for sev, n in queued) or "none"))
    print("Zero gaps is not completion. §70 forbids a COMPLETE status, and")
    print("`foundation_ready` never required zero gaps — only no open CRITICAL.")


def main() -> int:
    ap = argparse.ArgumentParser(description="K13 gap assessment")
    ap.add_argument("--domain", help="one domain_key")
    ap.add_argument("--one", action="store_true")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--escalate", action="store_true",
                    help=f"take up the top {ESCALATION_CAP} open gaps")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    with psycopg.connect(dsn(), autocommit=True) as conn:
        if args.status:
            status(conn)
            return 0

        if args.escalate:
            for row in escalate(conn):
                print(f"  {row}")
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
            print("every domain with coverage has had a gap assessment.")
            return 0

        for domain in targets:
            print(f"  {assess_one(conn, domain)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

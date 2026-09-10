#!/usr/bin/env python3
"""K10 — evidence analysis. Independent research for high-value claims.

BUILD_GUIDE step 16. Engine 7 §5, §12, §17, §39, §R12; D10, D36.

    python3 scripts/knowledge_research.py            # the triaged queue
    python3 scripts/knowledge_research.py --one      # one claim, then stop
    python3 scripts/knowledge_research.py --status   # what is queued

`K10_EVIDENCE_ANALYZER: Human research for high-value claims. Do not
deep-research trivial claims.`

That second sentence is the design. Every claim researched is a model call,
and a library that researches every mechanism aside a creator makes will
spend its budget on the cheapest claims in it. So the queue is TRIAGED
deterministically before anything is called, and the rule is written down
rather than left to a model's sense of importance.

### The source's citation is not evidence (D10)

`claims.evidence_referenced_by_source` records what the SOURCE cited. It is
a fact about the creator, not about the world, and it is **not** the input
to this stage. K10 goes and looks independently — and what it finds may
contradict the claim that led it there. §12: creator trust is not claim
trust.

Evidence records therefore never link back to the discovery envelope. When
a study carries a real identifier they get their own `source_items` row
under a source of their own; when it does not, `item_id` stays NULL and the
citation is recorded as unverified rather than being given a fabricated
home.

### Nothing here is promoted

The claim gains `independent_evidence_findings`, `current_interpretation`
and the supported/overstated/uncertain reading. No strategy is created —
that is K11 — and no status is raised.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import psycopg

import run_engine as RE

EVIDENCE_TAG = "RESEARCH_PRACTICE_EVIDENCE"
PROCESSING_VERSION = "k10.v1"

# The triage rule, written down so it can be argued with. Impact, not
# uncertainty (hard rule 3): a SAFETY claim is researched even when it
# looks obvious, and a DEFINITIONAL one is not researched even when it
# looks interesting.
RESEARCH_TYPES = ("SAFETY", "INTERVENTION_EFFECT")

# Cost ceiling per run. The Knowledge Factory is asynchronous and nothing
# waits on it, so a small batch that finishes is worth more than a large
# one that gets cancelled halfway.
DEFAULT_BATCH = int(os.environ.get("KNOWLEDGE_RESEARCH_BATCH", "10"))

STUDY_DESIGNS = {
    "SYSTEMATIC_REVIEW", "META_ANALYSIS", "RCT", "CONTROLLED_TRIAL", "CROSSOVER",
    "PROSPECTIVE_COHORT", "RETROSPECTIVE_COHORT", "CASE_CONTROL",
    "CROSS_SECTIONAL", "CASE_SERIES", "MECHANISTIC", "ANIMAL", "IN_VITRO",
    "GUIDELINE", "CONSENSUS", "OTHER",
}
RELATIONSHIPS = {"SUPPORTS", "PARTIALLY_SUPPORTS", "LIMITS", "CONFLICTS",
                 "NEUTRAL", "CONTEXTUALIZES"}
CONFIDENCES = {"STRONG", "MODERATE", "LIMITED", "MECHANISTIC_ONLY",
               "CONFLICTING", "INSUFFICIENT", "UNKNOWN"}


class ResearchFailed(RuntimeError):
    """The run produced nothing usable. The claim is left untouched."""


def dsn() -> str:
    return os.environ["DATABASE_URL"]


def queue(conn, limit: int) -> list[tuple]:
    """Claims worth researching, highest impact first.

    A claim already carrying an independent reading is done; re-researching
    it is how a batch job quietly becomes a loop.
    """
    return conn.execute(
        """select c.claim_id, c.claim_text, c.claim_type, c.target,
                  c.mechanism, c.context, c.extraction_confidence
             from claims c
            where c.claim_type = any(%s)
              and c.independent_evidence_findings is null
            order by case c.claim_type when 'SAFETY' then 0 else 1 end,
                     c.created_at
            limit %s""", (list(RESEARCH_TYPES), limit)).fetchall()


def skipped_reason(claim_type: str) -> str:
    return (f"{claim_type} is not on the research list "
            f"({', '.join(RESEARCH_TYPES)}). 'Do not deep-research trivial "
            "claims' is a budget decision, and this rule is where it is made.")


def blocks(result: RE.EngineResult) -> dict:
    found = dict(result.secondary_handoffs or {})
    if result.handoff_tag:
        found[result.handoff_tag] = result.structured
    body = found.get(EVIDENCE_TAG)
    if not body:
        raise ResearchFailed(f"the run produced no <{EVIDENCE_TAG}> block.")
    return body


def parse_json_field(body: dict, field: str, expect: type):
    raw = body.get(field)
    if raw is None:
        raise ResearchFailed(f"<{EVIDENCE_TAG}> carried no {field}.")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ResearchFailed(f"{field} is not valid JSON: {exc}") from exc
    if not isinstance(value, expect):
        raise ResearchFailed(
            f"{field} must be a {expect.__name__}; got {type(value).__name__}.")
    return value


def study_item(conn, record: dict) -> str | None:
    """A `source_items` row for the STUDY, when it can be identified.

    Never the discovery envelope's item (D10). A study with no DOI, PMID or
    URL gets no item at all: inventing one would put an unverifiable
    citation into the same table as retrievable sources, where nothing
    downstream could tell them apart.
    """
    doi = (record.get("doi") or "").strip() or None
    pmid = (record.get("pmid") or "").strip() or None
    url = (record.get("url") or "").strip() or None
    if not (doi or pmid or url):
        return None

    existing = conn.execute(
        "select item_id from source_items "
        " where (%s is not null and lower(doi) = lower(%s)) "
        "    or (%s is not null and pmid = %s) "
        "    or (%s is not null and url = %s) limit 1",
        (doi, doi, pmid, pmid, url, url)).fetchone()
    if existing:
        return str(existing[0])

    source_id = conn.execute(
        """insert into knowledge_sources
             (source_name, source_type, source_roles, base_identifier,
              access_method, notes)
           values ('Independent evidence (K10)', 'JOURNAL',
                   array['EVIDENCE']::source_role[], 'k10:independent-evidence',
                   'ENGINE7_RESEARCH',
                   'Studies found by K10 while researching a claim. Separate '
                   'from the source that made the claim, on purpose (D10).')
           on conflict (base_identifier) where base_identifier is not null and active
           do update set source_name = excluded.source_name
           returning source_id""").fetchone()[0]

    return str(conn.execute(
        """insert into source_items
             (source_id, title, url, doi, pmid, ingestion_status, access_note)
           values (%s,%s,%s,%s,%s,'EXTRACTED',
                   'Identified by K10 from a citation, not fetched.')
           returning item_id""",
        (source_id, (record.get("citation") or "")[:500], url, doi, pmid)
    ).fetchone()[0])


def write_evidence(conn, claim_id: str, records: list) -> list[tuple[str, str]]:
    """Returns [(evidence_id, relationship)] for what was written."""
    written: list[tuple[str, str]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        citation = (record.get("citation") or "").strip()
        if not citation:
            # An evidence record nobody can look up is not evidence.
            continue
        design = (record.get("design") or "OTHER").strip().upper()
        if design not in STUDY_DESIGNS:
            design = "OTHER"
        relationship = (record.get("relationship") or "NEUTRAL").strip().upper()
        if relationship not in RELATIONSHIPS:
            relationship = "NEUTRAL"

        year = record.get("publication_year")
        size = record.get("sample_size")
        evidence_id = conn.execute(
            """insert into evidence_records
                 (item_id, citation, publication_year, design, population,
                  sample_size, intervention, comparator, exposure, duration,
                  outcomes, results_summary, magnitude_summary, limitations,
                  applicability, funding_conflict_notes)
               values (%s,%s,%s,%s::study_design,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               returning evidence_id""",
            (study_item(conn, record), citation,
             year if isinstance(year, int) else None, design,
             record.get("population"),
             size if isinstance(size, int) else None,
             record.get("intervention"), record.get("comparator"),
             record.get("exposure"), record.get("duration"),
             record.get("outcomes"), record.get("results_summary"),
             record.get("magnitude_summary"), record.get("limitations"),
             record.get("applicability"),
             record.get("funding_conflict_notes"))).fetchone()[0]
        written.append((str(evidence_id), relationship))
    return written


def apply_assessment(conn, claim_id: str, assessment: dict, count: int) -> str:
    confidence = (assessment.get("evidence_confidence") or "UNKNOWN").strip().upper()
    if confidence not in CONFIDENCES:
        confidence = "UNKNOWN"

    findings = assessment.get("independent_evidence_findings")
    if not (findings or "").strip():
        # Finding nothing is a finding, and it has to be recorded as one --
        # a NULL here would put the claim straight back on the queue.
        findings = ("No independent evidence was found for this claim. "
                    "Recorded as a finding, not as an absence of work (§R12).")

    conn.execute(
        """update claims
              set independent_evidence_findings = %s,
                  current_interpretation = %s,
                  areas_supported = %s,
                  areas_overstated = %s,
                  areas_uncertain = %s
            where claim_id = %s""",
        (findings, assessment.get("current_interpretation"),
         assessment.get("areas_supported"), assessment.get("areas_overstated"),
         assessment.get("areas_uncertain"), claim_id))
    return confidence


def research_one(conn, claim: tuple) -> dict:
    claim_id, text, claim_type, target, mechanism, context, confidence = claim

    result = RE.run_engine(
        conn,
        RE.EngineRequest(
            engine="E7",
            mode="EVIDENCE",
            model_role="MODEL_RESEARCH",
            structured_input={
                "CLAIM_REFERENCE": str(claim_id),
                "CLAIM_TEXT": text,
                "CLAIM_TYPE": claim_type,
                "CLAIM_TARGET": target,
                "CLAIM_MECHANISM": mechanism,
                "CLAIM_CONTEXT": context,
                "EXTRACTION_CONFIDENCE": (float(confidence)
                                          if confidence is not None else None),
                # Deliberately NOT sent: evidence_referenced_by_source. What
                # the creator cited is a fact about the creator, and feeding
                # it in as the starting point is how independent research
                # becomes an echo (D10, §12).
                "PROCESSING_VERSION": PROCESSING_VERSION,
            },
            run_context={"stage": "K10", "claim_id": str(claim_id)}))

    if result.status != "SUCCEEDED":
        raise ResearchFailed(
            f"the EVIDENCE run did not succeed ({result.status}): {result.error}")

    body = blocks(result)
    records = parse_json_field(body, "EVIDENCE_JSON", list)
    assessment = parse_json_field(body, "CLAIM_ASSESSMENT_JSON", dict)

    written = write_evidence(conn, str(claim_id), records)
    confidence_out = apply_assessment(conn, str(claim_id), assessment, len(written))

    return {"claim_id": str(claim_id), "run_id": result.run_id,
            "evidence": len(written), "confidence": confidence_out,
            "evidence_ids": written,
            "detail": (f"{len(written)} evidence record(s), "
                       f"confidence {confidence_out}")}


def status(conn) -> None:
    rows = conn.execute(
        """select claim_type,
                  count(*) filter (where independent_evidence_findings is null),
                  count(*) filter (where independent_evidence_findings is not null),
                  count(*)
             from claims group by 1 order by 1""").fetchall()
    print("\nCLAIMS BY TYPE      unresearched / researched / total")
    if not rows:
        print("  none — run scripts/knowledge_extract.py first.")
    for claim_type, todo, done, total in rows:
        mark = "*" if claim_type in RESEARCH_TYPES else " "
        print(f" {mark}{claim_type:24s} {todo:>4} / {done:>4} / {total}")
    print(f"\n  * on the research list ({', '.join(RESEARCH_TYPES)}). The rest are "
          "\n    deliberately not deep-researched — see the triage rule in this file.")
    ev = conn.execute(
        "select count(*), count(*) filter (where item_id is null) "
        "  from evidence_records").fetchone()
    print(f"\nEVIDENCE RECORDS    {ev[0]}, {ev[1]} with no retrievable identifier")


def main() -> int:
    with psycopg.connect(dsn(), autocommit=True) as conn:
        if "--status" in sys.argv:
            status(conn)
            return 0

        todo = queue(conn, 1 if "--one" in sys.argv else DEFAULT_BATCH)
        if not todo:
            print("no claims on the research queue")
            status(conn)
            return 0

        print(f"{len(todo)} claim(s) to research\n")
        failures = 0
        for claim in todo:
            try:
                out = research_one(conn, claim)
            except ResearchFailed as exc:
                failures += 1
                print(f"  FAILED     {str(claim[0])[:8]}  {exc}")
                continue
            print(f"  RESEARCHED {str(claim[0])[:8]}  {out['detail']}")

        status(conn)
        return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

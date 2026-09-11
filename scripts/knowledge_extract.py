#!/usr/bin/env python3
"""K09 — claim extraction, and the concept normalization that follows it.

BUILD_GUIDE step 16. Engine 7 §17, §39, §54, §55, §R10, §R11; D10, D11,
D24, D35.

    python3 scripts/knowledge_extract.py            # every NORMALIZED envelope
    python3 scripts/knowledge_extract.py --one      # exactly one, then stop
    python3 scripts/knowledge_extract.py --status   # what is waiting

This is the first stage of the Knowledge Factory that calls a model. K07
and K08 are deterministic; from here on an envelope's fate depends on what
Engine 7 says about it, which is why every claim it produces carries the
run that produced it and the envelope it came from.

### The pipeline this implements

§17: SOURCE → CLAIM → CONCEPT NORMALIZATION → EVIDENCE RETRIEVAL → …

This module covers the first three. Evidence retrieval is K10 and strategy
synthesis is K11, and the boundary matters: **nothing here creates a
strategy, and nothing here creates an evidence record.**

### The source of the idea is not the source of the evidence (D10)

`claims.evidence_referenced_by_source` records what the SOURCE cited. It is
text, it stays text, and it never becomes an `evidence_records` row.
`envelope_derived_records` is written with `discovery_only = true`: this
envelope surfaced the claim, it does not evidence it. A video that gave us
an idea has not proved it.

### Extraction confidence is not authorisation (hard rule 4)

A claim extracted at 0.95 means the model read the source correctly. It
does not mean the claim is true, and nothing here promotes anything: every
claim lands unverified and every concept the claims mention goes through
the same normalization tiers as any other phrase — deterministic first,
escalating only high-impact ambiguity.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import psycopg

import normalize
import run_engine as RE

CLAIMS_TAG = "RESEARCH_PRACTICE_CLAIMS"
INBOX_TAG = "RESEARCH_PRACTICE_INBOX_HANDOFF"
PROCESSING_VERSION = "k09.v1"

# What a Claim Card may declare. Anything else lands in OTHER rather than
# being rejected -- an unseen claim type is a gap in this list, not a
# reason to lose the claim (the same reasoning as source_kinds' OTHER).
CLAIM_TYPES = {"INTERVENTION_EFFECT", "MECHANISM", "ASSOCIATION", "SAFETY",
               "IMPLEMENTATION", "DEFINITIONAL", "OTHER"}


class ExtractionFailed(RuntimeError):
    """The run did not produce usable claims. The envelope is not advanced."""


def dsn() -> str:
    return os.environ["DATABASE_URL"]


def pending(conn, limit: int | None = None) -> list[tuple]:
    rows = conn.execute(
        """select e.envelope_id, e.source_title, e.source_kind, e.source_role::text,
                  e.rights::text, e.content_hash, e.source_version
             from source_envelopes e
            where e.status = 'NORMALIZED'
              and e.send_to_e7
              and e.duplicate_of is null
            order by e.ingested_at""").fetchall()
    return rows[:limit] if limit else rows


def chunks_for(conn, content_hash: str) -> list[tuple[str, str]]:
    """(location, text) for one envelope's document, in order."""
    return conn.execute(
        """select coalesce(c.metadata->>'location', '(body)'), c.text
             from knowledge_chunks c
             join source_documents d on d.document_id = c.document_id
             join source_items i on i.item_id = d.item_id
            where i.content_hash = %s
            order by c.chunk_index""", (content_hash,)).fetchall()


def held_out(conn, content_hash: str) -> bool:
    """A3: a held-out source is the retrieval answer key, never synthesised from."""
    row = conn.execute(
        "select held_out from source_items where content_hash=%s", (content_hash,)
    ).fetchone()
    return bool(row and row[0])


def build_input(envelope: tuple, pieces: list[tuple[str, str]]) -> dict:
    envelope_id, title, kind, role, rights, _hash, version = envelope
    return {
        "SOURCE_REFERENCE": str(envelope_id),
        "SOURCE_TITLE": title,
        "SOURCE_KIND": kind,
        "SOURCE_ROLE": role,
        "RIGHTS_CONTEXT": rights,
        "SOURCE_VERSION": version,
        "PROCESSING_VERSION": PROCESSING_VERSION,
        # Located, so an extracted claim can be pointed back at a place in
        # the source. A claim nobody can check is not worth storing.
        "SOURCE_CONTENT": [{"location": loc, "text": text} for loc, text in pieces],
    }


def claim_cards(result: RE.EngineResult) -> list[dict]:
    """The Claim Cards from a completed INBOX run (§R11).

    Both INBOX blocks are required, so which one RUN_ENGINE calls primary
    is registry ordering and not something to depend on. Look both up by
    tag.
    """
    blocks = dict(result.secondary_handoffs or {})
    if result.handoff_tag:
        blocks[result.handoff_tag] = result.structured
    body = blocks.get(CLAIMS_TAG)
    if not body:
        raise ExtractionFailed(
            f"the run produced no <{CLAIMS_TAG}> block. §R10 reports the "
            "information gain and deliberately not the claims, so without "
            "this there is nothing to normalize or synthesise from.")

    raw = body.get("CLAIMS_JSON")
    if raw is None:
        raise ExtractionFailed(f"<{CLAIMS_TAG}> carried no CLAIMS_JSON field.")
    try:
        cards = json.loads(raw)
    except json.JSONDecodeError as exc:
        # K09 says strict JSON. Half-parsing it into whatever survives is
        # how a malformed extraction becomes a plausible-looking claim.
        raise ExtractionFailed(f"CLAIMS_JSON is not valid JSON: {exc}") from exc
    if not isinstance(cards, list):
        raise ExtractionFailed(
            f"CLAIMS_JSON must be an array; got {type(cards).__name__}.")
    return cards


def clamp_confidence(value) -> float | None:
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return None
    # Out of range is a malformed answer, not something to squash silently
    # into 1.0 -- but it is also not worth losing the claim over.
    return conf if 0.0 <= conf <= 1.0 else None


def write_claims(conn, envelope_id, item_id, cards: list[dict]) -> list[str]:
    written: list[str] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        text = (card.get("claim_text") or "").strip()
        if not text:
            # A Claim Card with no claim is not a claim.
            continue
        claim_type = (card.get("claim_type") or "OTHER").strip().upper()
        if claim_type not in CLAIM_TYPES:
            claim_type = "OTHER"

        # §39 keeps more fields than the claims table has columns for.
        # Rather than widening settled schema, the ones without a column
        # ride in `context`, labelled, so nothing the source said is lost.
        extra = {k: card.get(k) for k in ("population", "magnitude", "location")
                 if card.get(k)}
        context = card.get("context") or ""
        if extra:
            context = (context + " | " if context else "") + "; ".join(
                f"{k}={v}" for k, v in extra.items())

        claim_id = conn.execute(
            """insert into claims
                 (item_id, claim_text, claim_type, target, mechanism, context,
                  evidence_referenced_by_source, extraction_confidence)
               values (%s,%s,%s,%s,%s,%s,%s,%s) returning claim_id""",
            (item_id, text, claim_type,
             card.get("target"), card.get("mechanism"),
             context or None,
             # D10: what the SOURCE cited. Text, and it stays text.
             card.get("evidence_referenced_by_source"),
             clamp_confidence(card.get("extraction_confidence")))).fetchone()[0]

        # D11/hard rule 12: the provenance edge, and discovery_only means
        # this envelope surfaced the claim rather than evidencing it (D10).
        conn.execute(
            """insert into envelope_derived_records
                 (envelope_id, derived_kind, derived_id, discovery_only,
                  processing_version)
               values (%s,'CLAIM',%s,true,%s)
               on conflict do nothing""",
            (envelope_id, claim_id, PROCESSING_VERSION))
        written.append(str(claim_id))
    return written


def normalize_claim_concepts(conn, cards: list[dict]) -> tuple[int, int, int]:
    """§17's CONCEPT NORMALIZATION step. Returns (seen, known, new).

    The phrases a claim is ABOUT -- its target, its intervention and its
    mechanism -- go through the same tiers as any other phrase. Nothing
    here is special-cased for knowledge ingestion, which is the point: one
    ontology, one resolver.
    """
    phrases: list[str] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        for key in ("target", "intervention", "mechanism"):
            value = (card.get(key) or "").strip()
            if value and value not in phrases:
                phrases.append(value)

    known = new = 0
    for phrase in phrases:
        res = normalize.resolve(conn, phrase, context="K09 claim extraction")
        if res.concept_ids:
            known += 1
        else:
            new += 1
    return len(phrases), known, new


def classify_delta(claims_written: int, genuinely_new: int) -> str:
    """§54's verdict, from what actually happened rather than what was said.

    Deliberately conservative, and deliberately NOT the model's own count.
    Three outcomes are decidable at this stage:

      no claims at all            -> LOW_INFORMATION_GAIN
      claims, no new concepts     -> SUPPORTS_EXISTING
      claims and new concepts     -> NEW_CLAIM_REQUIRES_RESEARCH

    POTENTIAL_NEW_STRATEGY is NOT among them. That verdict belongs to K11
    after synthesis has actually compared the claim against the library;
    reaching it here would be a strategy decision made by the extractor.
    ALREADY_KNOWN is also withheld -- ck_delta_known_consistent forbids it
    alongside new items, and at this stage "already known" has not been
    established, only "nothing new was proposed".
    """
    if claims_written == 0:
        return "LOW_INFORMATION_GAIN"
    return "SUPPORTS_EXISTING" if genuinely_new == 0 else "NEW_CLAIM_REQUIRES_RESEARCH"


def extract_one(conn, envelope: tuple) -> dict:
    envelope_id, title, kind, _role, _rights, content_hash, _version = envelope

    if held_out(conn, content_hash):
        # A3. A held-out source is the answer key for retrieval evaluation.
        # Extracting from it puts the answers into the library being tested.
        conn.execute(
            "update source_envelopes set status='SKIPPED', processed_at=now(), "
            "       failure_reason=%s where envelope_id=%s",
            ("held out for retrieval evaluation (A3): never synthesised from",
             envelope_id))
        return {"envelope_id": str(envelope_id), "outcome": "HELD_OUT",
                "claims": 0, "detail": "held out (A3); nothing extracted"}

    pieces = chunks_for(conn, content_hash)
    if not pieces:
        raise ExtractionFailed(
            f"envelope {envelope_id} is NORMALIZED but has no chunks.")

    item_id = conn.execute(
        "select item_id from source_items where content_hash=%s", (content_hash,)
    ).fetchone()[0]

    result = RE.run_engine(
        conn,
        RE.EngineRequest(
            engine="E7",
            mode="INBOX",
            model_role="MODEL_EXTRACTION",
            structured_input=build_input(envelope, pieces),
            run_context={"stage": "K09", "envelope_id": str(envelope_id),
                         "processing_version": PROCESSING_VERSION}))

    if result.status != "SUCCEEDED":
        raise ExtractionFailed(
            f"the INBOX run did not succeed ({result.status}): {result.error}")

    cards = claim_cards(result)
    written = write_claims(conn, envelope_id, item_id, cards)
    seen, known, new = normalize_claim_concepts(conn, cards)

    conn.execute(
        """insert into source_delta_analyses
             (envelope_id, classification, rationale, concepts_extracted,
              claims_extracted, already_known_count, genuinely_new_count,
              processing_version)
           values (%s,%s::delta_classification,%s,%s,%s,%s,%s,%s)
           on conflict (envelope_id, coalesce(processing_version,''))
           do nothing""",
        (envelope_id, classify_delta(len(written), new),
         f"K09: {len(written)} claim(s) from {len(pieces)} chunk(s); "
         f"{known} concept phrase(s) already known, {new} newly proposed. "
         "Classification is derived from what was written, not from the "
         "model's own counts.",
         seen, len(written), known, new, PROCESSING_VERSION))

    conn.execute(
        "update source_envelopes set status='EXTRACTED', processed_at=now() "
        " where envelope_id=%s", (envelope_id,))

    return {"envelope_id": str(envelope_id), "outcome": "EXTRACTED",
            "run_id": result.run_id, "claims": len(written),
            "concepts_seen": seen, "concepts_known": known, "concepts_new": new,
            "detail": f"{len(written)} claim(s), {new} new concept(s)"}


def status(conn) -> None:
    waiting = conn.execute(
        "select count(*) from source_envelopes where status='NORMALIZED' "
        "  and send_to_e7 and duplicate_of is null").fetchone()[0]
    print(f"\nWAITING FOR K09   {waiting} envelope(s) at NORMALIZED")
    rows = conn.execute(
        "select classification::text, count(*), sum(claims_extracted) "
        "  from source_delta_analyses group by 1 order by 2 desc").fetchall()
    print("\nDELTA ANALYSES")
    if not rows:
        print("  none — nothing has been extracted yet.")
    for classification, n, claims in rows:
        print(f"  {classification:28s} {n} source(s), {claims or 0} claim(s)")
    total = conn.execute("select count(*) from claims").fetchone()[0]
    linked = conn.execute(
        "select count(*) from envelope_derived_records where derived_kind='CLAIM'"
    ).fetchone()[0]
    print(f"\nCLAIMS            {total}, {linked} with a provenance edge")


def main() -> int:
    with psycopg.connect(dsn(), autocommit=True) as conn:
        if "--status" in sys.argv:
            status(conn)
            return 0

        todo = pending(conn, limit=1 if "--one" in sys.argv else None)
        if not todo:
            print("nothing at NORMALIZED; run scripts/knowledge_ingest.py first")
            status(conn)
            return 0

        print(f"{len(todo)} envelope(s) to extract from\n")
        failures = 0
        for envelope in todo:
            try:
                out = extract_one(conn, envelope)
            except ExtractionFailed as exc:
                failures += 1
                conn.execute(
                    "update source_envelopes set status='FAILED', "
                    "       failure_reason=%s, processed_at=now() "
                    " where envelope_id=%s", (str(exc)[:2000], envelope[0]))
                print(f"  FAILED     {envelope[1]}  {exc}")
                continue
            print(f"  {out['outcome']:10s} {envelope[1]}  {out['detail']}")

        status(conn)
        return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

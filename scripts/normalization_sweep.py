#!/usr/bin/env python3
"""GATE 2 measurement — what the semantic tier does to the D47 phrases.

Reads `testing/fixtures/normalization/d47_answer_key.json`, which was
committed BEFORE this tier existed (commit dd95388) and holds, per phrase,
the outcome it SHOULD have. Nothing here assigns a verdict; it scores
against one written down earlier.

It writes NOTHING. Every resolution runs `read_only=True`, because the
ordinary path creates PROPOSED concepts and the measurement would then be
teaching the ontology the vocabulary it is measuring.

    python3 scripts/normalization_sweep.py            # the full report
    python3 scripts/normalization_sweep.py --json     # machine-readable

Cost: one embedding call per phrase that reaches the semantic tier, at the
text rate. 56 phrases is about $0.00004.
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

import normalize as NZ

KEY = REPO / "testing" / "fixtures" / "normalization" / "d47_answer_key.json"

# The thresholds to sweep. The endpoints come from the diagnosis's own
# sweep so the two are comparable; nothing here searches for a best one.
SWEEP = [0.92, 0.88, 0.85, 0.84, 0.82, 0.80, 0.78, 0.76, 0.72, 0.65, 0.60]


def load_key() -> list[dict]:
    return json.loads(KEY.read_text(encoding="utf-8"))["phrases"]


def names(conn, ids: list[str]) -> list[str]:
    if not ids:
        return []
    rows = conn.execute(
        "select canonical_name from concepts where concept_id = any(%s::uuid[])",
        (ids,)).fetchall()
    return [r[0] for r in rows]


def allowed_for(entry: dict):
    """The type set a caller would supply for this phrase, or None.

    ONLY `target` is known here, and that is the honest limit of this
    dataset: the stored claims record `target` and `mechanism` verbatim, so
    those phrases are identified, and the other 43 came from the Claim Card
    `intervention` field or from K11, which the claim row does not
    distinguish. Guessing which would be inventing the caller's structural
    knowledge -- exactly what the guard may not be fed.
    """
    if entry["field"] == "target":
        return NZ.TARGET_TYPES
    return None


def measure(conn, entry: dict) -> dict:
    phrase = entry["phrase"]
    phrase_norm = NZ.norm(conn, phrase)

    tiers = {}
    for method, fn in (("alias", NZ._tier_alias),
                       ("structured", NZ._tier_structured),
                       ("trigram", NZ._tier_trigram),
                       ("semantic", NZ._tier_semantic)):
        tr = fn(conn, phrase_norm, phrase=phrase, embed_call=None)
        tiers[method] = {
            "confidence": tr.confidence,
            "note": tr.note,
            "candidates": [{"name": c.name, "type": c.concept_type,
                            "score": round(c.score, 4)} for c in tr.candidates],
            "selected": names(conn, tr.selected),
        }

    # The semantic tier's UNGATED neighbourhood, for the sweep: the tier
    # itself refuses below its floor, and a sweep that could not see below
    # the floor could not measure the floor.
    raw = raw_semantic(conn, phrase)

    res = NZ.resolve(conn, phrase, context="GATE 2 sweep", llm=None,
                     use_cache=False, read_only=True,
                     allowed_types=allowed_for(entry))
    return {
        "phrase": phrase,
        "field": entry["field"],
        "expected": entry["expected"],
        "tiers": tiers,
        "raw_semantic": raw,
        "allowed_types": sorted(allowed_for(entry)) if allowed_for(entry) else None,
        "decision": res.decision,
        "method": res.method,
        "confidence": round(res.confidence, 4),
        "resolved_to": names(conn, res.concept_ids),
        "note": res.note,
    }


_VECTOR_CACHE: dict[str, list[dict]] = {}


def raw_semantic(conn, phrase: str) -> list[dict]:
    """Top-5 cosine neighbours with no floor and no threshold applied."""
    if phrase in _VECTOR_CACHE:
        return _VECTOR_CACHE[phrase]
    if not NZ._capability(conn, "vector"):
        return []
    if not os.environ.get("MODEL_EMBEDDING", "").strip():
        return []
    import embedding
    vector, _m, _d = embedding.embed(conn, phrase,
                                     entity_type="normalization_sweep")
    q = str(vector)
    rows = conn.execute(
        """select canonical_name, concept_type::text,
                  (1 - (embedding <=> %s::vector))::float
             from concepts
            where status in ('SEEDED','ACTIVE') and embedding is not null
            order by embedding <=> %s::vector limit 5""", (q, q)).fetchall()
    out = [{"name": r[0], "type": r[1], "score": round(float(r[2]), 4)} for r in rows]
    _VECTOR_CACHE[phrase] = out
    return out


def verdict(entry: dict, resolved_to: list[str], refused: bool = False) -> str:
    """Score one outcome against the answer key. The key decides, not this.

    REFUSED_CONFUSABLE is a category the key declares, not one invented
    after reading the results: "Refusal is the correct outcome even where
    `expected` is RESOLVE -- reported apart from MISSED, because a
    deliberate refusal and a failure to find anything are different events."
    """
    if refused and not resolved_to:
        return "REFUSED_CONFUSABLE"
    expected = entry["expected"]
    ok = set(entry.get("to") or [])
    bad = set(entry.get("must_not") or [])
    broad = set(entry.get("tolerable") or [])
    got = set(resolved_to)

    if not got:
        if expected == "NO_MATCH":
            return "RIGHT"          # a new concept is the correct outcome
        if expected == "PARTIAL":
            return "PARTIAL_MISS"   # acceptable: no single concept IS the phrase
        return "MISSED"
    if got & bad:
        return "WRONG"
    if got <= ok and ok:
        return "PARTIAL" if expected == "PARTIAL" else "RIGHT"
    if got <= broad and broad:
        return "BROADER"
    return "WRONG"


def sweep_at(rows: list[dict], key: list[dict], threshold: float) -> dict:
    """What the semantic tier's top-1 would have scored at `threshold`.

    Applied to the RAW neighbourhood, so a threshold below the tier's live
    floor is still measurable. The confusable and type guards are applied
    exactly as `resolve()` applies them, because a sweep that ignored them
    would be measuring a resolver nobody runs.
    """
    by_phrase = {e["phrase"]: e for e in key}
    tally = {"admits": 0, "RIGHT": 0, "PARTIAL": 0, "WRONG": 0, "BROADER": 0,
             "refused_confusable": 0, "refused_type": 0}
    worst: list[str] = []
    for row in rows:
        entry = by_phrase[row["phrase"]]
        raw = row["raw_semantic"]
        if not raw or raw[0]["score"] < threshold:
            continue
        top3 = [c["name"] for c in raw[:NZ.SEMANTIC_CANDIDATES]]
        if row.get("confusable_span"):
            tally["refused_confusable"] += 1
            continue
        allowed = sorted(entry.get("_allowed") or []) if entry.get("_allowed") else None
        if allowed and raw[0]["type"] not in allowed:
            tally["refused_type"] += 1
            continue
        tally["admits"] += 1
        v = verdict(entry, [raw[0]["name"]])
        if v in ("RIGHT", "PARTIAL", "BROADER"):
            tally[v] += 1
        else:
            tally["WRONG"] += 1
            worst.append(f'{row["phrase"]} -> {raw[0]["name"]} ({raw[0]["score"]:.3f})')
        _ = top3
    tally["worst"] = worst
    return tally


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    key = load_key()
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)

    embedded = conn.execute(
        "select count(*) from concepts where embedding is not null "
        "and status in ('SEEDED','ACTIVE')").fetchone()[0]
    seeded = conn.execute(
        "select count(*) from concepts where status in ('SEEDED','ACTIVE')"
    ).fetchone()[0]

    rows = []
    for entry in key:
        row = measure(conn, entry)
        # Does the top-3 span a do-not-merge pair? Asked of the RAW
        # neighbourhood so the sweep and the live tier agree.
        ids = conn.execute(
            """select concept_id::text from concepts
                where canonical_name = any(%s) and status in ('SEEDED','ACTIVE')""",
            ([c["name"] for c in row["raw_semantic"][:NZ.SEMANTIC_CANDIDATES]],)
        ).fetchall()
        clash = NZ.confusable_with(conn, [r[0] for r in ids])
        row["confusable_span"] = [list(c) for c in clash]
        row["verdict"] = verdict(
            entry, row["resolved_to"],
            refused=bool(clash) and bool(entry.get("confusable_expected")))
        entry["_allowed"] = row["allowed_types"]
        rows.append(row)

    report = {
        "library": {"seeded_or_active": seeded, "embedded": embedded,
                    "semantic_threshold": NZ.SEMANTIC_THRESHOLD,
                    "semantic_floor": NZ.SEMANTIC_FLOOR,
                    "semantic_candidates": NZ.SEMANTIC_CANDIDATES,
                    "trigram_threshold": NZ.ALIAS_THRESHOLD},
        "phrases": rows,
        "sweep": {str(t): sweep_at(rows, key, t) for t in SWEEP},
        "cost_usd": float(conn.execute(
            "select coalesce(sum(cost_usd),0) from cost_events "
            "where entity_type='normalization_sweep'").fetchone()[0]),
    }
    if args.json:
        print(json.dumps(report, indent=1))
        return 0

    print(render(report))
    return 0


def render(report: dict) -> str:
    lib = report["library"]
    out = [
        "GATE 2 — the semantic tier over the D47 phrases",
        "=" * 78,
        f"library: {lib['seeded_or_active']} SEEDED/ACTIVE concepts, "
        f"{lib['embedded']} embedded",
        f"thresholds: semantic {lib['semantic_threshold']} "
        f"(floor {lib['semantic_floor']}, top-{lib['semantic_candidates']}), "
        f"trigram {lib['trigram_threshold']}",
        "",
        "1. EVERY PHRASE",
        "-" * 78,
        f"{'#':>3}  {'phrase':52} {'nearest existing concept':34} {'score':>6} "
        f"{'tier':10} {'status':12} {'verdict':13}",
    ]
    for i, row in enumerate(report["phrases"], 1):
        raw = row["raw_semantic"]
        nearest = raw[0]["name"] if raw else "—"
        score = f"{raw[0]['score']:.3f}" if raw else "—"
        out.append(f"{i:>3}  {row['phrase'][:52]:52} {nearest[:34]:34} {score:>6} "
                   f"{row['method']:10} {row['decision']:12} {row['verdict']:13}")
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main())

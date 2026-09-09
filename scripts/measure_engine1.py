#!/usr/bin/env python3
"""BUILD_GUIDE step 10b — measure the Engine 1 call.

Runs the primary path on the synthetic client and reports, per engine call:
prompt tokens, completion tokens, cost, latency, retries and control-block
parse success. Everything comes out of `cost_events` (via
`v_engine_call_measurement`, migration 008), so the numbers are the ones the
system actually recorded rather than anything this script computed on the
side.

    E6 init -> case v1 -> E1 Pass A -> E7 -> E1 Pass B

D5 deferred this measurement until a canonical prompt and an API key were
both in place. The prompt is in place; the key is not. So:

  * with no LLM_API_KEY, run_engine.select_provider() returns the fixture
    provider and this runs end to end with no spend. Every column is real
    except the token counts, which are character estimates the fixture
    produces. The report says so on every line -- an estimated token count
    presented as a measurement is worse than no measurement, because D5 is
    a decision about whether to restructure Engine 1.

  * set LLM_API_KEY and it switches by itself. No flag here selects a
    provider, and no provider is named in this file.

What it does NOT do is touch the two-pass architecture. Pass A and Pass B
both go through run_engine with `engine="E1"`, which loads
prompts/engine1_prevention.md for both and records one hash for both
(D4, trg_enforce_two_pass). The report prints that hash per pass so a fork
would be visible rather than merely rejected.

    python3 scripts/measure_engine1.py            # run and report
    python3 scripts/measure_engine1.py --report-only   # last run's numbers
    python3 scripts/measure_engine1.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "testing" / "fixtures"))

import psycopg

import pricing
import run_engine as RE
import synthetic_client as SC


# ---------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------

def run_primary_path(conn) -> dict:
    """E6 -> E1 Pass A -> E7 -> E1 Pass B on the synthetic client."""
    client_id = SC.load(conn)
    intake = SC.intake_payload(client_id)

    leaked = SC.check_no_identity(intake)
    if leaked:
        raise SystemExit(
            f"identity leaked into the engine payload: {leaked}. "
            "STRIP_IDENTITY_FROM_ENGINE_PAYLOADS and docs/OPERATIONS.md: the "
            "database is in India and model inference is not."
        )

    cycle_id = conn.execute(
        """insert into case_cycles (client_id, cycle_number, cycle_type)
           values (%s,1,'NEW_CLIENT') returning cycle_id""",
        (client_id,),
    ).fetchone()[0]

    e6 = RE.run_engine(conn, RE.EngineRequest(
        engine="E6", structured_input=intake,
        client_id=client_id, cycle_id=cycle_id, model_role="MODEL_ANALYSIS"))
    if e6.status != "SUCCEEDED":
        raise SystemExit(f"E6 failed: {e6.error}")

    case_version_id = conn.execute(
        """insert into client_case_versions
             (client_id, case_version, canonical_state, phase, created_by)
           values (%s,1,%s,'PHASE_1','E6') returning case_version_id""",
        (client_id, json.dumps(intake)),
    ).fetchone()[0]

    # Pass A: the Engine 7 slot is empty and the engine stops at research
    # questions. Same prompt file, same hash -- the difference is context
    # and stopping point, not capability (D4).
    pass_a = RE.run_engine(conn, RE.EngineRequest(
        engine="E1", structured_input={**intake, "MODE": "PASS_A", "E7_HANDOFF": None},
        client_id=client_id, case_version_id=case_version_id,
        cycle_id=cycle_id, pass_label="A"))
    if pass_a.status != "SUCCEEDED":
        raise SystemExit(f"E1 Pass A failed: {pass_a.error}")

    e7 = RE.run_engine(conn, RE.EngineRequest(
        engine="E7",
        structured_input={
            "CASE_RESEARCH_QUESTIONS": pass_a.control.get("RESEARCH_QUESTIONS", []),
            "NORMALIZATION_PHRASES": pass_a.control.get("NORMALIZATION_PHRASES", []),
            "CASE_VERSION": 1,
        },
        client_id=client_id, case_version_id=case_version_id,
        cycle_id=cycle_id, model_role="MODEL_RESEARCH"))
    if e7.status != "SUCCEEDED":
        raise SystemExit(f"E7 failed: {e7.error}")

    # Pass B: the same specification with the Engine 7 slot populated.
    pass_b = RE.run_engine(conn, RE.EngineRequest(
        engine="E1",
        structured_input={**intake, "MODE": "PASS_B",
                          "E7_HANDOFF": {"strategies": [], "source": "E7 run "
                                         f"{e7.run_id}"}},
        client_id=client_id, case_version_id=case_version_id,
        cycle_id=cycle_id, pass_label="B"))
    if pass_b.status != "SUCCEEDED":
        raise SystemExit(f"E1 Pass B failed: {pass_b.error}")

    return {"client_id": client_id, "cycle_id": str(cycle_id),
            "intake_chars": len(json.dumps(intake))}


# ---------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------

def measurements(conn, cycle_id: str) -> list[dict]:
    rows = conn.execute(
        """select engine, pass, prompt_file, prompt_hash_short, model_role,
                  model_name, status, provider_attempts, retries,
                  prompt_tokens, completion_tokens, total_tokens,
                  cost_usd, has_unpriced_attempt, total_ms, slowest_attempt_ms,
                  provider_errors, control_block_parsed, human_output_chars
             from v_engine_call_measurement
            where cycle_id = %s
            order by started_at""",
        (cycle_id,),
    ).fetchall()
    cols = ["engine", "pass", "prompt_file", "prompt_hash_short", "model_role",
            "model_name", "status", "provider_attempts", "retries",
            "prompt_tokens", "completion_tokens", "total_tokens",
            "cost_usd", "has_unpriced_attempt", "total_ms", "slowest_attempt_ms",
            "provider_errors", "control_block_parsed", "human_output_chars"]
    return [dict(zip(cols, r)) for r in rows]


def _fmt_cost(value, unpriced: bool) -> str:
    if value is None:
        return "unpriced" if unpriced else "-"
    return f"${float(value):.6f}"


def print_report(conn, cycle_id: str, mode: str, context: dict) -> int:
    rows = measurements(conn, cycle_id)
    if not rows:
        print("no measurements for this cycle")
        return 1

    estimated = mode == "fixture"

    print()
    print("=" * 100)
    print("ENGINE CALL MEASUREMENT — BUILD_GUIDE step 10b")
    print("=" * 100)
    print(f"provider mode      : {mode}")
    print(f"price registry     : {pricing.describe()}")
    print(f"client             : {context.get('client_id')}  ({SC.EXTERNAL_REF}, synthetic)")
    print(f"intake payload     : {context.get('intake_chars'):,} chars")
    if estimated:
        print()
        print("  !! TOKEN COUNTS ARE ESTIMATES, NOT MEASUREMENTS.")
        print("     The fixture provider derives them from character counts; only a")
        print("     live provider returns real usage. Latency, retries, attempt")
        print("     counts and parse success below ARE real. Set LLM_API_KEY to")
        print("     measure the call size for D5.")
    print()

    header = (f"{'engine':<7}{'pass':<7}{'status':<11}{'att':>4}{'retry':>6}"
              f"{'prompt':>9}{'compl':>8}{'total':>8}{'cost':>13}"
              f"{'ms':>8}{'parsed':>8}  prompt hash")
    print(header)
    print("-" * len(header))
    for r in rows:
        print(f"{r['engine']:<7}{str(r['pass']):<7}{r['status']:<11}"
              f"{r['provider_attempts']:>4}{r['retries']:>6}"
              f"{(r['prompt_tokens'] or 0):>9,}{(r['completion_tokens'] or 0):>8,}"
              f"{(r['total_tokens'] or 0):>8,}"
              f"{_fmt_cost(r['cost_usd'], r['has_unpriced_attempt']):>13}"
              f"{(r['total_ms'] or 0):>8,}"
              f"{('yes' if r['control_block_parsed'] else 'NO'):>8}"
              f"  {r['prompt_hash_short']}")

    total_prompt = sum(r["prompt_tokens"] or 0 for r in rows)
    total_compl = sum(r["completion_tokens"] or 0 for r in rows)
    total_ms = sum(r["total_ms"] or 0 for r in rows)
    priced = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    total_retries = sum(r["retries"] for r in rows)
    print("-" * len(header))
    print(f"{'CYCLE':<7}{'':<7}{'':<11}{sum(r['provider_attempts'] for r in rows):>4}"
          f"{total_retries:>6}{total_prompt:>9,}{total_compl:>8,}"
          f"{total_prompt + total_compl:>8,}"
          f"{(f'${sum(map(float, priced)):.6f}' if priced else 'unpriced'):>13}"
          f"{total_ms:>8,}")

    # --- the D4 assertion, printed rather than merely enforced ------------
    e1 = [r for r in rows if r["engine"] == "E1"]
    hashes = {r["prompt_hash_short"] for r in e1}
    files = {r["prompt_file"] for r in e1}
    print()
    print("Engine 1 two-pass check (D4)")
    print(f"  passes run        : {sorted(str(r['pass']) for r in e1)}")
    print(f"  prompt file(s)    : {sorted(files)}")
    print(f"  prompt hash(es)   : {sorted(hashes)}")
    # Three outcomes, not two. A fork is two passes carrying DIFFERENT
    # hashes -- the thing D4 and trg_enforce_two_pass exist to catch. A run
    # where the second pass never happened is incomplete, and reporting that
    # as a fork sends the reader hunting an architectural violation that is
    # not there. Say which one it is.
    # ok_two_pass gates the exit code and must be set on every branch:
    # only a complete, unforked pair is a pass. INCOMPLETE is not a fork,
    # but it is not a success either.
    if len(e1) < 2:
        ok_two_pass = False
        verdict = (f"INCOMPLETE — {len(e1)} of 2 passes ran; "
                   "no fork is implied by this run")
    elif len(hashes) == 1 and len(files) == 1:
        ok_two_pass = True
        verdict = "YES"
    else:
        ok_two_pass = False
        verdict = "NO — FORK DETECTED"
    print(f"  one specification : {verdict}")

    parsed_all = all(r["control_block_parsed"] for r in rows)
    print()
    print("Control block")
    print(f"  parsed on every call : {'YES' if parsed_all else 'NO'}")
    print(f"  total retries        : {total_retries}")
    dead = conn.execute(
        """select count(*) from dead_letter_jobs d
             join engine_runs r on r.run_id::text = d.entity_id
            where r.cycle_id = %s""", (cycle_id,)).fetchone()[0]
    print(f"  dead-lettered runs   : {dead}")

    if estimated:
        print()
        print("D5 call-size inputs (character estimates, fixture mode)")
        for engine, filename in sorted(RE.ENGINE_PROMPTS.items()):
            path = RE.PROMPTS_DIR / filename
            if path.exists():
                chars = len(path.read_text())
                print(f"  {engine}  {filename:<34}{chars:>9,} chars  "
                      f"~{chars // 4:>7,} tok")
    print("=" * 100)
    return 0 if (ok_two_pass and parsed_all and dead == 0) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-only", action="store_true",
                    help="report the most recent cycle without running engines")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set. See docs/LOCAL_DEV.md.")
        return 2

    _, mode = RE.select_provider()
    conn = psycopg.connect(dsn, autocommit=True)

    if args.report_only:
        row = conn.execute(
            """select c.cycle_id, c.client_id
                 from case_cycles c join clients cl on cl.client_id = c.client_id
                where cl.external_ref like 'SYN-E1-%'
                order by c.opened_at desc limit 1""").fetchone()
        if not row:
            print("no synthetic cycle found — run without --report-only first")
            return 1
        context = {"client_id": str(row[1]),
                   "intake_chars": len(json.dumps(SC.intake_payload(str(row[1]))))}
        cycle_id = str(row[0])
    else:
        context = run_primary_path(conn)
        cycle_id = context["cycle_id"]

    if args.json:
        print(json.dumps({
            "provider_mode": mode,
            "token_counts_are_estimates": mode == "fixture",
            "cycle_id": cycle_id,
            "context": context,
            "calls": [
                {k: (float(v) if hasattr(v, "as_integer_ratio") and not isinstance(v, (int, bool))
                     else str(v) if not isinstance(v, (int, float, bool, type(None))) else v)
                 for k, v in row.items()}
                for row in measurements(conn, cycle_id)
            ],
        }, indent=2))
        return 0

    return print_report(conn, cycle_id, mode, context)


if __name__ == "__main__":
    sys.exit(main())

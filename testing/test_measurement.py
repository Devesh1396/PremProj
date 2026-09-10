#!/usr/bin/env python3
"""Step 10b — the synthetic client and the engine call measurement.

Two things under test.

**The synthetic client** has one job: give Engine 1 something to reason
from in every one of the 19 parts its section 62 requires. A part with no
input is a part the engine has to invent, and inventing is the failure mode
section 61 names. So the coverage map is asserted, not assumed.

**The measurement path** has to report real numbers. The assertions here
are about the honesty of those numbers: that an unpriced model yields NULL
rather than zero, that a retry is counted as the second call it really was,
that a run's tokens attribute to that run and not merely to its client, and
that Pass A and Pass B still record one prompt hash after going through it.
"""

from __future__ import annotations

import contextlib
import io
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
import measure_engine1 as ME

FAILS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def main() -> int:
    # Tests NEVER call a live provider. Without this, a developer or CI
    # runner with LLM_API_KEY in the environment would have the suite make
    # real API calls: real money per run, output that varies between runs,
    # and a suite that goes red when the provider is down or out of quota.
    # None of that is a property of the code under test.
    #
    # The provider-selection checks set and restore this themselves; the
    # engine runs below must all be fixture runs.
    os.environ["LLM_API_KEY"] = ""
    assert RE.select_provider()[1] == "fixture", \
        "test suite must run on the fixture provider"

    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)

    # Idempotent: re-runnable against a database that already holds fixtures.
    SC.clear(conn)
    conn.execute("delete from cost_events where workflow like 'RUN_ENGINE_%'"
                 " and run_id is null")

    # ------------------------------------------------------------------
    print("\nsynthetic client: coverage of Engine 1's 19 parts")
    payload = SC.intake_payload("00000000-0000-0000-0000-000000000000")

    check("section 62 has exactly 19 parts mapped", len(SC.PART_INPUTS) == 19,
          f"{len(SC.PART_INPUTS)} parts")

    missing_key: list[str] = []
    empty_value: list[str] = []
    for part, keys in SC.PART_INPUTS.items():
        for key in keys:
            if key not in payload:
                missing_key.append(f"{part}:{key}")
            elif not payload[key]:
                empty_value.append(f"{part}:{key}")
    check("every part's declared input exists in the payload",
          not missing_key, str(missing_key[:5]))
    check("no part is fed an empty value", not empty_value, str(empty_value[:5]))

    # A map that named one key per part would pass the check above while
    # leaving the engine nothing to connect. Section 21 is explicit that
    # data must not be interpreted in isolation.
    thin = [p for p, keys in SC.PART_INPUTS.items() if len(keys) < 2]
    check("no part rests on a single input", not thin, str(thin))

    # The parts that decide the plan need the parts that constrain it.
    for part, required in [
        ("PART 12 — PRIORITIZED INTERVENTION STRATEGY", "CONSTRAINTS"),
        ("PART 13 — FOOD / NUTRITION STRATEGY HANDOFF", "FOOD_LOG"),
        ("PART 15 — MOVEMENT / FUNCTION STRATEGY", "PAIN_AND_FUNCTION"),
        ("PART 18 — MEDICAL COORDINATION", "MEDICATIONS"),
    ]:
        check(f"{part.split(' ')[1]} reads {required}",
              required in SC.PART_INPUTS[part])

    # ------------------------------------------------------------------
    print("\nsynthetic client: clinical realism")
    check("labs span glycaemia, lipids, liver, thyroid and vegetarian deficiencies",
          all(any(m.startswith(prefix) for m, *_ in SC.LABS) for prefix in
              ("HbA1c", "Triglycerides", "ALT", "TSH", "Vitamin B12",
               "Vitamin D", "Serum ferritin")))
    check("food log covers weekdays and a weekend day",
          len({e["day_type"] for e in SC.FOOD_LOG}) >= 2,
          str([e["day_type"] for e in SC.FOOD_LOG]))
    check("protein intake is below 0.8 g/kg, so protein analysis has something to find",
          SC.FOOD_PATTERN["ESTIMATED_INTAKE"]["protein_g_per_kg"] < 0.8)
    check("diet is vegetarian, as the case requires",
          "vegetarian" in SC.FOOD_PATTERN["DIET_PATTERN"].lower())

    # D6: this exact combination must NOT trip the gate. A gate that fires
    # on an ordinary medicated metabolic client is a rubber stamp.
    med_names = " ".join(n for n, *_ in SC.MEDICATIONS).lower()
    check("medications are the ordinary metabolic set D6 requires to pass clean",
          "metformin" in med_names and "atorvastatin" in med_names
          and "telmisartan" in med_names)
    check("no insulin, sulfonylurea or warfarin in the synthetic case",
          not any(drug in med_names for drug in
                  ("insulin", "glimepiride", "gliclazide", "glipizide", "warfarin")),
          med_names)

    print("\nsynthetic client: no identity in the engine payload")
    check("payload carries no display name or locality",
          SC.check_no_identity(payload) == [], str(SC.check_no_identity(payload)))
    check("payload carries client_id and clinical facts",
          "CLIENT_ID" in payload and "LABS" in payload)
    check("region is kept — Engine 3 cannot reason about availability without it",
          "REGION" in payload["CONTEXT"])

    # ------------------------------------------------------------------
    print("\nsynthetic client: loads into the clinical tables")
    client_id = SC.load(conn)
    counts = {}
    for table in ("client_labs", "client_conditions", "client_symptoms",
                  "client_medications", "client_supplements",
                  "client_measurements", "client_food_logs"):
        counts[table] = conn.execute(
            f"select count(*) from {table} where client_id=%s", (client_id,)
        ).fetchone()[0]
    check("every clinical table is populated",
          all(v > 0 for v in counts.values()), str(counts))
    check("labs loaded match the fixture", counts["client_labs"] == len(SC.LABS),
          str(counts["client_labs"]))

    reloaded = SC.load(conn)
    total_clients = conn.execute(
        "select count(*) from clients where external_ref like 'SYN-E1-%'"
    ).fetchone()[0]
    check("re-loading replaces rather than duplicating (idempotent fixture)",
          total_clients == 1, f"{total_clients} synthetic clients")
    client_id = reloaded

    # ------------------------------------------------------------------
    print("\npricing: an unknown price is unknown, never zero")
    cost, source = pricing.price_call("no-such-model-anywhere", 1000, 500)
    check("unknown model is UNPRICED with a NULL cost",
          cost is None and source == pricing.UNPRICED, f"{cost} {source}")
    cost, source = pricing.price_call("claude-sonnet-5", 1_000_000, 1_000_000)
    check("known model prices from the registry",
          source == pricing.PRICE_REGISTRY and abs(cost - 12.0) < 1e-9,
          f"{cost} {source}")
    cost, source = pricing.price_call("claude-sonnet-5-20260101", 1_000_000, 0)
    check("a dated snapshot resolves to its family rate",
          source == pricing.PRICE_REGISTRY and abs(cost - 2.0) < 1e-9, f"{cost}")

    os.environ["LLM_PRICE_INPUT_PER_MTOK"] = "0.30"
    os.environ["LLM_PRICE_OUTPUT_PER_MTOK"] = "2.50"
    cost, source = pricing.price_call("some-provider-model", 1_000_000, 1_000_000)
    check("an env rate prices a model absent from the registry",
          source == pricing.PRICE_REGISTRY and abs(cost - 2.80) < 1e-9, f"{cost}")
    del os.environ["LLM_PRICE_INPUT_PER_MTOK"]
    del os.environ["LLM_PRICE_OUTPUT_PER_MTOK"]

    # The database refuses the pairing that would corrupt every total built
    # on top of it: "we have no rate" and "it cost nothing" are not the same
    # claim.
    try:
        with conn.transaction():
            conn.execute(
                """insert into cost_events (operation, model_name, cost_usd, price_source)
                   values ('ENGINE_RUN','x',0.5,'UNPRICED')""")
        check("UNPRICED with a cost is rejected", False, "accepted")
    except psycopg.Error as exc:
        check("UNPRICED with a cost is rejected", "ck_cost_priced" in str(exc), str(exc)[:90])

    # ------------------------------------------------------------------
    print("\nprovider selection is by environment, never hard-coded")
    saved = os.environ.get("LLM_API_KEY", "")
    os.environ["LLM_API_KEY"] = ""
    check("no key selects the fixture provider",
          RE.select_provider() == (RE.fixture_provider, "fixture"))
    os.environ["LLM_API_KEY"] = "change_me"
    check("the placeholder key is not treated as a key",
          RE.select_provider()[1] == "fixture")
    os.environ["LLM_API_KEY"] = "sk-not-a-real-key"
    provider, mode = RE.select_provider()
    check("a real key switches to the live provider with no code change",
          provider is RE.openai_compatible_provider and mode == "live")
    os.environ["LLM_API_KEY"] = saved
    if not saved:
        del os.environ["LLM_API_KEY"]
    check("selection reverts with the environment",
          RE.select_provider()[1] == "fixture")

    measure_source = (REPO / "scripts" / "measure_engine1.py").read_text().lower()
    check("the measurement runner names no provider and no model",
          not any(name in measure_source for name in
                  ("openai", "gemini", "anthropic", "gpt-", "claude-")),
          "a provider or model name appears in measure_engine1.py")

    # ------------------------------------------------------------------
    print("\nmeasurement: the primary path")
    context = ME.run_primary_path(conn)
    rows = ME.measurements(conn, context["cycle_id"])
    by_call = {(r["engine"], str(r["pass"])): r for r in rows}

    check("four calls measured: E6, E1 A, E7, E1 B", len(rows) == 4,
          str(sorted(by_call)))
    check("the calls are in orchestration order",
          [(r["engine"], str(r["pass"])) for r in rows]
          == [("E6", "SINGLE"), ("E1", "A"), ("E7", "SINGLE"), ("E1", "B")],
          str([(r["engine"], str(r["pass"])) for r in rows]))

    for key, row in by_call.items():
        check(f"{key[0]} {key[1]}: prompt and completion tokens recorded",
              (row["prompt_tokens"] or 0) > 0 and (row["completion_tokens"] or 0) > 0,
              str(row["prompt_tokens"]))
        check(f"{key[0]} {key[1]}: control block parsed",
              row["control_block_parsed"] is True)
    check("latency recorded for every call",
          all(r["total_ms"] is not None for r in rows))
    check("no retries needed on well-formed output",
          all(r["retries"] == 0 for r in rows), str([r["retries"] for r in rows]))

    check("the fixture provider is unpriced, so cost is NULL not 0",
          all(r["cost_usd"] is None and r["has_unpriced_attempt"] for r in rows),
          str([r["cost_usd"] for r in rows]))
    check("a fixture run records a fixture: model name",
          all(str(r["model_name"]).startswith("fixture:") for r in rows),
          str([r["model_name"] for r in rows]))

    # The reason migration 008 exists.
    e1 = [r for r in rows if r["engine"] == "E1"]
    check("Pass A and Pass B are separable in the cost table",
          len(e1) == 2 and e1[0]["prompt_tokens"] != e1[1]["prompt_tokens"]
          or len({str(r["pass"]) for r in e1}) == 2,
          str([(str(r["pass"]), r["prompt_tokens"]) for r in e1]))
    check("both E1 passes record one prompt hash (D4)",
          len({r["prompt_hash_short"] for r in e1}) == 1,
          str({r["prompt_hash_short"] for r in e1}))
    check("both E1 passes record one prompt file (D4)",
          len({r["prompt_file"] for r in e1}) == 1)
    check("Pass B carries more input than Pass A — the E7 slot is populated",
          by_call[("E1", "B")]["prompt_tokens"] >= by_call[("E1", "A")]["prompt_tokens"],
          f"A={by_call[('E1','A')]['prompt_tokens']} B={by_call[('E1','B')]['prompt_tokens']}")

    # print_report's EXIT CODE, not just its output. It is the last line of
    # a long function, so every line above it can be correct while it raises
    # -- which is exactly what happened: a refactor replaced the pass/fail
    # boolean with a three-way verdict string and left the return statement
    # referencing the deleted name. The report printed perfectly and then
    # died with NameError. run_all.sh never ran this script, so only CI
    # caught it. Now the suite does.
    print("\nmeasurement: the report's exit code")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ME.print_report(conn, context["cycle_id"], "fixture", context)
    report = buf.getvalue()
    check("a complete, unforked cycle reports success", rc == 0, f"rc={rc}")
    check("...and says so in the two-pass verdict",
          "one specification : YES" in report,
          str([l for l in report.splitlines() if "one specification" in l]))

    # A cycle where Pass B never ran is INCOMPLETE, not a fork. Reporting it
    # as a fork sends the reader hunting an architectural violation that is
    # not there -- but it must still fail, because it is not a success.
    lone_cycle = conn.execute(
        """insert into case_cycles (client_id, cycle_number, cycle_type)
           values (%s,2,'NEW_CLIENT') returning cycle_id""",
        (context["client_id"],)).fetchone()[0]
    RE.run_engine(conn, RE.EngineRequest(
        engine="E1", structured_input={"CASE_VERSION": 1},
        client_id=context["client_id"], cycle_id=lone_cycle, pass_label="A"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc_partial = ME.print_report(conn, str(lone_cycle), "fixture", context)
    partial = buf.getvalue()
    check("a cycle missing Pass B fails", rc_partial != 0, f"rc={rc_partial}")
    check("...and is called INCOMPLETE, not a fork",
          "INCOMPLETE" in partial and "FORK DETECTED" not in partial,
          str([l for l in partial.splitlines() if "one specification" in l]))

    print("\nmeasurement: tokens attribute to the run, not just the client")
    unattributed = conn.execute(
        """select count(*) from cost_events c
             where c.entity_id = %s and c.run_id is null""", (context["client_id"],)
    ).fetchone()[0]
    check("no engine cost event is left unattributed to a run", unattributed == 0,
          f"{unattributed} unattributed")
    run_totals = conn.execute(
        """select r.input_tokens, r.output_tokens, r.duration_ms
             from engine_runs r where r.cycle_id=%s and r.engine='E1' and r.pass='A'""",
        (context["cycle_id"],)).fetchone()
    check("engine_runs carries its own token and latency totals",
          run_totals[0] > 0 and run_totals[1] > 0 and run_totals[2] is not None,
          str(run_totals))

    # ------------------------------------------------------------------
    # The regression this exists for: configure a real, PRICED model but
    # leave the key unset. The run uses the fixture provider, whose token
    # counts are character estimates -- and if it were recorded under the
    # real model name the registry would match and the cycle would report a
    # dollar figure for calls that never left the machine, printed directly
    # under the banner saying the counts are estimates.
    print("\nmeasurement: estimated tokens are never costed as money")
    saved_role = os.environ.get("MODEL_ANALYSIS", "")
    priced_model = "claude-sonnet-5"
    assert pricing.price_call(priced_model, 1000, 1000)[1] == pricing.PRICE_REGISTRY
    os.environ["MODEL_ANALYSIS"] = priced_model
    try:
        priced_run = RE.run_engine(conn, RE.EngineRequest(
            engine="E4", structured_input={"CASE_VERSION": 1},
            client_id=context["client_id"], cycle_id=context["cycle_id"]))
    finally:
        os.environ["MODEL_ANALYSIS"] = saved_role
        if not saved_role:
            del os.environ["MODEL_ANALYSIS"]

    row = conn.execute(
        """select model_name, cost_usd, has_unpriced_attempt, prompt_tokens
             from v_engine_call_measurement where run_id=%s""",
        (priced_run.run_id,)).fetchone()
    check("a priced model configured with no key still runs on the fixture",
          priced_run.status == "SUCCEEDED" and (row[3] or 0) > 0, str(row))
    check("...and is recorded under fixture:<model>, not the model itself",
          row[0] == f"fixture:{priced_model}", str(row[0]))
    check("...so estimated tokens produce NO cost, not a plausible one",
          row[1] is None and row[2] is True, str(row))

    print("\nan unset model role fails loudly on a live run")
    saved_key = os.environ.get("LLM_API_KEY", "")
    saved_role = os.environ.get("MODEL_ANALYSIS", "")
    os.environ["LLM_API_KEY"] = "sk-not-a-real-key"
    os.environ["MODEL_ANALYSIS"] = ""
    try:
        RE.run_engine(conn, RE.EngineRequest(
            engine="E5", structured_input={"CASE_VERSION": 1},
            client_id=context["client_id"], cycle_id=context["cycle_id"]))
        check("live run with no model configured raises", False, "no exception")
    except RE.ModelRoleUnset as exc:
        # Without this the empty role fell through to the fixture
        # placeholder and "fixture:live" was sent to the provider AS the
        # model id, so the real error arrived as an opaque 400.
        check("live run with no model configured raises", "MODEL_ANALYSIS" in str(exc),
              str(exc)[:100])
    except Exception as exc:
        check("live run with no model configured raises", False,
              f"wrong exception: {type(exc).__name__}: {exc}")
    finally:
        os.environ["LLM_API_KEY"] = saved_key
        os.environ["MODEL_ANALYSIS"] = saved_role
        for var, val in (("LLM_API_KEY", saved_key), ("MODEL_ANALYSIS", saved_role)):
            if not val:
                del os.environ[var]

    # ------------------------------------------------------------------
    print("\nmeasurement: a repair retry is counted as the second call it was")
    calls = {"n": 0}

    def flaky(system, user, params):
        calls["n"] += 1
        if calls["n"] == 1:
            return "no control block here at all", 700, 40
        return RE.fixture_provider(system, user, params)

    original = RE.select_provider
    RE.select_provider = lambda: (flaky, "fixture")
    try:
        repaired = RE.run_engine(conn, RE.EngineRequest(
            engine="E2", structured_input={"CASE_VERSION": 1},
            client_id=context["client_id"], cycle_id=context["cycle_id"]))
    finally:
        RE.select_provider = original

    check("run succeeded after a repair", repaired.status == "SUCCEEDED", repaired.error or "")
    row = conn.execute(
        """select provider_attempts, retries, prompt_tokens, control_block_parsed
             from v_engine_call_measurement where run_id=%s""",
        (repaired.run_id,)).fetchone()
    check("both attempts appear in the cost table", row[0] == 2, str(row))
    check("retries reports 1, not 2 or 0", row[1] == 1, str(row))
    check("the failed attempt's tokens are included in the run total",
          row[2] >= 700, str(row))
    check("parse success reflects the final state", row[3] is True, str(row))

    # ------------------------------------------------------------------
    print("\nthe measurement view is not an RLS bypass")
    opts = conn.execute(
        "select reloptions from pg_class where relname='v_engine_call_measurement'"
    ).fetchone()[0]
    check("v_engine_call_measurement runs with security_invoker",
          opts is not None and "security_invoker=true" in opts, str(opts))

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

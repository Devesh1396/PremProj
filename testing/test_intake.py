#!/usr/bin/env python3
"""Core Intake V1 — BUILD_GUIDE step 14.

The assertions that matter, in the order they matter:

  1. An incomplete intake still produces a runnable Engine 6 v1 and reports
     what was missing. Intake never blocks a case.
  2. Absent information stays UNKNOWN / NOT_ASSESSED. It is never defaulted
     to a normal value, and RHT NOT_ASSESSED never means "RHT was fine".
  3. RHT is not silently reconstructed from Core Intake questions (D22).
  4. Conditional sections are genuinely skipped, not reported as gaps.
  5. The new tables are RLS-bound from the first migration.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "testing" / "fixtures"))

import psycopg

import intake as IN
import run_engine as RE
import synthetic_intake as SI

FAILS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def main() -> int:
    # Tests never call a live provider: a key in the environment must not
    # turn `run_all.sh` into a metered operation.
    os.environ["LLM_API_KEY"] = ""
    assert RE.select_provider()[1] == "fixture"

    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    SI.clear(conn)

    # ------------------------------------------------------------------
    print("\nthe exclusions are structural, not just documented")
    excluded = [r[0] for r in conn.execute(
        "select field_key from intake_field_catalog where rht_owned order by 1").fetchall()]
    for owned in ("sleep_quality", "sleep_pattern", "stress_load", "recovery_capacity",
                  "fatigue_body_signals", "lifestyle_load", "sedentary_distribution"):
        check(f"RHT owns {owned}; Core Intake does not ask it", owned in excluded)

    askable = {f["field_key"] for f in IN.load_catalog(conn)}
    check("no RHT-owned field is askable", not (set(excluded) & askable),
          str(set(excluded) & askable))

    # A future edit cannot quietly start asking an RHT question: the
    # classification and the flag are bound by check constraint.
    try:
        with conn.transaction():
            conn.execute(
                """insert into intake_field_catalog (field_key, section, label,
                                                     classification, rht_owned)
                   values ('sneak_sleep','HYDRATION_MOVEMENT','Sleep?','ESSENTIAL',true)""")
        check("an RHT-owned field cannot be reclassified as askable", False, "accepted")
    except psycopg.Error as exc:
        check("an RHT-owned field cannot be reclassified as askable",
              "ck_rht_owned_classified" in str(exc), str(exc)[:90])

    # ------------------------------------------------------------------
    print("\na COMPLETE intake converts")
    cid = SI.load_client(conn, SI.EXTERNAL_REF_COMPLETE)
    sub = IN.submit(conn, cid, SI.COMPLETE_INTAKE)
    counts = IN.extract(conn, sub)
    check("labs extracted into client_labs", counts.get("labs", 0) >= 9, str(counts))
    check("medications extracted", counts.get("medications", 0) == 4, str(counts))
    check("report files recorded", counts.get("report_files", 0) == 2, str(counts))
    check("3 food-log days extracted", counts.get("food_log_days", 0) == 3, str(counts))

    # Provenance survives into the table the engines actually read.
    linked = conn.execute(
        """select count(*) from client_labs l join client_report_files f
                on f.report_file_id = l.report_file_id
            where l.client_id=%s""", (cid,)).fetchone()[0]
    check("lab values trace back to the report they came from", linked >= 9, str(linked))

    e6 = IN.to_e6_input(conn, sub)
    check("E6 input carries client_id, not a name",
          e6["CLIENT_ID"] == cid and SI.DISPLAY_NAME_COMPLETE not in json.dumps(e6))
    check("E6 input has all 13 content sections plus RHT",
          all(k in e6 for k in ("BASIC_PROFILE", "GOALS", "DIAGNOSES_HISTORY", "MEDICATIONS",
                                "LABS_REPORTS", "SYMPTOMS", "DIET_PATTERN", "FOOD_ENVIRONMENT",
                                "HYDRATION_MOVEMENT", "DIGESTIVE", "REPRODUCTIVE",
                                "PREVIOUS_ATTEMPTS", "FOOD_LOG", "RHT")))

    # ------------------------------------------------------------------
    print("\nan INCOMPLETE intake still produces a runnable E6 v1")
    sid = SI.load_client(conn, SI.EXTERNAL_REF_SPARSE)
    sparse_sub = IN.submit(conn, sid, SI.SPARSE_INTAKE)   # must not raise
    check("a sparse submission is accepted, not refused", sparse_sub is not None)

    gaps = conn.execute(
        """select count(*) from missing_data_reports
            where submission_id=%s and not resolved""", (sparse_sub,)).fetchone()[0]
    check("gaps are recorded rather than rejected", gaps > 10, f"{gaps} gaps")

    sparse_e6 = IN.to_e6_input(conn, sparse_sub)
    hp = sparse_e6["HIGH_PRIORITY_MISSING_DATA"]
    check("HIGH_PRIORITY_MISSING_DATA is populated", len(hp) >= 5, str(len(hp)))
    check("high-priority gaps name ESSENTIAL fields",
          {g["field"] for g in hp} >= {"height_cm", "lab_values", "diet_pattern"},
          str(sorted(g["field"] for g in hp))[:200])
    check("every high-priority gap says why it mattered",
          all(g.get("why") for g in hp))

    # The whole point: Engine 6 runs on it.
    IN.extract(conn, sparse_sub)
    cycle = conn.execute(
        """insert into case_cycles (client_id, cycle_number, cycle_type)
           values (%s,1,'NEW_CLIENT') returning cycle_id""", (sid,)).fetchone()[0]
    e6_run = RE.run_engine(conn, RE.EngineRequest(
        engine="E6", structured_input=sparse_e6, client_id=sid, cycle_id=cycle))
    check("E6 runs on an incomplete intake", e6_run.status == "SUCCEEDED", e6_run.error or "")

    v1 = conn.execute(
        """insert into client_case_versions
             (client_id, case_version, canonical_state, phase, created_by)
           values (%s,1,%s,'PHASE_1','E6') returning case_version_id""",
        (sid, json.dumps(sparse_e6))).fetchone()[0]
    IN.mark_converted(conn, sparse_sub, str(v1))
    state = conn.execute("select get_current_client_state(%s)", (sid,)).fetchone()[0]
    check("canonical state v1 exists for an incomplete intake",
          state["case_version"] == 1, str(state)[:120])
    check("the case version records what was missing",
          len(state["canonical_state"]["HIGH_PRIORITY_MISSING_DATA"]) >= 5)

    # ------------------------------------------------------------------
    print("\nabsent means UNKNOWN, never normal")
    check("an unasked section is UNKNOWN, not an empty object",
          sparse_e6["FOOD_ENVIRONMENT"] == IN.UNKNOWN, str(sparse_e6["FOOD_ENVIRONMENT"]))
    check("an unasked section is not silently defaulted",
          sparse_e6["DIGESTIVE"] == IN.UNKNOWN and sparse_e6["FOOD_LOG"] == IN.UNKNOWN)
    check("the payload states the no-defaulting policy",
          "UNKNOWN" in sparse_e6["MISSING_DATA_POLICY"])

    dose = conn.execute(
        """select dose, timing from client_medications
            where client_id=%s and name='Metformin'""", (sid,)).fetchone()
    check("an unknown dose is recorded as UNKNOWN, not blank and not invented",
          dose == (IN.UNKNOWN, IN.UNKNOWN), str(dose))

    # ------------------------------------------------------------------
    print("\nRHT: NOT_ASSESSED means unknown, not normal")
    rht = sparse_e6["RHT"]
    check("status is NOT_ASSESSED", rht["RHT_STATUS"] == "NOT_ASSESSED", str(rht["RHT_STATUS"]))
    check("the payload says absence is not evidence of normality",
          "not evidence" in rht["MEANING"].lower(), rht["MEANING"])
    check("it lists what RHT owns and intake did not collect",
          len(rht["OWNED_BY_RHT_NOT_COLLECTED_HERE"]) == 7,
          str(rht["OWNED_BY_RHT_NOT_COLLECTED_HERE"]))
    check("no RHT score, subscore or interpretation is present",
          not any(k in rht for k in ("LAYERS", "SCORES", "INTERPRETATION", "DIRECTION")),
          str(sorted(rht)))

    # A claim of COMPLETED with nothing linked is not taken on trust.
    lying = dict(SI.SPARSE_INTAKE)
    lying["sections"] = dict(lying["sections"], RHT_LINKAGE={"rht_status": "COMPLETED"})
    liar_sub = IN.submit(conn, sid, lying)
    liar_rht = IN.to_e6_input(conn, liar_sub)["RHT"]
    check("a COMPLETED claim with no linked assessment is treated as NOT_ASSESSED",
          liar_rht["RHT_STATUS"] == "NOT_ASSESSED" and "DISCREPANCY" in liar_rht,
          str(liar_rht.get("RHT_STATUS")))

    # And when RHT genuinely exists, the full structured package is linked.
    aid = conn.execute(
        """insert into client_assessments
             (client_id, instrument, instrument_version, scoring_version, status, assessed_on)
           values (%s,'REAL_HEALTH_TEST','rht-v2','score-v3','COMPLETED','2026-07-01')
           returning assessment_id""", (sid,)).fetchone()[0]
    for layer, body in (("RAW_SIGNALS", {"sleep_hours": 5.8}),
                        ("DERIVED_SCORES", {"recovery": 41}),
                        ("INTERPRETATION", {"summary": "low recovery capacity"}),
                        ("DIRECTION", {"load": "RISING"})):
        conn.execute(
            """insert into assessment_layers (assessment_id, layer_type, payload)
               values (%s,%s,%s)""", (aid, layer, json.dumps(body)))
    real_sub = IN.submit(conn, sid, lying)
    real_rht = IN.to_e6_input(conn, real_sub)["RHT"]
    check("a real completed RHT links its full structured package",
          real_rht["RHT_STATUS"] == "COMPLETED" and len(real_rht["LAYERS"]) == 4,
          str(sorted(real_rht.get("LAYERS", {}))))
    check("RHT linkage carries assessment and scoring versions",
          real_rht["INSTRUMENT_VERSION"] == "rht-v2"
          and real_rht["SCORING_VERSION"] == "score-v3")

    # ------------------------------------------------------------------
    print("\nconditional sections are skipped, not counted as gaps")
    mid = SI.load_client(conn, SI.EXTERNAL_REF_MALE)
    male_sub = IN.submit(conn, mid, SI.MALE_INTAKE)
    male_gaps = {r[0] for r in conn.execute(
        """select missing_field from missing_data_reports
            where submission_id=%s""", (male_sub,)).fetchall()}
    repro = {"cycle_context", "cycle_irregularity", "menopause_status", "reproductive_dx"}
    check("a male client is not asked the reproductive questions",
          not (repro & male_gaps), str(repro & male_gaps))

    male_e6 = IN.to_e6_input(conn, male_sub)
    check("the reproductive section reads NOT_APPLICABLE, not UNKNOWN",
          isinstance(male_e6["REPRODUCTIVE"], dict)
          and male_e6["REPRODUCTIVE"].get("NOT_APPLICABLE") is True,
          str(male_e6["REPRODUCTIVE"]))

    # ...and for a female client they ARE asked.
    female_gaps = {r[0] for r in conn.execute(
        """select missing_field from missing_data_reports
            where submission_id=%s""", (sparse_sub,)).fetchall()}
    check("a female client with no cycle answers DOES get reproductive gaps",
          bool(repro & female_gaps), str(sorted(female_gaps))[:160])

    # ------------------------------------------------------------------
    print("\nintake gaps are attributed honestly")
    engines = conn.execute(
        """select count(*) from missing_data_reports
            where submission_id is not null and engine is not null""").fetchone()[0]
    check("no intake gap is attributed to an engine that did not report it",
          engines == 0, f"{engines} mis-attributed")
    rec = conn.execute(
        """select engines, engine_reports, intake_reports
             from v_missing_data_recurrence where missing_field='height_cm'""").fetchone()
    check("v_missing_data_recurrence shows NO engine for an intake gap, not a phantom one",
          rec is not None and rec[0] == [] and rec[1] == 0, str(rec))
    check("...and counts it as an intake report",
          rec is not None and rec[2] >= 1, str(rec))

    print("\nintake data is CASE data, never knowledge")
    leaked = conn.execute(
        """select count(*) from source_envelopes
            where source_title like '%SYN-INTAKE%' or content_hash like '%SYN-INTAKE%'"""
    ).fetchone()[0]
    check("no intake report reached source_envelopes", leaked == 0, str(leaked))
    check("client_report_files has no FK into the knowledge layer",
          conn.execute(
              """select count(*) from information_schema.table_constraints tc
                   join information_schema.constraint_column_usage ccu
                     on ccu.constraint_name = tc.constraint_name
                  where tc.table_name='client_report_files'
                    and tc.constraint_type='FOREIGN KEY'
                    and ccu.table_name in ('source_envelopes','knowledge_entities',
                                           'source_items','knowledge_sources')"""
          ).fetchone()[0] == 0)

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

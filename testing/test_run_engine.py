#!/usr/bin/env python3
"""RUN_ENGINE + E6 initialization + E1 Pass A on a synthetic client.

Prompt fixtures live under testing/fixtures/prompts and are pointed at by
overriding PROMPTS_DIR. They are never written into prompts/, so a stub can
never be mistaken for a canonical master specification.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import psycopg
import run_engine as RE

FIXTURE_PROMPTS = REPO / "testing" / "fixtures" / "prompts"
RE.PROMPTS_DIR = FIXTURE_PROMPTS

FAILS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def main() -> int:
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)

    # Idempotent: tests must be re-runnable against a database that already
    # has fixtures from a previous run. Cascades clear runs, outputs, flags.
    conn.execute("delete from clients where external_ref like 'SYN-%'")
    conn.execute("delete from dead_letter_jobs where job_type like 'RUN_ENGINE_%'")
    conn.execute("delete from cost_events where workflow like 'RUN_ENGINE_%'")

    print("\nprompt discipline")
    RE._prompt_cache.clear()
    # Point at a directory with no prompt files. Asserting that prompts/ is
    # empty would break the moment the canonical prompts land — the
    # behaviour under test is the refusal to stub, not the absence.
    import tempfile
    with tempfile.TemporaryDirectory() as empty:
        RE.PROMPTS_DIR = pathlib.Path(empty)
        try:
            RE.load_prompt("E1")
            check("missing canonical prompt raises rather than stubbing", False,
                  "load_prompt returned instead of raising")
        except RE.PromptMissing as exc:
            check("missing canonical prompt raises rather than stubbing",
                  "will not fall back to a stub" in str(exc))
    RE.PROMPTS_DIR = FIXTURE_PROMPTS
    RE._prompt_cache.clear()

    # The real prompts must also load and hash, now that they exist.
    real = REPO / "prompts"
    if (real / "engine1_prevention.md").exists():
        RE.PROMPTS_DIR = real
        RE._prompt_cache.clear()
        hashes = {}
        for e in ["E1", "E2", "E3", "E4", "E5", "E6", "E7"]:
            fn, content, digest = RE.load_prompt(e)
            hashes[e] = digest
            if "<CONTROL_BLOCK>" not in content:
                check(f"{e} prompt specifies the control block tag", False, fn)
        check("all seven canonical prompts load and hash",
              len(set(hashes.values())) == 7, str(len(hashes)))
        check("every canonical prompt specifies the control block tag", True)
        RE.PROMPTS_DIR = FIXTURE_PROMPTS
        RE._prompt_cache.clear()

    fname, content, digest = RE.load_prompt("E1")
    check("prompt hashed for provenance",
          digest == hashlib.sha256(content.encode()).hexdigest() and len(digest) == 64)

    print("\ncontrol block extraction")
    good = 'preamble\n<CONTROL_BLOCK>\n{"CASE_VERSION":1,"ENGINE_RUN_STATUS":"SUCCEEDED"}\n</CONTROL_BLOCK>'
    fenced = 'x\n<CONTROL_BLOCK>\n```json\n{"CASE_VERSION":1,"ENGINE_RUN_STATUS":"SUCCEEDED"}\n```\n</CONTROL_BLOCK>'
    check("plain block parsed", RE.extract_control(good) is not None)
    check("fenced block parsed", RE.extract_control(fenced) is not None)
    check("missing block returns None", RE.extract_control("no block here") is None)
    check("malformed JSON returns None",
          RE.extract_control("<CONTROL_BLOCK>{not json}</CONTROL_BLOCK>") is None)

    print("\ncontract validation")
    check("valid control passes",
          RE.validate_control({"CASE_VERSION": 1, "ENGINE_RUN_STATUS": "SUCCEEDED"}) == [])
    check("missing required field caught",
          any("CASE_VERSION" in e for e in RE.validate_control({"ENGINE_RUN_STATUS": "SUCCEEDED"})))
    check("bad enum caught",
          RE.validate_control({"CASE_VERSION": 1, "ENGINE_RUN_STATUS": "MAYBE"}) != [])
    check("routing without a reason caught",
          RE.validate_control({"CASE_VERSION": 1, "ENGINE_RUN_STATUS": "SUCCEEDED",
                               "ROUTING_RECOMMENDATION": "ENGINE2"}) != [])
    check("routing with a reason passes",
          RE.validate_control({"CASE_VERSION": 1, "ENGINE_RUN_STATUS": "SUCCEEDED",
                               "ROUTING_RECOMMENDATION": "ENGINE2",
                               "ROUTING_REASON": "Adherence, not strategy"}) == [])
    check("live research without an insufficiency finding caught",
          RE.validate_control({"CASE_VERSION": 1, "ENGINE_RUN_STATUS": "SUCCEEDED",
                               "LIVE_RESEARCH_REQUIRED": True,
                               "KNOWLEDGE_SUFFICIENT": True}) != [])
    check("FAILED without ERROR_STATE caught",
          RE.validate_control({"CASE_VERSION": 1, "ENGINE_RUN_STATUS": "FAILED"}) != [])

    # ------------------------------------------------------------------
    print("\nsynthetic client: E6 initialization")
    client = conn.execute(
        """insert into clients (external_ref, display_name, year_of_birth, sex,
                                country, region, locality, status)
           values ('SYN-001','Synthetic: vegetarian PCOS + MASLD + prediabetes',
                   1983,'F','India','Gujarat','Ahmedabad','INTAKE')
           returning client_id"""
    ).fetchone()[0]

    intake = {
        "ACTIVE_CONDITIONS": ["PCOS", "MASLD", "Prediabetes"],
        "DIET_PATTERN_CURRENT": "Vegetarian",
        "CURRENT_MAJOR_BIOMARKERS": {"HbA1c": 6.1, "Triglycerides": 210, "ALT": 58},
        "CURRENT_BODY_MEASUREMENTS": {"waist_cm": 96, "weight_kg": 74},
        "PRACTICAL_CONSTRAINTS_CURRENT": ["Family cooking", "Limited evening time"],
        "CASE_VERSION": 1,
    }
    cycle = conn.execute(
        """insert into case_cycles (client_id, cycle_number, cycle_type)
           values (%s,1,'NEW_CLIENT') returning cycle_id""",
        (client,),
    ).fetchone()[0]

    e6 = RE.run_engine(conn, RE.EngineRequest(
        engine="E6", structured_input=intake, client_id=client, cycle_id=cycle,
        model_role="MODEL_ANALYSIS"))
    check("E6 run succeeded", e6.status == "SUCCEEDED", e6.error or "")

    v1 = conn.execute(
        """insert into client_case_versions (client_id, case_version, canonical_state, phase, created_by)
           values (%s,1,%s,'PHASE_1','E6') returning case_version_id""",
        (client, json.dumps(intake)),
    ).fetchone()[0]
    state = conn.execute("select get_current_client_state(%s)", (client,)).fetchone()[0]
    check("canonical state readable through the single read path",
          state["case_version"] == 1
          and "PCOS" in state["canonical_state"]["ACTIVE_CONDITIONS"], str(state)[:120])

    # ------------------------------------------------------------------
    print("\nE1 Pass A")
    pass_a = RE.run_engine(conn, RE.EngineRequest(
        engine="E1", structured_input={**intake, "MODE": "PASS_A"},
        client_id=client, case_version_id=v1, cycle_id=cycle, pass_label="A"))
    check("Pass A succeeded", pass_a.status == "SUCCEEDED", pass_a.error or "")
    check("Pass A emits research questions for Engine 7",
          len(pass_a.control.get("RESEARCH_QUESTIONS", [])) >= 2,
          str(pass_a.control.get("RESEARCH_QUESTIONS")))
    check("Pass A emits clinical phrases, not canonical keys",
          any(" " in p and p.islower() for p in pass_a.control.get("NORMALIZATION_PHRASES", [])),
          str(pass_a.control.get("NORMALIZATION_PHRASES")))
    check("Pass A hands off to Engine 7",
          pass_a.control.get("NEXT_ENGINE") == "E7", str(pass_a.control.get("NEXT_ENGINE")))

    print("\nE7 then E1 Pass B")
    e7 = RE.run_engine(conn, RE.EngineRequest(
        engine="E7",
        structured_input={"CASE_RESEARCH_QUESTIONS": pass_a.control["RESEARCH_QUESTIONS"],
                          "CASE_VERSION": 1},
        client_id=client, case_version_id=v1, cycle_id=cycle, model_role="MODEL_RESEARCH"))
    check("E7 case mode succeeded", e7.status == "SUCCEEDED", e7.error or "")
    check("E7 reports library sufficiency", e7.control.get("KNOWLEDGE_SUFFICIENT") is True)

    pass_b = RE.run_engine(conn, RE.EngineRequest(
        engine="E1", structured_input={**intake, "MODE": "PASS_B", "E7_HANDOFF": {"strategies": []}},
        client_id=client, case_version_id=v1, cycle_id=cycle, pass_label="B"))
    check("Pass B succeeded", pass_b.status == "SUCCEEDED", pass_b.error or "")

    hashes = conn.execute(
        "select distinct prompt_hash from engine_runs where cycle_id=%s and engine='E1'", (cycle,)
    ).fetchall()
    check("both E1 passes recorded one prompt hash", len(hashes) == 1, str(hashes))

    print("\nrepair retry and dead letter")
    calls = {"n": 0}

    def flaky(system, user, params):
        calls["n"] += 1
        if calls["n"] == 1:
            return "prose only, no control block", 10, 5
        return ('ok\n<CONTROL_BLOCK>\n{"CASE_VERSION":1,"ENGINE_RUN_STATUS":"SUCCEEDED"}\n'
                '</CONTROL_BLOCK>'), 10, 20

    original = RE.select_provider
    RE.select_provider = lambda: (flaky, "test")
    repaired = RE.run_engine(conn, RE.EngineRequest(
        engine="E2", structured_input={"CASE_VERSION": 1}, client_id=client, cycle_id=cycle))
    check("invalid first response repaired on retry",
          repaired.status == "SUCCEEDED" and repaired.attempts == 2,
          f"status={repaired.status} attempts={repaired.attempts}")

    RE.select_provider = lambda: ((lambda s, u, p: ("never valid", 5, 5)), "test")
    dead = RE.run_engine(conn, RE.EngineRequest(
        engine="E3", structured_input={"CASE_VERSION": 1}, client_id=client, cycle_id=cycle))
    RE.select_provider = original

    check("persistently invalid output dead-lettered",
          dead.status == "DEAD_LETTER" and dead.attempts == RE.MAX_ATTEMPTS,
          f"status={dead.status} attempts={dead.attempts}")
    check("no engine_output row written for a dead-lettered run",
          conn.execute("select count(*) from engine_outputs where run_id=%s",
                       (dead.run_id,)).fetchone()[0] == 0)
    check("dead letter recorded with raw payload",
          conn.execute("select count(*) from dead_letter_jobs where entity_id=%s",
                       (dead.run_id,)).fetchone()[0] == 1)

    print("\ncost telemetry")
    rows = conn.execute(
        """select count(*), sum(input_tokens + output_tokens)
             from cost_events where operation='ENGINE_RUN' and entity_id=%s""",
        (str(client),),
    ).fetchone()
    check("every model call recorded, including failed attempts",
          rows[0] >= 8, f"{rows[0]} cost events")
    health = conn.execute(
        "select engine, pass, status, runs from v_engine_run_health order by engine, pass"
    ).fetchall()
    check("run health view reports per-engine status", len(health) >= 4, str(health))

    print("\nno free-text routing")
    ctrl = conn.execute(
        """select control from engine_outputs o
             join engine_runs r on r.run_id = o.run_id
            where r.run_id=%s""",
        (pass_a.run_id,),
    ).fetchone()[0]
    check("routing reads a typed field, never prose",
          isinstance(ctrl.get("NEXT_ENGINE"), str)
          and ctrl["NEXT_ENGINE"] in {"E1","E2","E3","E4","E5","E6","E7","REVIEW","NONE"},
          str(ctrl.get("NEXT_ENGINE")))

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): {', '.join(FAILS)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

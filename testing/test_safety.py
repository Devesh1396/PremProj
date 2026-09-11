#!/usr/bin/env python3
"""Step 20 — the deterministic flag rule set, review, E5 and release.

D6, hard rule 9; migrations 004 and 026.

**The headline is a NEGATIVE.** A client on metformin, a statin and an ACE
inhibitor must pass clean. An early proposal made antihypertensives and
thyroid replacement HOLD triggers, which against this population fires on
nearly every case — and a gate that fires constantly is a rubber stamp,
less protection than no gate plus friction. So the first thing this suite
asserts is that the gate stays shut up, and the failure mode it guards
against is a rule set that quietly widens.

Every rule is then driven through the REAL `evaluate_safety_rules()` with
real client rows (V2), and every optional dependency degrades through
`preflight` (V3).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "testing"))

import psycopg

import client_release as CR
import preflight
import run_engine as RE

FAILS: list[str] = []
PREFIX = "SAFETEST_"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def expect_error(conn, sql, params, name, fragment):
    try:
        with conn.transaction():
            conn.execute(sql, params)
    except psycopg.Error as exc:
        check(name, fragment.lower() in str(exc).lower(), str(exc)[:200])
        return
    check(name, False, "no error was raised")


# ---------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------

def clear(conn) -> None:
    conn.execute("delete from clients where external_ref like %s", (PREFIX + "%",))


def make_client(conn, ref: str, year_of_birth: int = 1980) -> str:
    client_id = str(conn.execute(
        "insert into clients (external_ref, display_name, year_of_birth, status) "
        "values (%s,%s,%s,'ACTIVE') returning client_id",
        (PREFIX + ref, PREFIX + ref, year_of_birth)).fetchone()[0])
    conn.execute("select set_client_scope(%s::uuid)", (client_id,))
    return client_id


def med(conn, client_id: str, name: str) -> None:
    conn.execute(
        "insert into client_medications (client_id, name, status) "
        "values (%s::uuid,%s,'CURRENT')", (client_id, name))


def condition(conn, client_id: str, name: str) -> None:
    conn.execute(
        "insert into client_conditions (client_id, condition, status) "
        "values (%s::uuid,%s,'ACTIVE')", (client_id, name))


def lab(conn, client_id: str, marker: str, value, unit: str = None,
        on: str = "2026-09-01") -> None:
    conn.execute(
        "insert into client_labs (client_id, measured_on, marker, value, unit) "
        "values (%s::uuid,%s::date,%s,%s,%s)",
        (client_id, on, marker, value, unit))


def intervention(conn, client_id: str, name: str, status: str = "PROPOSED",
                 outcome: str = "NOT_TRACKED") -> None:
    conn.execute(
        "insert into client_interventions (client_id, name, status, outcome) "
        "values (%s::uuid,%s,%s::intervention_status,%s::outcome_direction)",
        (client_id, name, status, outcome))


# Every rule this suite has actually made fire, accumulated AS it fires.
# Re-deriving it at the end would ask a mutated fixture what it used to say:
# by then the turmeric intervention is deleted and the potassium corrected,
# so two rules that demonstrably fired would read as never having fired.
FIRED_DURING_RUN: set[str] = set()


def fired(conn, client_id: str) -> dict:
    """What the REAL rule function says, keyed by rule."""
    verdict = {r[0]: (r[1], r[2]) for r in conn.execute(
        "select rule_key, severity::text, detail "
        "  from evaluate_safety_rules(%s::uuid)", (client_id,)).fetchall()}
    FIRED_DURING_RUN.update(verdict)
    return verdict


def main() -> int:
    os.environ["LLM_API_KEY"] = ""
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    clear(conn)

    # ==================================================================
    print("\nD6's acceptance case: the ordinary medicated metabolic client")

    ordinary = make_client(conn, "ordinary")
    for name in ("Metformin 1000mg", "Atorvastatin 20mg", "Ramipril 5mg",
                 "Levothyroxine 50mcg", "Amlodipine 5mg"):
        med(conn, ordinary, name)
    condition(conn, ordinary, "type 2 diabetes")
    condition(conn, ordinary, "hypertension")
    lab(conn, ordinary, "HBA1C", 7.4, "%")
    lab(conn, ordinary, "GLUCOSE_FASTING", 132, "mg/dL")
    lab(conn, ordinary, "EGFR", 78, "mL/min/1.73m2")
    lab(conn, ordinary, "ALT", 44, "U/L")
    intervention(conn, ordinary, "carbohydrate reduction at dinner")
    intervention(conn, ordinary, "walk after meals")

    result = fired(conn, ordinary)
    check("metformin + statin + ACE inhibitor + thyroid + amlodipine: CLEAN",
          result == {}, str(result))
    check("...even with a glucose-lowering intervention proposed",
          "HYPOGLYCAEMIA_RISK" not in result,
          "metformin is not insulin and not a sulfonylurea")
    check("...and with labs abnormal but not CRITICAL",
          "CRITICAL_LAB" not in result, str(result))

    # ==================================================================
    print("\nhypoglycaemia risk needs BOTH halves")

    insulin_only = make_client(conn, "insulin_only")
    med(conn, insulin_only, "Insulin glargine 20u")
    check("insulin with no glucose-lowering intervention is not a flag",
          fired(conn, insulin_only) == {}, str(fired(conn, insulin_only)))

    intervention(conn, insulin_only, "intermittent fasting 16:8")
    both = fired(conn, insulin_only)
    check("insulin PLUS the intervention is a HOLD",
          both.get("HYPOGLYCAEMIA_RISK", ("", ""))[0] == "HOLD", str(both))
    check("and the detail names the intervention",
          "intermittent fasting" in both["HYPOGLYCAEMIA_RISK"][1],
          both["HYPOGLYCAEMIA_RISK"][1])

    su = make_client(conn, "sulfonylurea")
    med(conn, su, "Glimepiride 2mg")
    intervention(conn, su, "low carbohydrate evening meal")
    check("a sulfonylurea counts the same as insulin",
          "HYPOGLYCAEMIA_RISK" in fired(conn, su), str(fired(conn, su)))

    plan_only = make_client(conn, "plan_only")
    intervention(conn, plan_only, "extended fasting")
    check("the intervention alone, with no such medication, is not a flag",
          fired(conn, plan_only) == {}, str(fired(conn, plan_only)))

    # ==================================================================
    print("\nadding a drug to a class is an INSERT, not a migration")

    novel = make_client(conn, "novel_su")
    med(conn, novel, "Tolbutamide 500mg")
    check("an unregistered sulfonylurea is NOT matched — honestly",
          "HYPOGLYCAEMIA_RISK" not in fired(conn, novel))
    intervention(conn, novel, "berberine with meals")
    conn.execute(
        "insert into safety_match_patterns (match_class, applies_to, pattern, note) "
        "values ('SULFONYLUREA','MEDICATION','tolbutamide','SAFETEST') "
        "on conflict do nothing")
    check("...and one INSERT later it is (hard rule 13)",
          "HYPOGLYCAEMIA_RISK" in fired(conn, novel), str(fired(conn, novel)))
    conn.execute("delete from safety_match_patterns where note='SAFETEST'")

    # ==================================================================
    print("\nwarfarin, and only where the intervention interacts")

    warf = make_client(conn, "warfarin")
    med(conn, warf, "Warfarin 3mg")
    intervention(conn, warf, "walk after meals")
    check("warfarin with an unrelated intervention is not a flag",
          fired(conn, warf) == {}, str(fired(conn, warf)))
    intervention(conn, warf, "turmeric with black pepper daily")
    check("warfarin with an interacting one is a HOLD",
          fired(conn, warf).get("ANTICOAGULANT_INTERACTION", ("", ""))[0] == "HOLD",
          str(fired(conn, warf)))

    # ==================================================================
    print("\ncritical labs are CRITICAL, not merely abnormal")

    labs = make_client(conn, "labs")
    lab(conn, labs, "POTASSIUM", 5.4, "mmol/L")
    check("a potassium of 5.4 is abnormal and not critical",
          fired(conn, labs) == {}, str(fired(conn, labs)))
    lab(conn, labs, "POTASSIUM", 6.4, "mmol/L", on="2026-09-05")
    check("6.4 is", "CRITICAL_LAB" in fired(conn, labs), str(fired(conn, labs)))

    # The LATEST value per marker, not any historical one.
    lab(conn, labs, "POTASSIUM", 4.4, "mmol/L", on="2026-09-09")
    check("a corrected value clears it — the rule reads the latest, not the worst",
          "CRITICAL_LAB" not in fired(conn, labs), str(fired(conn, labs)))

    # ==================================================================
    print("\none rule, two evidence sources: renal and hepatic")

    renal = make_client(conn, "renal_lab")
    lab(conn, renal, "EGFR", 32, "mL/min/1.73m2")
    by_lab = fired(conn, renal)
    check("a low eGFR raises RENAL_HEPATIC_IMPAIRMENT, not CRITICAL_LAB",
          "RENAL_HEPATIC_IMPAIRMENT" in by_lab and "CRITICAL_LAB" not in by_lab,
          str(by_lab))

    hepatic = make_client(conn, "hepatic_condition")
    condition(conn, hepatic, "compensated cirrhosis")
    check("and so does the condition, through the same rule key",
          "RENAL_HEPATIC_IMPAIRMENT" in fired(conn, hepatic),
          str(fired(conn, hepatic)))

    # ==================================================================
    print("\npregnancy, breastfeeding, minors")

    pregnant = make_client(conn, "pregnant")
    condition(conn, pregnant, "pregnancy, second trimester")
    check("pregnancy is a HOLD",
          fired(conn, pregnant).get("PREGNANCY_BREASTFEEDING_MINOR",
                                    ("", ""))[0] == "HOLD",
          str(fired(conn, pregnant)))

    minor = make_client(conn, "minor", year_of_birth=2012)
    check("a client under 18 is a HOLD",
          "PREGNANCY_BREASTFEEDING_MINOR" in fired(conn, minor),
          str(fired(conn, minor)))

    adult = make_client(conn, "adult", year_of_birth=1995)
    check("an adult is not", fired(conn, adult) == {}, str(fired(conn, adult)))

    # ==================================================================
    print("\nhard rule 9: a worsening marker is a NOTE, and never blocks")

    worse = make_client(conn, "worsening")
    intervention(conn, worse, "protein at breakfast", status="ONGOING",
                 outcome="WORSENING")
    verdict = fired(conn, worse)
    check("a worsening marker fires", "WORSENING_MARKER" in verdict, str(verdict))
    check("...as a NOTE, not a HOLD",
          verdict["WORSENING_MARKER"][0] == "NOTE", str(verdict))

    conn.execute("select apply_safety_rules(%s::uuid, null, null)", (worse,))
    readiness = conn.execute(
        "select open_holds, open_notes from v_release_readiness "
        " where client_id=%s::uuid", (worse,)).fetchone()
    check("it opens a NOTE and no HOLD", readiness == (0, 1), str(readiness))

    # ==================================================================
    print("\napplying rules is idempotent, and never auto-closes")

    opened_first = conn.execute(
        "select apply_safety_rules(%s::uuid, null, null)", (warf,)).fetchone()[0]
    opened_again = conn.execute(
        "select apply_safety_rules(%s::uuid, null, null)", (warf,)).fetchone()[0]
    check("a rule already OPEN is not opened twice",
          opened_first >= 1 and opened_again == 0,
          f"{opened_first} then {opened_again}")

    conn.execute("delete from client_interventions where client_id=%s::uuid "
                 "  and name like '%%turmeric%%'", (warf,))
    check("the rule no longer fires...",
          "ANTICOAGULANT_INTERACTION" not in fired(conn, warf))
    still = conn.execute(
        "select count(*) from case_flags where client_id=%s::uuid "
        "  and rule_key='ANTICOAGULANT_INTERACTION' and status='OPEN'",
        (warf,)).fetchone()[0]
    check("...but the open flag stays: clearing one is a practitioner act",
          still == 1, str(still))

    # ==================================================================
    print("\nan engine may add a flag; it may not clear a deterministic one")

    flag_id = conn.execute(
        "select flag_id::text from case_flags where client_id=%s::uuid "
        "  and source='DETERMINISTIC' limit 1", (warf,)).fetchone()[0]
    expect_error(
        conn,
        "update case_flags set status='RESOLVED', resolved_by='E5' "
        " where flag_id=%s::uuid", (flag_id,),
        "an engine cannot resolve a deterministic flag", "deterministic")

    expect_error(
        conn,
        "insert into case_flags (client_id, rule_key, severity, source, detail) "
        "values (%s::uuid,'INVENTED_RULE','HOLD','DETERMINISTIC','x')", (warf,),
        "an unregistered deterministic rule_key is refused", "registered safety rule")

    # An LLM flag with its own key is fine: engines MAY add flags.
    conn.execute(
        "insert into case_flags (client_id, rule_key, severity, source, detail) "
        "values (%s::uuid,'E1_CONCERN','NOTE','LLM','a note from an engine')",
        (warf,))
    check("an engine MAY add its own flag", True)

    # ==================================================================
    print("\nrelease: three separate conditions, none substituting")

    releasable = make_client(conn, "releasable")
    med(conn, releasable, "Metformin 1000mg")
    cycle = str(conn.execute(
        "insert into case_cycles (client_id, cycle_number, cycle_type) "
        "values (%s::uuid,1,'NEW_CLIENT') returning cycle_id",
        (releasable,)).fetchone()[0])
    conn.execute(
        "insert into client_case_versions (client_id, case_version, phase, "
        " canonical_state, is_current, change_reason, created_by) "
        "values (%s::uuid,1,'PHASE_1',%s::jsonb,true,%s,'SAFETEST')",
        (releasable, json.dumps({"PRIMARY_HEALTH_PROBLEM": "test"}), "SAFETEST"))
    intervention(conn, releasable, "fibre before carbohydrate at lunch")

    drafted = CR.draft(conn, releasable)
    check("drafting is never gated — it produced a message", drafted["characters"] > 0,
          str(drafted))
    check("and it is NOT released", drafted["released"] is False)

    try:
        CR.release(conn, drafted["communication_id"], by="tester")
        check("release with no approval is refused", False, "it was released")
    except CR.ReleaseRefused as exc:
        check("release with no approval is refused",
              "approval" in str(exc).lower(), str(exc)[:120])

    review = str(conn.execute(
        "insert into practitioner_reviews (client_id, cycle_id, decision) "
        "values (%s::uuid,%s::uuid,'PENDING') returning review_id",
        (releasable, cycle)).fetchone()[0])
    approved = CR.approve(conn, review, by="tester")
    check("approval is recorded", approved["decision"] == "APPROVED", str(approved))
    check("and reports no open HOLD for this client", approved["open_holds"] == 0)

    out = CR.release(conn, drafted["communication_id"], by="tester")
    check("with approval and no HOLD it releases", out["released"] is True, str(out))

    # ==================================================================
    print("\nthe gate is the DATABASE's, not this file's")

    blocked = make_client(conn, "blocked")
    condition(conn, blocked, "pregnancy")
    cycle2 = str(conn.execute(
        "insert into case_cycles (client_id, cycle_number, cycle_type) "
        "values (%s::uuid,1,'NEW_CLIENT') returning cycle_id",
        (blocked,)).fetchone()[0])
    conn.execute(
        "insert into client_case_versions (client_id, case_version, phase, "
        " canonical_state, is_current, change_reason, created_by) "
        "values (%s::uuid,1,'PHASE_1',%s::jsonb,true,%s,'SAFETEST')",
        (blocked, json.dumps({"PRIMARY_HEALTH_PROBLEM": "test"}), "SAFETEST"))
    conn.execute("select apply_safety_rules(%s::uuid, %s::uuid, null)",
                 (blocked, cycle2))
    review2 = str(conn.execute(
        "insert into practitioner_reviews (client_id, cycle_id, decision) "
        "values (%s::uuid,%s::uuid,'PENDING') returning review_id",
        (blocked, cycle2)).fetchone()[0])
    CR.approve(conn, review2, by="tester")

    draft2 = CR.draft(conn, blocked)
    check("a HOLD does not stop DRAFTING (hard rule 9)",
          draft2["characters"] > 0, str(draft2))

    # Approved, drafted -- and still refused, by the trigger rather than by
    # any check in client_release.py. Written directly so it is unambiguous
    # which layer refuses.
    expect_error(
        conn,
        "update client_communications set released=true where communication_id=%s::uuid",
        (draft2["communication_id"],),
        "an approved message is still blocked by an open HOLD",
        "open HOLD")

    ready = conn.execute(
        "select open_holds, approvals, releasable from v_release_readiness "
        " where client_id=%s::uuid", (blocked,)).fetchone()
    check("v_release_readiness says why: approved, but held",
          ready[0] == 1 and ready[1] == 1 and ready[2] is False, str(ready))

    # ==================================================================
    print("\nthe catalogue and the implementation agree")

    registered = {r[0] for r in conn.execute(
        "select rule_key from safety_rules where active").fetchall()}
    # A registered rule nothing can make fire is either unreachable code or
    # a rule whose fixture was never written -- and both look identical to a
    # green suite that does not check.
    check("every registered rule has been made to fire by this suite",
          registered <= FIRED_DURING_RUN,
          f"never fired: {sorted(registered - FIRED_DURING_RUN)}")
    check("and this suite invented no rule the catalogue does not know",
          FIRED_DURING_RUN <= registered,
          f"unregistered: {sorted(FIRED_DURING_RUN - registered)}")

    disabled = conn.execute(
        "update safety_rules set active=false where rule_key='WORSENING_MARKER' "
        " returning rule_key", ).fetchone()
    conn.execute("select set_client_scope(%s::uuid)", (worse,))
    check("disabling a rule is an UPDATE, and it stops firing",
          "WORSENING_MARKER" not in fired(conn, worse), str(fired(conn, worse)))
    conn.execute("update safety_rules set active=true where rule_key=%s", disabled)

    clear(conn)
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("test_safety: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

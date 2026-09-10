#!/usr/bin/env python3
"""Core Intake V1 — validation, conditional logic, and conversion to E6 v1.

BUILD_GUIDE step 14. Scope and exclusions: DECISIONS.md D22, written before
any field here existed.

The one rule that shapes every function below: **intake never blocks a
case.** `validate()` returns gaps, it does not raise. `submit()` accepts an
incomplete payload. `to_e6_input()` builds a runnable Engine 6 input out of
whatever is present and tells Engine 6 what is missing. A client who
answered half the questions still gets a case; they get follow-up questions
from Engine 5 rather than a rejection.

The second rule: **absence is never normality.** A field that was not asked,
or asked and not answered, becomes UNKNOWN in the E6 input. It is never
defaulted to a normal value, and RHT NOT_ASSESSED never means "RHT was
fine".
"""

from __future__ import annotations

import json
import os
from typing import Any

import psycopg

UNKNOWN = "UNKNOWN"

# Gaps at or above this severity are what Engine 5 turns into follow-up
# questions, and what HIGH_PRIORITY_MISSING_DATA carries to Engine 6.
HIGH_PRIORITY = ("CRITICAL", "HIGH")

# Which catalog classification becomes which gap severity. ESSENTIAL is the
# only one that reaches Engine 5 as a follow-up question by default: if
# everything is urgent then nothing is, and D8 caps escalation by impact.
SEVERITY_BY_CLASSIFICATION = {
    "ESSENTIAL": "HIGH",
    "USEFUL": "MODERATE",
    "CONDITIONAL": "LOW",
    "OPTIONAL": "LOW",
    "ALREADY_COVERED_BY_RHT": "LOW",
    "UNNECESSARY": "LOW",
}

# Sections whose content is extracted into the typed 004 tables rather than
# living only as intake payload.
EXTRACTED_SECTIONS = {
    "BASIC_PROFILE", "DIAGNOSES_HISTORY", "MEDICATIONS",
    "LABS_REPORTS", "SYMPTOMS", "FOOD_LOG",
}


# ---------------------------------------------------------------------
# The field catalog and conditional logic
# ---------------------------------------------------------------------

def load_catalog(conn) -> list[dict]:
    """Active, askable fields. RHT-owned entries are excluded by definition."""
    rows = conn.execute(
        """select field_key, section::text, label, classification::text,
                  condition_field, condition_values, rht_owned
             from intake_field_catalog
            where active and not rht_owned
            order by section, field_key"""
    ).fetchall()
    keys = ["field_key", "section", "label", "classification",
            "condition_field", "condition_values", "rht_owned"]
    return [dict(zip(keys, r)) for r in rows]


def _flatten(payload: dict) -> dict[str, Any]:
    """field_key -> value across all sections, ignoring empty answers.

    An empty string, empty list or explicit None is NOT an answer. Treating
    "" as answered is how a blank form becomes a complete one.
    """
    flat: dict[str, Any] = {}
    for section, body in (payload.get("sections") or {}).items():
        if not isinstance(body, dict):
            continue
        for key, value in body.items():
            if value is None or value == "" or value == [] or value == {}:
                continue
            flat[key] = value
    return flat


def is_applicable(field: dict, answers: dict[str, Any]) -> bool:
    """Should this field have been asked, given what the client has said?

    A conditional field that does not apply is NOT a gap. A male client has
    not failed to answer the menstrual-cycle question.
    """
    cond_field = field.get("condition_field")
    if not cond_field:
        return True
    actual = answers.get(cond_field)
    if actual is None:
        # The gating answer itself is missing, so applicability is unknown.
        # Unknown applicability is not a gap in the conditional field: it is
        # a gap in the gating field, and that is reported on its own.
        return False
    wanted = [w.upper() for w in (field.get("condition_values") or [])]
    if any(w.startswith("__") for w in wanted):
        # Marker conditions (e.g. __ANY_MOBILITY_OR_PAIN__) are evaluated by
        # the practitioner surface, not by string equality. Treat as asked
        # so the field is offered rather than silently dropped.
        return True
    if isinstance(actual, list):
        return any(str(a).upper() in wanted for a in actual)
    return str(actual).upper() in wanted


# ---------------------------------------------------------------------
# Validation — records gaps, never refuses
# ---------------------------------------------------------------------

def validate(conn, payload: dict) -> list[dict]:
    """Return the gaps in this submission. NEVER raises, never rejects.

    A gap is an applicable, active, non-RHT field with no answer. The return
    value is a list of dicts ready for missing_data_reports.
    """
    answers = _flatten(payload)
    sections = payload.get("sections") or {}
    not_applicable = {
        s for s, body in sections.items()
        if isinstance(body, dict) and body.get("_not_applicable")
    }

    gaps = []
    for field in load_catalog(conn):
        if field["section"] in not_applicable:
            continue
        if field["field_key"] in answers:
            continue
        if not is_applicable(field, answers):
            continue
        gaps.append({
            "missing_field": field["field_key"],
            "section": field["section"],
            "classification": field["classification"],
            "severity": SEVERITY_BY_CLASSIFICATION.get(field["classification"], "MODERATE"),
            "why_it_mattered": field["label"],
        })
    return gaps


def record_gaps(conn, client_id: str, submission_id: str, gaps: list[dict]) -> int:
    """Write gaps to the EXISTING missing_data_reports machinery (005).

    engine is NULL and submission_id is set: this gap was found by intake
    validation, not by an engine's reasoning. ck_gap_has_a_source enforces
    that exactly one of the two is present, so an intake gap cannot be
    laundered into an engine attribution and pollute
    v_missing_data_recurrence's `engines` column.

    `classification` is deliberately NOT written, even though the catalog
    holds one for every field. That column is the GOVERNANCE decision --
    should this become an intake question? -- and section 57, D8 and D22
    all require it to be a deliberate human act. Writing it here would do
    two bad things: duplicate a fact that already lives in
    intake_field_catalog and can then drift from it, and drop the row out
    of the unclassified triage queue (idx_missing_unclassified) that the
    whole "aggregate, then classify deliberately" policy runs on. Severity
    IS written: that is derived urgency, not governance.
    """
    conn.execute("delete from missing_data_reports where submission_id = %s",
                 (submission_id,))
    for gap in gaps:
        conn.execute(
            """insert into missing_data_reports
                 (engine, submission_id, client_id, missing_field, why_it_mattered,
                  severity, constrained_reasoning, rht_would_supply)
               values (NULL,%s,%s,%s,%s,%s,%s,false)""",
            (submission_id, client_id, gap["missing_field"], gap["why_it_mattered"],
             gap["severity"], gap["severity"] in HIGH_PRIORITY))
    return len(gaps)


# ---------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------

def submit(conn, client_id: str, payload: dict, captured_by: str = "practitioner",
           capture_method: str = "CONSULTATION_TRANSCRIPTION") -> str:
    """Store a submission and its sections, and record its gaps.

    Accepts an incomplete payload by design. Returns submission_id.
    """
    conn.execute(
        """update intake_submissions set status='SUPERSEDED'
            where client_id=%s and status in ('DRAFT','SUBMITTED')""",
        (client_id,))

    submission_id = conn.execute(
        """insert into intake_submissions
             (client_id, status, captured_by, capture_method, raw_payload, submitted_at)
           values (%s,'SUBMITTED',%s,%s,%s, now())
           returning submission_id""",
        (client_id, captured_by, capture_method, json.dumps(payload)),
    ).fetchone()[0]

    for section, body in (payload.get("sections") or {}).items():
        if not isinstance(body, dict):
            continue
        na = bool(body.get("_not_applicable"))
        conn.execute(
            """insert into intake_sections
                 (submission_id, client_id, section, payload, not_applicable, na_reason)
               values (%s,%s,%s,%s,%s,%s)""",
            (submission_id, client_id, section,
             json.dumps({k: v for k, v in body.items() if not k.startswith("_")}),
             na, body.get("_na_reason") if na else None))

    record_gaps(conn, client_id, str(submission_id), validate(conn, payload))
    return str(submission_id)


# ---------------------------------------------------------------------
# Extraction into the typed case tables
# ---------------------------------------------------------------------

def extract(conn, submission_id: str) -> dict[str, int]:
    """Write intake content into the EXISTING 004 clinical tables.

    Nothing new is invented to hold clinical facts: client_labs,
    client_medications, client_supplements, client_conditions,
    client_symptoms, client_measurements and client_food_logs already exist
    and already carry RLS, so every view and engine built on them works on
    intake-sourced data unchanged.
    """
    row = conn.execute(
        "select client_id, raw_payload from intake_submissions where submission_id=%s",
        (submission_id,)).fetchone()
    client_id, payload = row[0], row[1]
    sections = payload.get("sections") or {}
    counts: dict[str, int] = {}

    def bump(name: str, n: int = 1):
        counts[name] = counts.get(name, 0) + n

    basic = sections.get("BASIC_PROFILE", {}) or {}
    for measure, unit in (("height_cm", "cm"), ("weight_kg", "kg"), ("waist_cm", "cm")):
        value = basic.get(measure)
        if value is not None:
            conn.execute(
                """insert into client_measurements
                     (client_id, measured_on, measure, value, unit, is_baseline, source)
                   values (%s, coalesce(%s, current_date), %s,%s,%s,true,'CORE_INTAKE')""",
                (client_id, payload.get("measured_on"), measure, value, unit))
            bump("measurements")

    for condition in (sections.get("DIAGNOSES_HISTORY", {}) or {}).get("known_diagnoses", []) or []:
        name = condition if isinstance(condition, str) else condition.get("condition")
        conn.execute(
            """insert into client_conditions (client_id, condition, status, source, is_inferred)
               values (%s,%s,'ACTIVE','CORE_INTAKE',false)""", (client_id, name))
        bump("conditions")

    for symptom in (sections.get("SYMPTOMS", {}) or {}).get("current_symptoms", []) or []:
        name = symptom if isinstance(symptom, str) else symptom.get("symptom")
        severity = None if isinstance(symptom, str) else symptom.get("severity")
        conn.execute(
            """insert into client_symptoms (client_id, symptom, severity, reported_on)
               values (%s,%s,%s, current_date)""", (client_id, name, severity))
        bump("symptoms")

    meds = sections.get("MEDICATIONS", {}) or {}
    for med in meds.get("medications", []) or []:
        if isinstance(med, str):
            med = {"name": med}
        conn.execute(
            """insert into client_medications (client_id, name, dose, timing, status, prescriber_note)
               values (%s,%s,%s,%s,'CURRENT',%s)""",
            (client_id, med.get("name"),
             # An unknown dose is recorded as UNKNOWN. It is never guessed,
             # and it is never left to read as "no dose".
             med.get("dose") or UNKNOWN, med.get("timing") or UNKNOWN,
             med.get("reason") or UNKNOWN))
        bump("medications")

    for sup in meds.get("supplements", []) or []:
        if isinstance(sup, str):
            sup = {"name": sup}
        conn.execute(
            """insert into client_supplements (client_id, name, dose, timing, status, is_therapeutic_dose)
               values (%s,%s,%s,%s,'CURRENT',false)""",
            (client_id, sup.get("name"), sup.get("dose") or UNKNOWN,
             sup.get("timing") or UNKNOWN))
        bump("supplements")

    labs = sections.get("LABS_REPORTS", {}) or {}
    report_ids = {}
    for report in labs.get("lab_reports", []) or []:
        rid = conn.execute(
            """insert into client_report_files
                 (client_id, submission_id, report_kind, report_date, laboratory,
                  storage_ref, original_filename, provenance_note, transcribed)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s) returning report_file_id""",
            (client_id, submission_id, report.get("kind", "LAB_PANEL"),
             report.get("date"), report.get("laboratory"), report.get("storage_ref"),
             report.get("filename"), report.get("note", "Supplied at Core Intake"),
             bool(report.get("transcribed")))).fetchone()[0]
        report_ids[report.get("ref") or report.get("filename")] = rid
        bump("report_files")

    for lab in labs.get("lab_values", []) or []:
        conn.execute(
            """insert into client_labs
                 (client_id, measured_on, marker, value, unit,
                  reference_low, reference_high, is_baseline, source, report_file_id)
               values (%s,%s,%s,%s,%s,%s,%s,true,'CORE_INTAKE',%s)""",
            (client_id, lab.get("date") or labs.get("lab_dates"), lab.get("marker"),
             lab.get("value"), lab.get("unit"), lab.get("ref_low"), lab.get("ref_high"),
             report_ids.get(lab.get("report_ref"))))
        bump("labs")

    for day in (sections.get("FOOD_LOG", {}) or {}).get("food_log_days", []) or []:
        conn.execute(
            """insert into client_food_logs (client_id, logged_on, raw_text, structured, source)
               values (%s,%s,%s,%s,'CORE_INTAKE')""",
            (client_id, day.get("date"), day.get("raw_text"),
             json.dumps({k: v for k, v in day.items() if k not in ("raw_text",)})))
        bump("food_log_days")

    return counts


# ---------------------------------------------------------------------
# RHT linkage
# ---------------------------------------------------------------------

def rht_state(conn, client_id: str, payload: dict) -> dict:
    """The RHT block for Engine 6.

    NOT_ASSESSED MEANS UNKNOWN, NOT NORMAL. Core Intake does not and must
    not reconstruct RHT's depth from its own questions (D22); when RHT is
    absent, the honest answer is that these signals are unknown.
    """
    declared = ((payload.get("sections") or {}).get("RHT_LINKAGE") or {}).get("rht_status")
    status = (declared or "NOT_ASSESSED").upper()

    block: dict[str, Any] = {
        "RHT_STATUS": status,
        "MEANING": ("Real Health Test signals are UNKNOWN. Absence of an assessment "
                    "is not evidence that these areas are normal."),
        "OWNED_BY_RHT_NOT_COLLECTED_HERE": [
            r[0] for r in conn.execute(
                "select field_key from intake_field_catalog where rht_owned order by field_key"
            ).fetchall()],
    }

    if status != "COMPLETED":
        return block

    row = conn.execute(
        """select assessment_id, instrument_version, scoring_version, assessed_on
             from client_assessments
            where client_id=%s and instrument='REAL_HEALTH_TEST' and status='COMPLETED'
            order by assessed_on desc nulls last limit 1""", (client_id,)).fetchone()
    if row is None:
        # Declared COMPLETED with nothing linked. Do not take the claim on
        # trust: report it as unknown, which is what it actually is.
        block["RHT_STATUS"] = "NOT_ASSESSED"
        block["DISCREPANCY"] = ("Intake declared RHT COMPLETED but no completed "
                                "assessment is linked. Treated as NOT_ASSESSED.")
        return block

    assessment_id, iv, sv, assessed_on = row
    layers = conn.execute(
        """select layer_type::text, payload from assessment_layers
            where assessment_id=%s order by layer_type""", (assessment_id,)).fetchall()
    block.update({
        "MEANING": "Real Health Test completed; structured package linked below.",
        "ASSESSMENT_ID": str(assessment_id),
        "INSTRUMENT_VERSION": iv,
        "SCORING_VERSION": sv,
        "ASSESSED_ON": assessed_on.isoformat() if assessed_on else None,
        "LAYERS": {layer: body for layer, body in layers},
    })
    return block


# ---------------------------------------------------------------------
# Conversion into the Engine 6 canonical-state input
# ---------------------------------------------------------------------

def to_e6_input(conn, submission_id: str) -> dict:
    """Build the structured input that initializes E6 canonical state v1.

    Works on whatever is present. Missing sections appear as UNKNOWN, and
    the high-priority gaps travel with the payload so Engine 6 records what
    it could not see and Engine 5 can ask for it.

    Carries client_id and clinical facts, never the display name
    (STRIP_IDENTITY_FROM_ENGINE_PAYLOADS, docs/OPERATIONS.md data residency).
    """
    row = conn.execute(
        """select client_id, raw_payload, status::text
             from intake_submissions where submission_id=%s""", (submission_id,)).fetchone()
    client_id, payload, status = row
    sections = payload.get("sections") or {}

    def section(name: str) -> Any:
        body = sections.get(name)
        if body is None:
            return UNKNOWN
        if isinstance(body, dict) and body.get("_not_applicable"):
            return {"NOT_APPLICABLE": True, "REASON": body.get("_na_reason")}
        return {k: v for k, v in body.items() if not k.startswith("_")} or UNKNOWN

    gaps = conn.execute(
        """select missing_field, severity::text, why_it_mattered
             from missing_data_reports
            where submission_id=%s and not resolved
            order by array_position(array['CRITICAL','HIGH','MODERATE','LOW'], severity::text),
                     missing_field""", (submission_id,)).fetchall()

    return {
        "CLIENT_ID": str(client_id),
        "CASE_VERSION": 1,
        "INTAKE_SUBMISSION_ID": str(submission_id),
        "INTAKE_SCHEMA": "intake.v1",
        "INTAKE_STATUS": status,

        "BASIC_PROFILE":      section("BASIC_PROFILE"),
        "GOALS":              section("GOALS"),
        "DIAGNOSES_HISTORY":  section("DIAGNOSES_HISTORY"),
        "MEDICATIONS":        section("MEDICATIONS"),
        "LABS_REPORTS":       section("LABS_REPORTS"),
        "SYMPTOMS":           section("SYMPTOMS"),
        "DIET_PATTERN":       section("DIET_PATTERN"),
        "FOOD_ENVIRONMENT":   section("FOOD_ENVIRONMENT"),
        "HYDRATION_MOVEMENT": section("HYDRATION_MOVEMENT"),
        "DIGESTIVE":          section("DIGESTIVE"),
        "REPRODUCTIVE":       section("REPRODUCTIVE"),
        "PREVIOUS_ATTEMPTS":  section("PREVIOUS_ATTEMPTS"),
        "FOOD_LOG":           section("FOOD_LOG"),

        "RHT": rht_state(conn, client_id, payload),

        # What Engine 6 could not see. Engine 5 turns the high-priority set
        # into follow-up questions; nothing here blocked the case.
        "HIGH_PRIORITY_MISSING_DATA": [
            {"field": f, "severity": s, "why": w}
            for f, s, w in gaps if s in HIGH_PRIORITY
        ],
        "ALL_MISSING_DATA_COUNT": len(gaps),
        "MISSING_DATA_POLICY": ("Absent fields are UNKNOWN. No absent value has been "
                                "defaulted to a normal one."),
    }


def mark_converted(conn, submission_id: str, case_version_id: str) -> None:
    conn.execute(
        """update intake_submissions
              set status='CONVERTED', converted_at=now(), case_version_id=%s
            where submission_id=%s""", (case_version_id, submission_id))


if __name__ == "__main__":
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is not set. See docs/LOCAL_DEV.md.")
    conn = psycopg.connect(dsn, autocommit=True)
    cat = load_catalog(conn)
    print(f"Core Intake V1: {len(cat)} askable fields across "
          f"{len({f['section'] for f in cat})} sections")
    excluded = conn.execute(
        "select field_key from intake_field_catalog where rht_owned order by 1").fetchall()
    print(f"deliberately NOT asked (RHT owns): {', '.join(r[0] for r in excluded)}")

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
# Value validation
# ---------------------------------------------------------------------
#
# 009 proved COMPLETENESS -- which applicable fields have no answer. It
# said nothing about whether a supplied answer was USABLE, and the two
# failures that produced are opposite and both bad:
#
#   height_cm: "about 170"      extract() died on a numeric column,
#                               hundreds of lines from where intake
#                               accepted it
#   rht_status: "probably fine" flowed into the Engine 6 payload as
#                               RHT_STATUS "PROBABLY FINE"
#
# The first is a crash a long way from its cause. The second is worse: a
# safety-bearing field silently accepting a value that means nothing, in
# the one place D22 insists NOT_ASSESSED must mean unknown.
#
# What this is NOT is a schema for intake answers. D22 keeps the field
# registry as data and calls V1 explicitly unfinished; a rigid
# validate-everything layer would freeze both and would be the "giant
# rigid schema" D22 rejects. Only the shapes that BEAR SAFETY OR DATA
# INTEGRITY are checked -- the ones step 15 has to write into typed
# columns, and the ones an engine would read as clinical fact.
#
# Three outcomes, and never a fourth:
#
#   missing              -> a GAP, exactly as before. Not an issue.
#   valid                -> accepted unchanged.
#   supplied but         -> an ISSUE, and the value is treated as unknown
#   malformed               or dropped. Never silently accepted, and never
#                           carried far enough to crash extraction.

# What a bad value did about itself. Recorded so "we ignored this" is a
# fact in the record rather than an inference from its absence.
TREATED_AS_UNKNOWN = "TREATED_AS_UNKNOWN"   # the field now reads as unknown
DROPPED = "DROPPED"                          # the item is not carried forward

# Numeric intake fields, with the range outside which a number is more
# likely a typo or a unit confusion than a measurement. Wide on purpose:
# this catches "170" entered in the weight box, not an unusual client.
# Anything outside is an issue, never a silent clamp.
NUMERIC_RANGES = {
    "height_cm": (50.0, 260.0),
    "weight_kg": (2.0, 400.0),
    "waist_cm": (20.0, 250.0),
}


def _issue(path: str, section: str | None, value: Any, problem: str,
           action: str) -> dict:
    return {
        "field_path": path,
        "section": section,
        # repr, and truncated. The raw payload keeps the real thing; this
        # is a legible summary and must not become a second copy of a
        # 200-line food log.
        "supplied": repr(value)[:200],
        "problem": problem,
        "action": action,
    }


def as_number(value: Any) -> float | None:
    """A number, or None if this cannot be read as one without guessing.

    Deliberately refuses "about 170" and "170cm". Stripping the unit and
    taking the digits is exactly the kind of helpfulness that turns an
    ambiguous answer into a confident wrong one.
    """
    if isinstance(value, bool):        # bool is an int in Python; not a measurement
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def as_date(value: Any) -> str | None:
    """An ISO date string, or None. Never a guess.

    ISO only, and that is a decision rather than laziness: "03/04/2026" is
    a different day in Mumbai and in New York, and intake has no way to
    know which was meant. An ambiguous date is treated as unknown.
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        try:
            import datetime
            datetime.date.fromisoformat(text)
            return text
        except (ValueError, TypeError):
            return None
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10]
    return None


def allowed_rht_statuses(conn) -> set[str]:
    """The assessment_status vocabulary, read from the database (011).

    Not a list in this file. assessment_status already says what an
    assessment can be, and a second copy here would drift from it.
    """
    return {r[0] for r in conn.execute(
        "select status_value from v_assessment_status_values").fetchall()}


def check_values(conn, payload: dict) -> list[dict]:
    """Issues with the values that WERE supplied. Never raises, never rejects.

    Pure: nothing here writes, and nothing here decides whether a case may
    proceed. sanitize() applies the same rules to produce a payload that
    extraction can survive; this one explains what happened.
    """
    issues: list[dict] = []
    sections = payload.get("sections") or {}

    if not isinstance(sections, dict):
        return [_issue("sections", None, sections,
                       "sections must be an object keyed by section name",
                       TREATED_AS_UNKNOWN)]

    known = {r[0] for r in conn.execute(
        "select distinct section::text from intake_field_catalog").fetchall()}

    for name, body in sections.items():
        if name not in known:
            # Not dropped: an unrecognised section is stored as submitted
            # and flagged. V2 adds sections by INSERT (D22), so today's
            # unknown key is quite possibly tomorrow's field -- discarding
            # it would throw away the evidence for adding it.
            issues.append(_issue(f"sections.{name}", name, list(body)
                                 if isinstance(body, dict) else body,
                                 "not a known intake section; stored but not extracted",
                                 DROPPED))
            continue
        if not isinstance(body, dict):
            issues.append(_issue(f"sections.{name}", name, body,
                                 "section body must be an object", TREATED_AS_UNKNOWN))

    basic = sections.get("BASIC_PROFILE")
    if isinstance(basic, dict):
        for key, (low, high) in NUMERIC_RANGES.items():
            if key not in basic or basic[key] is None:
                continue                      # missing is a gap, not an issue
            number = as_number(basic[key])
            if number is None:
                issues.append(_issue(f"BASIC_PROFILE.{key}", "BASIC_PROFILE", basic[key],
                                     "not a number", TREATED_AS_UNKNOWN))
            elif not low <= number <= high:
                issues.append(_issue(f"BASIC_PROFILE.{key}", "BASIC_PROFILE", basic[key],
                                     f"outside the plausible range {low}-{high}",
                                     TREATED_AS_UNKNOWN))

    # measured_on sits at the TOP level, not inside BASIC_PROFILE -- that is
    # where extract() reads it from, and validating the wrong key would be
    # a check that always passes.
    if payload.get("measured_on") is not None \
            and as_date(payload["measured_on"]) is None:
        issues.append(_issue("measured_on", None, payload["measured_on"],
                             "not an ISO date (YYYY-MM-DD); measurements will be "
                             "dated on the day they were entered",
                             TREATED_AS_UNKNOWN))

    labs = sections.get("LABS_REPORTS")
    if isinstance(labs, dict):
        panel_date = labs.get("lab_dates")
        if panel_date is not None and as_date(panel_date) is None:
            issues.append(_issue("LABS_REPORTS.lab_dates", "LABS_REPORTS", panel_date,
                                 "not an ISO date (YYYY-MM-DD); values relying on "
                                 "the panel date cannot be placed in a trend",
                                 TREATED_AS_UNKNOWN))
            panel_date = None
        for index, lab in enumerate(labs.get("lab_values") or []):
            path = f"LABS_REPORTS.lab_values[{index}]"
            if not isinstance(lab, dict):
                issues.append(_issue(path, "LABS_REPORTS", lab,
                                     "a lab value must be an object with a marker",
                                     DROPPED))
                continue
            if not str(lab.get("marker") or "").strip():
                issues.append(_issue(f"{path}.marker", "LABS_REPORTS", lab.get("marker"),
                                     "a lab value without a marker names nothing",
                                     DROPPED))
                continue
            # A lab with no usable value is not a lab result. Recording the
            # marker with a NULL value would read as "measured, and blank".
            if lab.get("value") is not None and as_number(lab["value"]) is None:
                issues.append(_issue(f"{path}.value", "LABS_REPORTS", lab["value"],
                                     "not a number", DROPPED))
                continue
            for bound in ("ref_low", "ref_high"):
                if lab.get(bound) is not None and as_number(lab[bound]) is None:
                    issues.append(_issue(f"{path}.{bound}", "LABS_REPORTS", lab[bound],
                                         "not a number", TREATED_AS_UNKNOWN))
            supplied_date = lab.get("date") if lab.get("date") is not None else panel_date
            if supplied_date is None:
                # measured_on is NOT NULL, and a lab value whose date is
                # unknown cannot join a trend. Dropped rather than dated
                # today: a wrong date is worse than a missing result.
                issues.append(_issue(f"{path}.date", "LABS_REPORTS", None,
                                     "no date on the value or the panel; "
                                     "an undated result cannot be placed in a trend",
                                     DROPPED))
            elif as_date(supplied_date) is None:
                issues.append(_issue(f"{path}.date", "LABS_REPORTS", supplied_date,
                                     "not an ISO date (YYYY-MM-DD)", DROPPED))

        for index, report in enumerate(labs.get("lab_reports") or []):
            path = f"LABS_REPORTS.lab_reports[{index}]"
            if not isinstance(report, dict):
                issues.append(_issue(path, "LABS_REPORTS", report,
                                     "a lab report must be an object", DROPPED))
                continue
            if report.get("date") is not None and as_date(report["date"]) is None:
                issues.append(_issue(f"{path}.date", "LABS_REPORTS", report["date"],
                                     "not an ISO date (YYYY-MM-DD)", TREATED_AS_UNKNOWN))

    meds = sections.get("MEDICATIONS")
    if isinstance(meds, dict):
        for key, noun in (("medications", "medication"), ("supplements", "supplement")):
            for index, item in enumerate(meds.get(key) or []):
                path = f"MEDICATIONS.{key}[{index}]"
                if isinstance(item, str):
                    if not item.strip():
                        issues.append(_issue(path, "MEDICATIONS", item,
                                             f"an empty {noun} name", DROPPED))
                    continue
                if not isinstance(item, dict):
                    issues.append(_issue(path, "MEDICATIONS", item,
                                         f"a {noun} must be a name or an object "
                                         "with one", DROPPED))
                    continue
                if not str(item.get("name") or "").strip():
                    # name is NOT NULL, and a dose with no drug is not a
                    # medication record -- it is a question for the
                    # practitioner.
                    issues.append(_issue(f"{path}.name", "MEDICATIONS", item,
                                         f"a {noun} entry with no name", DROPPED))

    for section, key, noun in (("DIAGNOSES_HISTORY", "known_diagnoses", "diagnosis"),
                               ("SYMPTOMS", "current_symptoms", "symptom")):
        body = sections.get(section)
        if not isinstance(body, dict):
            continue
        for index, item in enumerate(body.get(key) or []):
            path = f"{section}.{key}[{index}]"
            name_key = "condition" if noun == "diagnosis" else "symptom"
            if isinstance(item, str):
                if not item.strip():
                    issues.append(_issue(path, section, item,
                                         f"an empty {noun}", DROPPED))
                continue
            if not isinstance(item, dict):
                issues.append(_issue(path, section, item,
                                     f"a {noun} must be a name or an object with one",
                                     DROPPED))
                continue
            if not str(item.get(name_key) or "").strip():
                issues.append(_issue(f"{path}.{name_key}", section, item,
                                     f"a {noun} entry with no name", DROPPED))
                continue
            severity = item.get("severity")
            if severity is not None:
                number = as_number(severity)
                if number is None or not 0 <= number <= 10:
                    issues.append(_issue(f"{path}.severity", section, severity,
                                         "severity must be a number from 0 to 10",
                                         TREATED_AS_UNKNOWN))

    food = sections.get("FOOD_LOG")
    if isinstance(food, dict):
        for index, day in enumerate(food.get("food_log_days") or []):
            path = f"FOOD_LOG.food_log_days[{index}]"
            if not isinstance(day, dict):
                # A bare string is a plausible mistake -- someone types the
                # day's food straight into the array. It is still dropped:
                # client_food_logs.logged_on is NOT NULL and there is no
                # honest date to give it. Dating it today would put food
                # eaten last month into this week's pattern, and the raw
                # text survives in raw_payload either way.
                issues.append(_issue(path, "FOOD_LOG", day,
                                     "a food log day must be an object with a date "
                                     "and raw_text; no date means it cannot be "
                                     "placed in a week", DROPPED))
                continue
            if as_date(day.get("date")) is None:
                issues.append(_issue(f"{path}.date", "FOOD_LOG", day.get("date"),
                                     "no usable ISO date; an undated day cannot be "
                                     "placed in a week", DROPPED))

    rht = sections.get("RHT_LINKAGE")
    if isinstance(rht, dict) and rht.get("rht_status") is not None:
        declared = str(rht["rht_status"]).strip().upper()
        allowed = allowed_rht_statuses(conn)
        if declared not in allowed:
            # The one that matters most. An unrecognised RHT status must
            # never reach an engine: D22 and hard rule "NOT_ASSESSED means
            # unknown, not normal" both depend on this field meaning
            # exactly one of a known set.
            issues.append(_issue("RHT_LINKAGE.rht_status", "RHT_LINKAGE",
                                 rht["rht_status"],
                                 "not a recognised assessment status "
                                 f"({', '.join(sorted(allowed))}); "
                                 "treated as NOT_ASSESSED",
                                 TREATED_AS_UNKNOWN))

    return issues


def sanitize(conn, payload: dict) -> dict:
    """The payload with unusable values removed, for extraction to work on.

    Applies the same rules check_values() reports, so the two cannot say
    different things about the same answer. Returns a NEW payload; the
    stored raw_payload is never touched, because it is the provenance
    record of what was actually submitted.

    Nothing here invents a value. Removing is allowed, defaulting is not:
    a dropped lab result is honestly absent, whereas a lab result dated
    today because its own date was unreadable is a false fact that will
    outlive everyone who remembers why.
    """
    import copy
    clean = copy.deepcopy(payload)
    if clean.get("measured_on") is not None:
        # Dropped rather than kept as text: extract() coalesces a missing
        # date to today, which is honest, while passing "last Tuesday" to a
        # date column is a crash.
        clean["measured_on"] = as_date(clean["measured_on"])

    sections = clean.get("sections")
    if not isinstance(sections, dict):
        clean["sections"] = {}
        return clean

    for name, body in list(sections.items()):
        if not isinstance(body, dict):
            sections.pop(name)

    basic = sections.get("BASIC_PROFILE")
    if isinstance(basic, dict):
        for key, (low, high) in NUMERIC_RANGES.items():
            if key not in basic or basic[key] is None:
                continue
            number = as_number(basic[key])
            if number is None or not low <= number <= high:
                basic.pop(key)
            else:
                basic[key] = number

    labs = sections.get("LABS_REPORTS")
    if isinstance(labs, dict):
        panel_date = as_date(labs.get("lab_dates"))
        kept = []
        for lab in labs.get("lab_values") or []:
            if not isinstance(lab, dict):
                continue
            if not str(lab.get("marker") or "").strip():
                continue
            value = lab.get("value")
            if value is not None:
                number = as_number(value)
                if number is None:
                    continue
                lab["value"] = number
            # A date that was SUPPLIED and cannot be read is not the same
            # as no date at all. Falling back to the panel date here would
            # silently place "14/08/2026" on the panel's day, which might
            # be right and might be four months out -- and check_values()
            # has already reported it as dropped, so keeping it would make
            # the two disagree about the same value.
            if lab.get("date") is not None:
                when = as_date(lab["date"])
            else:
                when = panel_date
            if when is None:
                continue
            lab["date"] = when
            for bound in ("ref_low", "ref_high"):
                if lab.get(bound) is not None:
                    lab[bound] = as_number(lab[bound])
            kept.append(lab)
        labs["lab_values"] = kept
        labs["lab_reports"] = [
            {**r, "date": as_date(r.get("date"))}
            for r in (labs.get("lab_reports") or []) if isinstance(r, dict)]

    meds = sections.get("MEDICATIONS")
    if isinstance(meds, dict):
        for key in ("medications", "supplements"):
            meds[key] = [
                item for item in (meds.get(key) or [])
                if (isinstance(item, str) and item.strip())
                or (isinstance(item, dict) and str(item.get("name") or "").strip())
            ]

    for section, key, name_key in (("DIAGNOSES_HISTORY", "known_diagnoses", "condition"),
                                   ("SYMPTOMS", "current_symptoms", "symptom")):
        body = sections.get(section)
        if not isinstance(body, dict):
            continue
        kept = []
        for item in body.get(key) or []:
            if isinstance(item, str):
                if item.strip():
                    kept.append(item)
                continue
            if not isinstance(item, dict) or not str(item.get(name_key) or "").strip():
                continue
            severity = item.get("severity")
            if severity is not None:
                number = as_number(severity)
                item["severity"] = int(number) if number is not None and 0 <= number <= 10 \
                    else None
            kept.append(item)
        body[key] = kept

    food = sections.get("FOOD_LOG")
    if isinstance(food, dict):
        kept = []
        for day in food.get("food_log_days") or []:
            if isinstance(day, str):
                # Kept as text with no date. It cannot be placed in a week,
                # and it is still the only record of what someone ate.
                continue
            if not isinstance(day, dict):
                continue
            when = as_date(day.get("date"))
            if when is None:
                continue
            day["date"] = when
            kept.append(day)
        food["food_log_days"] = kept

    rht = sections.get("RHT_LINKAGE")
    if isinstance(rht, dict) and rht.get("rht_status") is not None:
        declared = str(rht["rht_status"]).strip().upper()
        rht["rht_status"] = declared if declared in allowed_rht_statuses(conn) \
            else "NOT_ASSESSED"

    return clean


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

    # raw_payload is stored EXACTLY as submitted, malformed values and all.
    # It is the provenance record of what arrived; sanitize() cleans on the
    # way out, at extraction, so the original answer stays recoverable and
    # stays comparable against what was made of it.
    issues = check_values(conn, payload)

    submission_id = conn.execute(
        """insert into intake_submissions
             (client_id, status, captured_by, capture_method, raw_payload,
              validation_issues, submitted_at)
           values (%s,'SUBMITTED',%s,%s,%s,%s, now())
           returning submission_id""",
        (client_id, captured_by, capture_method, json.dumps(payload),
         json.dumps(issues)),
    ).fetchone()[0]

    # intake_sections.section is an ENUM, so an unrecognised key is not a
    # row that can exist -- inserting one raises InvalidTextRepresentation
    # and takes the whole submission down with it, which is intake blocking
    # a case over a typo. The key stays in raw_payload, where a V2 field
    # discussion can find it (D22 adds sections by INSERT, so today's
    # unknown key may be tomorrow's section), and check_values() has
    # already recorded it as an issue.
    known_sections = {r[0] for r in conn.execute(
        "select distinct section::text from intake_field_catalog").fetchall()}

    for section, body in (payload.get("sections") or {}).items():
        if section not in known_sections or not isinstance(body, dict):
            continue
        na = bool(body.get("_not_applicable"))
        conn.execute(
            """insert into intake_sections
                 (submission_id, client_id, section, payload, not_applicable, na_reason)
               values (%s,%s,%s,%s,%s,%s)""",
            (submission_id, client_id, section,
             json.dumps({k: v for k, v in body.items() if not k.startswith("_")}),
             na, body.get("_na_reason") if na else None))

    # Gaps are computed against the SANITIZED payload, so a field whose only
    # answer was unusable reads as unknown rather than as answered. That is
    # the whole point: "height_cm: about 170" must produce a follow-up
    # question, not a silently absent measurement.
    record_gaps(conn, client_id, str(submission_id),
                validate(conn, sanitize(conn, payload)))
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
    client_id = row[0]
    # SANITIZED, not raw. Every insert below writes into a typed column --
    # numeric, date, NOT NULL -- and a malformed answer reaching one of them
    # is a psycopg exception hundreds of lines from where intake accepted
    # it. What was wrong is already recorded in validation_issues; this is
    # where it stops being dangerous.
    payload = sanitize(conn, row[1])
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
    status = (str(declared).strip().upper() if declared is not None else "NOT_ASSESSED")

    # An unrecognised status is NOT_ASSESSED, and says so out loud.
    #
    # This used to pass anything through: "probably fine" arrived at Engine
    # 6 as RHT_STATUS "PROBABLY FINE". A field whose entire job is to say
    # whether these signals are known cannot carry a value that is neither
    # known nor unknown, and defaulting it to NOT_ASSESSED without a note
    # would hide that someone answered the question badly.
    allowed = allowed_rht_statuses(conn)
    unrecognised = None
    if status not in allowed:
        unrecognised = declared
        status = "NOT_ASSESSED"

    block: dict[str, Any] = {
        "RHT_STATUS": status,
        "MEANING": ("Real Health Test signals are UNKNOWN. Absence of an assessment "
                    "is not evidence that these areas are normal."),
        "OWNED_BY_RHT_NOT_COLLECTED_HERE": [
            r[0] for r in conn.execute(
                "select field_key from intake_field_catalog where rht_owned order by field_key"
            ).fetchall()],
    }

    if unrecognised is not None:
        block["DISCREPANCY"] = (
            f"Intake declared RHT status {unrecognised!r}, which is not a "
            "recognised assessment status. Treated as NOT_ASSESSED: an "
            "unrecognised status is not evidence of anything.")

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
        """select client_id, raw_payload, status::text, validation_issues
             from intake_submissions where submission_id=%s""", (submission_id,)).fetchone()
    client_id, raw, status, issues = row
    # The engine sees the SANITIZED payload. An answer nobody could read is
    # not a clinical fact, and handing "height_cm: about 170" to Engine 6
    # invites it to reason about a number that was never measured. What was
    # supplied is preserved in raw_payload and summarised below, so the
    # engine knows the question was answered badly rather than not at all.
    payload = sanitize(conn, raw)
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

        # Answers that arrived and could not be used. Distinct from missing
        # data on purpose: "not asked" and "answered unusably" are different
        # facts about the client and about the intake process, and only the
        # second one says the question needs asking differently.
        "UNUSABLE_ANSWERS": [
            {"field": i["field_path"], "problem": i["problem"], "action": i["action"]}
            for i in (issues or [])
        ],
        "UNUSABLE_ANSWER_POLICY": ("A supplied answer that could not be read was "
                                   "treated as unknown or dropped. None was guessed "
                                   "at, corrected, or accepted as given."),
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

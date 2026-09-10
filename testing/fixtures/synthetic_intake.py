#!/usr/bin/env python3
"""Synthetic Core Intake V1 submissions. NOT REAL PHI.

Three fixtures, because three different things need proving:

  COMPLETE_INTAKE     a well-filled submission from a client the system was
                      designed around
  SPARSE_INTAKE       the realistic bad case: half the questions unanswered.
                      It must still produce a runnable Engine 6 v1.
  MALE_INTAKE         a male client, to prove the REPRODUCTIVE section is
                      genuinely skipped rather than reported as a gap

The clinical picture matches testing/fixtures/synthetic_client.py so the
two can be compared: the same vegetarian Gujarati metabolic-cluster case,
arriving through intake instead of being hand-constructed.
"""

from __future__ import annotations

EXTERNAL_REF_COMPLETE = "SYN-INTAKE-001"
EXTERNAL_REF_SPARSE = "SYN-INTAKE-002"
EXTERNAL_REF_MALE = "SYN-INTAKE-003"

DISPLAY_NAME_COMPLETE = "SYNTHETIC — intake, complete (not a real client)"
DISPLAY_NAME_SPARSE = "SYNTHETIC — intake, sparse (not a real client)"
DISPLAY_NAME_MALE = "SYNTHETIC — intake, male (not a real client)"


COMPLETE_INTAKE = {
    "measured_on": "2026-08-14",
    "sections": {
        "BASIC_PROFILE": {
            "year_of_birth": 1984,
            "biological_sex": "F",
            "height_cm": 157.0,
            "weight_kg": 74.6,
            "waist_cm": 97.0,
            "body_composition": {"body_fat_pct": 41.2, "device": "home bioimpedance scale"},
            "occupation": "School administrator, desk-based",
            "daily_structure": "Up 06:15, cooks before leaving, 35-min commute each way, "
                               "home 18:30, cooks again, family dinner 21:45",
            "region": "Gujarat, India",
        },
        "GOALS": {
            "consultation_reason": "Fatty liver went from grade 1 to grade 2 and I was told to fix it",
            "health_goals": ["Stop the fatty liver getting worse",
                             "Not become diabetic like my father",
                             "Energy through the afternoon"],
            "priority_concerns": "Afternoon crashes and the liver report",
            "desired_outcomes": "Normal reports and not feeling tired by 4pm",
        },
        "DIAGNOSES_HISTORY": {
            "known_diagnoses": ["PCOS", "MASLD (grade 2 hepatic steatosis)", "Prediabetes",
                                "Atherogenic dyslipidaemia", "Subclinical hypothyroidism",
                                "Stage 1 hypertension"],
            "medical_history": ["Gestational diabetes 2016, resolved postpartum",
                                "Gallstones on ultrasound 2022, asymptomatic"],
            "prior_events": ["Two pregnancies", "No surgeries"],
            "family_history": ["Father: type 2 diabetes from 49, now on insulin",
                               "Mother: hypothyroidism", "Sister: PCOS"],
        },
        "MEDICATIONS": {
            "medications": [
                {"name": "Metformin", "dose": "500 mg", "timing": "twice daily with food",
                 "reason": "Prediabetes"},
                {"name": "Atorvastatin", "dose": "10 mg", "timing": "at night",
                 "reason": "Dyslipidaemia"},
                {"name": "Telmisartan", "dose": "40 mg", "timing": "morning",
                 "reason": "Blood pressure"},
                {"name": "Levothyroxine", "dose": "25 mcg", "timing": "fasting 06:30",
                 "reason": "Thyroid"},
            ],
            "supplements": [
                {"name": "Multivitamin (retail)", "dose": "1 tablet",
                 "timing": "with breakfast, about three days a week"},
                {"name": "Calcium with vitamin D3", "dose": "1 tablet", "timing": "at night"},
            ],
            "medication_reasons": "All prescribed by endocrinologist except telmisartan (GP)",
        },
        "LABS_REPORTS": {
            "lab_dates": "2026-08-14",
            "lab_reports": [
                {"ref": "panel-aug", "kind": "LAB_PANEL", "date": "2026-08-14",
                 "laboratory": "SYNTHETIC Diagnostics", "filename": "panel_2026_08.pdf",
                 "storage_ref": "case-files/SYN-INTAKE-001/panel_2026_08.pdf",
                 "transcribed": True},
                {"ref": "usg-jul", "kind": "IMAGING", "date": "2026-07-30",
                 "laboratory": "SYNTHETIC Imaging", "filename": "abdo_usg.pdf",
                 "storage_ref": "case-files/SYN-INTAKE-001/abdo_usg.pdf",
                 "note": "Grade 2 hepatic steatosis; gallstones unchanged"},
            ],
            "lab_values": [
                {"marker": "HbA1c", "value": 6.1, "unit": "%", "ref_low": 4.0, "ref_high": 5.6,
                 "date": "2026-08-14", "report_ref": "panel-aug"},
                {"marker": "Fasting glucose", "value": 108, "unit": "mg/dL",
                 "ref_low": 70, "ref_high": 99, "date": "2026-08-14", "report_ref": "panel-aug"},
                {"marker": "Triglycerides", "value": 218, "unit": "mg/dL",
                 "ref_low": 0, "ref_high": 150, "date": "2026-08-14", "report_ref": "panel-aug"},
                {"marker": "HDL cholesterol", "value": 37, "unit": "mg/dL",
                 "ref_low": 50, "ref_high": 90, "date": "2026-08-14", "report_ref": "panel-aug"},
                {"marker": "ALT", "value": 58, "unit": "U/L", "ref_low": 0, "ref_high": 33,
                 "date": "2026-08-14", "report_ref": "panel-aug"},
                {"marker": "TSH", "value": 4.6, "unit": "uIU/mL", "ref_low": 0.4, "ref_high": 4.0,
                 "date": "2026-08-14", "report_ref": "panel-aug"},
                {"marker": "Vitamin B12", "value": 168, "unit": "pg/mL",
                 "ref_low": 200, "ref_high": 900, "date": "2026-08-14", "report_ref": "panel-aug"},
                {"marker": "Vitamin D (25-OH)", "value": 14, "unit": "ng/mL",
                 "ref_low": 30, "ref_high": 100, "date": "2026-08-14", "report_ref": "panel-aug"},
                {"marker": "Serum ferritin", "value": 16, "unit": "ng/mL",
                 "ref_low": 30, "ref_high": 200, "date": "2026-08-14", "report_ref": "panel-aug"},
            ],
        },
        "SYMPTOMS": {
            "current_symptoms": [
                {"symptom": "Afternoon energy crash between 15:00 and 17:00", "severity": 4},
                {"symptom": "Post-meal sleepiness, worst after lunch", "severity": 4},
                {"symptom": "Sugar craving after dinner", "severity": 3},
                {"symptom": "Irregular cycles, 45 to 70 days", "severity": 3},
                {"symptom": "Hair thinning at the crown", "severity": 3},
                {"symptom": "Bloating after the evening meal", "severity": 2},
            ],
            "symptom_severity": "Afternoon crash affects work most",
        },
        "DIET_PATTERN": {
            "diet_pattern": "Lacto-vegetarian since birth",
            "restrictions": ["No eggs", "No meat", "No fish"],
            "allergies": ["None known"],
            "intolerances": ["Possibly heavy dairy in the evening"],
            "dislikes": ["Bitter gourd", "Soya chunks"],
            "cultural_constraints": "No onion or garlic on Ekadashi and during Shravan; "
                                    "household fasting days observed",
        },
        "FOOD_ENVIRONMENT": {
            "who_cooks": "I cook, but my mother-in-law decides the menu",
            "cooking_facilities": "Pressure cooker, gas hob, no oven, no blender",
            "eating_out": "Rarely, maybe twice a month",
            "meal_timing": {"breakfast": "08:15", "lunch": "13:30", "dinner": "21:45"},
            "prep_time": "Under 20 minutes for my own food on a weekday",
            "food_budget": "Moderate; will not buy imported or specialty items",
            "travel_constraints": "None regular",
        },
        "HYDRATION_MOVEMENT": {
            "hydration": "About 1.3 litres of water, 4 cups of tea with sugar",
            "activity_basic": "About 3,200 steps a day, no structured exercise",
            "movement_limitations": "Knees ache on stairs",
        },
        "DIGESTIVE": {
            "bowel_pattern": "Every other day, often hard",
            "gi_symptoms": ["Bloating after dinner", "Occasional reflux when eating late"],
        },
        "REPRODUCTIVE": {
            "cycle_context": "Cycles 45 to 70 days",
            "cycle_irregularity": "Irregular since my twenties",
            "menopause_status": "Not menopausal",
            "reproductive_dx": "PCOS diagnosed 2009",
        },
        "PREVIOUS_ATTEMPTS": {
            "previous_attempts": ["Low-carb plan in 2021", "Meal-replacement programme 2023"],
            "what_worked": "Walking 30 minutes daily in 2022 — I kept it up for five months",
            "what_failed": "Both diets stopped at week 3. Cooking separately from the family "
                           "felt like rejecting them",
        },
        "FOOD_LOG": {
            "food_log_days": [
                {"date": "2026-08-11", "day_type": "working weekday",
                 "raw_text": "06:30 masala chai 2 tsp sugar, 2 biscuits. 08:15 two methi thepla "
                             "with pickle and curd. 11:00 chai, 2 khakhra. 13:30 tiffin: 3 rotli, "
                             "bottle-gourd sabzi, dal, rice, buttermilk. 16:30 chai and two "
                             "handfuls chevdo. 19:00 a few spoons while cooking. 21:45 khichdi "
                             "with ghee, kadhi, papad, aloo sabzi, 1 rotli. 22:30 two pieces mithai"},
                {"date": "2026-08-12", "day_type": "working weekday",
                 "raw_text": "06:30 chai 2 tsp sugar. 08:20 poha with peanuts. 11:45 chai. "
                             "13:45 tiffin: 3 rotli, tindora sabzi, dal, rice, buttermilk. "
                             "16:00 very hungry, 4 khakhra with chundo, chai. 19:15 grazing while "
                             "cooking, cannot say how much. 21:30 bhakhri, ringan-bateta, dal, "
                             "rice, curd. 22:15 small bowl shrikhand"},
                {"date": "2026-08-17", "day_type": "Sunday, family lunch",
                 "raw_text": "07:00 chai. 09:30 three fafda with two jalebi, Sunday habit. "
                             "13:00 family lunch: 4 puri, batata nu shaak, dal, rice, kadhi, "
                             "boondi raita, two pieces basundi. 16:30 chai and leftover fafda. "
                             "20:00 light: 2 rotli, sabzi, curd"},
            ],
        },
        "RHT_LINKAGE": {"rht_status": "NOT_ASSESSED"},
    },
}


# The realistic bad case. A client who filled in what they could and left
# the rest. Missing: labs entirely, food log, food environment, diet detail,
# previous attempts, most of the profile. It must still produce a case.
SPARSE_INTAKE = {
    "sections": {
        "BASIC_PROFILE": {
            "year_of_birth": 1979,
            "biological_sex": "F",
            "weight_kg": 81.0,
            # height, waist, occupation, daily structure, region all absent
        },
        "GOALS": {
            "consultation_reason": "Tired all the time and my sugar is borderline",
            # health_goals absent
        },
        "DIAGNOSES_HISTORY": {
            "known_diagnoses": ["Prediabetes"],
        },
        "MEDICATIONS": {
            # A real and common case: the client knows what they take and
            # not the dose. UNKNOWN must survive as UNKNOWN.
            "medications": [{"name": "Metformin"}],
        },
        "SYMPTOMS": {
            "current_symptoms": ["Tiredness", "Waking at night"],
        },
        "RHT_LINKAGE": {"rht_status": "NOT_ASSESSED"},
    },
}


# A male client. REPRODUCTIVE must be skipped, not reported as five gaps.
MALE_INTAKE = {
    "sections": {
        "BASIC_PROFILE": {
            "year_of_birth": 1975,
            "biological_sex": "M",
            "height_cm": 172.0,
            "weight_kg": 88.0,
            "waist_cm": 104.0,
            "occupation": "Long-distance driver",
            "daily_structure": "Irregular shifts, eats on the road",
            "region": "Gujarat, India",
        },
        "GOALS": {
            "consultation_reason": "Blood pressure and weight",
            "health_goals": ["Lose weight", "Come off one BP tablet if possible"],
        },
        "DIAGNOSES_HISTORY": {"known_diagnoses": ["Hypertension", "Prediabetes"]},
        "MEDICATIONS": {"medications": [{"name": "Amlodipine", "dose": "5 mg",
                                         "timing": "morning", "reason": "Blood pressure"}]},
        "SYMPTOMS": {"current_symptoms": ["Breathlessness on stairs"]},
        "DIET_PATTERN": {"diet_pattern": "Non-vegetarian", "restrictions": [],
                         "allergies": ["None known"]},
        "REPRODUCTIVE": {"_not_applicable": True, "_na_reason": "Male client"},
        "RHT_LINKAGE": {"rht_status": "NOT_ASSESSED"},
    },
}


FIXTURES = {
    EXTERNAL_REF_COMPLETE: (DISPLAY_NAME_COMPLETE, COMPLETE_INTAKE),
    EXTERNAL_REF_SPARSE: (DISPLAY_NAME_SPARSE, SPARSE_INTAKE),
    EXTERNAL_REF_MALE: (DISPLAY_NAME_MALE, MALE_INTAKE),
}


def clear(conn) -> None:
    conn.execute("delete from clients where external_ref like 'SYN-INTAKE-%'")


def load_client(conn, external_ref: str) -> str:
    display_name, payload = FIXTURES[external_ref]
    basic = payload["sections"].get("BASIC_PROFILE", {})
    return str(conn.execute(
        """insert into clients (external_ref, display_name, year_of_birth, sex,
                                country, region, status)
           values (%s,%s,%s,%s,'India',%s,'INTAKE') returning client_id""",
        (external_ref, display_name, basic.get("year_of_birth"),
         basic.get("biological_sex"), basic.get("region"))).fetchone()[0])


if __name__ == "__main__":
    import json
    for ref, (name, payload) in FIXTURES.items():
        sections = payload["sections"]
        print(f"{ref}: {len(sections)} sections, {len(json.dumps(payload)):,} chars")

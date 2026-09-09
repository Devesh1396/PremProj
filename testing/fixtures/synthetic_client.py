#!/usr/bin/env python3
"""A synthetic client rich enough to exercise all 19 parts of Engine 1.

NOT A REAL PERSON. Every value here was written for this file. The record
is deliberately marked SYNTHETIC in `clients.display_name` and carries the
external_ref prefix `SYN-E1-`, so it can never be mistaken for, or
accumulate alongside, a real case. Real client information must never be
placed in a development database: see docs/LOCAL_DEV.md.

The case is a vegetarian Gujarati woman with the metabolic cluster the
system was designed around -- PCOS, MASLD, prediabetes, atherogenic
dyslipidaemia -- because that is the case where a diagnosis-folder library
returns one strategy and a concept-based one returns several
(testing/test_knowledge_layer.py asserts exactly that gap).

Three things it is built to do:

1. **Supply input for every one of the 19 output parts of Engine 1 section
   62.** PART_INPUTS below maps each part to the intake keys it reads.
   A part with no input is a part the engine has to invent, and inventing
   is the failure mode section 61 warns about.

2. **Pass the safety gate clean.** Metformin, a statin, an ACE-family
   antihypertensive and levothyroxine together are the ordinary medicated
   metabolic client D6 requires NOT to trigger a HOLD. A gate that fires
   here is a rubber stamp.

3. **Carry no identity into an engine payload.** `intake_payload()` is
   built from clinical facts and client_id only, never the display name,
   per STRIP_IDENTITY_FROM_ENGINE_PAYLOADS and the data-residency section
   of docs/OPERATIONS.md. `check_no_identity()` asserts it.
"""

from __future__ import annotations

import json
from datetime import date

EXTERNAL_REF = "SYN-E1-001"
DISPLAY_NAME = "SYNTHETIC — vegetarian Gujarati metabolic cluster (not a real client)"

# Identity strings that must never appear in an engine payload. Used by
# check_no_identity() so the rule is asserted rather than merely intended.
IDENTIFIERS = [DISPLAY_NAME, "Ahmedabad"]

BASELINE = date(2026, 8, 14)


# ---------------------------------------------------------------------
# The case
# ---------------------------------------------------------------------

DEMOGRAPHICS = {
    "year_of_birth": 1984,
    "sex": "F",
    "country": "India",
    "region": "Gujarat",
    "locality": "Ahmedabad",
    "primary_language": "Gujarati",
}

# PART 1 -- identity, context, goals, history
CONTEXT = {
    "AGE_YEARS": 42,
    "SEX": "F",
    "REGION": "Gujarat, India",
    "OCCUPATION": "School administrator, desk-based, 09:00-17:30",
    "DAILY_STRUCTURE": (
        "Wakes 06:15, cooks for the household before leaving, 35-minute "
        "two-wheeler commute each way, home 18:30, cooks again, eats with "
        "the family at 21:45"
    ),
    "HOUSEHOLD": "Joint family of six; mother-in-law leads menu decisions",
    "PRIMARY_GOALS": [
        "Stop the fatty liver getting worse — was told it had gone from grade 1 to grade 2",
        "Not become diabetic like her father",
        "Energy through the afternoon without a third tea",
        "Regular cycles",
    ],
    "MEDICAL_HISTORY": [
        "PCOS diagnosed 2009 during infertility workup",
        "Two pregnancies; gestational diabetes in the second (2016), resolved postpartum",
        "Gallstones on ultrasound 2022, asymptomatic, no surgery",
        "Two prior weight-loss attempts: a low-carb plan in 2021 (abandoned week 3) "
        "and a commercial meal-replacement programme in 2023 (regained within four months)",
    ],
    "FAMILY_HISTORY": [
        "Father: type 2 diabetes from age 49, now on insulin",
        "Mother: hypothyroidism",
        "Elder sister: PCOS, gestational diabetes",
    ],
}

# PART 2 -- body and functional baseline
MEASUREMENTS = [
    ("height_cm", 157.0, "cm", "standing, no footwear"),
    ("weight_kg", 74.6, "kg", "morning, fasted"),
    ("bmi", 30.3, "kg/m2", "derived"),
    ("waist_cm", 97.0, "cm", "at umbilicus, end-expiration"),
    ("hip_cm", 104.0, "cm", "widest point"),
    ("waist_to_height_ratio", 0.62, "ratio", "derived"),
    ("body_fat_pct", 41.2, "%", "bioimpedance, home scale — device-dependent"),
    ("skeletal_muscle_mass_kg", 20.8, "kg", "bioimpedance, home scale"),
    ("grip_strength_kg", 19.0, "kg", "right hand, best of three"),
    ("sit_to_stand_30s", 9.0, "reps", "chair stand test"),
    ("resting_heart_rate", 78.0, "bpm", "morning, seated"),
    ("blood_pressure_systolic", 132.0, "mmHg", "seated, clinic"),
    ("blood_pressure_diastolic", 86.0, "mmHg", "seated, clinic"),
]

WEIGHT_HISTORY = [
    {"year": 2009, "weight_kg": 58.0, "note": "at PCOS diagnosis"},
    {"year": 2016, "weight_kg": 68.0, "note": "post second pregnancy"},
    {"year": 2021, "weight_kg": 71.0, "note": "before low-carb attempt"},
    {"year": 2022, "weight_kg": 66.5, "note": "lowest recent; regained over 11 months"},
    {"year": 2026, "weight_kg": 74.6, "note": "current"},
]

FUNCTIONAL_STATUS = {
    "STAIRS": "Two flights leaves her breathless and her knees ache",
    "CARRYING": "Manages household shopping but sets it down twice on the way up",
    "STANDING_COOKING": "45 minutes before lower-back discomfort",
    "SELF_REPORTED_STAMINA": "Worst between 15:00 and 17:00",
}

# PART 3 -- labs. Internally coherent: insulin-resistant, atherogenic
# dyslipidaemia, transaminitis consistent with MASLD, plus the three
# deficiencies a long-term vegetarian diet with no supplementation produces.
LABS = [
    # marker, value, unit, ref_low, ref_high
    ("HbA1c",                  6.1,  "%",        4.0,  5.6),
    ("Fasting glucose",       108.0, "mg/dL",   70.0,  99.0),
    ("Fasting insulin",        21.4, "uIU/mL",   2.6,  24.9),
    ("HOMA-IR",                 5.7, "index",    0.5,   2.0),
    ("Post-prandial glucose (2h)", 164.0, "mg/dL", 70.0, 139.0),
    ("Total cholesterol",     206.0, "mg/dL",    0.0, 200.0),
    ("Triglycerides",         218.0, "mg/dL",    0.0, 150.0),
    ("HDL cholesterol",        37.0, "mg/dL",   50.0,  90.0),
    ("LDL cholesterol",       124.0, "mg/dL",    0.0, 100.0),
    ("Non-HDL cholesterol",   169.0, "mg/dL",    0.0, 130.0),
    ("ALT",                    58.0, "U/L",      0.0,  33.0),
    ("AST",                    41.0, "U/L",      0.0,  32.0),
    ("GGT",                    64.0, "U/L",      0.0,  40.0),
    ("Alkaline phosphatase",   88.0, "U/L",     35.0, 104.0),
    ("Total bilirubin",         0.7, "mg/dL",    0.2,   1.2),
    ("TSH",                     4.6, "uIU/mL",   0.4,   4.0),
    ("Free T4",                 1.02, "ng/dL",   0.8,   1.8),
    ("Anti-TPO antibodies",    96.0, "IU/mL",    0.0,  34.0),
    ("Vitamin D (25-OH)",      14.0, "ng/mL",   30.0, 100.0),
    ("Vitamin B12",           168.0, "pg/mL",  200.0, 900.0),
    ("Serum ferritin",         16.0, "ng/mL",   30.0, 200.0),
    ("Haemoglobin",            11.4, "g/dL",    12.0,  15.5),
    ("MCV",                    88.0, "fL",      80.0, 100.0),
    ("Serum creatinine",        0.78, "mg/dL",   0.5,   1.1),
    ("eGFR",                   94.0, "mL/min/1.73m2", 90.0, 200.0),
    ("Uric acid",               5.9, "mg/dL",    2.4,   6.0),
    ("hs-CRP",                  4.2, "mg/L",     0.0,   3.0),
    ("Total testosterone",     62.0, "ng/dL",   15.0,  70.0),
    ("SHBG",                   23.0, "nmol/L",  32.0, 128.0),
    ("Free androgen index",     9.4, "index",    0.0,   5.0),
    ("AMH",                     6.9, "ng/mL",    1.0,   4.0),
]

IMAGING = [
    {
        "study": "Abdominal ultrasound",
        "date": "2026-07-30",
        "finding": "Grade 2 hepatic steatosis. Increased echogenicity with "
                   "reduced visualisation of portal vein walls. Gallstones "
                   "unchanged. Spleen normal.",
        "prior": "Grade 1 on the same modality in 2023",
    },
    {
        "study": "Transvaginal ultrasound",
        "date": "2026-07-30",
        "finding": "Both ovaries with >20 follicles, ovarian volume 12 mL right, "
                   "11 mL left. Endometrium 7 mm.",
    },
]

# PART 1 -- diagnoses, symptoms, medications, supplements
CONDITIONS = [
    ("PCOS",                                  "ACTIVE", date(2009, 3, 12), False, "HIGH"),
    ("MASLD (grade 2 hepatic steatosis)",     "ACTIVE", date(2026, 7, 30), False, "HIGH"),
    ("Prediabetes",                           "ACTIVE", date(2024, 11,  8), False, "HIGH"),
    ("Atherogenic dyslipidaemia",             "ACTIVE", date(2024, 11,  8), False, "HIGH"),
    ("Subclinical hypothyroidism (TPO positive)", "ACTIVE", date(2023, 5, 19), False, "MODERATE"),
    ("Stage 1 hypertension",                  "ACTIVE", date(2025, 2, 11), False, "MODERATE"),
    ("Iron deficiency without anaemia progressing to mild anaemia",
                                              "ACTIVE", None,             True,  "MODERATE"),
    ("Insulin resistance",                    "ACTIVE", None,             True,  "HIGH"),
    ("Cholelithiasis, asymptomatic",          "ACTIVE", date(2022, 6,  4), False, "HIGH"),
]

SYMPTOMS = [
    ("Afternoon energy crash between 15:00 and 17:00", 4, date(2026, 8, 14)),
    ("Post-meal sleepiness, worst after lunch",        4, date(2026, 8, 14)),
    ("Sugar craving in the hour after dinner",         3, date(2026, 8, 14)),
    ("Irregular cycles, 45 to 70 days",                3, date(2026, 8, 14)),
    ("Hair thinning at the crown",                     3, date(2026, 8, 14)),
    ("Facial hair on chin and upper lip",              2, date(2026, 8, 14)),
    ("Bilateral knee pain on stairs",                  3, date(2026, 8, 14)),
    ("Morning heel pain, first steps",                 3, date(2026, 8, 14)),
    ("Non-restorative sleep; wakes twice",             4, date(2026, 8, 14)),
    ("Bloating after the evening meal",                2, date(2026, 8, 14)),
    ("Breathlessness climbing two flights",            3, date(2026, 8, 14)),
    ("Cold intolerance",                               2, date(2026, 8, 14)),
]

# Exactly the combination D6 says must PASS CLEAN. No insulin, no
# sulfonylurea, no warfarin, no pregnancy, no renal or hepatic failure.
MEDICATIONS = [
    ("Metformin",      "500 mg",  "twice daily with food", date(2024, 11, 20),
     "Prescribed by endocrinologist for prediabetes. Dose unchanged since start."),
    ("Atorvastatin",   "10 mg",   "at night",              date(2025, 1, 15),
     "For dyslipidaemia. Last lipid review 2026-07."),
    ("Telmisartan",    "40 mg",   "morning",               date(2025, 2, 20),
     "For stage 1 hypertension."),
    ("Levothyroxine",  "25 mcg",  "fasting, 06:30",        date(2023, 6,  2),
     "Subclinical hypothyroidism with positive TPO. TSH reviewed six-monthly."),
]

SUPPLEMENTS = [
    ("Multivitamin (retail, non-therapeutic)", "1 tablet", False, "with breakfast, "
     "taken perhaps three days a week"),
    ("Calcium 500 mg with vitamin D3 250 IU",  "1 tablet", False, "at night"),
]

# PART 4 -- food forensics. Three days written as the client would report
# them, not as tidy nutrition data. Weekday, weekday, and a festival-
# adjacent Sunday, because the pattern that matters is the variance.
FOOD_LOG = [
    {
        "logged_on": "2026-08-11",
        "day_type": "working weekday",
        "raw_text": (
            "06:30 — masala chai with 2 tsp sugar and full-fat buffalo milk, "
            "2 Parle-G biscuits while cooking.\n"
            "08:15 — 2 methi thepla with mango pickle, small bowl of curd.\n"
            "11:00 — chai again, 1 tsp sugar. Colleague brought khakhra, had 2.\n"
            "13:30 — tiffin: 3 rotli, bowl of bottle-gourd sabzi, dal about half a "
            "katori, rice about a katori, buttermilk.\n"
            "16:30 — chai, 1 tsp sugar, and 2 handfuls of chevdo from the office tin.\n"
            "19:00 — 'just something while cooking' — a few spoons of the sabzi, "
            "one leftover thepla.\n"
            "21:45 — dinner with family: khichdi with ghee, kadhi, papad, "
            "small portion of aloo sabzi, 1 rotli.\n"
            "22:30 — 2 pieces of dates-and-nut mithai from a wedding box."
        ),
    },
    {
        "logged_on": "2026-08-12",
        "day_type": "working weekday",
        "raw_text": (
            "06:30 — masala chai, 2 tsp sugar.\n"
            "08:20 — poha with peanuts, small; chai leftover from the pot.\n"
            "11:15 — nothing, busy. Chai at 11:45 with 1 tsp sugar.\n"
            "13:45 — tiffin: 3 rotli, tindora sabzi, dal, rice, buttermilk.\n"
            "16:00 — very hungry. 4 khakhra with chundo, chai.\n"
            "19:15 — 'grazing' while cooking, could not say how much.\n"
            "21:30 — dinner: bhakhri, ringan-bateta sabzi, dal, rice, curd.\n"
            "22:15 — 1 small bowl of shrikhand from the fridge."
        ),
    },
    {
        "logged_on": "2026-08-17",
        "day_type": "Sunday, family lunch",
        "raw_text": (
            "07:00 — chai, 2 tsp sugar.\n"
            "09:30 — 3 fafda with jalebi (2), Sunday habit for years.\n"
            "13:00 — family lunch: puri (4), batata nu shaak, dal, rice, "
            "kadhi, boondi raita, 2 pieces basundi.\n"
            "16:30 — chai and leftover fafda.\n"
            "20:00 — light: 2 rotli, sabzi, curd. Says she has no appetite by then.\n"
            "Fasting the following day is common after a Sunday like this."
        ),
    },
]

FOOD_PATTERN = {
    "DIET_PATTERN": "Lacto-vegetarian since birth. No eggs, no fish, no meat.",
    "RELIGIOUS_CONSTRAINTS": (
        "No onion or garlic on Ekadashi and during Shravan. "
        "Household observes fasting days; she often fasts with them."
    ),
    "COOKING_FAT": "Groundnut oil and ghee; ghee is added at the table as well",
    "PROTEIN_SOURCES_USED": ["dal", "curd", "buttermilk", "peanuts", "milk"],
    "PROTEIN_SOURCES_NOT_USED": [
        "paneer (only at festivals)", "soya", "tofu", "sprouts",
        "besan chilla", "whey", "Greek-style curd",
    ],
    "ESTIMATED_INTAKE": {
        "energy_kcal_per_day": 1980,
        "protein_g_per_day": 44,
        "protein_g_per_kg": 0.59,
        "fibre_g_per_day": 17,
        "added_sugar_g_per_day": 38,
        "refined_grain_servings_per_day": 6.5,
        "note": "Practitioner estimate from the three-day log, not weighed. "
                "Sunday materially higher; weekdays are the pattern.",
    },
    "HYDRATION": {
        "water_litres_per_day": 1.3,
        "tea_cups_per_day": 4,
        "sugar_tsp_per_cup": 1.5,
        "other": "No alcohol. No soft drinks. Occasional buttermilk.",
    },
    "MEAL_TIMING": {
        "first_intake": "06:30 (tea with sugar and biscuits)",
        "last_intake": "22:30",
        "eating_window_hours": 16,
        "overnight_fast_hours": 8,
        "largest_meal": "dinner, 21:45",
        "note": "Dinner is the largest and latest meal of the day and is followed "
                "within 45 minutes by sleep.",
    },
    "EATING_ENVIRONMENT": {
        "eats_with_family": True,
        "cooks_for_household": True,
        "menu_control": "Limited — mother-in-law decides the main menu",
        "office_tin": "Shared chevdo/khakhra tin on the desk, refilled weekly",
        "distracted_eating": "Dinner eaten in front of the television",
    },
}

# PART 6 -- lifestyle and physical function
SLEEP = {
    "typical_bedtime": "22:45",
    "typical_wake": "06:15",
    "time_in_bed_hours": 7.5,
    "estimated_sleep_hours": 5.8,
    "sleep_latency_minutes": 35,
    "night_wakings": 2,
    "wakes_refreshed": False,
    "snoring_reported_by_partner": True,
    "witnessed_apnoea": "Not reported, never assessed",
    "screen_before_bed": "Phone in bed, 30-45 minutes",
    "note": "Snoring plus central adiposity plus non-restorative sleep has never "
            "been investigated. No sleep study has been done.",
}

MOVEMENT = {
    "daily_steps_average": 3200,
    "steps_source": "phone pedometer, 14-day average",
    "sitting_hours_per_workday": 9.5,
    "longest_uninterrupted_sitting_minutes": 110,
    "structured_exercise": "None currently",
    "resistance_training": "Never done any",
    "past_activity": "Walked 30 minutes daily in 2022 for about five months",
    "commute": "Two-wheeler, no walking component",
    "stairs_per_day": "2 flights, at home",
    "barriers_stated": ["No time before 06:15 or after 21:00",
                        "No women-only gym nearby that she would use",
                        "Knee pain on stairs discourages her"],
}

PAIN_AND_FUNCTION = {
    "bilateral_knee_pain": {
        "trigger": "descending stairs, prolonged standing",
        "severity_0_10": 4,
        "duration": "18 months, gradual",
        "imaging": "None",
        "red_flags": "No locking, no giving way, no swelling, no night pain",
    },
    "plantar_heel_pain": {
        "trigger": "first steps in the morning and after sitting",
        "severity_0_10": 5,
        "duration": "7 months",
        "footwear": "Flat rubber chappals indoors and outdoors",
    },
    "low_back": "Discomfort after 45 minutes standing; no radiation, no neurology",
}

STRESS_AND_RECOVERY = {
    "self_rated_stress_0_10": 7,
    "main_sources": ["Father's declining health", "Elder child's board exams",
                     "Household expectations around cooking"],
    "recovery_practices": "None deliberate; television in the evening",
    "smoking": "Never",
    "alcohol": "Never",
    "tobacco_other": "None",
}

CONSTRAINTS = {
    "BUDGET": "Moderate. Will not buy imported or specialty foods.",
    "KITCHEN_CONTROL": "Shared. Cooks, but does not set the menu.",
    "TIME": "Under 20 minutes for her own food on a weekday.",
    "EQUIPMENT": "Pressure cooker, gas hob, no oven, no blender.",
    "TRAVEL": "None regular.",
    "FESTIVALS": "Navratri, Diwali, Uttarayan — extended sweet and fried-food exposure.",
    "LITERACY": "Comfortable reading Gujarati and English; uses WhatsApp daily.",
    "MEASUREMENT_ACCESS": "Home BP monitor and a bioimpedance weighing scale. "
                          "Lab work affordable roughly quarterly.",
    "GLUCOSE_MONITORING": "No glucometer. Willing to buy one; has not been asked to.",
}

# PART 7 -- behaviour
BEHAVIOUR = {
    "PATTERN": "Consistent and rule-following in the morning; intake becomes "
               "unstructured from 16:00 onward.",
    "ADHERENCE_HISTORY": "Has never missed a medication dose in two years.",
    "REPEATED_FAILURE_POINTS": [
        "Week 3 of any restrictive plan — both previous attempts ended there",
        "The 16:00-17:00 office tea and snack",
        "Grazing while cooking the family dinner, which she does not count as eating",
        "Sunday fafda-jalebi, a family ritual rather than a food choice",
    ],
    "BARRIERS": [
        "Cooking separately for herself reads as rejecting the family meal",
        "Mother-in-law interprets refusal of ghee as an insult",
        "Evening time is genuinely scarce",
    ],
    "EXISTING_STRONG_HABITS": [
        "Cooks fresh food daily; almost nothing ultra-processed enters the house",
        "Takes medication reliably",
        "Keeps every lab report in a folder, in order, with dates",
        "Buttermilk daily",
        "Walked 30 minutes daily for five months in 2022 — she can sustain a habit",
    ],
    "STRENGTHS": [
        "Understands her numbers and asks specific questions",
        "Motivated by her father's insulin rather than by appearance",
        "Household eats together, so a change to the shared meal reaches her too",
    ],
    "STATED_READINESS": "Willing to change breakfast and the evening snack. "
                        "Not willing to eat separately from the family at dinner.",
}

# PART 18 -- medical coordination context
MEDICAL_CONTEXT = {
    "TREATING_CLINICIANS": ["Endocrinologist, six-monthly", "General physician, local"],
    "NEXT_REVIEW": "Endocrinology review due 2026-11",
    "PRESCRIBER_QUESTIONS_OPEN": [
        "TSH 4.6 on 25 mcg levothyroxine with positive TPO — dose adequacy is the "
        "prescriber's decision, not this system's",
        "Untested snoring plus central adiposity plus non-restorative sleep",
        "Ferritin 16 with haemoglobin 11.4 — cause of iron deficiency not established",
    ],
    "NOT_PREGNANT": True,
    "BREASTFEEDING": False,
    "CONTRACEPTION": "None; not currently trying to conceive",
}


# ---------------------------------------------------------------------
# Coverage map: which intake keys feed which of the 19 output parts
# ---------------------------------------------------------------------
#
# Engine 1 section 62 fixes the 19 parts. Parts 1-7 and 18 are read
# directly from intake. Parts 8-17 and 19 are SYNTHESIS -- the mirror, the
# driver map, the endpoint, the interventions, the handoffs, the summary --
# so what they need is not new input but the prerequisites they reason
# over. Both are listed, because "the engine will work it out" is exactly
# how a part ends up unsupported and invented.

PART_INPUTS: dict[str, list[str]] = {
    "PART 1 — CLIENT IDENTITY & CONTEXT":
        ["CONTEXT", "CONDITIONS", "SYMPTOMS", "MEDICATIONS", "SUPPLEMENTS"],
    "PART 2 — BODY & FUNCTIONAL BASELINE":
        ["MEASUREMENTS", "WEIGHT_HISTORY", "FUNCTIONAL_STATUS"],
    "PART 3 — LAB & BIOMARKER INTELLIGENCE":
        ["LABS", "IMAGING"],
    "PART 4 — FOOD FORENSICS":
        ["FOOD_LOG", "FOOD_PATTERN"],
    "PART 5 — NUTRIENT INTELLIGENCE":
        ["FOOD_PATTERN", "LABS", "SUPPLEMENTS"],
    "PART 6 — LIFESTYLE & PHYSICAL FUNCTION":
        ["SLEEP", "MOVEMENT", "PAIN_AND_FUNCTION", "STRESS_AND_RECOVERY", "CONSTRAINTS"],
    # Section 35 does not read behaviour off a self-report alone: the
    # grazing-while-cooking that the client does not count as eating is
    # visible in the food log, and the barriers are only meaningful against
    # the day she actually has.
    "PART 7 — BEHAVIOUR":
        ["BEHAVIOUR", "CONTEXT", "FOOD_LOG", "CONSTRAINTS"],
    "PART 8 — COMPLETE CLIENT MIRROR":
        ["CONTEXT", "LABS", "FOOD_PATTERN", "SLEEP", "MOVEMENT", "BEHAVIOUR"],
    "PART 9 — DRIVER & BOTTLENECK MAP":
        ["LABS", "FOOD_PATTERN", "MOVEMENT", "SLEEP", "CONDITIONS", "MEDICATIONS"],
    "PART 10 — HEALTH ENDPOINT & INTERNAL TARGETS":
        ["LABS", "MEASUREMENTS", "SYMPTOMS", "CONTEXT"],
    "PART 11 — INTERVENTION OPTION DISCOVERY":
        ["CONDITIONS", "LABS", "FOOD_PATTERN", "MOVEMENT", "CONSTRAINTS"],
    "PART 12 — PRIORITIZED INTERVENTION STRATEGY":
        ["CONSTRAINTS", "BEHAVIOUR", "MEDICATIONS", "LABS"],
    "PART 13 — FOOD / NUTRITION STRATEGY HANDOFF":
        ["FOOD_PATTERN", "FOOD_LOG", "LABS", "CONSTRAINTS"],
    "PART 14 — BEHAVIOUR HANDOFF":
        ["BEHAVIOUR", "CONTEXT", "CONSTRAINTS"],
    "PART 15 — MOVEMENT / FUNCTION STRATEGY":
        ["MOVEMENT", "PAIN_AND_FUNCTION", "FUNCTIONAL_STATUS"],
    "PART 16 — FOUR-WEEK SUCCESS SYSTEM":
        ["LABS", "SYMPTOMS", "FUNCTIONAL_STATUS", "BEHAVIOUR", "CONSTRAINTS"],
    "PART 17 — PRACTITIONER LEARNING":
        ["CONDITIONS", "LABS", "MEDICATIONS"],
    "PART 18 — MEDICAL COORDINATION":
        ["MEDICATIONS", "MEDICAL_CONTEXT", "LABS", "CONDITIONS"],
    "PART 19 — FINAL INTERNAL CASE SUMMARY":
        ["CONTEXT", "LABS", "FOOD_PATTERN", "BEHAVIOUR", "CONSTRAINTS"],
}


# ---------------------------------------------------------------------
# The engine payload
# ---------------------------------------------------------------------

def intake_payload(client_id: str, case_version: int = 1) -> dict:
    """The structured input an engine receives.

    client_id and clinical facts. No display name, no locality, no
    household identifiers -- STRIP_IDENTITY_FROM_ENGINE_PAYLOADS, and the
    data-residency section of docs/OPERATIONS.md: the database is in India
    and model inference is not.

    REGION is kept because Engine 3 cannot reason about seasonal and
    regional food availability without it, and a state is not an identifier.
    """
    return {
        "CLIENT_ID": str(client_id),
        "CASE_VERSION": case_version,
        "CONTEXT": CONTEXT,
        "CONDITIONS": [
            {"condition": c, "status": s, "diagnosed_on": d.isoformat() if d else None,
             "is_inferred": inf, "confidence": conf}
            for c, s, d, inf, conf in CONDITIONS
        ],
        "SYMPTOMS": [
            {"symptom": s, "severity_0_5": sev, "reported_on": d.isoformat()}
            for s, sev, d in SYMPTOMS
        ],
        "MEDICATIONS": [
            {"name": n, "dose": dose, "timing": t,
             "started_on": s.isoformat(), "prescriber_note": note}
            for n, dose, t, s, note in MEDICATIONS
        ],
        "SUPPLEMENTS": [
            {"name": n, "dose": d, "is_therapeutic_dose": th, "timing": t}
            for n, d, th, t in SUPPLEMENTS
        ],
        "MEASUREMENTS": [
            {"measure": m, "value": v, "unit": u, "context": ctx}
            for m, v, u, ctx in MEASUREMENTS
        ],
        "WEIGHT_HISTORY": WEIGHT_HISTORY,
        "FUNCTIONAL_STATUS": FUNCTIONAL_STATUS,
        "LABS": [
            {"marker": m, "value": v, "unit": u,
             "reference_low": lo, "reference_high": hi,
             "measured_on": BASELINE.isoformat()}
            for m, v, u, lo, hi in LABS
        ],
        "IMAGING": IMAGING,
        "FOOD_LOG": FOOD_LOG,
        "FOOD_PATTERN": FOOD_PATTERN,
        "SLEEP": SLEEP,
        "MOVEMENT": MOVEMENT,
        "PAIN_AND_FUNCTION": PAIN_AND_FUNCTION,
        "STRESS_AND_RECOVERY": STRESS_AND_RECOVERY,
        "CONSTRAINTS": CONSTRAINTS,
        "BEHAVIOUR": BEHAVIOUR,
        "MEDICAL_CONTEXT": MEDICAL_CONTEXT,
    }


def check_no_identity(payload: dict) -> list[str]:
    """Return any identifier that leaked into an engine payload."""
    text = json.dumps(payload)
    return [ident for ident in IDENTIFIERS if ident in text]


# ---------------------------------------------------------------------
# Loading into the database
# ---------------------------------------------------------------------

def clear(conn) -> None:
    """Remove any previous copy. Cascades runs, outputs, labs, flags."""
    conn.execute("delete from clients where external_ref like 'SYN-E1-%'")


def load(conn) -> str:
    """Insert the synthetic client and its clinical record. Returns client_id.

    Idempotent by way of clear(): suites and the measurement runner must
    both be re-runnable against a database that already holds fixtures.
    """
    clear(conn)

    client_id = conn.execute(
        """insert into clients (external_ref, display_name, year_of_birth, sex,
                                country, region, locality, primary_language, status)
           values (%s,%s,%s,%s,%s,%s,%s,%s,'INTAKE') returning client_id""",
        (EXTERNAL_REF, DISPLAY_NAME, DEMOGRAPHICS["year_of_birth"],
         DEMOGRAPHICS["sex"], DEMOGRAPHICS["country"], DEMOGRAPHICS["region"],
         DEMOGRAPHICS["locality"], DEMOGRAPHICS["primary_language"]),
    ).fetchone()[0]

    for measure, value, unit, context in MEASUREMENTS:
        conn.execute(
            """insert into client_measurements
                 (client_id, measured_on, measure, value, unit, context, is_baseline, source)
               values (%s,%s,%s,%s,%s,%s,true,'SYNTHETIC_FIXTURE')""",
            (client_id, BASELINE, measure, value, unit, context))

    for marker, value, unit, lo, hi in LABS:
        conn.execute(
            """insert into client_labs
                 (client_id, measured_on, marker, value, unit,
                  reference_low, reference_high, is_baseline, source)
               values (%s,%s,%s,%s,%s,%s,%s,true,'SYNTHETIC_FIXTURE')""",
            (client_id, BASELINE, marker, value, unit, lo, hi))

    for condition, status, diagnosed, inferred, confidence in CONDITIONS:
        conn.execute(
            """insert into client_conditions
                 (client_id, condition, status, diagnosed_on, is_inferred,
                  confidence, source)
               values (%s,%s,%s,%s,%s,%s,'SYNTHETIC_FIXTURE')""",
            (client_id, condition, status, diagnosed, inferred, confidence))

    for symptom, severity, reported in SYMPTOMS:
        conn.execute(
            """insert into client_symptoms
                 (client_id, symptom, severity, reported_on)
               values (%s,%s,%s,%s)""",
            (client_id, symptom, severity, reported))

    for name, dose, timing, started, note in MEDICATIONS:
        conn.execute(
            """insert into client_medications
                 (client_id, name, dose, timing, status, started_on, prescriber_note)
               values (%s,%s,%s,%s,'CURRENT',%s,%s)""",
            (client_id, name, dose, timing, started, note))

    for name, dose, therapeutic, timing in SUPPLEMENTS:
        conn.execute(
            """insert into client_supplements
                 (client_id, name, dose, is_therapeutic_dose, timing, status)
               values (%s,%s,%s,%s,%s,'CURRENT')""",
            (client_id, name, dose, therapeutic, timing))

    for entry in FOOD_LOG:
        conn.execute(
            """insert into client_food_logs
                 (client_id, logged_on, raw_text, structured, source)
               values (%s,%s,%s,%s,'SYNTHETIC_FIXTURE')""",
            (client_id, entry["logged_on"], entry["raw_text"],
             json.dumps({"day_type": entry["day_type"]})))

    return str(client_id)


if __name__ == "__main__":
    payload = intake_payload("00000000-0000-0000-0000-000000000000")
    print(f"intake payload: {len(json.dumps(payload)):,} chars, "
          f"{len(payload)} top-level keys")
    print(f"labs {len(LABS)}, symptoms {len(SYMPTOMS)}, "
          f"medications {len(MEDICATIONS)}, food-log days {len(FOOD_LOG)}")
    leaked = check_no_identity(payload)
    print("identity leak:", leaked or "none")
    missing = sorted({k for keys in PART_INPUTS.values() for k in keys} - set(payload))
    print("part inputs missing from payload:", missing or "none")

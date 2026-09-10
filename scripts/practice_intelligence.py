#!/usr/bin/env python3
"""Step 23 — de-identified practice aggregation into `practice_strategy_outcomes`.

BUILD_GUIDE step 23. DECISIONS.md D9, D43, D45. Hard rules 3, 4, 6, 8.

    python3 scripts/practice_intelligence.py                 # plan (default)
    python3 scripts/practice_intelligence.py --execute
    python3 scripts/practice_intelligence.py --block         # the engine block
    python3 scripts/practice_intelligence.py --queue         # why a cohort is short

### Practice experience is never evidence, and this is the file that could
### have made it evidence

Hard rule 6 and D9: `practice_strategy_outcomes` has no foreign key to
`evidence_records` and no view joins them. Nothing here creates, updates or
reads an evidence record, and the block this produces carries `basis` and
`evidence_status` as FIELDS -- not as a caption around them, because a
caption is what gets dropped when a payload is reformatted.

### It is COUNTS, never copied client text

Every summary below is composed from counts. No `stop_reason`, no
`adherence` note, no outcome evidence string is copied out of the client
layer into the aggregate -- at a cohort of five, one verbatim sentence is
quasi-identifying, and "de-identified" that depends on nobody having
written anything distinctive is not de-identified.

`trg_practice_deidentified` is the backstop (a UUID, an email, a display
name, an external ref). This rule is what keeps the backstop from being
the only thing standing between the client layer and a global table.
Surfacing reason text is a later decision with its own de-identification
step, not something to slip in here.

### One client, one observation

`n_clients` counts DISTINCT CLIENTS WITH A RECORDED OUTCOME, using each
client's latest one. Five intervention rows from two clients is one
person's record with a count on it, and the cohort minimum only means
something if the number it guards counts people. The database agrees:
`ck_practice_outcomes_account_for_cohort` refuses a distribution that does
not sum to `n_clients`.

### A proposal nobody started is not experience

`started_on IS NOT NULL`. A plan that was never carried out says nothing
about the strategy, and counting proposals inflates every cohort with
things that never happened.

### Adherence sits BESIDE the outcome (D43)

Never folded into it. A cohort whose adherence is mostly UNKNOWN has not
shown the strategy does not work; it has shown nobody measured. The
summary says so in that case rather than reporting a neutral result.

### Plan by default

`--execute` is an explicit act, as with K00 (D44). This writes to a GLOBAL
table from CROSS-CLIENT reads; a runner whose safe mode is the one you have
to remember to ask for is not safe.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

import psycopg
from psycopg.rows import dict_row

# The stable cohort definition. No client attributes: age, sex or region at
# a cohort of five are quasi-identifiers, and this string is also the key
# `uq_practice_generated` de-duplicates on, so it must not drift.
COHORT_CRITERIA = "All assessed clients who started this strategy"
GENERATION_METHOD = "DETERMINISTIC_V1"

# Best to worst, for the range summary. NOT_TRACKED and TOO_EARLY are not
# on the scale: they are statements about the observation, not the response.
OUTCOME_SCALE = ["IMPROVING", "STABLE", "LIMITED_RESPONSE", "WORSENING"]


def dsn() -> str:
    try:
        return os.environ["DATABASE_URL"]
    except KeyError:
        sys.exit("DATABASE_URL is not set")


# ---------------------------------------------------------------------
# Reading the cohort
# ---------------------------------------------------------------------

def candidates(conn, *, ready_only: bool = True) -> list[dict]:
    """Per-strategy cohort readiness, from the view.

    The minimum is NOT re-implemented here. `meets_cohort_minimum` comes
    from `v_practice_cohort_candidates`, and `ck_min_cohort` refuses the
    write independently -- two mechanisms, neither derived from the other.
    """
    sql = """select * from v_practice_cohort_candidates
              where n_clients_exposed > 0"""
    if ready_only:
        sql += " and meets_cohort_minimum"
    sql += " order by n_clients_assessed desc, strategy_name"
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(sql).fetchall()


def observations(conn, strategy_id: str) -> dict:
    """One observation per client: their latest recorded outcome.

    The tie-break is deterministic (`recorded_at`, then the later start,
    then the id) so a re-run cannot return a different cohort from the same
    rows -- V2's bug 62 was a page decided by a UUID tie-break passing four
    times in a row.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        exposure = cur.execute(
            """select i.client_id, i.intervention_id, i.started_on, i.ended_on,
                      i.status, i.strategy_id
                 from client_interventions i
                where i.strategy_id = %s
                  and i.started_on is not null""",
            (strategy_id,)).fetchall()

        per_client = cur.execute(
            """with exposure as (
                   select i.client_id, i.intervention_id, i.started_on,
                          i.ended_on, i.status
                     from client_interventions i
                    where i.strategy_id = %s
                      and i.started_on is not null),
                    assessed as (
                   select e.*, h.recorded_at, h.new_outcome
                     from exposure e
                     join lateral (
                           select h.recorded_at, h.new_outcome
                             from intervention_outcome_history h
                            where h.intervention_id = e.intervention_id
                            order by h.recorded_at desc, h.history_id
                            limit 1) h on true)
               select distinct on (a.client_id)
                      a.client_id, a.intervention_id, a.new_outcome as outcome,
                      a.status, a.started_on, a.ended_on,
                      adherence_band(
                        (select x.adherence_pct
                           from client_intervention_exposure x
                          where x.intervention_id = a.intervention_id
                          order by x.period_start desc, x.exposure_id
                          limit 1)) as adherence
                 from assessed a
                order by a.client_id, a.recorded_at desc,
                         a.started_on desc nulls last, a.intervention_id""",
            (strategy_id,)).fetchall()

    starts = [r["started_on"] for r in exposure if r["started_on"]]
    ends = [r["ended_on"] for r in exposure if r["ended_on"]]
    return {
        "n_clients_exposed": len({r["client_id"] for r in exposure}),
        "n_interventions": len(exposure),
        "per_client": per_client,
        "period_start": min(starts) if starts else None,
        "period_end": max(ends) if ends else None,
    }


# ---------------------------------------------------------------------
# Composing the aggregate -- from counts only
# ---------------------------------------------------------------------

def summarise(obs: dict) -> dict:
    """The aggregate row, composed entirely from counts."""
    people = obs["per_client"]
    n = len(people)
    outcomes = Counter(str(p["outcome"]) for p in people)
    adherence = Counter(str(p["adherence"]) for p in people)
    never = obs["n_clients_exposed"] - n
    stopped = sum(1 for p in people if str(p["status"]) == "STOPPED")

    def dist(c: Counter) -> str:
        return ", ".join(f"{k} {v}" for k, v in sorted(c.items(),
                                                       key=lambda kv: (-kv[1], kv[0])))

    outcome_summary = (
        f"{dist(outcomes)} — of {n} assessed client(s), "
        f"{obs['n_clients_exposed']} exposed"
        + (f", {never} never assessed." if never else "."))

    on_scale = [o for o in OUTCOME_SCALE if outcomes.get(o)]
    if on_scale:
        best, worst = on_scale[0], on_scale[-1]
        outcome_range = (f"{best} only" if best == worst
                         else f"{best} to {worst}")
    else:
        # Everyone is TOO_EARLY or NOT_TRACKED. That is not a null result.
        outcome_range = "no client has a readable response yet"

    unknown = adherence.get("UNKNOWN", 0)
    adherence_summary = f"{dist(adherence)} — of {n} assessed client(s)."
    if unknown * 2 > n:
        # D43, at cohort scale. An intervention nobody carried out has not
        # failed; it has not been tested. Saying that HERE is what stops
        # the outcome distribution being read as an effect size.
        adherence_summary += (
            " Adherence is unrecorded for the majority: a neutral or poor "
            "outcome in this cohort is untested, not ineffective.")

    return {
        "cohort_criteria": COHORT_CRITERIA,
        "n_clients": n,
        "n_clients_exposed": obs["n_clients_exposed"],
        "n_interventions": obs["n_interventions"],
        "outcome_counts": dict(outcomes),
        "adherence_counts": dict(adherence),
        "outcome_summary": outcome_summary,
        "outcome_range": outcome_range,
        "adherence_summary": adherence_summary,
        "drop_out": f"{stopped} of {n} assessed client(s) stopped.",
        # Nothing structured records a side effect. NULL, not an invented
        # summary: an empty field reads as "not captured", a fabricated one
        # reads as "none occurred".
        "common_side_effects": None,
        # Counts only. A verbatim stop reason at a cohort of five is
        # quasi-identifying, so the count travels and the text does not.
        "common_failure_reasons":
            (f"{stopped} stop(s) recorded; reason text is held in the client "
             f"record and is not aggregated." if stopped
             else "no client stopped."),
        "implementation_acceptance":
            f"{n - stopped} of {n} assessed client(s) still on it or completed; "
            f"adherence {dist(adherence)}.",
        "period_start": obs["period_start"],
        "period_end": obs["period_end"],
        "generation_method": GENERATION_METHOD,
    }


COMPARED = ("cohort_criteria", "n_clients", "n_clients_exposed",
            "n_interventions", "outcome_counts", "adherence_counts",
            "outcome_summary", "outcome_range", "adherence_summary",
            "drop_out", "common_side_effects", "common_failure_reasons",
            "implementation_acceptance", "period_start", "period_end")


def unchanged(existing: dict | None, row: dict) -> bool:
    """An aggregate that did not change is not rewritten.

    Same reason `embedding_source_hash` exists (migration 023): a second
    pass over unchanged data should be a no-op, and `generated_at` moving
    on every run would make every row look freshly derived.
    """
    if existing is None:
        return False
    return all(existing.get(k) == row[k] for k in COMPARED)


def write(conn, strategy_id: str, row: dict) -> str:
    with conn.cursor(row_factory=dict_row) as cur:
        existing = cur.execute(
            """select * from practice_strategy_outcomes
                where strategy_id = %s and generation_method is not null""",
            (strategy_id,)).fetchone()
        if unchanged(existing, row):
            return "UNCHANGED"
        cur.execute(
            """insert into practice_strategy_outcomes
                 (strategy_id, cohort_criteria, n_clients, n_clients_exposed,
                  n_interventions, outcome_counts, adherence_counts,
                  outcome_summary, outcome_range, adherence_summary, drop_out,
                  common_side_effects, common_failure_reasons,
                  implementation_acceptance, period_start, period_end,
                  generated_at, generation_method)
               values (%(sid)s, %(cohort_criteria)s, %(n_clients)s,
                       %(n_clients_exposed)s, %(n_interventions)s,
                       %(outcome_counts)s, %(adherence_counts)s,
                       %(outcome_summary)s, %(outcome_range)s,
                       %(adherence_summary)s, %(drop_out)s,
                       %(common_side_effects)s, %(common_failure_reasons)s,
                       %(implementation_acceptance)s, %(period_start)s,
                       %(period_end)s, now(), %(generation_method)s)
               on conflict (strategy_id, cohort_criteria)
                 where generation_method is not null
               do update set
                  n_clients = excluded.n_clients,
                  n_clients_exposed = excluded.n_clients_exposed,
                  n_interventions = excluded.n_interventions,
                  outcome_counts = excluded.outcome_counts,
                  adherence_counts = excluded.adherence_counts,
                  outcome_summary = excluded.outcome_summary,
                  outcome_range = excluded.outcome_range,
                  adherence_summary = excluded.adherence_summary,
                  drop_out = excluded.drop_out,
                  common_side_effects = excluded.common_side_effects,
                  common_failure_reasons = excluded.common_failure_reasons,
                  implementation_acceptance = excluded.implementation_acceptance,
                  period_start = excluded.period_start,
                  period_end = excluded.period_end,
                  generated_at = now()""",
            {**row, "sid": strategy_id,
             "outcome_counts": json.dumps(row["outcome_counts"]),
             "adherence_counts": json.dumps(row["adherence_counts"])})
        return "UPDATED" if existing else "CREATED"


def run(conn, *, execute: bool = False) -> dict:
    """Aggregate every strategy whose assessed cohort reaches the minimum."""
    report = {"ready": 0, "created": 0, "updated": 0, "unchanged": 0,
              "refused": [], "rows": []}
    for c in candidates(conn, ready_only=True):
        report["ready"] += 1
        obs = observations(conn, c["strategy_id"])
        row = summarise(obs)

        # The view said the cohort was ready. Recount here from the
        # observations actually gathered and refuse a disagreement rather
        # than writing a number the constraint would have to catch.
        if row["n_clients"] != c["n_clients_assessed"]:
            report["refused"].append(
                (c["strategy_name"],
                 f"cohort disagrees: view {c['n_clients_assessed']}, "
                 f"observations {row['n_clients']}"))
            continue

        entry = {"strategy": c["strategy_name"], **row}
        report["rows"].append(entry)
        if not execute:
            continue
        outcome = write(conn, c["strategy_id"], row)
        report[outcome.lower()] += 1
        entry["action"] = outcome
    return report


# ---------------------------------------------------------------------
# The separately labelled block (D9, Engine 1 Pass B, Engine 7 A4)
# ---------------------------------------------------------------------

CAVEAT = ("De-identified internal practice observation. Hypothesis-generating "
          "and context-setting. NOT trial evidence and never to be described "
          "in language implying trial support.")


def practice_block(conn, *, concept_ids: list[str] | None = None,
                   strategy_ids: list[str] | None = None,
                   limit: int = 20) -> list[dict]:
    """Practice aggregates for the engine payload, each carrying its label.

    Filtered to the case's concepts when there are any -- the same concept
    spine retrieval uses (D39) -- or to named strategies on the follow-up
    path, where the question is how the strategies this client is actually
    on have gone across the practice. With neither, the whole (small) set.
    The label is per entry, so a block that gets split or reordered on the
    way into a prompt cannot lose it.
    """
    params: list = []
    where: list[str] = []
    sql = """select strategy_name, cohort_criteria, n_clients, n_clients_exposed,
                    n_interventions, outcome_counts, adherence_counts,
                    outcome_summary, outcome_range, adherence_summary, drop_out,
                    common_side_effects, common_failure_reasons,
                    implementation_acceptance, period_start, period_end,
                    basis, evidence_status
               from v_practice_experience p"""
    if concept_ids:
        where.append("""exists (select 1 from strategy_concepts sc
                                 where sc.strategy_id = p.strategy_id
                                   and sc.concept_id = any(%s::uuid[]))""")
        params.append(list(concept_ids))
    if strategy_ids:
        where.append("p.strategy_id = any(%s::uuid[])")
        params.append(list(strategy_ids))
    if where:
        # OR, not AND: the case's concepts and the client's current
        # strategies are two reasons for an aggregate to be relevant, and
        # ANDing them returns only their intersection -- which is usually
        # empty, and would look exactly like an empty library.
        sql += " where (" + " or ".join(where) + ")"
    sql += " order by n_clients desc, strategy_name limit %s"
    params.append(limit)

    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(sql, params).fetchall()
    for r in rows:
        for k in ("period_start", "period_end"):
            r[k] = r[k].isoformat() if r[k] else None
        r["caveat"] = CAVEAT
    return rows


# ---------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="De-identified practice aggregation (step 23)")
    ap.add_argument("--execute", action="store_true",
                    help="write the aggregates; without it this only plans")
    ap.add_argument("--queue", action="store_true",
                    help="show every strategy with exposure and why it is short")
    ap.add_argument("--block", action="store_true",
                    help="print the separately labelled engine block")
    args = ap.parse_args()

    conn = psycopg.connect(dsn(), autocommit=True)

    if args.block:
        print(json.dumps(practice_block(conn), indent=2, default=str))
        return 0

    if args.queue:
        rows = candidates(conn, ready_only=False)
        if not rows:
            print("no strategy has a started intervention yet")
            return 0
        for r in rows:
            state = "READY" if r["meets_cohort_minimum"] else "SHORT"
            if r["aggregate_exists"]:
                state += " (aggregate present)"
            print(f"  {state:26} {r['strategy_name'][:48]:50} "
                  f"{r['blocked_reason'] or ''}")
        return 0

    report = run(conn, execute=args.execute)
    mode = "EXECUTE" if args.execute else "PLAN (use --execute to write)"
    print(f"== practice aggregation :: {mode} ==")
    for r in report["rows"]:
        print(f"\n  {r['strategy']}")
        print(f"    cohort         {r['n_clients']} assessed of "
              f"{r['n_clients_exposed']} exposed, "
              f"{r['n_interventions']} intervention(s)")
        print(f"    outcomes       {r['outcome_summary']}")
        print(f"    adherence      {r['adherence_summary']}")
        if r.get("action"):
            print(f"    action         {r['action']}")
    for name, why in report["refused"]:
        print(f"\n  REFUSED {name}: {why}")
    print(f"\n{report['ready']} strategy(ies) at or above the cohort minimum; "
          f"created {report['created']}, updated {report['updated']}, "
          f"unchanged {report['unchanged']}")
    if not report["ready"]:
        print("Nothing to aggregate. `--queue` says why each strategy is short.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

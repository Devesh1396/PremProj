#!/usr/bin/env python3
"""CLIENT_FOLLOWUP. Step 21 — the second and every subsequent cycle.

BUILD_GUIDE step 21; migration `027`; D6, D42, D43. Hard rules 3, 8, 9.

    follow-up -> E6 UPDATE -> E4 -> routing -> E1/E2/E3 -> E6 -> review

    python3 scripts/client_followup.py --queue
    python3 scripts/client_followup.py FOLLOWUP_ID

### Why this is a different pipeline from CLIENT_NEW, and not a parameter

`CLIENT_NEW` establishes a case: every engine runs, in a fixed order,
because a new client needs all of them and there is nothing yet to route
on. A follow-up is the opposite — most of the case is unchanged, Engine 4
is the routing authority (§64A), and running E1, E2 and E3 unconditionally
would spend a full cycle's tokens to re-derive a plan nothing has
challenged.

So this reads `ROUTING_RECOMMENDATION` — a **typed control-block field**,
never prose (hard rule 5) — and runs only what it names.

### E6 runs in UPDATE mode here, and that is the whole difference

`CLIENT_NEW` uses `REBUILD` because the case is still being established
across one cycle. A follow-up is Engine 6 §A1's *normal path*: a
`<CASE_MEMORY_DELTA>` describing what changed. The delta goes in the
`delta` column; a **new full state** is what becomes `canonical_state`
(D24) — a description of a change is not a case, and storing one as the
state would make `get_current_client_state()` return a diff.

### The routing budget is real and it is spent here

`case_cycles.max_loops` defaults to 3 and `ck_loop_bound` refuses the
fourth. One follow-up opens one cycle and spends one hop; a re-routed pass
within that cycle spends another. That is what stops a case cycling on its
own recommendation.

### Nothing here reaches a client

The cycle ends at the review queue, exactly as `CLIENT_NEW` does. E5 and
release live in `client_release.py`, behind a practitioner decision and the
safety gate (hard rule 9).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import psycopg

import client_new as CN
import normalize as NZ
import run_engine as RE

PipelineStopped = CN.PipelineStopped

OUTCOMES_TAG = "PROGRESS_OUTCOMES"
PIPELINE_DESCRIPTION = "followup -> E6(UPDATE) -> E4 -> routing -> E1/E2/E3 -> E6 -> review"

# Which engines a routing recommendation actually means. A registry rather
# than a chain of `if`s: ROUTING_RECOMMENDATION is a closed enum in the
# control contract, and a value this map does not know must be loud rather
# than silently routing nowhere.
ROUTES: dict[str, tuple[str, ...]] = {
    "NONE": (),
    "ENGINE1": ("E1",),
    "ENGINE2": ("E2",),
    "ENGINE3": ("E3",),
    # E1 re-deciding what matters invalidates the plans built on the old
    # decision, so MULTIPLE runs the chain rather than three engines in
    # parallel that disagree.
    "MULTIPLE": ("E1", "E2", "E3"),
    # Neither is a re-plan. Both are "a human, or more data, before
    # anything else happens" -- and both still end at the review queue,
    # which is where a human is.
    "MEDICAL_COORDINATION": (),
    "MORE_DATA": (),
}

OUTCOME_VALUES = {"IMPROVING", "STABLE", "WORSENING", "LIMITED_RESPONSE",
                  "TOO_EARLY", "NOT_TRACKED"}
STATUS_VALUES = {"ONGOING", "MODIFIED", "PAUSED", "STOPPED", "COMPLETED"}


@dataclass
class Step:
    name: str
    status: str
    run_id: str | None = None
    detail: str | None = None


@dataclass
class Outcome:
    followup_id: str
    client_id: str
    status: str = "RUNNING"
    cycle_id: str | None = None
    case_version_id: str | None = None
    final_case_version_id: str | None = None
    review_id: str | None = None
    routed: tuple[str, ...] = ()
    routing_reason: str | None = None
    outcomes_recorded: int = 0
    stopped_because: str | None = None
    steps: list[Step] = field(default_factory=list)

    def step(self, name: str, status: str, run_id: str | None = None,
             detail: str | None = None) -> None:
        self.steps.append(Step(name, status, run_id, detail))


def dsn() -> str:
    return os.environ["DATABASE_URL"]


def queue(conn) -> list[tuple]:
    return conn.execute(
        "select followup_id::text, client_id::text, display_name, review_period, "
        "       submitted_on, live_interventions, last_cycle_hops, "
        "       last_cycle_budget from v_followup_queue").fetchall()


def live_interventions(conn, client_id: str) -> list[dict]:
    """What Engine 4 is being asked to report a response on.

    Passed in explicitly rather than left for E4 to recall from the case
    state: §64B requires one entry per intervention, and an engine cannot
    be held to that if it was never told what the list was.
    """
    rows = conn.execute(
        """select i.intervention_id::text, i.name, i.purpose, i.status::text,
                  i.outcome::text, i.started_on, i.proposed_on,
                  r.never_assessed
             from client_interventions i
             join v_intervention_response r using (intervention_id)
            where i.client_id = %s::uuid
              and i.status in ('PROPOSED','APPROVED','STARTED','ONGOING','MODIFIED')
            order by i.name""", (client_id,)).fetchall()
    return [{"intervention_id": r[0], "name": r[1], "purpose": r[2],
             "status": r[3], "previous_outcome": r[4],
             "started_on": str(r[5]) if r[5] else None,
             "proposed_on": str(r[6]) if r[6] else None,
             "never_assessed": r[7]} for r in rows]


def record_outcomes(conn, client_id: str, followup_id: str, result,
                    outcome: Outcome) -> int:
    """§64B. Turn E4's outcomes into rows, through the one function that
    keeps the history (`record_intervention_outcome`).

    Matching is by NAME against this client's live interventions, because
    that is what §64B asks the engine to echo back. An outcome naming
    something this client does not have is DROPPED and counted -- writing
    it would create a response to a plan nobody made, and
    `record_intervention_outcome` refuses that anyway.
    """
    body = (result.secondary_handoffs or {}).get(OUTCOMES_TAG)
    if not body:
        raise PipelineStopped(
            f"E4 produced no <{OUTCOMES_TAG}> block, so what it learned "
            "exists only as prose. client_interventions.outcome would stay "
            "unwritten and WORSENING_MARKER would keep reading a column "
            "nobody has ever filled (D42).")
    raw = body.get("OUTCOMES_JSON")
    if raw is None:
        raise PipelineStopped(f"<{OUTCOMES_TAG}> carried no OUTCOMES_JSON.")
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PipelineStopped(
            f"OUTCOMES_JSON is not valid JSON: {exc}") from exc
    if not isinstance(items, list):
        raise PipelineStopped("OUTCOMES_JSON must be a JSON array.")

    by_name = {row["name"].strip().lower(): row["intervention_id"]
               for row in live_interventions(conn, client_id)}
    written = unmatched = 0
    for item in items:
        if not isinstance(item, dict):
            unmatched += 1
            continue
        name = (item.get("name") or "").strip()
        target = by_name.get(name.lower())
        if not target:
            unmatched += 1
            continue

        value = (item.get("outcome") or "").strip().upper()
        if value not in OUTCOME_VALUES:
            # NOT an assumed STABLE. An unreadable outcome is an outcome
            # nobody can act on, and NOT_TRACKED says exactly that --
            # whereas STABLE would claim a measurement that was never made.
            value = "NOT_TRACKED"
        status = (item.get("status") or "").strip().upper() or None
        if status not in STATUS_VALUES:
            status = None

        conn.execute(
            "select record_intervention_outcome(%s::uuid, %s::outcome_direction, "
            "  %s::intervention_status, %s, %s, %s::uuid, %s::uuid, %s)",
            (target, value, status, item.get("adherence"), item.get("evidence"),
             followup_id, result.run_id, item.get("stop_reason")))
        written += 1

    outcome.step("E4_OUTCOMES", "OK",
                 detail=f"{written} recorded"
                        + (f", {unmatched} named nothing live" if unmatched else ""))
    return written


def route(control: dict | None) -> tuple[tuple[str, ...], str]:
    """What to run next, from a TYPED field. Never from prose (hard rule 5)."""
    recommendation = ((control or {}).get("ROUTING_RECOMMENDATION")
                      or "NONE").strip().upper()
    if recommendation not in ROUTES:
        raise PipelineStopped(
            f"ROUTING_RECOMMENDATION {recommendation!r} is not a value the "
            "control contract defines. Routing on an unknown recommendation "
            "would be guessing what an engine meant.")
    reason = (control or {}).get("ROUTING_REASON") or "no reason given"
    return ROUTES[recommendation], f"{recommendation}: {reason}"


def run_followup(conn: psycopg.Connection, followup_id: str,
                 llm=None, max_loops: int | None = None) -> Outcome:
    """One follow-up, one cycle. Ends at the review queue."""
    row = conn.execute(
        """select f.client_id::text, f.processed_at, f.review_period,
                  f.raw_answers, f.structured
             from client_followups f where f.followup_id = %s::uuid""",
        (followup_id,)).fetchone()
    if row is None:
        raise PipelineStopped(f"no follow-up {followup_id}")
    client_id, processed_at, period, raw_answers, structured = row

    outcome = Outcome(followup_id=followup_id, client_id=client_id)

    if processed_at is not None:
        outcome.status = "STOPPED"
        outcome.stopped_because = (
            f"follow-up {followup_id} was already processed at "
            f"{processed_at:%Y-%m-%d %H:%M}. Running it again would spend a "
            "routing hop and write a second set of outcomes over the first.")
        return outcome

    try:
        # Hard rule 8. Every write below is inside this transaction, and
        # the scope is what the RLS policies read (D25).
        conn.execute("select set_client_scope(%s::uuid)", (client_id,))

        state = conn.execute(
            "select get_current_client_state(%s::uuid)", (client_id,)).fetchone()[0]
        if state is None:
            raise PipelineStopped(
                f"client {client_id} has no current case version. A follow-up "
                "is a response to a plan, and there is no plan to respond to.")
        case_version = int(state.get("case_version") or 1)

        interventions = live_interventions(conn, client_id)
        if not interventions:
            raise PipelineStopped(
                "this client has no live interventions, so there is no "
                "response to learn from. A follow-up that arrived before any "
                "plan did is a data point about timing, not about response.")

        outcome.cycle_id = CN.open_cycle(conn, client_id, cycle_type="FOLLOWUP",
                                         max_loops=max_loops)
        outcome.step("CYCLE_OPEN", "OK", detail=outcome.cycle_id)
        CN.spend_routing_hop(conn, outcome.cycle_id)

        followup_input = {
            "CLIENT_ID": client_id,
            "CASE_VERSION": case_version,
            "REVIEW_PERIOD": period,
            "FOLLOWUP_ANSWERS": raw_answers or {},
            "FOLLOWUP_STRUCTURED": structured or {},
            "CURRENT_STATE": state,
            "LIVE_INTERVENTIONS": interventions,
        }

        # E6 UPDATE. §A1's normal path: a delta describing what changed.
        # The delta is stored as a delta; the full state is what becomes
        # canonical_state, and E6 emits both in this mode.
        e6 = CN._run(conn, outcome, "E6_UPDATE", engine="E6", mode="UPDATE",
                     structured_input=followup_input)

        # E4 is the routing authority for this cycle (§64A).
        e4 = CN._run(conn, outcome, "E4", engine="E4",
                     structured_input={**followup_input,
                                       "E6_DELTA": e6.structured})
        outcome.outcomes_recorded = record_outcomes(
            conn, client_id, followup_id, e4, outcome)

        # Routing, from the typed field.
        engines, outcome.routing_reason = route(e4.control)
        outcome.routed = engines
        outcome.step("ROUTING", "OK", detail=outcome.routing_reason)

        handoffs: dict[str, Any] = {"E4_HANDOFF": e4.structured,
                                    "E6_DELTA": e6.structured}

        if "E1" in engines:
            # Normalization sits between E1 and E7 on the new-client path
            # and belongs here too: a follow-up introduces new phrases, and
            # an unnormalized phrase is a strategy nothing will retrieve.
            phrases = (e4.control or {}).get("NORMALIZATION_PHRASES") or []
            resolved = NZ.resolve_all(conn, phrases, context="C3_FOLLOWUP",
                                      llm=llm) if phrases else []
            outcome.step("NORMALIZE", "OK",
                         detail=f"{len(resolved)} of {len(phrases)} phrases resolved")
            e1 = CN._run(conn, outcome, "E1", engine="E1", pass_label="SINGLE",
                         structured_input={**followup_input, **handoffs})
            handoffs["E1_HANDOFF"] = e1.structured

        for engine in ("E2", "E3"):
            if engine in engines:
                result = CN._run(conn, outcome, engine, engine=engine,
                                 structured_input={**followup_input, **handoffs})
                handoffs[f"{engine}_HANDOFF"] = result.structured
                wrote, refused = CN.record_plan_items(
                    conn, client_id, engine, result,
                    "BEHAVIOUR_PLAN_ITEMS" if engine == "E2"
                    else "NUTRITION_PLAN_ITEMS")
                outcome.step(f"{engine}_PLAN_ITEMS", "OK",
                             detail=f"{wrote} proposed"
                                    + (f", {refused} unusable" if refused else ""))

        # E6 again, so the cycle's own conclusions are in the case rather
        # than only in the run log. REBUILD because canonical_state is NOT
        # NULL and a delta cannot be mechanically merged into a state --
        # the same reasoning as CLIENT_NEW's second E6 call.
        e6_final = CN._run(conn, outcome, "E6_FINAL", engine="E6", mode="REBUILD",
                           structured_input={**followup_input, **handoffs,
                                             "CASE_VERSION": case_version + 1})
        outcome.final_case_version_id = CN._new_case_version(
            conn, client_id, e6_final.structured,
            (e4.control or {}).get("FOLLOWUP_PHASE") or "PHASE_2",
            f"Follow-up {period or ''} — routed {outcome.routing_reason}".strip(),
            delta=e6_final.secondary_handoffs.get("CASE_MEMORY_DELTA"))
        outcome.step("CASE_VERSION", "OK", detail=outcome.final_case_version_id)

        # The deterministic rules see the NEW plan and the NEW outcomes --
        # which is the point of running them here rather than at the start.
        # WORSENING_MARKER cannot fire until E4 has written an outcome.
        opened = conn.execute(
            "select apply_safety_rules(%s::uuid, %s::uuid, %s::uuid)",
            (client_id, outcome.cycle_id, e4.run_id)).fetchone()[0]
        holds = conn.execute(
            "select count(*) from case_flags where client_id=%s::uuid "
            "  and severity='HOLD' and status='OPEN'", (client_id,)).fetchone()[0]
        outcome.step("SAFETY_RULES", "OK",
                     detail=f"{opened} flag(s) opened, {holds} HOLD(s) open")

        conn.execute(
            "update client_followups set processed_at=now(), processing_note=%s "
            " where followup_id=%s::uuid",
            (f"{PIPELINE_DESCRIPTION}; routed {outcome.routing_reason}",
             followup_id))

        outcome.review_id = str(conn.execute(
            """insert into practitioner_reviews (client_id, cycle_id, run_id,
                 decision, notes)
               values (%s::uuid,%s::uuid,%s::uuid,'PENDING',%s)
               returning review_id""",
            (client_id, outcome.cycle_id, e4.run_id,
             f"CLIENT_FOLLOWUP complete. {outcome.outcomes_recorded} "
             f"intervention outcome(s) recorded; routed "
             f"{outcome.routing_reason}. Engines requested review: "
             f"{bool((e4.control or {}).get('REVIEW_REQUIRED'))}. "
             "No client-facing output has been drafted or sent."
             )).fetchone()[0])
        outcome.step("REVIEW_QUEUED", "OK", detail=outcome.review_id)

        outcome.status = "AWAITING_REVIEW"
        return outcome

    except PipelineStopped as exc:
        outcome.status = "STOPPED"
        outcome.stopped_because = str(exc)
        return outcome


def main() -> int:
    ap = argparse.ArgumentParser(description="CLIENT_FOLLOWUP")
    ap.add_argument("followup_id", nargs="?")
    ap.add_argument("--queue", action="store_true")
    args = ap.parse_args()

    with psycopg.connect(dsn(), autocommit=True) as conn:
        if args.queue or not args.followup_id:
            rows = queue(conn)
            if not rows:
                print("no unprocessed follow-up.")
                return 0
            for r in rows:
                print(f"  {r[0]}  {r[2] or r[1]:<24} {r[4]}  "
                      f"{r[5]} live intervention(s)  "
                      f"cycle {r[6]}/{r[7]} hops")
            return 0

        with conn.transaction():
            result = run_followup(conn, args.followup_id)
        for s in result.steps:
            print(f"  {s.name:<18}{s.status:<12}{s.detail or ''}")
        print(f"\n{result.status}"
              + (f": {result.stopped_because}" if result.stopped_because else ""))
        return 0 if result.status == "AWAITING_REVIEW" else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""K00_FOUNDATION_CONTROLLER. Step 22 — the Wave-1 foundation build.

BUILD_GUIDE step 22; migration `028`; A4, D44. Hard rule 3.

    python3 scripts/foundation_controller.py --status
    python3 scripts/foundation_controller.py --plan
    python3 scripts/foundation_controller.py --execute --batch 1

```
domain map -> subdomains -> research questions -> source discovery
  -> ingestion -> claim extraction -> evidence analysis
  -> strategy synthesis -> gap assessment -> repeat
```

Every stage already exists as its own script (K02-K13). **This adds no new
knowledge work.** It decides what runs next, keeps the position so a
restart resumes, and stops when the budget says stop.

### It does not execute by default, and that is deliberate

K00 is the one component that could begin mass ingestion unattended, and
the standing instruction is **one source through the complete loop first,
then the 20-video pilot**. So `--plan` is the default and `--execute` is an
explicit act. A controller whose safe mode is the one you have to remember
to ask for is not safe.

### The budget was a name until now

`KNOWLEDGE_DAILY_TOKEN_BUDGET` has been in `.env.example` since the
beginning and **nothing has ever read it**. Every earlier stage ran on
fixtures or one item at a time, so it never mattered; a loop over 26
domains is where it does. The cap is checked from `cost_events` — what was
actually spent — rather than from a counter this file keeps, because a
counter can be forgotten to increment and rows cannot.

**Unset means unbounded, and this says so out loud** rather than inventing
a default. A number chosen here would be a spending decision made by the
builder.

### Resumable means the cursor is a row

`foundation_progress` holds each domain's stage. A controller that kept its
position in memory would restart every domain from `DISCOVER` after a
container restart, which turns a bounded build into an unbounded one.

### Priority orders the queue and nothing else

Core domains first, then `wave1_priority`, then least-recently-advanced.
That is a **weight on this queue**; it never restricts what Engine 7 may
discover, and autonomous domain expansion continues throughout.

### IDLE is not COMPLETE

A domain with nothing queued is `IDLE`. §70 forbids a `COMPLETE` status and
this file does not create one by another name — the next source to arrive
puts the domain back to work.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import psycopg

import knowledge_controversy as K12
import knowledge_extract as K09
import knowledge_gap as K13
import knowledge_research as K10
import knowledge_synthesize as K11

# Bounded by default. A batch is a handful of items, not "everything
# queued": the point of batching is that the operator can look at what
# happened before the next one runs.
DEFAULT_BATCH = int(os.environ.get("KNOWLEDGE_BATCH_SIZE", "5"))

# How many consecutive failures pause a domain. An unattended loop that
# retries a permanent failure spends the whole budget on it and covers
# nothing else.
ERROR_PAUSE_AFTER = int(os.environ.get("K00_ERROR_PAUSE_AFTER", "3"))


class BudgetExhausted(RuntimeError):
    """The daily cap is spent. Not an error — the cap working."""


def dsn() -> str:
    return os.environ["DATABASE_URL"]


def token_budget() -> int | None:
    """The daily cap, or None for unbounded.

    Unset is UNBOUNDED and every caller says so. Choosing a number here
    would be the builder making a spending decision that belongs to the
    practitioner.
    """
    raw = (os.environ.get("KNOWLEDGE_DAILY_TOKEN_BUDGET") or "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


def spend_today(conn) -> tuple[int, float]:
    row = conn.execute("select * from knowledge_spend_today()").fetchone()
    return int(row[0]), float(row[1])


def budget_remaining(conn) -> tuple[int | None, int, float]:
    """(remaining tokens or None, spent tokens, spent usd)."""
    cap = token_budget()
    tokens, cost = spend_today(conn)
    return (None if cap is None else max(0, cap - tokens)), tokens, cost


# ---------------------------------------------------------------------
# The stage machine
# ---------------------------------------------------------------------
#
# Each entry is (stage, how much work is queued, how to do one item).
# A registry rather than a chain of `if`s: the loop is "find the first
# stage with work and do a bounded amount of it", and a new stage should be
# a row in this table rather than another branch.

@dataclass
class Stage:
    name: str
    scope: str               # LIBRARY | DOMAIN
    pending: object          # (conn, domain_id) -> list of work items
    run_one: object          # (conn, item) -> dict
    describe: str


def _extract_pending(conn, _domain_id):
    return K09.pending(conn, limit=None)


def _research_pending(conn, _domain_id):
    return K10.queue(conn, 100)


def _synthesis_pending(conn, _domain_id):
    return K11.queue(conn, 100)


def _controversy_pending(conn, domain_id):
    return [row for row in K12.queue(conn) if row[0] == domain_id]


def _gap_pending(conn, domain_id):
    return [row for row in K13.queue(conn) if row[0] == domain_id]


# DISCOVER and INGEST are deliberately absent from the executable stages.
#
# Discovery reaches real external APIs that this build has never spoken to
# (the proxy blocks all three), and ingestion is where mass ingestion would
# begin. Both are real, tested scripts; wiring them into an unattended loop
# before one source has been through the whole thing by hand is exactly
# what the standing instruction forbids. The controller reports them as
# MANUAL rather than pretending they are not stages.
MANUAL_STAGES = {
    "DISCOVER": "K02-K06 reach external APIs this build has never called; "
                "run knowledge_discover.py deliberately",
    "INGEST": "K07/K08 is where mass ingestion begins; run "
              "knowledge_ingest.py on one source first",
}

# LIBRARY stages are not per-domain, and pretending otherwise is a bug.
#
# A claim belongs to a SOURCE, not to a domain: `knowledge_extract.pending`,
# `knowledge_research.queue` and `knowledge_synthesize.queue` each return
# everything queued library-wide. Running them once per domain would have
# every domain claim the same item -- three domains "processing" one claim,
# with the accounting to match. They run ONCE per batch.
#
# CONTROVERSY and GAP genuinely are per-domain: both read across what has
# accumulated in one domain, which is why they exist as separate passes at
# all (D41).
STAGES: list[Stage] = [
    Stage("EXTRACT", "LIBRARY", _extract_pending,
          lambda conn, item: K09.extract_one(conn, item),
          "K09 claim extraction"),
    Stage("RESEARCH", "LIBRARY", _research_pending,
          lambda conn, item: K10.research_one(conn, item),
          "K10 evidence analysis"),
    Stage("SYNTHESIZE", "LIBRARY", _synthesis_pending,
          lambda conn, item: K11.synthesize_one(conn, item),
          "K11 strategy synthesis"),
    Stage("CONTROVERSY", "DOMAIN", _controversy_pending,
          lambda conn, item: K12.assess_one(conn, item),
          "K12 controversy + negative knowledge"),
    Stage("GAP", "DOMAIN", _gap_pending,
          lambda conn, item: K13.assess_one(conn, item),
          "K13 gap assessment"),
]

LIBRARY_STAGES = [s for s in STAGES if s.scope == "LIBRARY"]
DOMAIN_STAGES = [s for s in STAGES if s.scope == "DOMAIN"]

STAGE_BY_NAME = {stage.name: stage for stage in STAGES}


@dataclass
class BatchResult:
    batch_id: str | None = None
    dry_run: bool = True
    domains_touched: int = 0
    items_processed: int = 0
    stages_run: list[str] = field(default_factory=list)
    stopped_reason: str | None = None
    plan: list[dict] = field(default_factory=list)


def queue(conn, limit: int | None = None) -> list[tuple]:
    rows = conn.execute(
        "select domain_id::text, domain_key, name, is_core_domain, "
        "       wave1_priority, stage::text, passes, paused "
        "  from v_foundation_queue where not paused").fetchall()
    return rows[:limit] if limit else rows


def next_library_stage(conn) -> tuple[Stage | None, list, str]:
    """The first library-wide stage with work, and its queue.

    Ordered as the loop is: extraction before research before synthesis.
    Synthesising claims whose evidence has not been read yet would produce
    strategies resting on nothing.
    """
    for stage in LIBRARY_STAGES:
        items = stage.pending(conn, None)
        if items:
            return stage, items, f"{len(items)} item(s) for {stage.describe}"
    return None, [], "nothing queued library-wide"


def next_stage(conn, domain_id: str) -> tuple[Stage | None, list, str]:
    """The first PER-DOMAIN stage with work for this domain.

    Library stages are handled once per batch, not here (see STAGES):
    assessing a domain whose claims are still queued would read across work
    that has not happened yet.
    """
    for stage in DOMAIN_STAGES:
        items = stage.pending(conn, domain_id)
        if items:
            return stage, items, f"{len(items)} item(s) for {stage.describe}"
    return None, [], "nothing queued"


def progress_row(conn, domain_id: str) -> None:
    conn.execute(
        "insert into foundation_progress (domain_id) values (%s::uuid) "
        "on conflict (domain_id) do nothing", (domain_id,))


def advance(conn, domain_id: str, stage: str, items: int) -> None:
    progress_row(conn, domain_id)
    conn.execute(
        """update foundation_progress
              set stage = %s::foundation_stage,
                  passes = passes + 1,
                  items_processed = items_processed + %s,
                  last_advanced = now(),
                  last_error = null,
                  consecutive_errors = 0,
                  updated_at = now()
            where domain_id = %s::uuid""", (stage, items, domain_id))


def record_error(conn, domain_id: str, stage: str, message: str) -> bool:
    """Record a failure; pause the domain if it keeps happening.

    Returns True when the domain was paused. A paused domain is skipped by
    the queue and stays visible with its reason — an unattended loop that
    retries a permanent failure covers nothing else.
    """
    # The progress row is ensured first. Failing to RECORD a
    # failure because the row was missing is the worst possible
    # moment to be strict: the domain would fail silently and
    # forever, never reaching the pause this exists to trigger.
    progress_row(conn, domain_id)
    row = conn.execute(
        """update foundation_progress
              set stage = %s::foundation_stage,
                  last_error = %s,
                  consecutive_errors = consecutive_errors + 1,
                  updated_at = now()
            where domain_id = %s::uuid
        returning consecutive_errors""",
        (stage, message[:2000], domain_id)).fetchone()
    if row and row[0] >= ERROR_PAUSE_AFTER:
        conn.execute(
            "update foundation_progress set paused = true, paused_reason = %s "
            " where domain_id = %s::uuid",
            (f"{row[0]} consecutive failures at {stage}: {message[:300]}",
             domain_id))
        return True
    return False


def plan(conn, limit: int | None = None) -> list[dict]:
    """What a batch WOULD do. Reads only, so it costs nothing to look."""
    out = []
    stage, items, detail = next_library_stage(conn)
    out.append({"domain": "(library-wide)", "core": None, "priority": None,
                "stage": stage.name if stage else "IDLE",
                "queued": len(items), "detail": detail, "passes": None,
                "manual_next": None})
    for domain_id, key, name, core, priority, stage, passes, _paused in queue(conn, limit):
        found, items, detail = next_stage(conn, domain_id)
        out.append({
            "domain": key, "core": core, "priority": priority,
            "stage": found.name if found else "IDLE",
            "queued": len(items), "detail": detail, "passes": passes,
            "manual_next": None if found else sorted(MANUAL_STAGES),
        })
    return out


def run_batch(conn, *, batch: int = DEFAULT_BATCH, execute: bool = False,
              domains: int | None = None) -> BatchResult:
    """One bounded, cost-capped, resumable pass.

    `execute=False` is the default and does no work: it records the plan and
    a `dry_run` batch row, so a look costs nothing and leaves a trace.
    """
    result = BatchResult(dry_run=not execute)
    cap = token_budget()
    remaining, tokens_before, cost_before = budget_remaining(conn)

    result.batch_id = str(conn.execute(
        """insert into foundation_batches
             (token_budget, tokens_before, cost_before, dry_run)
           values (%s,%s,%s,%s) returning batch_id""",
        (cap, tokens_before, cost_before, not execute)).fetchone()[0])

    if not execute:
        result.plan = plan(conn, domains)
        result.stopped_reason = (
            "dry run: nothing was executed. K00 is the one component that "
            "could begin mass ingestion unattended, so --execute is an "
            "explicit act.")
    elif cap is not None and remaining <= 0:
        result.stopped_reason = (
            f"the daily token budget is spent ({tokens_before} of {cap}). "
            "Not an error — the cap working.")
    else:
        # Library-wide stages first, ONCE. They feed the per-domain ones:
        # a controversy pass over a domain whose claims are still queued is
        # reading across work that has not happened yet.
        stage, items, _detail = next_library_stage(conn)
        if stage is not None:
            done = 0
            try:
                for item in items[:batch]:
                    stage.run_one(conn, item)
                    done += 1
            except Exception as exc:                    # noqa: BLE001
                result.stopped_reason = (
                    f"library stage {stage.name} failed: {str(exc)[:200]}")
            if done:
                result.items_processed += done
                result.stages_run.append(stage.name)

        for domain_id, key, _name, _core, _priority, _stage, _passes, _paused in \
                queue(conn, domains):
            if cap is not None:
                remaining, spent, _cost = budget_remaining(conn)
                if remaining <= 0:
                    result.stopped_reason = (
                        f"the daily token budget is spent ({spent} of {cap}) "
                        f"after {result.items_processed} item(s). Not an "
                        "error — the cap working.")
                    break

            progress_row(conn, domain_id)
            stage, items, _detail = next_stage(conn, domain_id)
            if stage is None:
                # IDLE is not COMPLETE (§70). Nothing is queued right now.
                conn.execute(
                    "update foundation_progress set stage='IDLE', "
                    "       updated_at=now() where domain_id=%s::uuid",
                    (domain_id,))
                continue

            done = 0
            try:
                for item in items[:batch]:
                    stage.run_one(conn, item)
                    done += 1
                advance(conn, domain_id, stage.name, done)
            except Exception as exc:                    # noqa: BLE001
                paused = record_error(conn, domain_id, stage.name, str(exc))
                result.stopped_reason = (
                    f"{key} failed at {stage.name}: {str(exc)[:200]}"
                    + (" (domain paused)" if paused else ""))

            if done:
                result.domains_touched += 1
                result.items_processed += done
                if stage.name not in result.stages_run:
                    result.stages_run.append(stage.name)

    tokens_after, cost_after = spend_today(conn)
    conn.execute(
        """update foundation_batches
              set finished_at = now(), domains_touched = %s, items_processed = %s,
                  stages_run = %s, tokens_after = %s, cost_after = %s,
                  stopped_reason = %s
            where batch_id = %s::uuid""",
        (result.domains_touched, result.items_processed, result.stages_run,
         tokens_after, cost_after, result.stopped_reason, result.batch_id))
    return result


def status(conn) -> None:
    cap = token_budget()
    remaining, tokens, cost = budget_remaining(conn)
    print("\nBUDGET")
    if cap is None:
        print("  KNOWLEDGE_DAILY_TOKEN_BUDGET is UNSET — the knowledge clock "
              "is UNBOUNDED.")
        print("  Set it before running --execute unattended. No default is "
              "invented here: that is a spending decision.")
    else:
        print(f"  cap {cap:,} tokens/day    spent {tokens:,}    "
              f"remaining {remaining:,}")
    print(f"  spent today: ${cost:.4f} on knowledge-clock work "
          "(client cycles are excluded in both directions)")

    print("\nQUEUE")
    print(f"  {'domain':<26}{'core':>6}{'pri':>5}{'stage':>14}{'passes':>8}")
    for row in conn.execute(
            "select domain_key, is_core_domain, wave1_priority, stage::text, "
            "       passes, paused, paused_reason from v_foundation_queue"
    ).fetchall():
        key, core, priority, stage, passes, paused, reason = row
        print(f"  {key:<26}{('yes' if core else ''):>6}{priority:>5}"
              f"{stage:>14}{passes:>8}"
              + (f"   PAUSED: {(reason or '')[:60]}" if paused else ""))

    print("\nSTAGES THIS CONTROLLER WILL NOT RUN")
    for name, why in sorted(MANUAL_STAGES.items()):
        print(f"  {name:<12}{why}")

    print("\nWAVE 1 READINESS — computed, never stored, and never COMPLETE")
    row = conn.execute(
        "select core_domains, core_domains_ready, core_domains_at_depth, "
        "       core_domains_gap_assessed, core_domains_with_critical_gaps, "
        "       strategies, tests_defined, last_mean_score, unprovenanced, "
        "       unretrievable, wave1_foundation_ready from v_wave1_readiness"
    ).fetchone()
    labels = ("core domains", "…ready", "…at depth", "…gap assessed",
              "…with CRITICAL gaps", "strategies", "retrieval tests",
              "last mean score", "unprovenanced", "unretrievable")
    for label, value in zip(labels, row):
        print(f"  {label:<24}{value if value is not None else '-'}")
    print(f"  {'WAVE1_FOUNDATION_READY':<24}{row[10]}")
    print("\n  All four dimensions at once (A4): coverage, depth, retrieval,")
    print("  provenance. Counts are engineering floors, never definitions of")
    print("  quality — and IDLE is not COMPLETE (§70).")


def main() -> int:
    ap = argparse.ArgumentParser(description="K00 foundation controller")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--plan", action="store_true",
                    help="what a batch would do; reads only")
    ap.add_argument("--execute", action="store_true",
                    help="actually run the batch. NOT the default.")
    ap.add_argument("--batch", type=int, default=DEFAULT_BATCH,
                    help="items per domain per stage")
    ap.add_argument("--domains", type=int, default=None,
                    help="how many domains to consider this batch")
    args = ap.parse_args()

    with psycopg.connect(dsn(), autocommit=True) as conn:
        if args.status or not (args.plan or args.execute):
            status(conn)
            return 0

        result = run_batch(conn, batch=args.batch, execute=args.execute,
                           domains=args.domains)
        for row in result.plan:
            print(f"  {row['domain']:<26}{row['stage']:<14}{row['detail']}")
        print(f"\n  batch          {result.batch_id}")
        print(f"  dry run        {result.dry_run}")
        print(f"  domains        {result.domains_touched}")
        print(f"  items          {result.items_processed}")
        print(f"  stages         {', '.join(result.stages_run) or '-'}")
        if result.stopped_reason:
            print(f"  stopped        {result.stopped_reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

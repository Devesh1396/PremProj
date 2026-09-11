#!/usr/bin/env python3
"""K00_FOUNDATION_CONTROLLER. Step 22 — the Wave-1 foundation build.

BUILD_GUIDE step 22; migration `028`; A4, D44. Hard rules 3 and 11.

Everything here drives the real controller against the real database (V2),
and every optional dependency degrades through `preflight` (V3).

The five properties that make a long-running unattended loop safe, each of
which this controller would otherwise lose:

1. **The budget is enforced, from `cost_events`.** It was a name in
   `.env.example` and nothing read it — which mattered nowhere until a loop
   over 26 domains existed.
2. **It does not execute by default.** K00 is the one component that could
   begin mass ingestion unattended.
3. **The cursor is a row.** A restart resumes; it does not restart every
   domain from the beginning.
4. **Priority orders the queue and nothing else.**
5. **`IDLE` is not `COMPLETE`, and readiness is computed, never stored.**
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "testing"))

import psycopg

import foundation_controller as K00
import preflight

FAILS: list[str] = []
PREFIX = "FCTEST_"


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


def clear(conn) -> None:
    conn.execute(
        "delete from foundation_progress where domain_id in "
        "  (select domain_id from knowledge_domains where domain_key like %s)",
        (PREFIX + "%",))
    conn.execute("delete from knowledge_domains where domain_key like %s",
                 (PREFIX + "%",))
    conn.execute("delete from foundation_batches where stopped_reason like %s",
                 (PREFIX + "%",))
    conn.execute("delete from cost_events where entity_type = %s",
                 (PREFIX + "spend",))


def domain(conn, key: str, core: bool, priority: int) -> str:
    return str(conn.execute(
        "insert into knowledge_domains (name, domain_key, domain_type, "
        " description, wave1_priority, is_core_domain, discovered_by) "
        "values (%s,%s,'OTHER',%s,%s,%s,'FCTEST') returning domain_id",
        (PREFIX + key, PREFIX + key, "fixture", priority, core)).fetchone()[0])


def main() -> int:
    os.environ["LLM_API_KEY"] = ""
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    clear(conn)

    low = domain(conn, "LOW", core=False, priority=1)
    mid = domain(conn, "MID", core=False, priority=9)
    core = domain(conn, "CORE", core=True, priority=1)

    # ==================================================================
    print("\nthe budget is enforced from cost_events, not from a counter")

    before_tokens, _before_cost = K00.spend_today(conn)
    conn.execute(
        "insert into cost_events (operation, model_role, model_name, "
        " entity_type, input_tokens, output_tokens, cost_usd) "
        "values ('CLAIM_EXTRACTION','MODEL_EXTRACTION','x',%s,50000,10000,0.05)",
        (PREFIX + "spend",))
    after_tokens, _after_cost = K00.spend_today(conn)
    check("a knowledge-clock call counts against the budget",
          after_tokens == before_tokens + 60000,
          f"{before_tokens} -> {after_tokens}")

    # Client work is excluded in BOTH directions: a case does not eat the
    # foundation budget, and is never blocked by it.
    conn.execute(
        "insert into cost_events (operation, model_role, model_name, "
        " entity_type, input_tokens, output_tokens, cost_usd) "
        "values ('ENGINE_RUN','MODEL_ANALYSIS','x','client_case',90000,10000,0.4)")
    client_excluded, _ = K00.spend_today(conn)
    check("a CLIENT call does not consume the knowledge budget",
          client_excluded == after_tokens, f"{after_tokens} -> {client_excluded}")
    conn.execute("delete from cost_events where entity_type='client_case'")

    original = os.environ.get("KNOWLEDGE_DAILY_TOKEN_BUDGET")
    try:
        os.environ.pop("KNOWLEDGE_DAILY_TOKEN_BUDGET", None)
        check("unset means UNBOUNDED, and is not silently given a default",
              K00.token_budget() is None, str(K00.token_budget()))
        remaining, _spent, _cost = K00.budget_remaining(conn)
        check("...and remaining is None rather than a number",
              remaining is None, str(remaining))

        os.environ["KNOWLEDGE_DAILY_TOKEN_BUDGET"] = "1000"
        check("a cap below today's spend leaves nothing",
              K00.budget_remaining(conn)[0] == 0,
              str(K00.budget_remaining(conn)))

        result = K00.run_batch(conn, batch=1, execute=True, domains=2)
        check("an exhausted budget stops the batch before any work",
              result.items_processed == 0
              and "budget is spent" in (result.stopped_reason or ""),
              str(result.stopped_reason)[:140])
        check("...and says it is the cap working, not an error",
              "not an error" in (result.stopped_reason or "").lower(),
              str(result.stopped_reason)[:140])

        recorded = conn.execute(
            "select token_budget, tokens_before, dry_run from foundation_batches "
            " where batch_id=%s::uuid", (result.batch_id,)).fetchone()
        check("the batch recorded the cap it ran under",
              recorded[0] == 1000, str(recorded))
        check("and that it was not a dry run", recorded[2] is False, str(recorded))

        os.environ["KNOWLEDGE_DAILY_TOKEN_BUDGET"] = str(after_tokens + 500_000)
        check("raising the cap makes room again",
              K00.budget_remaining(conn)[0] > 0, str(K00.budget_remaining(conn)))
    finally:
        if original is None:
            os.environ.pop("KNOWLEDGE_DAILY_TOKEN_BUDGET", None)
        else:
            os.environ["KNOWLEDGE_DAILY_TOKEN_BUDGET"] = original

    # ==================================================================
    print("\nit does not execute by default")

    dry = K00.run_batch(conn, batch=1, domains=2)
    check("the default is a dry run", dry.dry_run is True)
    check("it processed nothing", dry.items_processed == 0, str(dry))
    check("and it says why executing is an explicit act",
          "explicit act" in (dry.stopped_reason or ""),
          str(dry.stopped_reason)[:120])
    check("a dry run still leaves a batch row",
          conn.execute("select dry_run from foundation_batches "
                       " where batch_id=%s::uuid", (dry.batch_id,)
                       ).fetchone()[0] is True)

    # ==================================================================
    print("\npriority orders the queue and nothing else")

    order = [r[1] for r in K00.queue(conn)]
    positions = {key: order.index(key) for key in
                 (PREFIX + "CORE", PREFIX + "MID", PREFIX + "LOW")
                 if key in order}
    check("a CORE domain outranks a higher-priority non-core one",
          positions[PREFIX + "CORE"] < positions[PREFIX + "MID"],
          str(positions))
    check("and priority breaks the tie among non-core domains",
          positions[PREFIX + "MID"] < positions[PREFIX + "LOW"], str(positions))

    # Priority is a weight on THIS queue. It is not a boundary on what
    # Engine 7 may discover, and nothing in the schema turns it into one.
    check("no column makes priority restrict discovery",
          conn.execute(
              "select count(*) from information_schema.columns "
              " where table_name='knowledge_domains' "
              "   and column_name in ('discovery_allowed','max_subdomains')"
          ).fetchone()[0] == 0)

    # ==================================================================
    print("\nthe cursor is a row, so a restart resumes")

    K00.progress_row(conn, core)
    K00.advance(conn, core, "SYNTHESIZE", 3)
    saved = conn.execute(
        "select stage::text, passes, items_processed, last_advanced "
        "  from foundation_progress where domain_id=%s::uuid", (core,)).fetchone()
    check("the stage and counts persist", saved[0] == "SYNTHESIZE"
          and saved[1] == 1 and saved[2] == 3, str(saved))

    # A fresh process reads the same row -- which is the whole claim.
    reread = conn.execute(
        "select stage::text from v_foundation_queue where domain_id=%s::uuid",
        (core,)).fetchone()[0]
    check("and the queue reports it back", reread == "SYNTHESIZE", reread)

    K00.advance(conn, core, "GAP", 2)
    totals = conn.execute(
        "select passes, items_processed from foundation_progress "
        " where domain_id=%s::uuid", (core,)).fetchone()
    check("advancing accumulates rather than resetting",
          totals == (2, 5), str(totals))

    # ==================================================================
    print("\na domain that keeps failing is paused, not retried forever")

    for n in range(K00.ERROR_PAUSE_AFTER - 1):
        paused = K00.record_error(conn, low, "EXTRACT", f"FCTEST failure {n}")
        check(f"failure {n + 1} does not pause it", paused is False)
    paused = K00.record_error(conn, low, "EXTRACT", "FCTEST final failure")
    check(f"failure {K00.ERROR_PAUSE_AFTER} pauses the domain", paused is True)

    row = conn.execute(
        "select paused, paused_reason from foundation_progress "
        " where domain_id=%s::uuid", (low,)).fetchone()
    check("and the reason is recorded", row[0] is True and row[1], str(row))
    check("a paused domain leaves the working queue",
          PREFIX + "LOW" not in [r[1] for r in K00.queue(conn)])
    check("but stays visible, with its reason",
          conn.execute("select paused_reason from v_foundation_queue "
                       " where domain_id=%s::uuid", (low,)).fetchone()[0] is not None)

    # The row must EXIST for the constraint to have anything to refuse --
    # an UPDATE matching nothing raises nothing, which would have made this
    # check pass for the wrong reason.
    K00.progress_row(conn, mid)
    expect_error(
        conn,
        "update foundation_progress set paused=true, paused_reason=null "
        " where domain_id=%s::uuid", (mid,),
        "pausing with no reason is refused", "ck_paused_has_reason")

    # ==================================================================
    print("\nlibrary stages are library-wide, not once per domain")

    check("EXTRACT, RESEARCH and SYNTHESIZE are LIBRARY scope",
          {s.name for s in K00.LIBRARY_STAGES}
          == {"EXTRACT", "RESEARCH", "SYNTHESIZE"},
          str([s.name for s in K00.LIBRARY_STAGES]))
    check("CONTROVERSY and GAP are the per-domain ones",
          {s.name for s in K00.DOMAIN_STAGES} == {"CONTROVERSY", "GAP"},
          str([s.name for s in K00.DOMAIN_STAGES]))

    # The bug this split exists to prevent: a claim belongs to a SOURCE, not
    # a domain, so a per-domain extraction queue returns the same item for
    # every domain and three domains "process" one claim.
    plan = K00.plan(conn, 3)
    library_rows = [row for row in plan if row["domain"] == "(library-wide)"]
    check("the plan reports library work exactly once",
          len(library_rows) == 1, str(len(library_rows)))
    domain_stages = {row["stage"] for row in plan
                     if row["domain"] != "(library-wide)"}
    check("and no domain row claims a library stage",
          not (domain_stages & {"EXTRACT", "RESEARCH", "SYNTHESIZE"}),
          str(domain_stages))

    # ==================================================================
    print("\nDISCOVER and INGEST are named, not silently skipped")

    check("both are listed as manual",
          set(K00.MANUAL_STAGES) == {"DISCOVER", "INGEST"},
          str(sorted(K00.MANUAL_STAGES)))
    check("and each says why",
          all(len(v) > 40 for v in K00.MANUAL_STAGES.values()))
    check("neither is an executable stage",
          not ({"DISCOVER", "INGEST"} & {s.name for s in K00.STAGES}),
          str([s.name for s in K00.STAGES]))

    # ==================================================================
    print("\nhard rule 11: IDLE is not COMPLETE, readiness is computed")

    stages = {r[0] for r in conn.execute(
        "select unnest(enum_range(null::foundation_stage))::text").fetchall()}
    check("there is no COMPLETE stage (§70)", "COMPLETE" not in stages,
          str(sorted(stages)))
    check("IDLE exists instead", "IDLE" in stages)

    ready = conn.execute(
        "select core_domains, core_domains_ready, strategies, tests_defined, "
        "       unprovenanced, unretrievable, wave1_foundation_ready "
        "  from v_wave1_readiness").fetchone()
    check("readiness reports all four dimensions at once",
          len(ready) == 7 and ready[0] > 0, str(ready))
    check("WAVE1_FOUNDATION_READY is false while core domains are not ready",
          ready[6] is False and ready[1] < ready[0], str(ready))

    check("readiness is a VIEW, so it cannot be stored stale",
          conn.execute(
              "select count(*) from pg_views where schemaname='public' "
              "  and viewname='v_wave1_readiness'").fetchone()[0] == 1)
    # BASE TABLES only. information_schema.columns includes view columns,
    # so v_wave1_readiness's own output column matched and this check was
    # failing on the very thing it exists to protect.
    check("and no base table carries a readiness flag to contradict it",
          conn.execute(
              "select count(*) from information_schema.columns c "
              "  join information_schema.tables t "
              "    on t.table_schema=c.table_schema and t.table_name=c.table_name "
              " where c.table_schema='public' and t.table_type='BASE TABLE' "
              "   and c.column_name in ('wave1_foundation_ready','is_complete')"
          ).fetchone()[0] == 0)

    # A domain with nothing queued goes IDLE and stays in the queue -- the
    # next source to arrive puts it back to work.
    conn.execute("update foundation_progress set stage='IDLE' "
                 " where domain_id=%s::uuid", (mid,))
    check("an IDLE domain is still queued, not retired",
          PREFIX + "MID" in [r[1] for r in K00.queue(conn)])

    clear(conn)
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("test_foundation: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Load the model rate card into the runtime registry.

config/model_prices.json is the AUTHORED form. `model_prices` is the
RUNTIME form (D30, migration 016) -- what the n8n workflow reads, because
n8n cannot read this repository.

The fourth loader, and deliberately the same shape as load_prompts.py,
load_contracts.py and load_handoffs.py: one writer, idempotent, and a
--check that reports readiness rather than drift.

    python3 scripts/load_prices.py            # load, report what changed
    python3 scripts/load_prices.py --check    # verify only, change nothing

An empty registry is NOT an error. A deployment with no rates configured
prices nothing, cost_usd stays NULL and price_source says UNPRICED -- which
is the honest answer, and the one thing that must never happen is a zero.
"""
from __future__ import annotations

import os
import sys

import psycopg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pricing  # noqa: E402


def dsn() -> str:
    return os.environ["DATABASE_URL"]


def load(conn: psycopg.Connection, check_only: bool = False) -> list[tuple[str, str]]:
    """Sync `model_prices` to config/model_prices.json. Returns (model, action)."""
    authored = pricing.load_prices(force=True)
    source_file = str(pricing.price_file().name)
    actions: list[tuple[str, str]] = []

    existing = {
        (row[0], row[1]): (float(row[2]), float(row[3]), row[4])
        for row in conn.execute(
            "select model_name, modality, input_usd_per_mtok, "
            "       output_usd_per_mtok, active from model_prices").fetchall()
    }

    authored_keys: set[tuple[str, str]] = set()
    for model_name, entry in sorted(authored.items()):
        # One row PER MODALITY (022). A model priced in four modalities that
        # sit 60x apart cannot be represented by one rate, and pretending it
        # can is how an audio embedding gets charged at the text rate.
        for modality, rate in sorted(pricing.modalities_of(entry).items()):
            label = f"{model_name} [{modality}]"
            authored_keys.add((model_name, modality))
            try:
                rates = (float(rate["input_usd_per_mtok"]),
                         float(rate["output_usd_per_mtok"]))
            except (KeyError, TypeError, ValueError):
                # A malformed entry is skipped, not fatal, and not guessed at.
                # pricing._rates() already treats it as no rate; the registry
                # must agree or the two implementations diverge on bad data.
                actions.append((label, "skipped-malformed"))
                continue

            current = existing.get((model_name, modality))
            if current == (rates[0], rates[1], True):
                actions.append((label, "unchanged"))
                continue
            if check_only:
                actions.append((label, "would-load" if current is None
                                else "would-update"))
                continue

            conn.execute(
                """insert into model_prices
                     (model_name, modality, input_usd_per_mtok,
                      output_usd_per_mtok, source_file, active, loaded_at)
                   values (%s,%s,%s,%s,%s,true,now())
                   on conflict (model_name, modality) do update
                      set input_usd_per_mtok = excluded.input_usd_per_mtok,
                          output_usd_per_mtok = excluded.output_usd_per_mtok,
                          source_file = excluded.source_file,
                          active = true,
                          loaded_at = now()""",
                (model_name, modality, rates[0], rates[1], source_file))
            actions.append((label, "loaded" if current is None else "updated"))

    # A rate removed from the file is DEACTIVATED, never deleted: it is the
    # evidence for every cost_events row already priced with it, and
    # deleting it would make a historical cost unexplainable.
    for model_name, modality in sorted(set(existing) - authored_keys):
        if not existing[(model_name, modality)][2]:
            continue
        label = f"{model_name} [{modality}]"
        if check_only:
            actions.append((label, "would-deactivate"))
            continue
        conn.execute(
            "update model_prices set active=false "
            " where model_name=%s and modality=%s", (model_name, modality))
        actions.append((label, "deactivated"))

    return actions


def main() -> int:
    check_only = "--check" in sys.argv
    with psycopg.connect(dsn(), autocommit=True) as conn:
        actions = load(conn, check_only=check_only)
        for model_name, action in actions:
            print(f"  {model_name:32s} {action}")

        rows = conn.execute(
            "select model_name, modality, input_usd_per_mtok, output_usd_per_mtok "
            "  from model_prices where active "
            " order by model_name, modality").fetchall()
        print()
        print(f"ACTIVE RATES  ({len(rows)})")
        for model_name, modality, in_rate, out_rate in rows:
            print(f"  {model_name:24s} {modality:6s} in {in_rate}/Mtok   "
                  f"out {out_rate}/Mtok")
        if not rows:
            print("  none — every call will record UNPRICED with a NULL cost.")

        # The gap, named. UNPRICED is the honest answer when no rate is
        # configured (D30) and it is also invisible: the call still costs
        # money and appears in no total. A configured ROLE with no rate is
        # the case worth saying out loud, because it means the next run of
        # that engine spends money nobody can account for.
        gaps = []
        for role in ("MODEL_ANALYSIS", "MODEL_EXTRACTION", "MODEL_RESEARCH",
                     "MODEL_EMBEDDING", "MODEL_FAST"):
            name = os.environ.get(role, "").strip()
            if not name:
                continue
            # MODEL_EMBEDDING embeds TEXT only (022, D38) and the others are
            # text too, so the question is asked WITH a modality. Asking
            # without one would report a multimodal model as unpriced merely
            # because it is priced in several.
            cost, source = pricing.price_call(name, 1000, 1000, "TEXT")
            if source == pricing.UNPRICED:
                gaps.append((role, name))
        if gaps:
            print()
            print(f"NO RATE CONFIGURED for {len(gaps)} model role(s) in use:")
            for role, name in gaps:
                print(f"  {role:18s} {name}")
            print("  Calls by these roles record UNPRICED with a NULL cost — "
                  "honest, and\n  invisible in every cost total. Add the rate to "
                  f"{pricing.price_file().name}.")

        spent = conn.execute(
            "select model_name, modality, calls from v_unpriced_spend limit 5"
        ).fetchall()
        if spent:
            print()
            print("ALREADY SPENT WITHOUT A RATE (v_unpriced_spend):")
            for name, modality, calls in spent:
                print(f"  {name:24s} {modality:6s} {calls} call(s)")

    changed = [(m, a) for m, a in actions
               if a not in ("unchanged", "skipped-malformed")]
    if check_only and changed:
        print(f"\n{len(changed)} rate(s) differ from {pricing.price_file()}: "
              + ", ".join(f"{m} ({a})" for m, a in changed)
              + "\nRun `python3 scripts/load_prices.py` to load them.",
              file=sys.stderr)
        return 1
    if check_only:
        print(f"\nREADY: registry matches {pricing.price_file()}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Turn token counts into a cost, or say honestly that it cannot.

`cost_events.cost_usd` has existed since migration 001 and nothing has ever
written to it. Step 10b needs it, and the moment a number appears in that
column it has to be defensible.

Two rules:

1. **No model name in logic.** Rates live in `config/model_prices.json`, a
   registry keyed by model name. Adding a model's price is a data edit, the
   same principle as `source_kinds` in D19. Which model runs is still
   decided by the five model ROLES in `.env`.

2. **An unknown price is reported as unknown.** A model with no rate
   returns UNPRICED and a NULL cost, never 0.0. Zero would read as "this
   call was free", which is the one thing it certainly was not, and it
   would quietly corrupt every cost total built on top of it.
   `ck_cost_priced` enforces the pairing in the database.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DEFAULT_PRICE_FILE = REPO / "config" / "model_prices.json"

PROVIDER_REPORTED = "PROVIDER_REPORTED"
PRICE_REGISTRY = "PRICE_REGISTRY"
UNPRICED = "UNPRICED"

_cache: dict[str, Any] | None = None


def price_file() -> Path:
    return Path(os.environ.get("MODEL_PRICE_FILE") or DEFAULT_PRICE_FILE)


def load_prices(force: bool = False) -> dict[str, dict[str, float]]:
    """The rate card. A missing or malformed file means UNPRICED, not a crash.

    Pricing must never be able to stop an engine run: the run is the
    valuable thing and the cost is instrumentation about it.
    """
    global _cache
    if _cache is not None and not force:
        return _cache
    try:
        data = json.loads(price_file().read_text())
        _cache = {k: v for k, v in data.get("prices", {}).items()
                  if not k.startswith("_")}
    except (OSError, json.JSONDecodeError):
        _cache = {}
    return _cache


def _rates(model_name: str) -> tuple[float, float] | None:
    """Env override, then exact match, then longest matching prefix.

    The prefix rule exists so a dated snapshot id resolves to its family
    entry rather than silently going unpriced.
    """
    env_in = os.environ.get("LLM_PRICE_INPUT_PER_MTOK", "").strip()
    env_out = os.environ.get("LLM_PRICE_OUTPUT_PER_MTOK", "").strip()
    if env_in and env_out:
        try:
            return float(env_in), float(env_out)
        except ValueError:
            pass

    prices = load_prices()
    if not model_name:
        return None
    entry = prices.get(model_name)
    if entry is None:
        matches = [k for k in prices if model_name.startswith(k)]
        if not matches:
            return None
        entry = prices[max(matches, key=len)]
    try:
        return (float(entry["input_usd_per_mtok"]),
                float(entry["output_usd_per_mtok"]))
    except (KeyError, TypeError, ValueError):
        return None


def price_call(model_name: str, input_tokens: int, output_tokens: int
               ) -> tuple[float | None, str]:
    """Return (cost_usd, price_source). cost_usd is None when UNPRICED."""
    rates = _rates(model_name or "")
    if rates is None:
        return None, UNPRICED
    in_rate, out_rate = rates
    cost = (input_tokens or 0) / 1_000_000 * in_rate \
         + (output_tokens or 0) / 1_000_000 * out_rate
    return round(cost, 6), PRICE_REGISTRY


def describe() -> str:
    prices = load_prices()
    if not prices:
        return f"price registry: none loaded from {price_file()}"
    return (f"price registry: {len(prices)} model(s) from {price_file()} "
            f"({', '.join(sorted(prices))})")


if __name__ == "__main__":
    print(describe())
    for model in ("claude-sonnet-5", "claude-sonnet-5-20260101", "fixture:fixture"):
        print(f"  {model:32} {price_call(model, 68_437, 12_000)}")

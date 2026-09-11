#!/usr/bin/env python3
"""The single embedding call boundary. TEXT ONLY, by constraint.

BUILD_GUIDE step 17 (K14). DECISIONS.md D34, D38; migrations 018, 022.

Every embedding in this system goes through `embed()`. There is no second
path, for the same reason there is no second `RUN_ENGINE`: the guarantees
below are only guarantees if nothing can go around them.

### K14 embeds TEXT ONLY

Transcripts and extracted document text, never the source media. Measured
rates, supplied 2026-09-10:

| | per 1M tokens |
|---|---|
| TEXT | **$0.20** |
| IMAGE | $0.45 |
| AUDIO | $6.50 |
| VIDEO | $12.00 |

Embedding a podcast's audio instead of its transcript costs **32x** and
produces a worse retrieval index. This is a **cost decision, not a
capability limit** — if multimodal embedding is ever wanted, drop
`ck_embedding_text_only` in a migration that says why, and change this
file deliberately. Until then a non-text payload is refused here, and the
database refuses the cost row too, so neither can happen quietly.

### Three things are checked, and none of them is optional

1. **The payload is text.** `bytes` that are not valid UTF-8 are refused,
   and so is anything carrying a data URL or a media MIME type.
2. **The vector comes back unit-norm** (D34). `gemini-embedding-001`
   truncated to 1536 returns 0.702 and would degrade retrieval silently;
   `trg_embedding_coherent` refuses to store it, and this refuses to
   return it.
3. **The dimension matches the column** (`embedding_dim()`), read from the
   catalog rather than from a constant.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import psycopg

import pricing

MODALITY = "TEXT"
ROLE = "MODEL_EMBEDDING"

# A payload claiming to be any of these is not text, whatever it decodes to.
MEDIA_HINT = re.compile(
    r"^\s*data:(image|audio|video)/|^\s*(image|audio|video)/[a-z0-9.+-]+\s*$",
    re.IGNORECASE)

# Magic bytes for the formats a media file most plausibly arrives as. A
# file that is a PNG is not text merely because it survived a lenient
# decode.
MEDIA_MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"RIFF", b"OggS",
               b"ID3", b"\x1aE\xdf\xa3", b"%PDF", b"fLaC")


class NotText(RuntimeError):
    """The payload is not text. K14 embeds text only (D38)."""


class BadVector(RuntimeError):
    """The provider returned something this system will not store (D34)."""


def dsn() -> str:
    return os.environ["DATABASE_URL"]


def as_text(payload) -> str:
    """The payload as text, or a refusal that says which rule it broke."""
    if isinstance(payload, (bytes, bytearray)):
        raw = bytes(payload)
        if raw.startswith(MEDIA_MAGIC):
            raise NotText(
                "the payload begins with media magic bytes. K14 embeds the "
                "TRANSCRIPT or the extracted text, never the source media: "
                "audio costs 32x text per token and indexes worse (D38).")
        try:
            payload = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise NotText(
                f"the payload is not valid UTF-8 ({exc}). K14 embeds text "
                "only; extract the text first (K08) and embed that.") from exc
    if not isinstance(payload, str):
        raise NotText(
            f"a {type(payload).__name__} is not text. K14 embeds text only.")
    if MEDIA_HINT.search(payload[:200]):
        raise NotText(
            "the payload looks like a media reference (a data: URL or a media "
            "MIME type), not text. Embedding the media instead of its "
            "transcript is a 32x bill for a worse index (D38).")
    if not payload.strip():
        raise NotText("an empty payload has nothing to embed.")
    return payload


def norm(vector: list[float]) -> float:
    return math.sqrt(sum(x * x for x in vector))


def provider(model: str, text: str, dims: int) -> list[float]:
    """The live call. Kept thin; everything interesting is around it."""
    base = os.environ["LLM_BASE_URL"].rstrip("/")
    body = json.dumps({"model": model, "input": text, "dimensions": dims}).encode()
    request = urllib.request.Request(
        f"{base}/embeddings", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ['LLM_API_KEY']}"})
    with urllib.request.urlopen(request, timeout=120) as reply:
        return json.load(reply)["data"][0]["embedding"]


def embed(conn, payload, *, entity_type: str | None = None,
          entity_id: str | None = None, call=None) -> tuple[list[float], str, int]:
    """Embed text. Returns (vector, model, dimension).

    `call` is injected so a suite can drive this exact path without paying
    a provider — the transport is replaced, never the checks (V2).
    """
    text = as_text(payload)

    model = os.environ.get(ROLE, "").strip()
    if not model:
        raise BadVector(
            f"{ROLE} is not set. The embedding model is pinned per column by "
            "the first vector written (D34); it is not a per-call choice.")

    dims = conn.execute("select embedding_dim()").fetchone()[0]
    if not dims:
        raise BadVector(
            "there is no embedding column, so pgvector is absent (D15). "
            "Retrieval runs on metadata and full text; nothing to embed.")

    vector = (call or provider)(model, text, dims)

    if len(vector) != dims:
        raise BadVector(
            f"the provider returned {len(vector)} dimensions and the column is "
            f"{dims}. Storing it would fail trg_embedding_coherent; returning "
            "it would put the mismatch one layer further from where it began.")

    measured = norm(vector)
    tolerance = conn.execute("select embedding_norm_tolerance()").fetchone()[0]
    if abs(measured - 1.0) > tolerance:
        raise BadVector(
            f"the vector has L2 norm {measured:.6f}, not 1. A truncated "
            "vector that was never re-normalised still returns results — just "
            "worse ones, with no error anywhere. gemini-embedding-001 at 1536 "
            "returns 0.702 (D34).")

    # Priced at the TEXT rate because it IS text, asserted above and
    # enforced by ck_embedding_text_only on the row below.
    cost, source = pricing.price_call(model, estimate_tokens(text), 0, MODALITY)
    conn.execute(
        """insert into cost_events
             (operation, model_role, model_name, modality, entity_type,
              entity_id, input_tokens, output_tokens, cost_usd, price_source,
              success)
           values ('EMBEDDING',%s,%s,%s,%s,%s,%s,0,%s,%s,true)""",
        (ROLE, model, MODALITY, entity_type, entity_id,
         estimate_tokens(text), cost, source))
    return vector, model, dims


def estimate_tokens(text: str) -> int:
    """A character estimate, and it says so.

    The embeddings endpoint returns no usage block, so this is an estimate
    and never a measurement. ~4 characters per token is the usual English
    approximation; the measurement report must not quote it as a count.
    """
    return max(1, len(text) // 4)


if __name__ == "__main__":
    with psycopg.connect(dsn(), autocommit=True) as conn:
        print(f"embedding dimension : {conn.execute('select embedding_dim()').fetchone()[0]}")
        print(f"model role          : {ROLE} = {os.environ.get(ROLE, '(unset)')}")
        print(f"modality            : {MODALITY} only (D38)")
        rate = pricing.price_call(os.environ.get(ROLE, ""), 1_000_000, 0, MODALITY)
        print(f"rate per 1M tokens  : {rate}")
        for other in ("IMAGE", "AUDIO", "VIDEO"):
            other_rate = pricing.price_call(os.environ.get(ROLE, ""), 1_000_000, 0, other)
            print(f"  {other:6s} would be    : {other_rate}  (refused before it is priced)")

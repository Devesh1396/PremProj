#!/usr/bin/env python3
"""GATE 4 baseline: the CURRENT grammar, run against Video 14, unchanged.

Read-only. It adds no rule, changes no rule, and imports nothing. It exists
so the "before" number is reproducible rather than remembered, and so the
first run can be compared against a prediction that was committed before it.

    python3 testing/gate4_baseline.py

Every count it prints is derived from `curated_parser.parse()` itself — the
production function — not from a second implementation of what that function
is believed to do (V2).
"""
from __future__ import annotations

import collections
import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import psycopg

import curated_parser as CP

FIXTURE = ROOT / "testing" / "fixtures" / "curated" / "t2d_video14.md"
EXPECTED_SHA = "03b6577d6190dfa53f1f13ea35b0957581fed2fc5dd5764a54841948fffd6bfd"


def main() -> int:
    raw = FIXTURE.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    print(f"fixture      {FIXTURE.relative_to(ROOT)}")
    print(f"bytes        {len(raw)}")
    print(f"sha256       {sha}")
    if sha != EXPECTED_SHA:
        print(f"FIXTURE HASH MISMATCH -- expected {EXPECTED_SHA}")
        return 1
    print("hash         MATCHES the frozen manifest")

    text = raw.decode("utf-8")
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rules = CP.load_rules(conn)
    print(f"rules loaded {len(rules)} active (migration 033, unchanged)\n")

    blocks, cards = CP.parse(text, rules)

    parsed = [b for b in blocks if b.status == "PARSED"]
    review = [b for b in blocks if b.status == "REVIEW_REQUIRED"]
    print("=" * 70)
    print("COUNTS")
    print("=" * 70)
    print(f"structural blocks detected  {len(blocks)}")
    print(f"PARSED                      {len(parsed)}")
    print(f"REVIEW_REQUIRED             {len(review)}")
    print(f"cards produced              {len(cards)}")
    print(f"fields stored               {sum(len(c.fields) for c in cards)}")
    print("provider / model calls      0  (curated_parser makes none; the "
          "module imports no provider)")

    print("\n" + "=" * 70)
    print("RULE USED FOR EVERY PARSED BLOCK")
    print("=" * 70)
    if not parsed:
        print("(none)")
    for b in parsed:
        print(f"  line-ordinal {b.ordinal:>3}  level {b.level}  "
              f"{b.rule.rule_id:<20} {b.raw_heading!r}")

    print("\n" + "=" * 70)
    print("MATCHED A RULE, THEN REFUSED BY attach()")
    print("=" * 70)
    refused = [b for b in review if b.failure_reason
               and "matched a subsection rule" in b.failure_reason]
    if not refused:
        print("(none)")
    for b in refused:
        print(f"  ordinal {b.ordinal:>3}  {b.raw_heading!r}")
        print(f"            {b.failure_reason}")

    print("\n" + "=" * 70)
    print("UNKNOWN HEADINGS / CONSTRUCT FREQUENCIES")
    print("=" * 70)
    fam = collections.Counter()
    for b in review:
        head = b.raw_heading
        key = head.split("—")[0].split("–")[0].strip() if ("—" in head or "–" in head) else head
        fam[f"L{b.level} {key}"] += 1
    for k, n in sorted(fam.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {n:>3}x  {k}")

    print("\n" + "=" * 70)
    print("EVERY REVIEW_REQUIRED BLOCK, WITH ITS BYTE RANGE")
    print("=" * 70)
    for b in review:
        s, e = CP.strip_span(text, b.body_start, b.body_end)
        print(f"  ordinal {b.ordinal:>3}  L{b.level}  "
              f"[{b.heading_start}:{b.body_end}]  body[{s}:{e}]  {b.raw_heading!r}")

    print("\n" + "=" * 70)
    print("SOURCE TEXT NOT OWNED BY ANY STORED FIELD")
    print("=" * 70)
    owned = 0
    for c in cards:
        for f in c.fields:
            owned += f.source_end - f.source_start
    print(f"  document bytes (chars)   {len(text)}")
    print(f"  chars inside a stored field  {owned}")
    print(f"  chars owned by NO field      {len(text) - owned}")
    print("  Every one of those chars is inside a REVIEW_REQUIRED block listed")
    print("  above, with its heading and range. None is silently discarded.")

    print("\n" + "=" * 70)
    print("AMBIGUOUS OWNERSHIP")
    print("=" * 70)
    amb = [b for b in blocks if b.parent_ordinal is not None]
    print(f"  subsections attached to a card: {len(amb)}")
    for b in amb:
        print(f"    {b.raw_heading!r} -> ordinal {b.parent_ordinal}")

    print("\n" + "=" * 70)
    print("TRANSFORMED TEXT")
    print("=" * 70)
    trans = [f for c in cards for f in c.fields
             if f.provenance != "VERBATIM_SOURCE"]
    print(f"  fields not VERBATIM_SOURCE: {len(trans)}")

    print("\n" + "=" * 70)
    print("PRESERVATION CHECK ON WHAT DID PARSE")
    print("=" * 70)
    problems = CP.verify(text, [f for c in cards for f in c.fields])
    print(f"  verify() problems: {len(problems)}")
    for p in problems:
        print(f"    {p}")

    print("\n" + "=" * 70)
    print("CARDS PRODUCED")
    print("=" * 70)
    for c in cards:
        print(f"  {c.kind} {c.name!r}  span[{c.source_start}:{c.source_end}]  "
              f"name_span[{c.name_start}:{c.name_end}]")
        for f in c.fields:
            print(f"      {f.field_name}  [{f.source_start}:{f.source_end}]  "
                  f"{f.provenance}")
            print(f"        {f.text_value[:160]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Structural survey of a curated document. READ ONLY. NO MODEL.

    python3 scripts/curated_survey.py <file.md> [--after "<heading>"]

This is NOT ingestion. It writes nothing to the knowledge library, creates
no envelope, no block, no field, no concept and no grammar rule. It opens a
file, counts shapes, and prints. The only database access is an OPTIONAL
read of `curated_grammar_rules` to report which headings the CURRENT
grammar would already match; with no `DATABASE_URL` that section degrades
to a named skip (V3) and everything else still runs.

It reports STRUCTURE, never meaning. It does not say what a section is
about, does not group headings by topic, and does not propose rules. A
family here is a repeated SYNTACTIC shape -- same prefix token, same
level, same punctuation -- and nothing more.

Why it exists: GATE 4 recommended a structural survey of the corpus after
the recognised `Video N` region before any corpus-wide rule estimate,
because two samples from inside that region cannot describe material
outside it.
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import sys
from pathlib import Path

HEADING = re.compile(r'^(?P<hashes>#{1,6})[ \t]+(?P<text>.*\S)[ \t]*$', re.M)

# A "prefix token" is the leading run before a dash/colon separator. It is
# a SYNTACTIC observation -- the shape `WORD — rest` -- not a claim that
# the word means anything.
PREFIX = re.compile(r'^(?P<prefix>[A-Za-z][A-Za-z0-9 /]{0,24}?)\s*[—–:-]\s+\S')

# A prose region with no heading at all. 1,200 characters is roughly a
# page of text; it is a REPORTING bucket, not a threshold anything branches
# on, and the raw distribution is printed beside it.
LARGE_GAP = 1200


def headings(text: str):
    out = []
    ms = list(HEADING.finditer(text))
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        out.append({
            "level": len(m.group("hashes")),
            "text": m.group("text").strip(),
            "start": m.start(),
            "body_start": m.end(),
            "end": end,
        })
    return out


def shape(h: str) -> str:
    """A heading reduced to its SYNTACTIC skeleton.

    Words become W, numbers N, and separators are kept. `Strategy 1 —
    Breakfast restructuring` and `Strategy 4 — Meal-linked movement` both
    become `W N — W W`, so identical constructs collapse and genuinely
    different ones do not.
    """
    toks = []
    for t in h.split():
        if re.fullmatch(r'\d+[.)]?', t):
            toks.append("N")
        elif t in ("—", "–", "-", ":", "/", "|"):
            toks.append(t)
        else:
            toks.append("W")
    return " ".join(toks)


def survey(path: Path, after: str | None) -> int:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    hs = headings(text)

    region_note = ""
    if after:
        idx = next((i for i, h in enumerate(hs)
                    if after.lower() in h["text"].lower()), None)
        if idx is None:
            print(f"--after {after!r} matched no heading; surveying the whole file")
        else:
            cut = hs[idx]["end"]
            text = text[cut:]
            hs = [h for h in headings(text)]
            region_note = f"  (region AFTER the heading matching {after!r})"

    words = len(text.split())
    print("=" * 70)
    print(f"STRUCTURAL SURVEY — {path.name}{region_note}")
    print("=" * 70)
    print(f"  characters {len(text):>8}")
    print(f"  words      {words:>8}")
    print(f"  headings   {len(hs):>8}")
    if not hs:
        print("\n  NO HEADINGS AT ALL. This region is prose-only and a heading")
        print("  grammar has nothing to attach to.")
        return 0
    print(f"  words per heading (mean) {words / len(hs):>8.1f}")

    print("\n-- heading LEVELS " + "-" * 51)
    lv = collections.Counter(h["level"] for h in hs)
    for k in sorted(lv):
        print(f"  L{k}  {lv[k]:>5}")

    print("\n-- NESTING SHAPES (parent level -> child level) " + "-" * 22)
    pairs = collections.Counter()
    for a, b in zip(hs, hs[1:]):
        pairs[(a["level"], b["level"])] += 1
    for (a, b), n in sorted(pairs.items(), key=lambda kv: -kv[1])[:10]:
        print(f"  L{a} -> L{b}   {n:>5}")

    print("\n-- REPEATED PREFIX TOKENS (syntactic, before a dash/colon) " + "-" * 11)
    pref = collections.Counter()
    for h in hs:
        m = PREFIX.match(h["text"])
        if m:
            pref[(h["level"], m.group("prefix").strip().upper())] += 1
    if not pref:
        print("  (none)")
    for (l, p), n in sorted(pref.items(), key=lambda kv: (-kv[1], kv[0])):
        if n >= 2:
            print(f"  {n:>5}x  L{l}  {p!r}")
    singles = sum(1 for v in pref.values() if v == 1)
    print(f"  ...plus {singles} prefix token(s) seen exactly once")

    print("\n-- SYNTACTIC SHAPE FAMILIES " + "-" * 42)
    sh = collections.Counter((h["level"], shape(h["text"])) for h in hs)
    rep = [(k, v) for k, v in sh.items() if v >= 2]
    one = [(k, v) for k, v in sh.items() if v == 1]
    print(f"  distinct shapes {len(sh)};  repeated {len(rep)};  one-offs {len(one)}")
    covered = sum(v for _, v in rep)
    print(f"  headings inside a REPEATED shape: {covered} of {len(hs)}"
          f"  ({100.0 * covered / len(hs):.0f}%)")
    for (l, s), n in sorted(rep, key=lambda kv: -kv[1])[:12]:
        print(f"  {n:>5}x  L{l}  {s}")

    print("\n-- EXACT HEADING TEXT REPEATED " + "-" * 39)
    txt = collections.Counter(h["text"] for h in hs)
    rep_txt = [(t, n) for t, n in txt.items() if n >= 2]
    if not rep_txt:
        print("  (none)")
    for t, n in sorted(rep_txt, key=lambda kv: -kv[1])[:15]:
        print(f"  {n:>5}x  {t[:60]!r}")

    print("\n-- REPEATED SECTION TEMPLATES (a parent's child-heading set) " + "-" * 9)
    tmpl = collections.Counter()
    for i, h in enumerate(hs):
        kids = []
        for j in range(i + 1, len(hs)):
            if hs[j]["level"] <= h["level"]:
                break
            if hs[j]["level"] == h["level"] + 1:
                kids.append(hs[j]["text"])
        if kids:
            tmpl[tuple(kids)] += 1
    rep_t = [(k, v) for k, v in tmpl.items() if v >= 2]
    print(f"  distinct child-sets {len(tmpl)};  repeated {len(rep_t)}")
    for k, v in sorted(rep_t, key=lambda kv: -kv[1])[:6]:
        print(f"  {v:>5}x  {list(k)[:5]}")

    print("\n-- PROSE REGIONS WITH NO HEADING " + "-" * 37)
    gaps = sorted((h["end"] - h["body_start"]) for h in hs)
    big = [g for g in gaps if g >= LARGE_GAP]
    print(f"  body-length distribution (chars): min {gaps[0]}, "
          f"median {gaps[len(gaps)//2]}, max {gaps[-1]}")
    print(f"  bodies >= {LARGE_GAP} chars: {len(big)}  "
          f"({100.0 * len(big) / len(gaps):.0f}% of headings), "
          f"holding {sum(big)} chars "
          f"({100.0 * sum(big) / len(text):.0f}% of the region)")

    print("\n-- WHAT THE CURRENT GRAMMAR WOULD ALREADY MATCH " + "-" * 22)
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("  SKIP  curated_grammar_rules is not available — DATABASE_URL is "
              "not set, so rule coverage cannot be reported. Every section "
              "above is unaffected.")
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import psycopg
        import curated_parser as CP
        with psycopg.connect(dsn) as conn:
            rules = CP.load_rules(conn)
        hit = collections.Counter()
        miss = 0
        for h in hs:
            for r in rules:
                if r.heading_level and r.heading_level != h["level"]:
                    continue
                if r.regex.match(h["text"]):
                    hit[r.rule_id] += 1
                    break
            else:
                miss += 1
        matched = sum(hit.values())
        print(f"  matched by a rule: {matched} of {len(hs)} "
              f"({100.0 * matched / len(hs):.0f}%)")
        for rid, n in sorted(hit.items(), key=lambda kv: -kv[1]):
            print(f"    {n:>5}x  {rid}")
        print(f"  matched by NOTHING: {miss}")
        print("  NOTE: a pattern match is not ownership. A subsection rule can")
        print("  match and still be refused by attach() for want of an owner.")

    print("\n" + "=" * 70)
    print("Structure only. No heading above was interpreted, grouped by")
    print("meaning, or turned into a rule. Nothing was written anywhere.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", type=Path)
    ap.add_argument("--after", default=None,
                    help="survey only the region AFTER the first heading "
                         "containing this text")
    a = ap.parse_args()
    if not a.path.exists():
        print(f"no such file: {a.path}")
        return 2
    return survey(a.path, a.after)


if __name__ == "__main__":
    raise SystemExit(main())

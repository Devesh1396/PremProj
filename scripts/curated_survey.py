#!/usr/bin/env python3
"""Structural survey of a FLAT curated corpus. READ ONLY. NO MODEL.

    python3 scripts/curated_survey.py <file> [<file> ...]

Accepts `.md` and `.docx`. Several files may be given, and SHOULD be,
because the most important finding -- a label that means different things
in different containers -- only appears across sections.

### What changed, and why (D57)

The previous survey reported Markdown heading LEVELS, level-to-level
nesting transitions and parent/child level templates. The canonical source
states no level anywhere (0 Heading styles, 0 `w:outlineLvl` across 13,763
paragraphs); the fixture levels were assigned by a Claude model during
conversion. A survey built on them was describing the converter, and
presenting it as corpus structure.

This survey reports NO DEPTH OF ANY KIND. A Markdown heading's `#` count is
discarded on read. A `.docx` paragraph is a CANDIDATE BOUNDARY only if it
is bold-only, and bold never assigns a level -- in the real source the
longest bold-only paragraph is 838 characters, which is body prose.

### It reuses the production grammar rather than copying it

Candidates become `curated_parser.Block` objects and go through the REAL
`classify()`, `attach()` and `derive_paths()`. A survey with its own
matching logic would report what a second implementation believes the
grammar does (V2).

### What it writes

Nothing. No envelope, block, field, concept or rule. Its only database
access is a READ of `curated_grammar_rules`; with no `DATABASE_URL` the
rule-dependent sections degrade to a named skip and the signal counts
still print.
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import curated_parser as CP

MD_HEADING = re.compile(r'^#{1,6}[ \t]+(?P<text>.*\S)[ \t]*$')
MD_LIST = re.compile(r'^\s*(?:[-*+]|\d+[.)])\s+\S')
MD_BOLD_LINE = re.compile(r'^\s*\*\*[^*]+\*\*\s*$')


def md_candidates(path: Path) -> tuple[list[CP.Block], dict]:
    """Every Markdown heading LINE is a candidate. Its depth is DISCARDED."""
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks: list[CP.Block] = []
    sig = {"lines": len(lines), "list_items": 0, "bold_only_lines": 0,
           "candidate_signal": "MARKDOWN_HEADING_MARKER (depth discarded)"}
    for i, line in enumerate(lines):
        if MD_LIST.match(line):
            sig["list_items"] += 1
        if MD_BOLD_LINE.match(line):
            sig["bold_only_lines"] += 1
        m = MD_HEADING.match(line)
        if m:
            t = m.group("text").strip()
            # level=0 for every candidate: there is no depth to carry.
            blocks.append(CP.Block(ordinal=len(blocks), level=0, raw_heading=t,
                                   heading_path=t, heading_start=i,
                                   body_start=i, body_end=i))
    return blocks, sig


def docx_candidates(path: Path) -> tuple[list[CP.Block], dict]:
    """Every BOLD-ONLY paragraph is a candidate boundary. Never a level."""
    import docx_structure as DX
    r = DX.analyse(path)
    blocks = [CP.Block(ordinal=i, level=0, raw_heading=t, heading_path=t,
                       heading_start=i, body_start=i, body_end=i)
              for i, t in enumerate(r["bold_texts"])]
    sig = {"paragraphs": r["paragraphs"],
           "heading_styled": sum(r["styled_headings"].values()),
           "outline_levels": sum(r["outline_levels"].values()),
           "numbered": r["numbered_paragraphs"],
           "numbered_by_format": dict(r["numbered_by_format"]),
           "bold_only": r["bold_only_paragraphs"],
           "bold_direct": r["bold_direct"],
           "bold_via_paragraph_style": r["bold_inherited"],
           "bold_lengths": r["bold_lengths"],
           "conflicting_signals": len(r["conflicting_signals"]),
           "candidate_signal": "BOLD_ONLY_PARAGRAPH (candidate boundary, NOT a heading)"}
    return blocks, sig


def survey(paths: list[Path]) -> int:
    rules = None
    dsn = os.environ.get("DATABASE_URL")
    if dsn:
        import psycopg
        with psycopg.connect(dsn) as conn:
            rules = CP.load_rules(conn)

    # label (case-folded) -> {container kind or None} across ALL files
    label_contexts: dict[str, dict] = collections.defaultdict(
        lambda: collections.Counter())
    label_forms: dict[str, str] = {}
    label_files: dict[str, set] = collections.defaultdict(set)

    for path in paths:
        suffix = path.suffix.lower()
        if suffix == ".docx":
            blocks, sig = docx_candidates(path)
        else:
            blocks, sig = md_candidates(path)

        print("=" * 70)
        print(f"FLAT STRUCTURAL SURVEY — {path.name}")
        print("=" * 70)
        print("  NO DEPTH IS REPORTED. The source states no heading level, so")
        print("  any depth a converter emitted is not corpus structure.")
        print(f"\n-- SIGNALS {'-' * 58}")
        for k, v in sig.items():
            if k == "bold_lengths":
                if v:
                    bl = sorted(v)
                    print(f"  {'bold paragraph lengths':<28} min {bl[0]}, "
                          f"median {bl[len(bl)//2]}, max {bl[-1]}")
                continue
            print(f"  {k:<28} {v}")

        print(f"\n-- CANDIDATE LABELS, IN ORDER {'-' * 40}")
        print(f"  {len(blocks)} candidate(s)")
        for b in blocks[:12]:
            print(f"    {b.ordinal:>4}  {b.raw_heading[:62]!r}")
        if len(blocks) > 12:
            print(f"    ... {len(blocks) - 12} more")

        forms = collections.Counter(b.raw_heading for b in blocks)
        rep = [(t, n) for t, n in forms.items() if n > 1]
        print(f"\n-- EXACT LABEL FORMS REPEATED {'-' * 40}")
        print(f"  distinct {len(forms)};  repeated {len(rep)};  "
              f"once-only {len(forms) - len(rep)}")
        for t, n in sorted(rep, key=lambda kv: -kv[1])[:12]:
            print(f"    {n:>4}x  {t[:60]!r}")

        if rules is None:
            print("\n  SKIP  curated_grammar_rules is not available — DATABASE_URL "
                  "is not set, so rule matches, containers and cross-container "
                  "label recurrence cannot be reported. Signals above are "
                  "unaffected.")
            continue

        # THE PRODUCTION GRAMMAR, not a copy of it.
        CP.classify(blocks, rules)
        CP.attach(blocks)
        CP.derive_paths(blocks)

        hit = collections.Counter(b.rule.rule_id for b in blocks if b.rule)
        print(f"\n-- REGISTERED-RULE MATCHES {'-' * 44}")
        print(f"  recognised {sum(hit.values())} of {len(blocks)}")
        for rid, n in sorted(hit.items(), key=lambda kv: -kv[1]):
            print(f"    {n:>4}x  {rid}")

        unrec = collections.Counter(b.raw_heading for b in blocks
                                    if b.status == "REVIEW_REQUIRED")
        print(f"\n-- UNRECOGNISED CANDIDATES {'-' * 44}")
        print(f"  {sum(unrec.values())} unrecognised, {len(unrec)} distinct form(s)")
        for t, n in sorted(unrec.items(), key=lambda kv: -kv[1])[:10]:
            print(f"    {n:>4}x  {t[:60]!r}")

        print(f"\n-- RECOGNISED CONTAINER -> FOLLOWING REGISTERED LABELS {'-' * 15}")
        seqs = collections.Counter()
        by_ord = {b.ordinal: b for b in blocks}
        kids: dict[int, list[str]] = collections.defaultdict(list)
        for b in blocks:
            if b.parent_ordinal is not None:
                kids[b.parent_ordinal].append(b.rule.rule_id)
        for b in blocks:
            if b.status == "PARSED" and b.block_kind in CP.CONTAINER_KINDS:
                seqs[(b.block_kind, tuple(kids.get(b.ordinal, [])))] += 1
        for (k, seq), n in sorted(seqs.items(), key=lambda kv: -kv[1])[:10]:
            print(f"    {n:>4}x  {k:<15} -> {list(seq) if seq else '(none)'}")

        # Record, for the cross-file check, every candidate whose text is a
        # REGISTERED subsection label -- owned or not -- with the kind of
        # container that was open when the parser reached it.
        for b in blocks:
            sub = [r for r in b.candidates if r.block_kind == "SUBSECTION"]
            if not sub:
                continue
            key = b.raw_heading.casefold()
            label_forms.setdefault(key, b.raw_heading)
            label_contexts[key][b.context_kind or "NONE"] += 1
            label_files[key].add(path.name)

    if rules is None:
        return 0

    print("\n" + "=" * 70)
    print("LABELS WHOSE SURFACE FORM RECURS IN MORE THAN ONE KIND OF CONTAINER")
    print("=" * 70)
    print("  Under the flat design a label is the ONLY structural signal, so a")
    print("  label seen in two kinds of container may carry two meanings. Each")
    print("  one below needs a practitioner decision before it maps to a single")
    print("  field. This list does NOT judge meaning; it finds the candidates.")
    flagged = 0
    for key, ctx in sorted(label_contexts.items()):
        kinds = {k for k in ctx if k != "NONE"}
        if len(kinds) > 1:
            flagged += 1
            print(f"\n  {label_forms[key]!r}")
            for k, n in sorted(ctx.items()):
                print(f"      {n:>3}x  inside {k}")
            print(f"      files: {', '.join(sorted(label_files[key]))}")
    if not flagged:
        print("\n  (none across the files given)")
    print(f"\n  {flagged} label(s) flagged")
    print("\n" + "=" * 70)
    print("Structure only. No depth reported, no meaning interpreted, no rule")
    print("proposed, nothing written.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", type=Path, nargs="+")
    a = ap.parse_args()
    for p in a.paths:
        if not p.exists():
            print(f"no such file: {p}")
            return 2
    return survey(a.paths)


if __name__ == "__main__":
    raise SystemExit(main())

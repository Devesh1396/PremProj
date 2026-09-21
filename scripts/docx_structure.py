#!/usr/bin/env python3
"""Report which structural signals a .docx actually carries. READ ONLY.

    python3 scripts/docx_structure.py <file.docx>

NO MODEL. NO DEPENDENCY -- zipfile and xml.etree from the standard
library. It writes nothing: no markdown, no envelope, no library row. It
opens the package, counts signals, and prints.

### Why this is not a heading reader

The canonical source was inspected directly and carries NO hierarchy:
0 paragraphs with a Heading style, 0 `w:outlineLvl` anywhere, no numbering
on headings, and 3,979 short bold paragraphs whose formatting is
byte-identical whether the author meant a section or a subsection.

So the `##` and `###` levels in the Video 1 and Video 14 markdown fixtures
DO NOT EXIST IN THE SOURCE -- they appeared during conversion. A tool that
reads Word heading styles would pass against a synthetic Heading 1/2/3
document and find nothing at all in the real one: a harness that differs
from production, built on purpose (V2).

### What it therefore refuses to do

**It never infers a level.** Not from bold, not from length, not from
capitalisation, not from a following blank line, not from font size. Where
the document states a level -- a Heading style, or an explicit
`w:outlineLvl` -- it reports that level. Where it does not, it says
`NO HEADING HIERARCHY` and assigns nothing.

Reporting "this document has no heading hierarchy" is the CORRECT AND
COMPLETE output for such a document, not a failure to try harder. How the
corpus acquires a hierarchy is the practitioner's decision; see
`docs/evidence/gate4_docx_structure.md`.
"""
from __future__ import annotations

import argparse
import collections
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# A style id or name that Word uses for a heading. Matched on the STYLE,
# which is an authored statement of level -- never on the text.
HEADING_STYLE = re.compile(r"^heading\s*([1-9])$", re.I)


def _text(p) -> str:
    return "".join(t.text or "" for t in p.iter(f"{W}t"))


def heading_styles(z: zipfile.ZipFile) -> dict[str, int]:
    """styleId -> level, for styles that DECLARE they are headings."""
    out: dict[str, int] = {}
    try:
        root = ET.fromstring(z.read("word/styles.xml"))
    except KeyError:
        return out
    for st in root.iter(f"{W}style"):
        sid = st.get(f"{W}styleId") or ""
        name_el = st.find(f"{W}name")
        name = (name_el.get(f"{W}val") if name_el is not None else "") or ""
        lvl = None
        for candidate in (sid, name):
            m = HEADING_STYLE.match(candidate.strip())
            if m:
                lvl = int(m.group(1))
                break
        ol = st.find(f"./{W}pPr/{W}outlineLvl")
        if ol is not None and ol.get(f"{W}val") is not None:
            lvl = int(ol.get(f"{W}val")) + 1
        if lvl is not None:
            out[sid] = lvl
    return out


def analyse(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        styles = heading_styles(z)
        root = ET.fromstring(z.read("word/document.xml"))

    body = root.find(f"{W}body")
    paras = list(body.iter(f"{W}p")) if body is not None else []

    r = {
        "paragraphs": len(paras),
        "empty_paragraphs": 0,
        "styled_headings": collections.Counter(),   # level -> n
        "outline_levels": collections.Counter(),    # level -> n
        "numbered_paragraphs": 0,
        "bold_only_paragraphs": 0,
        # LENGTHS, NOT A THRESHOLDED COUNT. An earlier draft bucketed
        # "short" bold paragraphs at <= 120 characters, and the suite's own
        # no-inference guard caught it: a length threshold is a number that
        # can be moved until a fixture passes, and it has no business in a
        # tool whose whole contract is that it does not guess. The raw
        # distribution carries the same information and decides nothing.
        "bold_lengths": [],
        "font_sizes": collections.Counter(),
        "levels_assigned": [],                      # (level, text)
        "bold_texts": [],
    }

    for p in paras:
        txt = _text(p).strip()
        if not txt:
            r["empty_paragraphs"] += 1
            continue

        pPr = p.find(f"{W}pPr")
        level = None

        if pPr is not None:
            st = pPr.find(f"{W}pStyle")
            if st is not None and st.get(f"{W}val") in styles:
                level = styles[st.get(f"{W}val")]
                r["styled_headings"][level] += 1
            ol = pPr.find(f"{W}outlineLvl")
            if ol is not None and ol.get(f"{W}val") is not None:
                lv = int(ol.get(f"{W}val")) + 1
                r["outline_levels"][lv] += 1
                level = level or lv
            if pPr.find(f"{W}numPr") is not None:
                r["numbered_paragraphs"] += 1
            for sz in pPr.iter(f"{W}sz"):
                if sz.get(f"{W}val"):
                    r["font_sizes"][sz.get(f"{W}val")] += 1

        runs = [x for x in p.iter(f"{W}r")]
        bold = bool(runs) and all(
            x.find(f"./{W}rPr/{W}b") is not None for x in runs)
        if bold:
            r["bold_only_paragraphs"] += 1
            r["bold_lengths"].append(len(txt))
            r["bold_texts"].append(txt)

        # A LEVEL IS ONLY EVER RECORDED WHEN THE DOCUMENT STATED ONE.
        if level is not None:
            r["levels_assigned"].append((level, txt))

    return r


def report(path: Path) -> int:
    r = analyse(path)
    print("=" * 68)
    print(f"DOCX STRUCTURAL SIGNALS — {path.name}")
    print("=" * 68)
    print(f"  paragraphs                  {r['paragraphs']:>6}")
    print(f"  empty paragraphs            {r['empty_paragraphs']:>6}")
    print(f"  paragraphs w/ Heading style {sum(r['styled_headings'].values()):>6}")
    for lv in sorted(r["styled_headings"]):
        print(f"      level {lv}                 {r['styled_headings'][lv]:>6}")
    print(f"  explicit w:outlineLvl       {sum(r['outline_levels'].values()):>6}")
    print(f"  numbered paragraphs (numPr) {r['numbered_paragraphs']:>6}")
    print(f"  bold-only paragraphs        {r['bold_only_paragraphs']:>6}")
    if r["bold_lengths"]:
        bl = sorted(r["bold_lengths"])
        print(f"    their lengths (chars)     min {bl[0]}, "
              f"median {bl[len(bl)//2]}, max {bl[-1]}")
    print(f"  distinct font sizes declared{len(r['font_sizes']):>6}"
          f"   {dict(r['font_sizes']) if r['font_sizes'] else ''}")

    print("\n  VERDICT")
    if r["levels_assigned"]:
        print(f"    HIERARCHY PRESENT — {len(r['levels_assigned'])} paragraph(s) "
              "carry an authored level.")
        for lv, t in r["levels_assigned"][:12]:
            print(f"      L{lv}  {t[:60]!r}")
    else:
        print("    NO HEADING HIERARCHY.")
        print("    This document states no level anywhere: no Heading style, no")
        print("    w:outlineLvl, no heading numbering. NO LEVEL HAS BEEN")
        print("    ASSIGNED, and none will be inferred from bold, length,")
        print("    capitalisation, font size or spacing.")
        if r["bold_only_paragraphs"]:
            print(f"\n    {r['bold_only_paragraphs']} bold-only paragraph(s) are "
                  "present and are reported as a SIGNAL, not a level:")
            for t in r["bold_texts"][:8]:
                print(f"      bold  {t[:60]!r}")
            print("    Whether these are sections, subsections or emphasis is")
            print("    not stated by the document and is not guessed here.")
    print("=" * 68)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", type=Path)
    a = ap.parse_args()
    if not a.path.exists():
        print(f"no such file: {a.path}")
        return 2
    return report(a.path)


if __name__ == "__main__":
    raise SystemExit(main())

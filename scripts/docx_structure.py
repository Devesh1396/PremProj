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


def numbering_formats(z: zipfile.ZipFile) -> dict[str, str]:
    """numId -> the numbering FORMAT the document declares for it.

    Opened because the earlier version reported 351 numbered paragraphs and
    then printed "no heading numbering" -- a conclusion drawn from the
    PRESENCE of `w:numPr` without ever looking at what the numbering was.
    A count of numbered paragraphs says nothing about whether the numbering
    expresses a heading hierarchy, and the verdict claimed it did not.
    """
    out: dict[str, str] = {}
    try:
        root = ET.fromstring(z.read("word/numbering.xml"))
    except KeyError:
        return out
    # abstractNumId -> {ilvl: numFmt}
    abstract: dict[str, dict[str, str]] = {}
    for a in root.iter(f"{W}abstractNum"):
        aid = a.get(f"{W}abstractNumId")
        lv: dict[str, str] = {}
        for l in a.iter(f"{W}lvl"):
            fmt = l.find(f"{W}numFmt")
            if fmt is not None and fmt.get(f"{W}val"):
                lv[l.get(f"{W}ilvl") or "0"] = fmt.get(f"{W}val")
        abstract[aid] = lv
    for n in root.iter(f"{W}num"):
        nid = n.get(f"{W}numId")
        ab = n.find(f"{W}abstractNumId")
        if ab is not None:
            out[nid] = ",".join(
                f"L{k}:{v}" for k, v in sorted(abstract.get(ab.get(f"{W}val"), {}).items()))
    return out


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


def bold_style_ids(z: zipfile.ZipFile) -> set[str]:
    """Paragraph styles that DIRECTLY declare bold in their own `w:rPr`.

    Without this, a document whose headings are bold via a style rather
    than via direct run formatting reports zero bold paragraphs.

    SCOPE, STATED NARROWLY. This reads only the bold a style declares
    itself. It does NOT follow `w:basedOn` chains, does NOT read
    `w:docDefaults`, and does NOT resolve character styles (`w:rStyle`) or
    table styles. So "inherited" in this reader means "declared by the
    paragraph's own selected style" and nothing more. A style that is bold
    only because its parent is will be counted as not bold, and the report
    must not be read as claiming full style resolution.
    """
    out: set[str] = set()
    try:
        root = ET.fromstring(z.read("word/styles.xml"))
    except KeyError:
        return out
    for st in root.iter(f"{W}style"):
        b = st.find(f"./{W}rPr/{W}b")
        if b is not None and b.get(f"{W}val") not in ("0", "false"):
            out.add(st.get(f"{W}styleId") or "")
    return out


def run_is_bold(run) -> bool | None:
    """True if the run states bold, False if it states NOT bold, None if silent."""
    b = run.find(f"./{W}rPr/{W}b")
    if b is None:
        return None
    return b.get(f"{W}val") not in ("0", "false")


def analyse(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        styles = heading_styles(z)
        numbering = numbering_formats(z)
        bold_styles = bold_style_ids(z)
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
        "bold_direct": 0,              # bold stated on the runs themselves
        "bold_inherited": 0,           # bold coming from the paragraph style
        "bold_explicitly_off": 0,      # <w:b w:val="0"/> -- NOT bold
        "numbering_formats": {},
        "numbered_by_format": collections.Counter(),
        "conflicting_signals": [],
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
        # Per paragraph, deliberately. `num` used to be assigned only inside
        # the `pPr is not None` branch and read after it. That was not a
        # live crash -- `level` is only set in the same branch, so the later
        # `level is not None and num is not None` short-circuits first for a
        # paragraph with no pPr -- but it carried the PREVIOUS paragraph's
        # value across iterations, a stale-value hazard one refactor away
        # from a wrong conflict report.
        num = None

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
            num = pPr.find(f"{W}numPr")
            if num is not None:
                r["numbered_paragraphs"] += 1
                nid = num.find(f"{W}numId")
                key = nid.get(f"{W}val") if nid is not None else None
                r["numbered_by_format"][numbering.get(key, "UNDECLARED")] += 1

        # FONT SIZE, read where it is actually declared: on the RUNS, not
        # on pPr. The earlier version searched pPr and reported "0 distinct
        # font sizes" for every document, which was a fact about where it
        # looked.
        for sz in p.iter(f"{W}sz"):
            if sz.get(f"{W}val"):
                r["font_sizes"][sz.get(f"{W}val")] += 1

        runs = [x for x in p.iter(f"{W}r")]
        direct = bool(runs) and all(run_is_bold(x) is True for x in runs)
        # `<w:b w:val="0"/>` is bold turned OFF. The earlier version tested
        # only that the element EXISTED, so an explicit off would have been
        # counted as bold. The real source contains none, so its 4,207
        # stands -- but a document that used them would have been miscounted.
        turned_off = any(run_is_bold(x) is False for x in runs)
        if turned_off:
            r["bold_explicitly_off"] += 1

        st_el = pPr.find(f"{W}pStyle") if pPr is not None else None
        inherited = (st_el is not None
                     and st_el.get(f"{W}val") in bold_styles
                     and not turned_off
                     and bool(runs)
                     and all(run_is_bold(x) is not False for x in runs))

        bold = direct or inherited
        if bold:
            r["bold_direct" if direct else "bold_inherited"] += 1
        if bold:
            r["bold_only_paragraphs"] += 1
            r["bold_lengths"].append(len(txt))
            r["bold_texts"].append(txt)

        # A LEVEL IS ONLY EVER RECORDED WHEN THE DOCUMENT STATED ONE.
        if level is not None:
            r["levels_assigned"].append((level, txt))

        # CONFLICTING SIGNALS ARE REPORTED, NOT SILENTLY RESOLVED. A
        # paragraph that is both styled a heading and explicitly numbered,
        # or styled a heading while its runs turn bold off, is telling two
        # stories; picking one quietly is how a reader starts inventing.
        flags = []
        if level is not None and num is not None:
            flags.append("heading level AND list numbering")
        if level is not None and turned_off:
            flags.append("heading style AND bold explicitly off")
        if flags:
            r["conflicting_signals"].append((txt[:60], "; ".join(flags)))

    r["numbering_formats"] = dict(numbering)
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
    for fmt, n in sorted(r["numbered_by_format"].items(), key=lambda kv: -kv[1]):
        print(f"      {n:>6}  numFmt {fmt}")
    if r["numbering_formats"]:
        print(f"      numbering.xml declares {len(r['numbering_formats'])} "
              "numId definition(s)")
    print(f"  bold paragraphs             {r['bold_only_paragraphs']:>6}")
    print(f"      direct run formatting   {r['bold_direct']:>6}")
    print(f"      via paragraph's own style {r['bold_inherited']:>4}"
          "   (declared by that style; basedOn/docDefaults NOT resolved)")
    print(f"      bold explicitly OFF     {r['bold_explicitly_off']:>6}"
          "   (w:val=0/false; not counted as bold)")
    if r["bold_lengths"]:
        bl = sorted(r["bold_lengths"])
        print(f"    their lengths (chars)     min {bl[0]}, "
              f"median {bl[len(bl)//2]}, max {bl[-1]}")
    if r["font_sizes"]:
        print(f"  font sizes declared on runs {len(r['font_sizes']):>6}"
              f"   {dict(r['font_sizes'])}")
    else:
        print("  font sizes                  none declared on any run "
              "(inherited from styles; not resolved here)")

    if r["conflicting_signals"]:
        print(f"\n  CONFLICTING SIGNALS         {len(r['conflicting_signals']):>6}")
        for t, why in r["conflicting_signals"][:8]:
            print(f"      {t!r}: {why}")

    print("\n  VERDICT")
    if r["levels_assigned"]:
        print(f"    HIERARCHY PRESENT — {len(r['levels_assigned'])} paragraph(s) "
              "carry an authored level.")
        for lv, t in r["levels_assigned"][:12]:
            print(f"      L{lv}  {t[:60]!r}")
    else:
        # THE NARROWER, PROVEN STATEMENT. The earlier wording said "no
        # heading numbering", which was never established: the reader
        # counted `w:numPr` and never opened numbering.xml. What IS proven
        # is the absence of authored LEVELS.
        print("    NO AUTHORED HEADING LEVELS.")
        print("    No paragraph carries a Heading style or an explicit")
        print("    w:outlineLvl, so the document states no level anywhere. NO")
        print("    LEVEL HAS BEEN ASSIGNED, and none will be inferred from")
        print("    bold, numbering, length, capitalisation, font size or")
        print("    spacing.")
        if r["numbered_paragraphs"]:
            print(f"\n    {r['numbered_paragraphs']} paragraph(s) ARE numbered, "
                  "and their formats are listed above. Numbering is reported")
            print("    as a signal; it is not read as a hierarchy.")
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

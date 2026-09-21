#!/usr/bin/env python3
"""The DOCX structural reader: does it use a hierarchy, and refuse to invent one?

Two fixtures, and the SECOND is the one that matters.

  headed.docx     real Heading 1/2/3 styles -- proves the reader USES an
                  authored hierarchy when the document carries one.
  flat_bold.docx  mirrors the canonical source: headings are bold-only
                  paragraphs, no styles, no outline levels, formatting
                  byte-identical whether the author meant a section or a
                  subsection.

Without the second fixture the tool would be tested only on a document
shape the real corpus does not have -- a harness that differs from
production (V2). The real source has 0 Heading-styled paragraphs and 0
`w:outlineLvl`, so a reader validated only against `headed.docx` would pass
here and find nothing there.

Stdlib only. No database, no provider, every capability floor.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import docx_structure as DX

FAILS: list[str] = []
FIX = REPO / "testing" / "fixtures" / "docx"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def main() -> int:
    print("\nthe fixtures are real .docx packages, not stubs")
    for n in ("headed.docx", "flat_bold.docx", "signals.docx"):
        p = FIX / n
        check(f"{n} exists", p.exists())
        with zipfile.ZipFile(p) as z:
            names = set(z.namelist())
        check(f"{n} carries word/document.xml and word/styles.xml",
              {"word/document.xml", "word/styles.xml"} <= names, str(names))

    # ==================================================================
    print("\nFIXTURE 1 — an authored hierarchy IS used")
    h = DX.analyse(FIX / "headed.docx")
    print(f"        styled headings: {dict(h['styled_headings'])}")
    # TWO INDEPENDENT SIGNALS, exercised separately on purpose. L1 and L2
    # are declared by `w:outlineLvl` on the style; L3 is recognisable ONLY
    # by the style NAME "heading 3". The first version of this fixture put
    # outlineLvl on all three, and sabotaging the name regex changed
    # nothing -- the test had no teeth on that half.
    check("a style declaring w:outlineLvl is recognised",
          h["styled_headings"].get(1) == 1 and h["styled_headings"].get(2) == 2,
          str(dict(h["styled_headings"])))
    check("a style recognisable ONLY by its NAME is recognised too",
          h["styled_headings"].get(3) == 1,
          str(dict(h["styled_headings"])))
    check("four paragraphs receive an authored level",
          len(h["levels_assigned"]) == 4, str(h["levels_assigned"]))
    check("the levels are the ones the document states",
          [lv for lv, _ in h["levels_assigned"]] == [1, 2, 3, 2],
          str([lv for lv, _ in h["levels_assigned"]]))
    check("the level attaches to the right text",
          h["levels_assigned"][2] == (3, "A Subsection"),
          str(h["levels_assigned"][2]))

    # Even here, bold alone earns nothing.
    bold_titles = {t for _, t in h["levels_assigned"]}
    check("a BOLD paragraph in the same document gets NO level",
          "A bold run that is NOT a heading style" not in bold_titles
          and h["bold_only_paragraphs"] >= 1,
          f"bold={h['bold_only_paragraphs']} levels={sorted(bold_titles)}")

    # ==================================================================
    print("\nFIXTURE 2 — the shape of the REAL source: no hierarchy at all")
    f = DX.analyse(FIX / "flat_bold.docx")
    check("the document states NO heading style",
          sum(f["styled_headings"].values()) == 0,
          str(dict(f["styled_headings"])))
    check("...and NO outline level",
          sum(f["outline_levels"].values()) == 0,
          str(dict(f["outline_levels"])))
    check("...and NO heading numbering", f["numbered_paragraphs"] == 0)
    check("THE READER ASSIGNS NO LEVEL — it does not invent one",
          f["levels_assigned"] == [], str(f["levels_assigned"]))
    check("the bold paragraphs are still REPORTED, as a signal",
          f["bold_only_paragraphs"] == 5, str(f["bold_only_paragraphs"]))
    check("...as a LENGTH DISTRIBUTION, with no threshold anywhere",
          len(f["bold_lengths"]) == 5, str(f["bold_lengths"]))
    check("...and their text is preserved for the reader to see",
          "A Subsection" in f["bold_texts"], str(f["bold_texts"]))

    print("\nthe VERDICT wording says the absence out loud")
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        DX.report(FIX / "flat_bold.docx")
    out = buf.getvalue()
    # THE NARROWER, PROVEN CLAIM. The earlier wording said "no heading
    # numbering" while the reader had only counted `w:numPr` and never
    # opened numbering.xml.
    check("it prints NO AUTHORED HEADING LEVELS", "NO AUTHORED HEADING LEVELS" in out)
    check("...and does NOT claim anything about numbering it did not check",
          "no heading numbering" not in out)
    # Whitespace-normalised: the wording wraps across printed lines, and a
    # substring test on the raw text would fail for the wrong reason.
    flat_out = " ".join(out.split())
    check("...and says no level was assigned",
          "NO LEVEL HAS BEEN ASSIGNED" in flat_out, flat_out[-260:])
    check("...and names what it refuses to infer from",
          all(w in flat_out for w in
              ("bold", "numbering", "length", "capitalisation", "font size")),
          flat_out[-260:])

    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        DX.report(FIX / "headed.docx")
    out2 = buf2.getvalue()
    check("the headed document does NOT print that verdict",
          "NO AUTHORED HEADING LEVELS" not in out2 and "HIERARCHY PRESENT" in out2)

    # ==================================================================
    print("\nFIXTURE 3 — the signals the reader used to get wrong")
    g = DX.analyse(FIX / "signals.docx")

    print(f"        numbering by format: {dict(g['numbered_by_format'])}")
    check("numbering.xml is actually opened, and formats reported",
          dict(g["numbered_by_format"]) == {"L0:bullet": 1, "L0:decimal": 2},
          str(dict(g["numbered_by_format"])))
    check("...and the numId definitions are read",
          len(g["numbering_formats"]) == 2, str(g["numbering_formats"]))

    print(f"        bold: direct={g['bold_direct']} inherited={g['bold_inherited']}"
          f" explicitly_off={g['bold_explicitly_off']}")
    check("<w:b w:val=\"0\"> is NOT counted as bold",
          g["bold_explicitly_off"] == 2, str(g["bold_explicitly_off"]))
    check("...and neither is w:val=\"false\"",
          g["bold_only_paragraphs"] == 1, str(g["bold_only_paragraphs"]))
    check("bold INHERITED from a paragraph style is counted",
          g["bold_inherited"] == 1, str(g["bold_inherited"]))
    check("...and is distinguished from direct run formatting",
          g["bold_direct"] == 0, str(g["bold_direct"]))

    check("font sizes are read from the RUNS, where they are declared",
          dict(g["font_sizes"]) == {"28": 1, "22": 1}, str(dict(g["font_sizes"])))

    print(f"        conflicts: {g['conflicting_signals']}")
    check("a paragraph that is BOTH a heading and numbered is REPORTED",
          len(g["conflicting_signals"]) == 1
          and "list numbering" in g["conflicting_signals"][0][1],
          str(g["conflicting_signals"]))
    check("...rather than one signal being silently chosen",
          len(g["levels_assigned"]) == 1 and g["numbered_paragraphs"] == 3,
          f"{g['levels_assigned']} {g['numbered_paragraphs']}")

    # ==================================================================
    # The reader must not acquire an inference path later. These strings
    # are the ones a "helpful" heuristic would introduce.
    print("\nthe reader contains no level-inference heuristic")
    src = (REPO / "scripts" / "docx_structure.py").read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    for bad in ("isupper()", "istitle()", "len(txt) <", "len(txt) >",
                "ALL_CAPS"):
        check(f"  no inference on {bad!r}", bad not in body)

    print("\n" + "=" * 60)
    if FAILS:
        print(f"FAILURES: {len(FAILS)}")
        for x in FAILS:
            print(f"  - {x}")
        return 1
    print("test_docx_structure: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

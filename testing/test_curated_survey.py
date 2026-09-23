#!/usr/bin/env python3
"""The flat structural survey: no depth, the production grammar, and it finds
the labels that recur across container kinds.

D57. The previous survey reported Markdown levels, level-to-level nesting
and level templates -- all of it model-assigned, since the canonical source
states no level. This checks the replacement reports none of that, reuses
the real grammar, writes nothing, and flags the one ambiguity the corpus is
known to contain.

Synthetic documents are written here; the two committed fixtures are only
READ, and nothing from them is quoted.
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "testing"))

import psycopg

import curated_survey as SV

FAILS: list[str] = []
FIX = REPO / "testing" / "fixtures"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def run(paths) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        SV.survey([Path(p) for p in paths])
    return buf.getvalue()


SYNTH = """# Widget Maintenance — Update

### Strategy 1 — Rotor balancing

Balance first.

###### Decision intelligence

Pick this first when vibration dominates.

## ADD — Faster recovery is possible

Some rotors settle quickly.

#### Decision intelligence

A short settling time is plausible when the bearings are new.
"""


# D58 reporting. The title (no rule, no container); one registered label
# before any container; the SAME
# unregistered sentence inside a strategy and inside an object; a registered
# label attached inside the object only.
REASONS = """# Widget Maintenance — Update

## Monitoring

Nothing is open yet.

## Strategy 1 — Rotor balancing

Balance first.

## A sentence the author set apart for emphasis

Body.

## When useful

When vibration dominates.

## ADD — Bearing inspection

Look before replacing.

## A sentence the author set apart for emphasis

Body again.

## Monitoring

Weekly.
"""


def main() -> int:
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    tables = ("curated_blocks", "curated_fields", "curated_objects",
              "curated_strategies", "curated_grammar_rules",
              "source_envelopes", "concepts")
    before = {t: conn.execute(f"select count(*) from {t}").fetchone()[0]
              for t in tables}

    tmp = Path(tempfile.mkdtemp(prefix="svy-")) / "synthetic.md"
    tmp.write_text(SYNTH, encoding="utf-8")

    print("\nthe survey reports NO depth of any kind")
    out = run([FIX / "curated" / "t2d_video1.md",
               FIX / "curated" / "t2d_video14.md", tmp])
    for bad in (r"\bL[1-6]\b", r"NESTING", r"level\s*->", r"heading LEVELS",
                r"child-heading set", r"-> L\d"):
        check(f"  no depth token {bad!r}", not re.search(bad, out),
              str(re.findall(bad, out)[:3]))
    check("it says out loud that no depth is reported",
          "NO DEPTH IS REPORTED" in out)

    # A deliberately nonsensical depth scheme: the output must not change
    # with it. Same synthetic document, every heading at one depth.
    flat = tmp.with_name("synthetic_flat.md")
    flat.write_text(re.sub(r"^#{1,6}(?=[ \t])", "#", SYNTH, flags=re.M),
                    encoding="utf-8")
    a = run([tmp]).replace(tmp.name, "X")
    b = run([flat]).replace(flat.name, "X")
    check("rewriting every heading's depth does not change the survey", a == b)

    print("\nit finds the label that recurs across container kinds")

    def labels_section(text: str) -> str:
        # Bounded on BOTH sides. The rule-level section added in D58 shares
        # the phrase "MORE THAN ONE KIND OF CONTAINER", and an unbounded
        # split read whichever came last.
        tail = text.split("LABELS WHOSE SURFACE FORM RECURS")[-1]
        return tail.split("REGISTERED RULES MET INSIDE")[0]

    check("`Decision intelligence` is flagged across the two fixtures",
          "'Decision intelligence'" in labels_section(out))
    one = run([FIX / "curated" / "t2d_video14.md"])
    check("...and NOT from Video 14 alone, where it occurs in one kind",
          "(none across the files given)" in labels_section(one))
    syn = run([tmp])
    tail = labels_section(syn)
    check("a synthetic doc with the same label in a card AND an object is flagged",
          "'Decision intelligence'" in tail and "inside STRATEGY" in tail
          and "inside CURATED_OBJECT" in tail, tail[:300])

    print("\nit separates WHY a candidate is not structure (D58)")
    rp = tmp.with_name("reasons.md")
    rp.write_text(REASONS, encoding="utf-8")
    r = run([rp])
    reasons = r.split("NOT RECOGNISED AS STRUCTURE, BY REASON")[-1] \
        .split("UNOWNED")[0]
    check("'matches no rule' and 'registered, no container' are separate lines",
          re.search(r"\b3\s+matches no registered rule", reasons) is not None
          and re.search(r"\b1\s+matches a REGISTERED label, but no container",
                        reasons) is not None, reasons[:400])
    check("...and the registered label whose container was missing is NAMED",
          "registered labels whose container was missing" in reasons
          and "'Monitoring'" in reasons.split("container was missing")[-1]
                                        .split("most frequent")[0], reasons[:500])
    absorbed = r.split("UNOWNED")[-1].split("RECOGNISED CONTAINER")[0]
    check("unowned text inside a field is COUNTED, not just skipped",
          re.search(r"\b2 candidate\(s\) matching no rule absorbed", absorbed)
          is not None, absorbed[:300])
    lab = labels_section(r)
    check("bold prose recurring in two container kinds is NOT a label ambiguity",
          "set apart for emphasis" not in lab, lab[:300])
    check("...nor is a registered label that never met a container",
          "(none across the files given)" in lab, lab[:300])
    rules_sec = r.split("REGISTERED RULES MET INSIDE")[-1]
    check("...and a rule met in only ONE kind is not flagged either",
          "SUB_MONITORING" not in rules_sec and "0 rule(s) flagged" in rules_sec,
          rules_sec[:300])
    check("the fixtures' SUB_WHY drift is flagged at RULE level, attached in both",
          "SUB_WHY" in out.split("REGISTERED RULES MET INSIDE")[-1]
          and "1 of them ATTACHED" in out.split("REGISTERED RULES MET INSIDE")[-1],
          out.split("REGISTERED RULES MET INSIDE")[-1][:600])
    check("the label list says how much of it is REFUSAL",
          "0 of them ATTACHED in more than one kind" in labels_section(out),
          labels_section(out)[-300:])

    print("\nit uses the production grammar, not a copy")
    src = (REPO / "scripts" / "curated_survey.py").read_text(encoding="utf-8")
    check("it calls curated_parser.classify / attach / derive_paths",
          all(f"CP.{fn}(" in src for fn in ("classify", "attach", "derive_paths")))
    check("it compiles no grammar pattern of its own",
          "re.compile(r'^(?:Strategy" not in src and "SUB_" not in src)

    print("\nit reads a .docx by bold CANDIDATES, never by level")
    d = run([FIX / "docx" / "flat_bold.docx"])
    check("candidates come from bold-only paragraphs",
          "BOLD_ONLY_PARAGRAPH" in d and "5 candidate(s)" in d, d[:400])
    check("...labelled as candidate boundaries, not headings",
          "NOT a heading" in d)
    check("...and no depth appears", not re.search(r"\bL[1-6]\b", d))

    after = {t: conn.execute(f"select count(*) from {t}").fetchone()[0]
             for t in tables}
    check("the survey WROTE NOTHING to the library", before == after,
          str({t: (before[t], after[t]) for t in tables if before[t] != after[t]}))

    print("\nwithout a database it degrades, and says what it could not do")
    saved = os.environ.pop("DATABASE_URL")
    try:
        n = run([tmp])
    finally:
        os.environ["DATABASE_URL"] = saved
    check("rule-dependent sections are skipped BY NAME",
          "curated_grammar_rules is not available" in n)
    check("...and the signal counts still print", "list_items" in n)

    print("\n" + "=" * 60)
    if FAILS:
        print(f"FAILURES: {len(FAILS)}")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("test_curated_survey: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

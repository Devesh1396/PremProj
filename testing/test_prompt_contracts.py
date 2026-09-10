#!/usr/bin/env python3
"""
Anti-drift tests binding the prompt files to the database and the
orchestration contract.

Every check here exists because something already drifted once:
  - Engine 7 carried two control-block specifications at the same time
    (the older 70A was swallowed into a retained section during a merge).
  - The prompt claimed 19 coverage dimensions while listing 18.
  - The foundation curriculum was moved out of the prompt and could now
    change without anyone noticing.

These are cheap. Silent divergence between a prompt and the schema it
drives is not.
"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import psycopg
import manifest as MF

REPO = Path(__file__).resolve().parents[1]
PROMPTS = REPO / "prompts"
E7 = PROMPTS / "engine7_research_practice.md"
SEED = REPO / "knowledge" / "seed" / "foundation_domains.md"
CONTRACT = REPO / "schemas" / "orchestration" / "control_contract.v1.json"

DSN = os.environ.get("PHI_TEST_DSN") or os.environ.get("DATABASE_URL")
if not DSN:
    print("Set PHI_TEST_DSN or DATABASE_URL")
    sys.exit(2)

PASS = FAIL = 0
FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {label}")
    else:
        FAIL += 1
        FAILURES.append(label)
        print(f"  FAIL {label} {detail}")


ALL_ENGINES = [
    "engine1_prevention.md",
    "engine2_behaviour.md",
    "engine3_nutrition.md",
    "engine4_progress.md",
    "engine5_communication.md",
    "engine6_memory.md",
    "engine7_research_practice.md",
]


def main() -> int:
    e7 = E7.read_text(encoding="utf-8")

    # ------------------------------------------------ one control contract
    print("\nexactly one authoritative control contract per prompt")

    for name in ALL_ENGINES:
        text = (PROMPTS / name).read_text(encoding="utf-8")
        specs = re.findall(r"^#{1,4}\s*\S+\.\s*ORCHESTRATION CONTROL BLOCK", text, re.M)
        check(f"{name}: exactly one control-block specification section", len(specs) == 1,
              f"found {len(specs)}")
        check(f"{name}: exactly one <CONTROL_BLOCK> opening tag", text.count("<CONTROL_BLOCK>") == 1,
              f"found {text.count('<CONTROL_BLOCK>')}")
        check(f"{name}: exactly one </CONTROL_BLOCK> closing tag",
              text.count("</CONTROL_BLOCK>") == 1, f"found {text.count('</CONTROL_BLOCK>')}")

    check("engine 7 no longer carries the retired 70A section", "70A" not in e7)

    print("\ncomposition header cross-references")
    check("header states Part II is R1-R3", "Part II, §R1–§R3" in e7)
    # R10 was added by the build (D16 territory): §55 defines the Knowledge
    # Inbox information gain in prose and no machine block ever carried it,
    # so an INBOX run had no substantive output contract at all. These
    # assertions exist because a merge accident once mis-stated the ranges,
    # so they move together with the header rather than being relaxed.
    check("header states Part III is R4-R10 plus 88",
          "Part III, §R4–§R10 and §88" in e7)
    check("header does not claim R1-R4", "§R1–§R4" not in e7)
    check("header does not claim R5-R9", "§R5–§R9" not in e7)
    r_secs = re.findall(r"^## (R\d+)\.", e7, re.M)
    check("R sections run R1..R11 exactly",
          r_secs == [f"R{i}" for i in range(1, 12)], str(r_secs))
    check("control block points at R2 for the dimensions, not R3",
          "§R3 domain-depth" not in e7 and "§R2 domain-depth" in e7)

    # ------------------------------------------------ handoff tags
    print("\nengine 7 handoff tags are emittable")
    # "Emittable" means a STANDALONE opening line, not a mention inside a
    # section heading. §R8's tag lived only in its heading and §R9's only in
    # the §R3 example, so a model following the field template literally
    # would have produced a block the runtime cannot find. Both are
    # build-owned (D16), so they were fixed rather than parsed around.
    for tag in ("RESEARCH_PRACTICE_FOUNDATION_HANDOFF",
                "RESEARCH_PRACTICE_CASE_HANDOFF",
                "RESEARCH_PRACTICE_INBOX_HANDOFF"):
        check(f"<{tag}> opens on its own line",
              re.search(rf"^<{tag}>$", e7, re.M) is not None)
        check(f"</{tag}> closes on its own line",
              re.search(rf"^</{tag}>$", e7, re.M) is not None)
    check("every E7 mode has a handoff block",
          all(re.search(rf"^<{t}>$", e7, re.M) for t in
              ("RESEARCH_PRACTICE_FOUNDATION_HANDOFF",
               "RESEARCH_PRACTICE_CASE_HANDOFF",
               "RESEARCH_PRACTICE_INBOX_HANDOFF")))
    check("R8 says it serves FOUNDATION and UPDATE",
          "Emitted in **FOUNDATION** and **UPDATE** mode" in e7)
    check("the inbox block preserves the §55 information gain",
          all(f in e7 for f in ("CONCEPTS_EXTRACTED:", "ALREADY_KNOWN:",
                                "GENUINELY_NEW:", "SAFETY_ISSUES_IDENTIFIED:",
                                "INFORMATION_GAIN_SUMMARY:")))
    check("...and does not promote a candidate strategy",
          "A candidate strategy is still a candidate" in e7)

    # ------------------------------------------------ hygiene
    # ------------------------------------------------ manifest
    print("\nMANIFEST.json is checkable, and checked")
    # It used to carry `sections_expected`, a hand-declared number whose
    # counting rule could not be reproduced -- no rule matched all seven
    # prompts and the closest matched four. It looked like coverage and was
    # not, and its Engine 7 sha256 had been stale since the D16 merge
    # without anything noticing. Every field is derived now, and asserted
    # here for all seven rather than for the one that happened to change.
    manifest = json.loads((PROMPTS / "MANIFEST.json").read_text())
    header, rows = manifest[0], manifest[1:]
    check("the manifest documents its own counting rule",
          header.get("_section_rule") and header.get("_section_rule_meaning"))
    check("it covers all seven prompts",
          {r["file"] for r in rows} == set(ALL_ENGINES), str(sorted(
              r["file"] for r in rows)))
    stale = []
    for row in rows:
        fresh = MF.entry(PROMPTS / row["file"])
        for field, value in fresh.items():
            if row.get(field) != value:
                stale.append(f"{row['file']}.{field}: manifest={row.get(field)!r} "
                             f"actual={value!r}")
    check("every manifest field matches the file it describes",
          not stale, "; ".join(stale[:3]))
    check("every prompt declares a handoff tag that opens on its own line",
          all(r["has_handoff_open_tag"] for r in rows),
          str([r["file"] for r in rows if not r["has_handoff_open_tag"]]))
    check("...and closes on its own line",
          all(r["has_handoff_close_tag"] for r in rows))
    check("...and carries a control block", all(r["has_control_tag"] for r in rows))
    check("no two prompts have the same sha256",
          len({r["sha256"] for r in rows}) == 7)

    print("\nprompt hygiene")
    hashes = {}
    for name in ALL_ENGINES:
        text = (PROMPTS / name).read_text(encoding="utf-8")
        bad = [c for c in text if ord(c) < 32 and c not in "\n\t\r"]
        check(f"{name}: no non-printing characters", not bad, f"{len(bad)} found")
        hashes[name] = hashlib.sha256(text.encode()).hexdigest()
    check("all seven prompts hash distinctly", len(set(hashes.values())) == 7)

    # ------------------------------------------------ coverage dimensions
    print("\ncoverage dimensions: prompt <-> enum <-> readiness view")

    # Bound the slice at R2b: the gap-governance table that follows lists
    # control-block fields, not coverage dimensions, and must not be read
    # as part of the mapping.
    block = e7[e7.find("### R2a."):]
    for stop in ("### R2b.", "\n## "):
        if stop in block:
            block = block[: block.find(stop)]
            break
    # Rows may carry a trailing footnote marker for build-assigned mappings.
    prompt_dims = set(re.findall(r"\|\s*`([A-Z_]+)`\s*[^|]*\|", block))
    check("R2a mapping table parses", len(prompt_dims) > 0, f"{len(prompt_dims)} found")

    with psycopg.connect(DSN, autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
               WHERE t.typname = 'coverage_dimension' ORDER BY e.enumsortorder"""
        )
        db_dims = {r[0] for r in cur.fetchall()}

        check("prompt lists every database dimension", db_dims <= prompt_dims,
              f"missing from prompt: {sorted(db_dims - prompt_dims)}")
        check("prompt invents no dimension the database lacks", prompt_dims <= db_dims,
              f"not in enum: {sorted(prompt_dims - db_dims)}")
        check("prompt and enum agree exactly", prompt_dims == db_dims,
              f"db={len(db_dims)} prompt={len(prompt_dims)}")

        # The 18 recovered questions must still be present verbatim.
        r2 = e7[e7.find("## R2."): e7.find("### R2a.")]
        questions = [l.strip() for l in r2.split("\n") if l.strip().endswith("?")]
        check("all 18 recovered §35 questions retained verbatim", len(questions) == 18,
              f"found {len(questions)}")
        check("one dimension per recovered question, no extras",
              len(questions) == len(db_dims), f"{len(questions)} questions vs {len(db_dims)} dims")

        # Gap assessment is governance, not content coverage.
        check("KNOWLEDGE_GAPS is not a coverage dimension", "KNOWLEDGE_GAPS" not in db_dims)
        check("gap assessment absent from the R2a mapping table",
              not any("GAP" in d for d in prompt_dims), f"{sorted(d for d in prompt_dims if 'GAP' in d)}")

        # The two semantic shortcuts are gone.
        check("MEASUREMENT replaced by EFFECT_MAGNITUDE",
              "MEASUREMENT" not in db_dims and "EFFECT_MAGNITUDE" in db_dims)
        check("NUTRITION_STRATEGIES replaced by ALTERNATIVE_STRATEGIES",
              "NUTRITION_STRATEGIES" not in db_dims and "ALTERNATIVE_STRATEGIES" in db_dims)
        check("no build-assigned mapping markers remain in R2a", "†" not in block)

        # Gap governance modelled separately.
        print("\ngap assessment is governance, not coverage")
        cur.execute("""SELECT count(*) FROM information_schema.tables
                       WHERE table_name = 'domain_gap_assessments'""")
        check("domain_gap_assessments exists", cur.fetchone()[0] == 1)
        cur.execute("""SELECT count(*) FROM information_schema.columns
                       WHERE table_name = 'knowledge_gaps' AND column_name = 'severity'""")
        check("knowledge_gaps carries a severity", cur.fetchone()[0] == 1)

        viewdef_r = None
        cur.execute("SELECT pg_get_viewdef('v_domain_readiness'::regclass, true)")
        viewdef_r = cur.fetchone()[0]
        for col in ("gap_assessment_complete", "open_critical_gaps",
                    "open_high_priority_gaps", "foundation_ready"):
            check(f"v_domain_readiness exposes {col}", col in viewdef_r)
        check("readiness counts 18 dimensions, not 19", "18" in viewdef_r and "19" not in viewdef_r)

        for field in ("GAP_ASSESSMENT_COMPLETE", "OPEN_CRITICAL_GAPS", "OPEN_HIGH_PRIORITY_GAPS"):
            check(f"control block defines {field}", field in e7)
        check("prompt states zero gaps does not mean finished",
              "not a claim that the domain is finished" in e7)
        check("prompt no longer claims recording zero gaps implies completion",
              "Recording zero gaps is a claim that the domain is finished" not in e7)

        # The readiness view must consume the same enum.
        cur.execute("SELECT pg_get_viewdef('v_domain_readiness'::regclass, true)")
        viewdef = cur.fetchone()[0]
        check("v_domain_readiness reads domain_coverage", "domain_coverage" in viewdef)
        cur.execute(
            """SELECT count(*) FROM information_schema.columns
               WHERE table_name = 'domain_coverage' AND column_name = 'dimension'
                 AND udt_name = 'coverage_dimension'"""
        )
        check("domain_coverage.dimension is typed coverage_dimension", cur.fetchone()[0] == 1)

        # ------------------------------------------------ CASE_VERSION
        print("\nCASE_VERSION knowledge-clock semantics")
        contract = json.loads(CONTRACT.read_text())
        cv = contract["properties"]["CASE_VERSION"]
        check("contract allows CASE_VERSION 0", cv.get("minimum") == 0)
        check("contract documents 0 as the knowledge-clock value",
              "knowledge-clock" in cv.get("description", "").lower())
        check("CASE_VERSION is still required on every run",
              "CASE_VERSION" in contract["required"])
        check("engine 7 prompt instructs 0 on knowledge-clock runs",
              '"CASE_VERSION": 0' in e7)
        check("engine 7 prompt no longer carries a build blocker",
              "Build dependency" not in e7 and "only case mode is runnable" not in e7)

        cur.execute(
            """SELECT count(*) FROM information_schema.check_constraints
               WHERE constraint_name = 'ck_run_clock_coherent'"""
        )
        check("engine_runs enforces run-clock coherence", cur.fetchone()[0] == 1)
        cur.execute(
            """SELECT count(*) FROM information_schema.check_constraints
               WHERE constraint_name = 'ck_case_version_positive'"""
        )
        check("stored case versions cannot be 0", cur.fetchone()[0] == 1)

        # ------------------------------------------------ seed file
        print("\nexternalised foundation curriculum")
        check("seed file exists", SEED.exists())
        seed = SEED.read_text(encoding="utf-8")
        declared = re.search(r"`([0-9a-f]{64})`", seed).group(1)
        marker = "## §7. FOUNDATION KNOWLEDGE DOMAINS\n\n"
        body = seed[seed.find(marker) + len(marker):]
        actual = hashlib.sha256(body.encode()).hexdigest()
        check("seed body matches its declared hash", declared == actual,
              f"declared={declared[:12]} actual={actual[:12]}")
        check("all 26 recovered domains present",
              len(re.findall(r"^DOMAIN [A-Z] —", body, re.M)) == 26)
        check("engine 7 references the seed file by path",
              "knowledge/seed/foundation_domains.md" in e7)
        check("engine 7 references the seed file by hash", declared in e7)
        check("the curriculum is no longer inline in the prompt",
              len(re.findall(r"^DOMAIN [A-Z] —", e7, re.M)) == 0)

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    if FAILURES:
        for f in FAILURES:
            print("  failed:", f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Level independence of what is STORED and RETRIEVED, not only parsed.

D57. `test_curated_flat` proves the parser's output is identical across
Markdown renderings. This proves the same thing one layer further out:
each rendering is imported through the REAL inbox path and the REAL
importer, and the persisted rows and `curated_expansion()` output are
compared.

Each fixture is rendered four ways -- as committed, then with every
heading marker rewritten to `#`, `###` and `######`. The renderings are
different bytes, so each becomes its own envelope; nothing is deduplicated
away.

Compared WITHOUT raw offsets, source titles or file locations. Changing a
marker's length moves every offset, and each rendering is a different
file, so those differ by construction and are not structure. Everything
else -- ownership, heading paths, structural provenance, failure reasons,
field names, name provenance, text provenance and TEXT -- must match.

Also asserts the model-assigned markup depth cannot reach retrieval: it is
stored as `source_markup_depth` (051), and no expansion may carry it.

Deterministic. `LLM_API_KEY` is cleared; no provider call is made.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "testing"))

import psycopg

FAILS: list[str] = []
FIXTURES = REPO / "testing" / "fixtures" / "curated"
MARKERS = ("", "#", "###", "######")
OFFSET_KEYS = {"source_start", "source_end", "card_source_start",
               "card_source_end", "raw_location", "source_title"}


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def render(text: str, marker: str) -> str:
    if not marker:
        return text
    return re.sub(r"^#{1,6}(?=[ \t])", marker, text, flags=re.M)


def strip_offsets(obj):
    if isinstance(obj, dict):
        return {k: strip_offsets(v) for k, v in obj.items() if k not in OFFSET_KEYS}
    if isinstance(obj, list):
        return [strip_offsets(v) for v in obj]
    return obj


def main() -> int:
    os.environ["LLM_API_KEY"] = ""
    root = Path(tempfile.mkdtemp(prefix="g4rn-"))
    os.environ["KNOWLEDGE_DIR"] = str(root)
    for d in ("inbox", "raw", "processed", "failed"):
        (root / d).mkdir(parents=True, exist_ok=True)

    import knowledge_ingest as KI
    import curated_import as CI
    import retrieval as RET
    CI.KNOWLEDGE = root

    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    texts = []

    def clear():
        for t in texts:
            d = hashlib.sha256(t.encode("utf-8")).hexdigest()
            conn.execute("delete from source_items where content_hash=%s", (d,))
            conn.execute("delete from source_envelopes where content_hash=%s", (d,))
        conn.execute("delete from source_envelopes where source_title like 'G4RN%'")
        conn.execute("delete from source_items where title like 'G4RN%'")
        conn.execute("delete from knowledge_sources where source_name like 'G4RN%'")

    def ingest(text: str, title: str) -> str:
        texts.append(text)
        slug = hashlib.sha1(title.encode()).hexdigest()[:10]
        path = root / "inbox" / f"{slug}.md"
        path.write_text(text, encoding="utf-8")
        (root / "inbox" / f"{slug}.meta.json").write_text(json.dumps({
            "source_kind": "PRACTITIONER_CURATED", "source_title": title,
            "rights": "PRIVATE_INTERNAL", "send_to_e7": True}), encoding="utf-8")
        env = KI.ingest_one(conn, path).envelope_id
        todo = [e for e in CI.pending(conn) if str(e[0]) == env]
        CI.import_one(conn, todo[0])
        return env

    def persisted(env: str) -> dict:
        return {
            "blocks": conn.execute(
                """select ordinal, raw_heading, status::text, rule_id,
                          heading_path, structural_provenance::text,
                          failure_reason
                     from curated_blocks where envelope_id=%s
                    order by ordinal""", (env,)).fetchall(),
            "strategies": conn.execute(
                """select ordinal, name, heading_path from curated_strategies
                    where envelope_id=%s order by ordinal""", (env,)).fetchall(),
            "principles": conn.execute(
                """select ordinal, name, heading_path from curated_principles
                    where envelope_id=%s order by ordinal""", (env,)).fetchall(),
            "objects": conn.execute(
                """select ordinal, disposition::text, name, heading_path
                     from curated_objects where envelope_id=%s
                    order by ordinal""", (env,)).fetchall(),
            "fields": conn.execute(
                """select coalesce(s.name, p.name, o.name), f.field_name,
                          f.heading_path, f.name_source::text,
                          f.provenance::text, f.text_value,
                          b.structural_provenance::text
                     from curated_fields f
                     left join curated_strategies s on s.curated_id=f.curated_id
                     left join curated_principles p on p.principle_id=f.principle_id
                     left join curated_objects o on o.object_id=f.object_id
                     left join curated_blocks b on b.block_id=f.block_id
                    where coalesce(s.envelope_id, p.envelope_id, o.envelope_id)=%s
                    order by 1, 2""", (env,)).fetchall(),
        }

    def expansions(env: str) -> list:
        ids = [r[0] for r in conn.execute(
            "select curated_id::text from curated_strategies "
            " where envelope_id=%s order by ordinal", (env,)).fetchall()]
        return [RET.curated_expansion(conn, i) for i in ids]

    # FIRST, before any query reads the column. An earlier version checked
    # this at the end, after a query that selects `source_markup_depth` --
    # so renaming the column back to `heading_level` made the suite CRASH
    # rather than fail the assertion written for exactly that regression.
    # Red for the wrong reason is still the wrong reason.
    cols = {r[0] for r in conn.execute(
        "select column_name from information_schema.columns "
        " where table_name='curated_blocks'").fetchall()}
    named_ok = "source_markup_depth" in cols and "heading_level" not in cols
    check("the persisted column is NAMED as markup, not as a level",
          named_ok, str(sorted(c for c in cols if "level" in c or "depth" in c)))

    clear()
    try:
        for name in ("t2d_video1", "t2d_video14"):
            print(f"\n{name}: imported four times, one rendering each")
            text = (FIXTURES / f"{name}.md").read_text(encoding="utf-8")
            envs = {m: ingest(render(text, m), f"G4RN {name} [{m or 'as committed'}]")
                    for m in MARKERS}
            p = {m: persisted(e) for m, e in envs.items()}
            x = {m: expansions(e) for m, e in envs.items()}

            check("four distinct envelopes, not one deduplicated",
                  len(set(envs.values())) == 4, str(envs))
            for m in ("#", "###", "######"):
                for part in ("blocks", "strategies", "principles", "objects",
                             "fields"):
                    diff = sum(1 for a, b in zip(p[m][part], p[""][part]) if a != b)
                    check(f"  {m!r:>8} persisted {part} identical (paths, "
                          "provenance, ownership, text)",
                          p[m][part] == p[""][part]
                          and len(p[m][part]) == len(p[""][part]),
                          f"{diff} differ; {len(p[m][part])} vs {len(p[''][part])}")
                check(f"  {m!r:>8} retrieved expansion identical apart from offsets",
                      strip_offsets(x[m]) == strip_offsets(x[""]),
                      f"{len(x[m])} vs {len(x[''])} cards")

            sp = {r[5] for r in p[""]["blocks"]}
            check("structural provenance is never AUTHORED for a converted source",
                  "AUTHORED_STRUCTURAL_SIGNAL" not in sp, str(sp))
            check("...and every recognised block is GRAMMAR_DERIVED",
                  all(r[5] == "GRAMMAR_DERIVED_CLASSIFICATION"
                      for r in p[""]["blocks"] if r[3] is not None))
            check("...and every unrecognised block is NO_HIERARCHY_AVAILABLE",
                  all(r[5] == "NO_HIERARCHY_AVAILABLE"
                      for r in p[""]["blocks"] if r[3] is None))

            if named_ok:
                depths = conn.execute(
                    "select count(distinct source_markup_depth) from curated_blocks "
                    " where envelope_id=%s", (envs[""],)).fetchone()[0]
                flat_d = conn.execute(
                    "select count(distinct source_markup_depth) from curated_blocks "
                    " where envelope_id=%s", (envs["#"],)).fetchone()[0]
                check("the markup depth IS still recorded, for audit, as markup",
                      depths >= 2 and flat_d == 1,
                      f"committed {depths}, flat {flat_d}")

            if x[""]:
                e0 = x[""][0]
                check("expansion carries structural_provenance",
                      "structural_provenance" in e0
                      and all("structural_provenance" in f for f in e0["fields"]),
                      str(list(e0)))
                blob = json.dumps(x[""])
                check("expansion NEVER carries the markup depth",
                      "source_markup_depth" not in blob
                      and "heading_level" not in blob)
            else:
                check("no strategy card to expand is the expected state here",
                      name == "t2d_video14", name)

    finally:
        clear()

    print("\n" + "=" * 60)
    if FAILS:
        print(f"FAILURES: {len(FAILS)}")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("test_gate4_renderings: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

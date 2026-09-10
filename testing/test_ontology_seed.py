#!/usr/bin/env python3
"""K1 ontology seed — BUILD_GUIDE step 12, DECISIONS.md D2 and D3.

Seeding before extraction is the point: retrieval quality starts with
having canonical concepts for extraction to normalize onto. So the
assertions are about SEED QUALITY, not seed size. A large, badly typed
ontology is worse than a small clean one -- it makes every similarity
comparison noisier for the life of the system (D13, applied to concepts).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import psycopg
import seed_ontology as K1

FAILS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def main() -> int:
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)

    print("\nthe curriculum cannot drift silently")
    text = K1.SEED.read_text(encoding="utf-8")
    check("the seed body still matches its declared hash",
          K1.body_hash(text) == K1.declared_hash(text),
          f"{K1.body_hash(text)[:12]} vs {K1.declared_hash(text)[:12]}")

    print("\nseeding is idempotent")
    conn.execute("delete from concepts where origin_method='SEED'")
    conn.execute("delete from knowledge_domains where discovered_by='K1_SEED'")
    first = K1.seed(conn, verbose=False)
    after_first = conn.execute(
        "select count(*) from concepts where origin_method='SEED'").fetchone()[0]
    second = K1.seed(conn, verbose=False)
    after_second = conn.execute(
        "select count(*) from concepts where origin_method='SEED'").fetchone()[0]
    check("re-seeding creates no duplicate concepts",
          after_first == after_second, f"{after_first} -> {after_second}")
    check("the second run reports everything as reused",
          second["concepts"] == 0 and second["reused"] > 0, str(second))

    print("\nall 26 domains, and the source domains seed no clinical concepts")
    domains = conn.execute(
        "select count(*) from knowledge_domains where discovered_by='K1_SEED'").fetchone()[0]
    check("26 domains seeded", domains == 26, str(domains))
    for letter in ("T", "U", "V", "W", "X", "Y", "Z", "S"):
        got = conn.execute(
            """select count(*) from concepts
                where origin_method='SEED' and origin_detail like %s""",
            (f"%DOMAIN {letter} %",)).fetchone()[0]
        check(f"DOMAIN {letter} seeds a domain row and no concepts", got == 0, str(got))

    print("\nevery seeded concept carries provenance (D11)")
    unprovenanced = conn.execute(
        """select count(*) from concepts
            where origin_method='SEED'
              and (origin_detail is null or origin_detail not like '%foundation_domains.md%')"""
    ).fetchone()[0]
    check("no seeded concept is untraceable", unprovenanced == 0, str(unprovenanced))
    check("provenance names the domain it came from",
          conn.execute(
              """select count(*) from concepts
                  where origin_method='SEED' and origin_detail like '%DOMAIN %'"""
          ).fetchone()[0] == after_second)

    print("\nno uncontrolled duplicates")
    dupe_keys = conn.execute(
        """select count(*) from (
             select canonical_key from concepts group by canonical_key having count(*) > 1
           ) d""").fetchone()[0]
    check("no duplicate canonical_key", dupe_keys == 0, str(dupe_keys))
    dupe_names = conn.execute(
        """select count(*) from (
             select norm_phrase(canonical_name) n from concepts
              where origin_method='SEED'
              group by norm_phrase(canonical_name) having count(*) > 1
           ) d""").fetchone()[0]
    check("no two seeded concepts share a normalized name", dupe_names == 0, str(dupe_names))
    check("a term appearing in several domains is ONE concept with several notes",
          first["reused"] > 0, str(first["reused"]))

    print("\naliases are separate from canonical concepts")
    aliased = conn.execute(
        """select count(*) from concept_aliases a
             join concepts c on c.concept_id = a.concept_id
            where a.method='SEED' and c.origin_method='SEED'""").fetchone()[0]
    check("alternate forms became aliases, not concepts", aliased > 0, str(aliased))
    check("no alias text is also a canonical name",
          conn.execute(
              """select count(*) from concept_aliases a
                  join concepts c on norm_phrase(c.canonical_name) = a.alias_norm
                 where a.method='SEED' and c.concept_id <> a.concept_id"""
          ).fetchone()[0] == 0)

    print("\nconfusable pairs are GENERATED from sibling structure, not hand-listed (D3)")
    generated = conn.execute(
        """select count(*) from concept_relations
            where relation_type='CONFUSABLE_DO_NOT_MERGE' and method='SEED'
              and note like '%sibling structure%'""").fetchone()[0]
    check("pairs were derived from structure", generated > 0, str(generated))
    check("each carries a note saying why it must not be merged",
          conn.execute(
              """select count(*) from concept_relations
                  where relation_type='CONFUSABLE_DO_NOT_MERGE' and method='SEED'
                    and (note is null or note = '')"""
          ).fetchone()[0] == 0)
    check("the mirror is written so a merge check cannot miss the pair",
          conn.execute(
              """select count(*) from concept_relations r1
                  where r1.relation_type='CONFUSABLE_DO_NOT_MERGE' and r1.method='SEED'
                    and not exists (select 1 from concept_relations r2
                                     where r2.relation_type='CONFUSABLE_DO_NOT_MERGE'
                                       and r2.from_concept = r1.to_concept
                                       and r2.to_concept = r1.from_concept)"""
          ).fetchone()[0] == 0)

    print("\nseed QUALITY: types are right and prose did not become concepts")
    # The parser bug that made this suite worth writing: a domain lists its
    # own terms and then cross-references another type ("Connect exercise to
    # outcomes such as: glucose, BP, lipids"). Those are OUTCOME terms and
    # were being seeded as EXERCISE.
    wrong_type = conn.execute(
        """select count(*) from concepts
            where origin_method='SEED' and concept_type='EXERCISE'
              and canonical_key in ('LIPIDS','BP','GLUCOSE','LIVER_FAT','BONE','SLEEP')"""
    ).fetchone()[0]
    check("a cross-referenced outcome was not seeded as an exercise",
          wrong_type == 0, str(wrong_type))

    prose = conn.execute(
        """select count(*) from concepts
            where origin_method='SEED'
              and (canonical_name ilike 'what %' or canonical_name ilike 'how %'
                   or canonical_name ilike '%autonomously%'
                   or canonical_name ilike '%when relevant%'
                   or canonical_name like '%→%'
                   or array_length(string_to_array(canonical_name,' '),1) > 5)"""
    ).fetchone()[0]
    check("no instruction fragment became a concept", prose == 0, str(prose))

    shape = conn.execute(
        """select count(*) from concepts
            where origin_method='SEED' and canonical_key !~ '^[A-Z][A-Z0-9_]{2,79}$'"""
    ).fetchone()[0]
    check("every canonical_key matches the required shape", shape == 0, str(shape))

    print("\nthe seed does not pretend to be complete")
    check("concepts are SEEDED, and the curriculum says it is not closed",
          "NOT a closed curriculum" in text)
    check("autonomous discovery is still expected",
          conn.execute(
              "select count(*) from concepts where status='SEEDED'").fetchone()[0] > 100)

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

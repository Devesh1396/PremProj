#!/usr/bin/env python3
"""K1 — the ontology seed. BUILD_GUIDE step 12.

Seeds the concept dictionary from `knowledge/seed/foundation_domains.md`
(26 domains, A-Z, recovered verbatim and hash-verified) BEFORE any
large-scale extraction runs. D2 is the reason: 10,000 strategies with bad
retrieval is worse than 200 with good retrieval, and retrieval quality
starts with having canonical concepts for extraction to normalize onto.

Four properties this seeder is built to hold:

  * **Provenance on every concept.** origin_method='SEED' and origin_detail
    naming the domain and the source line. A concept nobody can trace is
    the knowledge-layer version of an untraceable engine output (D11).
  * **No uncontrolled duplicates.** Deduplication is deterministic, on
    norm_phrase(), BEFORE any similarity or LLM question is asked. The same
    term appearing under three domains produces one concept with three
    provenance notes, not three concepts.
  * **Aliases stay separate from canonical concepts.** A parenthetical or
    slash form in the curriculum becomes an alias row, never a second
    concept.
  * **CONFUSABLE_DO_NOT_MERGE is GENERATED from sibling structure**, not
    hand-enumerated (D3). Siblings under one domain are exactly where
    dangerous merges happen, so the pairs come from the structure itself.

It does NOT pretend the ontology is complete. The curriculum says so in its
own first line -- "seed dimensions, NOT a closed curriculum" -- and §41/§54
require autonomous discovery to continue.
"""

from __future__ import annotations

import hashlib
import itertools
import os
import re
import sys
from pathlib import Path

import psycopg

import concept_key
import trigram

REPO = Path(__file__).resolve().parent.parent
SEED = REPO / "knowledge" / "seed" / "foundation_domains.md"

# Domain letter -> (concept_type for its terms, is_core, wave-1 priority).
# Domains T-Z describe SOURCE and GOVERNANCE knowledge rather than clinical
# concepts, so they seed a domain row and no concepts: seeding "book
# intelligence" as a PHYSIOLOGY concept would be noise in the retrieval
# spine forever.
# Domain letter -> (concept_type for its terms, domain_type for the domain
# row, is_core, wave-1 priority). concept_type and domain_type are SEPARATE
# enums in the schema and do not have the same members, so both are stated
# rather than one being derived from the other.
#
# Domains T-Z describe SOURCE and GOVERNANCE knowledge rather than clinical
# concepts, so they seed a domain row and no concepts: seeding "book
# intelligence" as a PHYSIOLOGY concept would be noise in the retrieval
# spine forever.
DOMAIN_MAP = {
    "A": ("CONDITION",          "CONDITION",           True,  10),
    "B": ("PHYSIOLOGY",         "PHYSIOLOGY",          True,  10),
    "C": ("BIOMARKER",          "BIOMARKER",           True,  10),
    "D": ("SYMPTOM",            "SYMPTOM",             True,   9),
    "E": ("NUTRIENT",           "NUTRIENT",            True,   9),
    "F": ("FOOD",               "FOOD",                True,   8),
    "G": ("SEASON",             "SEASONALITY",         False,  6),
    "H": ("INTERVENTION",       "INTERVENTION_FAMILY", True,  10),
    "I": ("EXERCISE",           "EXERCISE",            True,   8),
    "J": ("BEHAVIOUR",          "BEHAVIOUR",           True,   8),
    "K": ("NUTRIENT",           "SUPPLEMENT",          False,  7),
    "L": ("INTERVENTION",       "TRADITIONAL",         False,  5),
    "M": ("MEDICATION_CONTEXT", "OTHER",               True,   9),
    "N": ("POPULATION",         "POPULATION",          False,  7),
    "O": ("PHYSIOLOGY",         "PHYSIOLOGY",          True,   7),
    "P": ("BEHAVIOUR",          "BEHAVIOUR",           False,  7),
    "Q": ("OUTCOME",            "OUTCOME",             True,   8),
    "R": ("OUTCOME",            "OUTCOME",             True,   8),
    # S is practitioner and source CREDIBILITY knowledge -- "a clinician",
    # "author", "scientific evidence". Real knowledge, and not clinical
    # concepts: seeding them into the retrieval spine would put source
    # provenance terms next to biomarkers in every similarity search.
    # Same treatment as T-Z, for the same reason.
    "S": (None,                 "BEHAVIOUR",           False,  5),
    "T": (None,                 "OTHER",               False,  4),
    "U": (None,                 "OTHER",               False,  4),
    "V": (None,                 "OTHER",               False,  4),
    "W": (None,                 "OTHER",               False,  3),
    "X": (None,                 "OTHER",               False,  6),
    "Y": (None,                 "OTHER",               False,  6),
    "Z": (None,                 "OTHER",               False,  5),
}

# A domain body is a sequence of BLOCKS, each introduced by a line ending
# in a colon. The blocks do not all hold concepts of the domain's own type:
#
#   DOMAIN I - EXERCISE & MOVEMENT
#     Develop deep intervention knowledge around:     <- exercise terms
#       resistance training ...
#     Connect exercise to outcomes such as:           <- OUTCOME terms
#       glucose, BP, lipids ...
#
# Collecting the whole body seeded "lipids" and "BP" as EXERCISE concepts,
# which is worse than not seeding them: a wrong type in the retrieval spine
# misroutes every future query that touches it. So each colon line is
# classified, and only blocks that genuinely list the domain's own terms
# are collected. D13 -- 1,000 poor cards are worse than 300 good connected
# ones -- applies to concepts before it applies to strategies.
CROSS_REFERENCE_BLOCK = re.compile(
    r"(connect\b|outcomes such as|answer questions|questions such as|"
    r"relate\b|link\b|map\b|cross[- ]ref)", re.IGNORECASE)

# ALL-CAPS lines are structural headings ("WHAT THE MARKER MEASURES",
# "WHAT MOVES:"), never terms.
ALL_CAPS = re.compile(r"^[A-Z][A-Z0-9 /&'\-]{4,}:?$")

# Instruction fragments that survive block classification because they sit
# inside a term list: "expand beyond these when relevant", "discover
# additional compounds autonomously", "food -> nutrients". They read like
# terms and are not, and a seeded ontology full of them makes every
# similarity comparison noisier for the life of the system.
INSTRUCTION = re.compile(
    r"(\u2192|->|when relevant|where appropriate|as (?:needed|required)|"
    r"if relevant|beyond these|autonomously|and beyond|etc\b|"
    r"^(?:expand|discover|include|consider|note|add|apply|use|treat|avoid|"
    r"prefer|always|never|other|others|additional|possible|important|"
    r"relevant|different|the same|typical|what|how|which|why|when)\b)",
    re.IGNORECASE)

# Terms are short. A curriculum line of six or more words is prose.
MAX_TERM_WORDS = 5

SCAFFOLD = re.compile(
    r"^(build\b|develop\b|including but not limited to|for each\b|understand\b|"
    r"capture\b|know\b|track\b|identify\b|where\b|this\b|these\b|the following\b|"
    r"the system\b|without needing\b)", re.IGNORECASE)


# The body is everything after the section marker, hashed exactly as
# testing/test_prompt_contracts.py hashes it. One definition, used in both
# places: a second, subtly different one would let the curriculum drift
# past whichever check was weaker.
BODY_MARKER = "## §7. FOUNDATION KNOWLEDGE DOMAINS\n\n"


def body_hash(text: str) -> str:
    body = text[text.find(BODY_MARKER) + len(BODY_MARKER):]
    return hashlib.sha256(body.encode()).hexdigest()


def declared_hash(text: str) -> str:
    """The hash the file declares about itself, in its own header."""
    return re.search(r"`([0-9a-f]{64})`", text).group(1)


# One rule, shared with normalize.py. Both create concepts and both must
# satisfy ck_canonical_key_shape; they were not using the same rule, and
# the normalizer's version produced keys the database rejected.
# Re-exported so existing callers and tests keep working.
canonical_key = concept_key.canonical_key


def split_aliases(term: str) -> tuple[str, list[str]]:
    """"fatty liver / MASLD" -> ("fatty liver", ["MASLD"]).

    The alternate form becomes an ALIAS, never a second concept: one thing
    with two names is one row in `concepts` and two in `concept_aliases`.
    """
    aliases: list[str] = []
    paren = re.search(r"\(([^)]+)\)", term)
    if paren:
        aliases.append(paren.group(1).strip())
        term = term[:paren.start()].strip()
    if "/" in term:
        parts = [p.strip() for p in term.split("/") if p.strip()]
        term, aliases = parts[0], aliases + parts[1:]
    return term.strip(), [a for a in aliases if a and a.lower() != term.lower()]


def parse(text: str) -> list[dict]:
    """The curriculum as (domain letter, name, terms). Verbatim, not reworded."""
    domains: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        header = re.match(r"^DOMAIN ([A-Z]) [—-]\s*(.*)$", line)
        if header:
            current = {"letter": header.group(1),
                       "name": header.group(2).strip() or f"Domain {header.group(1)}",
                       "terms": []}
            domains.append(current)
            continue
        if current is None or not line or line.startswith((">", "#", "|", "-")):
            continue

        # A colon line opens a block and decides whether it is collected.
        if line.endswith(":"):
            current["collect"] = not (CROSS_REFERENCE_BLOCK.search(line)
                                      or ALL_CAPS.match(line))
            continue

        if not current.get("collect", False):
            continue
        if SCAFFOLD.match(line) or ALL_CAPS.match(line) or len(line) > 70:
            continue
        if INSTRUCTION.search(line) or len(line.split()) > MAX_TERM_WORDS:
            continue

        # Trailing "?" is Domain Q's question framing, not part of the term.
        term = line.rstrip(".,;?").strip()
        if term:
            current["terms"].append(term)
    return domains


def seed(conn, verbose: bool = True) -> dict[str, int]:
    text = SEED.read_text()
    stats = {"domains": 0, "concepts": 0, "reused": 0, "aliases": 0,
             "confusable": 0, "domain_edges": 0}

    domains = parse(text)
    for dom in domains:
        letter = dom["letter"]
        concept_type, domain_type, is_core, priority = DOMAIN_MAP.get(
            letter, (None, "OTHER", False, 5))
        domain_key = f"DOMAIN_{letter}"

        conn.execute(
            """insert into knowledge_domains
                 (name, domain_key, domain_type, description, wave1_priority,
                  is_core_domain, discovered_by)
               values (%s,%s,%s,%s,%s,%s,'K1_SEED')
               -- uq_domain_key is PARTIAL (WHERE active), so the
               -- inference clause has to carry the same predicate.
               on conflict (domain_key) where active do update
                 set name = excluded.name,
                     wave1_priority = excluded.wave1_priority,
                     is_core_domain = excluded.is_core_domain""",
            (dom["name"], domain_key, domain_type,
             f"Seeded verbatim from foundation_domains.md DOMAIN {letter}.",
             priority, is_core))
        stats["domains"] += 1

        if concept_type is None:
            # Source and governance domains seed a domain row and no
            # concepts, deliberately. See DOMAIN_MAP.
            continue

        siblings: list[str] = []
        for term in dom["terms"]:
            name, aliases = split_aliases(term)
            if len(name) < 3:
                continue
            key = canonical_key(name)
            if not key:
                # Too short or unshapeable for a canonical key ("BP", "s").
                # Skipped rather than mangled into something that no longer
                # names the thing.
                continue

            # Deterministic dedup BEFORE any similarity question: the same
            # term under three domains is one concept with three provenance
            # notes, not three concepts.
            existing = conn.execute(
                """select concept_id from concepts
                    where canonical_key = %s
                       or norm_phrase(canonical_name) = norm_phrase(%s)
                    limit 1""", (key, name)).fetchone()
            if existing:
                concept_id = existing[0]
                conn.execute(
                    """update concepts
                          set origin_detail = origin_detail || %s
                        where concept_id = %s and origin_detail not like %s""",
                    (f"; also DOMAIN {letter}", concept_id, f"%DOMAIN {letter}%"))
                stats["reused"] += 1
            else:
                concept_id = conn.execute(
                    """insert into concepts
                         (canonical_key, canonical_name, concept_type, status,
                          origin_method, origin_detail)
                       values (%s,%s,%s,'SEEDED','SEED',%s)
                       returning concept_id""",
                    (key, name, concept_type,
                     f"K1 seed, foundation_domains.md DOMAIN {letter} ({dom['name']})")
                ).fetchone()[0]
                stats["concepts"] += 1
            # The domain edge is a ROW, not a sentence in origin_detail
            # (migration 024). Layer A scores against this family and
            # cannot be made to parse provenance prose for it.
            conn.execute(
                """insert into concept_domains (concept_id, domain_id, source)
                   select %s, domain_id, 'K1_SEED' from knowledge_domains
                    where domain_key = %s and active
                   on conflict do nothing""",
                (concept_id, domain_key))

            siblings.append(str(concept_id))

            for alias in aliases:
                conn.execute(
                    """insert into concept_aliases
                         (concept_id, alias_text, method, confidence, confirmed)
                       values (%s,%s,'SEED',1.0,true) on conflict do nothing""",
                    (concept_id, alias))
                stats["aliases"] += 1

        stats["confusable"] += _generate_confusable(conn, letter, siblings)

    stats["confusable"] += _resolve_alias_collisions(conn)
    stats["domain_edges"] = conn.execute(
        "select count(*) from concept_domains where source = 'K1_SEED'").fetchone()[0]

    if verbose:
        print(f"K1 seed: {stats['domains']} domains, {stats['concepts']} new concepts, "
              f"{stats['reused']} reused across domains, {stats['aliases']} aliases, "
              f"{stats['confusable']} confusable pairs, "
              f"{stats['domain_edges']} concept-domain edges")
    return stats


def _resolve_alias_collisions(conn) -> int:
    """A slash form that is independently a concept is NOT an alias.

    The curriculum lists "menopause / perimenopause" under one domain and
    "perimenopause" on its own under another. Splitting the first makes
    perimenopause an alias of menopause -- which merges two clinically
    distinct life stages, exactly the failure CONFUSABLE_DO_NOT_MERGE
    exists to prevent (D3). Ordering cannot fix it, because either term may
    be seeded first, so it is resolved once at the end.

    The alias is removed and the two are recorded as confusable instead:
    adjacent, easily conflated, and never to be merged.
    """
    collisions = conn.execute(
        """select a.alias_id, a.concept_id, c.concept_id
             from concept_aliases a
             join concepts c on norm_phrase(c.canonical_name) = a.alias_norm
            where a.method = 'SEED' and c.concept_id <> a.concept_id""").fetchall()
    made = 0
    for alias_id, owner_id, other_id in collisions:
        conn.execute("delete from concept_aliases where alias_id = %s", (alias_id,))
        conn.execute(
            """insert into concept_relations
                 (from_concept, to_concept, relation_type, note, method)
               values (%s,%s,'CONFUSABLE_DO_NOT_MERGE',%s,'SEED')
               on conflict do nothing""",
            (owner_id, other_id,
             "The curriculum lists these as alternate forms of one another AND as "
             "separate terms. They are adjacent and easily conflated, and they are "
             "not the same thing. Generated from sibling structure (D3)."))
        made += 1
    return made


def _generate_confusable(conn, letter: str, siblings: list[str]) -> int:
    """Derive CONFUSABLE_DO_NOT_MERGE pairs FROM STRUCTURE, not by hand (D3).

    Siblings under one domain that are lexically close are exactly where a
    dangerous merge happens -- "visceral fat" and "subcutaneous fat" sit
    beside each other in the curriculum and are different compartments with
    different risk. Hand-enumeration cannot keep up with a growing
    ontology; the structure can.
    """
    if len(siblings) < 2:
        return 0

    # Scored in Python, not by pg_trgm's similarity().
    #
    # This used to be an unguarded SQL `similarity()` call, which meant K1
    # died with UndefinedFunction on a database without pg_trgm -- an
    # extension D15 says is genuinely optional, and which step 10b had
    # proved the system ran without.
    #
    # Gating the call and seeding fewer pairs would satisfy the letter of
    # D15 and get the safety layer wrong: a CONFUSABLE_DO_NOT_MERGE pair
    # records that two concepts must never be merged, and which of those
    # records exist must not depend on which extensions the server happened
    # to have. scripts/trigram.py reproduces pg_trgm's similarity exactly,
    # so the seed is identical either way, and test_ontology_seed.py
    # asserts that agreement against the real function whenever pg_trgm IS
    # present.
    #
    # Sibling groups are small -- a domain's concepts, not the table -- so
    # scoring them here costs nothing. normalize.py's trigram TIER is a
    # different operation: it searches every concept and is answered by a
    # GIN index, so it stays gated on the capability.
    names = {str(cid): name for cid, name in conn.execute(
        "select concept_id, norm_phrase(canonical_name) from concepts "
        "where concept_id = any(%s::uuid[])", (siblings,)).fetchall()}
    pairs = [
        (a, b)
        for a, b in itertools.combinations(sorted(names), 2)
        if 0.45 <= trigram.similarity(names[a], names[b]) <= 0.85
    ]
    made = 0
    for a, b in pairs:
        conn.execute(
            """insert into concept_relations
                 (from_concept, to_concept, relation_type, note, method)
               values (%s,%s,'CONFUSABLE_DO_NOT_MERGE',%s,'SEED')
               on conflict do nothing""",
            (a, b, f"Lexically close siblings under DOMAIN {letter}. "
                   "Generated from sibling structure (D3), not hand-listed. "
                   "Review before ever merging."))
        made += 1
    return made


if __name__ == "__main__":
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is not set. See docs/LOCAL_DEV.md.")
    text = SEED.read_text(encoding="utf-8")
    expected = declared_hash(text)
    actual = body_hash(text)
    if actual != expected:
        raise SystemExit(
            f"foundation_domains.md body hash is {actual[:16]}, expected {expected[:16]}.\n"
            "The curriculum is recovered verbatim and must not drift. Refusing to seed.")
    conn = psycopg.connect(dsn, autocommit=True)
    seed(conn)

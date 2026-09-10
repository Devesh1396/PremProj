#!/usr/bin/env python3
"""K14 — embedding freshness and hybrid retrieval.

BUILD_GUIDE step 17. DECISIONS.md D8, D15, D34, D38; migrations 018, 023.
CLAUDE.md V2: nothing here constructs both halves of a comparison.

Two claims are under test, and both are behavioural:

**"Do not regenerate unchanged embeddings."** Proved by COUNTING REAL CALLS
through `embed_library.run()` -- the real selection query, the real
`embedding.embed()` boundary, the real write -- with only the transport
replaced by a stub. Running it twice must cost zero calls the second time,
and editing one row must cost exactly one.

**"The cross-domain case retrieves across nine domains, not three disease
folders."** Proved by running `retrieval.retrieve()` against a library that
is deliberately lopsided -- eighteen strategies in three disease folders,
six across the other six domains -- and then running THE SAME FUNCTION
again with the per-bucket cap lifted. Both halves are production code with
one parameter changed, so the comparison says something about production:
the cap is what produces the breadth, and without it the same library and
the same query return the folders.

The vector channel is driven by a deterministic stub embedder: unit-norm,
1536 dimensions, derived from the text. That is a transport, not a second
implementation -- every check in `embedding.py` and every trigger in 018
runs exactly as it does on a live provider (V2).
"""
from __future__ import annotations

import hashlib
import math
import os
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "testing"))

import psycopg

import embed_library as EL
import embedding as EM
import retrieval as RT

FAILS: list[str] = []
PREFIX = "RETTEST_"

# The nine domains the step 17 acceptance criterion names, in its words.
# The first three are the "disease folders" a lexical search collapses to;
# the other six are the breadth it must not lose.
FOLDERS = ["INSULIN_SENSITIVITY", "HEPATIC_FAT", "TRIGLYCERIDES"]
BREADTH = ["MUSCLE_MASS", "APPETITE_REGULATION", "SLEEP_QUALITY",
           "VEGETARIAN_IMPLEMENTATION", "EXERCISE_CAPACITY", "BEHAVIOUR_CHANGE"]
DOMAINS = FOLDERS + BREADTH


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


# ---------------------------------------------------------------------
# A deterministic stub embedder
# ---------------------------------------------------------------------

# Keywords that stand in for meaning. Each gets its own direction, and a
# text's vector is the sum of the directions its keywords name.
TOPICS = ["insulin", "hepatic", "triglycerid", "muscle", "appetite", "sleep",
          "vegetarian", "exercise", "behaviour"]


def _hash_vector(seed: str, dims: int) -> list[float]:
    raw = b""
    counter = 0
    while len(raw) < dims * 4:
        raw += hashlib.sha256(f"{counter}:{seed}".encode()).digest()
        counter += 1
    return [struct.unpack("<i", raw[i * 4:(i + 1) * 4])[0] / 2**31
            for i in range(dims)]


def stub_vector(text: str, dims: int) -> list[float]:
    """A unit-norm vector with enough semantics to be worth blending.

    A stub that hashed the whole string would give every pair of distinct
    texts a near-zero, effectively RANDOM similarity -- and per-channel
    normalization then rescales that noise across the full [0,1] range, so
    the vector channel would decide the ranking by coin flip. A suite whose
    acceptance check passes on that is not measuring retrieval; the first
    version of this file did exactly that and passed by luck on both
    capability floors.

    So each topic keyword gets its own pseudo-random direction and a text
    is the sum of the directions its keywords name, plus a small
    text-specific component to keep distinct texts distinct. Texts about
    insulin land near other texts about insulin and far from texts about
    sleep -- which is the ONE property of a real embedder any of this
    depends on.

    This replaces the PROVIDER and nothing else (V2). Every check in
    `embedding.py` and every trigger in 018 runs on its output exactly as
    on a live vector.
    """
    lowered = text.lower()
    values = [0.08 * v for v in _hash_vector(f"text:{text}", dims)]
    for topic in TOPICS:
        if topic in lowered:
            for i, v in enumerate(_hash_vector(f"topic:{topic}", dims)):
                values[i] += v
    length = math.sqrt(sum(v * v for v in values))
    return [v / length for v in values]


class Stub:
    """Counts calls. The count IS the assertion for the freshness claim."""

    def __init__(self, norm: float = 1.0):
        self.calls: list[str] = []
        self.norm = norm

    def __call__(self, model: str, text: str, dims: int) -> list[float]:
        self.calls.append(text)
        return [v * self.norm for v in stub_vector(text, dims)]


# ---------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------

def clear(conn) -> None:
    """Leave the database as this suite found it.

    The backfill under test is the REAL one, so it embeds every stale
    strategy -- including the fixtures other suites left behind, which it
    should, because restricting it would be testing a different function.
    The residue is this suite's to remove: stub vectors on rows it does not
    own, the provenance pin those vectors created, and cost rows for spend
    that never happened. A suite that leaves stub vectors in the library
    makes the next run of any retrieval check meaningless.
    """
    conn.execute("delete from strategies where canonical_key like %s", (PREFIX + "%",))
    conn.execute("delete from concepts where canonical_key like %s", (PREFIX + "%",))
    conn.execute(
        "delete from source_items where content_hash like %s", (PREFIX + "%",))
    if RT.vector_available(conn):
        conn.execute(
            "update strategies set embedding = null, embedding_model = null, "
            "embedding_dim = null, embedding_source_hash = null, embedded_at = null "
            "where embedding is not null")
        conn.execute(
            "delete from embedding_provenance where table_name = 'strategies'")
    conn.execute(
        "delete from cost_events where operation = 'EMBEDDING' "
        "  and entity_type in ('strategies', 'retrieval_query')")


def seed(conn) -> dict:
    """A deliberately lopsided cross-domain library.

    Six strategies in each of the three disease folders and one in each of
    the other six domains. That imbalance is the point: it is what a real
    library looks like after ingesting cardiometabolic sources, and it is
    what makes an uncapped ranking return three folders.
    """
    concepts = {}
    for name in DOMAINS:
        concepts[name] = str(conn.execute(
            "insert into concepts (canonical_key, canonical_name, concept_type, "
            "status, origin_method, definition) "
            "values (%s,%s,'DRIVER','ACTIVE','SEED',%s) returning concept_id",
            (PREFIX + name, name.lower().replace("_", " "),
             f"the {name.lower().replace('_', ' ')} domain")).fetchone()[0])

    strategies = {}
    for domain in DOMAINS:
        count = 6 if domain in FOLDERS else 1
        # The presenting complaint's concepts are PRIMARY links; the
        # concepts Engine 1 raised alongside it are weaker ones. That is
        # what a real case looks like, and it makes the breadth harder to
        # achieve rather than easier -- the sleep material has to survive
        # both a smaller library share AND a weaker link.
        weight = 1.0 if domain in FOLDERS else 0.4
        for n in range(count):
            key = f"{PREFIX}{domain}_{n}"
            sid = str(conn.execute(
                "insert into strategies (name, canonical_key, summary, mechanism, "
                "knowledge_status) values (%s,%s,%s,%s,'AI_DISCOVERED_CANDIDATE') "
                "returning strategy_id",
                (f"{PREFIX}{domain} strategy {n}", key,
                 f"a strategy addressing {domain.lower().replace('_', ' ')}",
                 f"the mechanism of {domain.lower().replace('_', ' ')}")).fetchone()[0])
            conn.execute(
                "insert into strategy_concepts (strategy_id, concept_id, link_role, "
                "weight) values (%s,%s,'INDICATED_FOR',%s)",
                (sid, concepts[domain], weight))
            strategies[key] = sid
    return {"concepts": concepts, "strategies": strategies}


def seed_chunks(conn) -> dict:
    """One ordinary item and one held-out item, each with one chunk.

    A3: the held-out item is the retrieval answer key. It must be
    retrievable when evaluation asks for it and invisible when it does not.
    """
    ids = {}
    for label, held_out in (("open", False), ("heldout", True)):
        item = str(conn.execute(
            "insert into source_items (title, content_hash, ingestion_status, "
            "held_out, held_out_batch) values (%s,%s,'NORMALIZED',%s,%s) "
            "returning item_id",
            (f"{PREFIX}{label}", f"{PREFIX}{label}", held_out,
             "RETTEST" if held_out else None)).fetchone()[0])
        doc = str(conn.execute(
            "insert into source_documents (item_id, document_type) "
            "values (%s,'TEST') returning document_id", (item,)).fetchone()[0])
        conn.execute(
            "insert into knowledge_chunks (document_id, chunk_index, text) "
            "values (%s,0,%s)",
            (doc, f"chelation of postprandial glycaemia {label} corpus"))
        ids[label] = item
    return ids


def domains_covered(conn, result: dict, concepts: dict) -> set:
    """Which of the nine domains the returned page actually reaches.

    Read from the RESULTS' buckets, which retrieval assigned -- not
    recomputed from the fixture. A page that returns three folders reaches
    three domains however many rows it has.
    """
    by_id = {v: k for k, v in concepts.items()}
    reached = set()
    for row in result["results"]:
        for bucket in row["buckets"]:
            if bucket in by_id:
                reached.add(by_id[bucket])
    return reached


def main() -> int:
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    vector_on = RT.vector_available(conn)
    clear(conn)
    fixture = seed(conn)
    items = seed_chunks(conn)
    concept_ids = list(fixture["concepts"].values())

    # ==================================================================
    print("\nembedding freshness (K14: do not regenerate unchanged embeddings)")

    if not vector_on:
        print("  SKIP  pgvector is absent (D15): there is no embedding column, "
              "so there is nothing to keep fresh.")
        print("        Retrieval below still runs on metadata + full text.")
    else:
        stub = Stub()
        first = EL.run(conn, ["strategies"], limit=100, call=stub)
        check("the backfill embeds every stale strategy",
              first["strategies"]["embedded"] >= len(fixture["strategies"]),
              str(first))
        check("nothing is left stale after a full pass",
              EL.stale_count(conn, "strategies") == 0,
              str(EL.stale_count(conn, "strategies")))

        calls_after_first = len(stub.calls)
        second = EL.run(conn, ["strategies"], limit=100, call=stub)
        check("a second pass makes NO provider call",
              len(stub.calls) == calls_after_first and second["strategies"]["embedded"] == 0,
              f"{len(stub.calls) - calls_after_first} extra call(s)")

        # NAMED, not `next(iter(...))`. The edits below change this row's
        # text, and the ranking checks further down query for a different
        # row by name -- picking whichever strategy happened to be first
        # coupled the two sections invisibly, and the coupling only
        # surfaced once the full-text channel started matching at all
        # (bug 63). A fixture whose sections interfere is a fixture that
        # will fail for a reason unrelated to what it is testing.
        one = fixture["strategies"][f"{PREFIX}APPETITE_REGULATION_0"]
        conn.execute("update strategies set summary = %s where strategy_id = %s",
                     (PREFIX + "edited summary", one))
        third = EL.run(conn, ["strategies"], limit=100, call=stub)
        check("editing one row costs exactly one call",
              len(stub.calls) == calls_after_first + 1
              and third["strategies"]["embedded"] == 1,
              f"{len(stub.calls) - calls_after_first} call(s), "
              f"{third['strategies']['embedded']} embedded")

        # The hash is of the TEXT, from the module's own expression -- not a
        # second copy of the concatenation written here.
        expr = EL.EMBEDDABLE["strategies"]["text"]
        mismatched = conn.execute(
            f"select count(*) from strategies where canonical_key like %s "
            f"  and embedding is not null "
            f"  and embedding_source_hash "
            f"      <> encode(sha256(convert_to(({expr}), 'UTF8')), 'hex')",
            (PREFIX + "%",)).fetchone()[0]
        check("every stored hash is the hash of the text that was embedded",
              mismatched == 0, f"{mismatched} row(s) disagree")

        model, dims = conn.execute(
            "select embedding_model, embedding_dim from embedding_provenance "
            " where table_name='strategies'").fetchone()
        check("the write pinned the model and dimension (018)",
              model == os.environ.get("MODEL_EMBEDDING") and dims == 1536,
              f"{model} / {dims}")

        priced = conn.execute(
            "select count(*) from cost_events where operation='EMBEDDING' "
            "  and entity_type='strategies' and modality='TEXT'").fetchone()[0]
        check("every embedding recorded a TEXT-modality cost row (D38)",
              priced >= len(fixture["strategies"]), str(priced))

        # ------------------------------------------------------------------
        print("\na degraded vector is refused at the boundary, not stored")

        bad = Stub(norm=0.702)   # gemini-embedding-001 truncated to 1536
        conn.execute("update strategies set summary=%s where strategy_id=%s",
                     (PREFIX + "forces a re-embed", one))
        before = conn.execute(
            "select embedding_source_hash from strategies where strategy_id=%s",
            (one,)).fetchone()[0]
        try:
            EL.run(conn, ["strategies"], limit=1, call=bad)
            check("a non-unit-norm vector is refused (D34)", False, "no error")
        except EM.BadVector as exc:
            check("a non-unit-norm vector is refused (D34)",
                  "0.702" in str(exc) or "norm" in str(exc).lower(), str(exc)[:120])
        after = conn.execute(
            "select embedding_source_hash from strategies where strategy_id=%s",
            (one,)).fetchone()[0]
        check("the refused row was not written",
              after == before, f"{before} -> {after}")

        # Put the library back into a fresh state for the retrieval checks.
        EL.run(conn, ["strategies"], limit=100, call=Stub())

    # ==================================================================
    print("\nthe cross-domain case (step 17 acceptance)")

    query = "insulin resistance with hepatic fat and raised triglycerides"
    # NO per_bucket_cap is passed. The acceptance criterion has to hold at
    # the DEFAULT setting, or the breadth is a knob this test turned rather
    # than a property the system has.
    capped = RT.retrieve(conn, query=query, concept_ids=concept_ids,
                         kinds=("strategy",), limit=12, embed_call=Stub())
    reached = domains_covered(conn, capped, fixture["concepts"])
    check("the default page reaches all nine domains",
          reached == set(DOMAINS), f"reached {sorted(reached)}")
    check("the cap was derived, not passed in",
          capped["diagnostics"]["per_bucket_cap"]
          == RT.derive_cap(12, len(concept_ids)),
          str(capped["diagnostics"].get("per_bucket_cap")))
    check("it is not three disease folders",
          not reached.issubset(set(FOLDERS)), sorted(reached))

    # The counterfactual, run through the SAME function with one parameter
    # changed. Both halves are production code (V2).
    uncapped = RT.retrieve(conn, query=query, concept_ids=concept_ids,
                           kinds=("strategy",), limit=12, per_bucket_cap=99,
                           embed_call=Stub())
    uncapped_reach = domains_covered(conn, uncapped, fixture["concepts"])
    # The sharp form of the claim, not "fewer": uncapped returns EXACTLY
    # the three disease folders the acceptance criterion names. "Fewer"
    # would still pass on a tie broken by UUID order, which is how the
    # first version of this check passed without measuring anything.
    check("without the cap the same library returns disease folders ONLY",
          uncapped_reach and uncapped_reach.issubset(set(FOLDERS)),
          f"uncapped {sorted(uncapped_reach)} vs capped {sorted(reached)}")
    check("...and strictly fewer domains than the capped page",
          len(uncapped_reach) < len(reached),
          f"{len(uncapped_reach)} vs {len(reached)}")
    check("both pages are the same size, so breadth cost no recall",
          len(capped["results"]) == len(uncapped["results"]),
          f"{len(capped['results'])} vs {len(uncapped['results'])}")

    # ==================================================================
    print("\nthe concept spine is a channel, not a filter")

    # Nothing in this query is lexically near sleep or behaviour. Only the
    # spine can reach them.
    spine_only = RT.retrieve(conn, query="hepatic steatosis",
                             concept_ids=[fixture["concepts"]["SLEEP_QUALITY"],
                                          fixture["concepts"]["BEHAVIOUR_CHANGE"]],
                             kinds=("strategy",), limit=10, embed_call=Stub())
    labels = [r["label"] for r in spine_only["results"]]
    check("a concept with no lexical overlap still retrieves",
          any("SLEEP_QUALITY" in l for l in labels), str(labels[:4]))
    check("the spine channel is reported in the diagnostics",
          "strategy_concepts" in spine_only["diagnostics"]["concept"],
          spine_only["diagnostics"]["concept"])

    # What the spine is worth is measured as RANK MOVEMENT, not as presence.
    # "Sleep is absent entirely" is a statement about how small the library
    # is -- in a library of 29 strategies a page of 10 reaches most of it,
    # and the check would pass or fail on the corpus size rather than on the
    # mechanism.
    def rank_of(result, fragment):
        for position, row in enumerate(result["results"]):
            if fragment in row["label"]:
                return position
        return None

    # "hepatic fat" so the full-text channel genuinely fires on BOTH
    # capability floors -- the point is what the spine adds on top of a
    # working lexical match, not what it adds to nothing.
    lexical = "hepatic fat"
    without = RT.retrieve(conn, query=lexical, concept_ids=[],
                          kinds=("strategy",), limit=40, embed_call=Stub())
    with_spine = RT.retrieve(conn, query=lexical,
                             concept_ids=[fixture["concepts"]["SLEEP_QUALITY"]],
                             kinds=("strategy",), limit=40, embed_call=Stub())
    check("the lexical query does find the hepatic material on its own",
          rank_of(without, "HEPATIC_FAT") is not None,
          str([r["label"][:40] for r in without["results"][:3]]))
    before_rank = rank_of(without, "SLEEP_QUALITY")
    after_rank = rank_of(with_spine, "SLEEP_QUALITY")
    # `before_rank is None` is the STRONGER form of the same claim, and it
    # is what happens without pgvector: the spine is the only way there at
    # all. Both floors assert the same thing -- naming the concept is what
    # puts the material on the page.
    check("naming the concept is what puts its material on the page",
          after_rank is not None and (before_rank is None
                                      or after_rank < before_rank),
          f"rank {before_rank} -> {after_rank}")
    # NOT "and it ranks first": a row the lexical AND vector channels both
    # found outranking one the spine alone reached is correct behaviour,
    # and asserting otherwise would be asserting a floor rather than an
    # invariant -- it holds without pgvector and fails with it. The
    # invariant is HOW it got there.
    #
    # Nor "through the spine ALONE": the vector channel ranks the whole
    # embedded table, so it also "finds" the sleep row at a negligible
    # 0.047. That is correct -- a low score sorts low. The invariant is
    # which channel DRIVES the row onto the page.
    sleep_row = with_spine["results"][after_rank] if after_rank is not None else {}
    channels = sleep_row.get("channels", {})
    check("and the spine is what drove it there",
          bool(channels) and max(channels, key=channels.get) == "concept",
          str({c: round(v, 3) for c, v in channels.items()}))

    # ==================================================================
    print("\ndedupe: one row per result, every channel recorded")

    both = RT.retrieve(conn, query=f"{PREFIX}INSULIN_SENSITIVITY strategy 0",
                       concept_ids=[fixture["concepts"]["INSULIN_SENSITIVITY"]],
                       kinds=("strategy",), limit=20, embed_call=Stub())
    ids = [r["id"] for r in both["results"]]
    check("no result appears twice", len(ids) == len(set(ids)),
          f"{len(ids)} rows, {len(set(ids))} distinct")
    multi = [r for r in both["results"] if len(r["channels"]) > 1]
    check("a row found by several channels carries all of them",
          bool(multi), str(both["diagnostics"]))
    if vector_on:
        check("the vector channel ran and is one of them",
              any("vector" in r["channels"] for r in both["results"]),
              both["diagnostics"]["vector"])
        top = both["results"][0]["label"]
        check("the row whose text the query repeats ranks first",
              "INSULIN_SENSITIVITY strategy 0" in top, top)
    else:
        print("  SKIP  no pgvector: the vector channel cannot run here (D15).")

    # ==================================================================
    print("\nD15: degradation is loud, never silent")

    diag = both["diagnostics"]["vector"]
    if vector_on:
        check("the vector diagnostic names what it searched",
              "embedded query against" in diag, diag)
    else:
        check("the vector diagnostic says pgvector is absent, and cites D15",
              "pgvector absent" in diag and "D15" in diag, diag)
        check("the other channels still returned results",
              bool(both["results"]), str(both["diagnostics"]))

    coverage = conn.execute(
        "select embedded, vector_capable from v_embedding_coverage "
        " where table_name='strategies'").fetchone()
    check("v_embedding_coverage exists in both configurations",
          coverage is not None)
    if vector_on:
        check("coverage reports a count when vectors are possible",
              coverage[0] is not None and coverage[1] is True, str(coverage))
    else:
        check("coverage reports NULL, not zero, when they are not",
              coverage[0] is None and coverage[1] is False, str(coverage))

    # ==================================================================
    print("\nA3: held-out material is the answer key, not a source")

    open_only = RT.retrieve(conn, query="chelation postprandial glycaemia",
                            kinds=("chunk",), limit=10, embed_call=Stub())
    found = {r["id"] for r in open_only["results"]}
    held_chunk = str(conn.execute(
        "select c.chunk_id from knowledge_chunks c "
        "  join source_documents d on d.document_id=c.document_id "
        " where d.item_id=%s", (items["heldout"],)).fetchone()[0])
    check("a held-out chunk is not retrieved by default",
          held_chunk not in found, str(open_only["diagnostics"]))
    check("the ordinary chunk is", bool(found), str(open_only["diagnostics"]))

    with_held = RT.retrieve(conn, query="chelation postprandial glycaemia",
                            kinds=("chunk",), limit=10, include_held_out=True,
                            embed_call=Stub())
    check("evaluation can ask for it explicitly",
          held_chunk in {r["id"] for r in with_held["results"]},
          str(with_held["diagnostics"]))

    # ==================================================================
    print("\ndeterminism and telemetry")

    a = RT.retrieve(conn, query=query, concept_ids=concept_ids,
                    kinds=("strategy",), limit=12, embed_call=Stub())
    b = RT.retrieve(conn, query=query, concept_ids=concept_ids,
                    kinds=("strategy",), limit=12, embed_call=Stub())
    check("the same library and query return the same page in the same order",
          [r["id"] for r in a["results"]] == [r["id"] for r in b["results"]])

    hits_before = conn.execute(
        "select retrieval_hits from concepts where concept_id=%s",
        (fixture["concepts"]["SLEEP_QUALITY"],)).fetchone()[0]
    RT.retrieve(conn, query=query,
                concept_ids=[fixture["concepts"]["SLEEP_QUALITY"]],
                kinds=("strategy",), limit=5, embed_call=Stub())
    hits_after = conn.execute(
        "select retrieval_hits from concepts where concept_id=%s",
        (fixture["concepts"]["SLEEP_QUALITY"],)).fetchone()[0]
    check("a retrieved concept records the hit (002 telemetry)",
          hits_after > hits_before, f"{hits_before} -> {hits_after}")

    # ==================================================================
    print("\nD8: a PROPOSED concept is not a retrieval anchor")

    proposed = str(conn.execute(
        "insert into concepts (canonical_key, canonical_name, concept_type, "
        "status, origin_method) values (%s,'proposed thing','DRIVER','PROPOSED','LLM') "
        "returning concept_id", (PREFIX + "PROPOSED",)).fetchone()[0])
    check("resolve_concepts ignores a PROPOSED key",
          RT.resolve_concepts(conn, [PREFIX + "PROPOSED"]) == [],
          proposed)
    check("and returns a live one",
          RT.resolve_concepts(conn, [PREFIX + "SLEEP_QUALITY"])
          == [fixture["concepts"]["SLEEP_QUALITY"]])

    # ==================================================================
    print("\nDEPRECATED strategies are filtered before anything is scored")

    dead = fixture["strategies"][f"{PREFIX}APPETITE_REGULATION_0"]
    conn.execute("update strategies set knowledge_status='DEPRECATED', "
                 "provenance_note='RETTEST merge loser' where strategy_id=%s", (dead,))
    after_dep = RT.retrieve(conn, query=query, concept_ids=concept_ids,
                            kinds=("strategy",), limit=30, embed_call=Stub())
    check("a DEPRECATED strategy is never returned",
          dead not in {r["id"] for r in after_dep["results"]})

    clear(conn)
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("test_retrieval: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

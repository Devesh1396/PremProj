#!/usr/bin/env python3
"""Embedding provenance and unit-norm enforcement.

BUILD_GUIDE step 16, DECISIONS.md D34, migration 018.

The failure this suite exists to stop is the quiet one. A vector truncated
to 1536 without being re-normalised still returns results — just worse
ones — with no error anywhere. `gemini-embedding-001` at 1536 returns an L2
norm of 0.702; measured, not recalled, in
`docs/evidence/embedding_dimension_probe.md`.

Nothing in the schema could have caught that. Three things now can: every
vector carries the model and dimensionality that made it, a non-unit-norm
vector is refused on write, and a second model into the same column is
refused outright.

Skips loudly without pgvector. That is a supported configuration (D15) in
which there are no embedding columns at all, and a suite that cannot run
must say so rather than pass quietly.
"""
from __future__ import annotations

import math
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import psycopg
import pricing as PR
import embedding as EM

FAILS: list[str] = []
PREFIX = "EMBTEST_"
TABLES = ("concepts", "concept_aliases", "strategies", "knowledge_chunks",
          "implementation_patterns")


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def expect_error(conn, sql, params, name, fragment):
    try:
        with conn.transaction():
            conn.execute(sql, params)
    except psycopg.Error as exc:
        check(name, fragment.lower() in str(exc).lower(), str(exc)[:200])
        return
    check(name, False, "no error was raised")


def vec(dim: int, norm: float = 1.0) -> str:
    """A vector of `dim` dimensions whose L2 norm is `norm`."""
    value = norm / math.sqrt(dim)
    return "[" + ",".join(f"{value!r}" for _ in range(dim)) + "]"


def clear(conn) -> None:
    conn.execute("delete from concepts where canonical_key like %s", (PREFIX + "%",))
    conn.execute("delete from embedding_provenance where table_name='concepts'")


def main() -> int:
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)

    enabled = conn.execute(
        "select enabled from system_capabilities where capability='vector'").fetchone()
    if not enabled or not enabled[0]:
        print("\n  SKIP  pgvector is absent; there are no embedding columns to "
              "guard (D15).")
        print("        This is a supported configuration, not a degraded one.\n")
        return 0

    clear(conn)

    # ------------------------------------------------------------------
    print("\none source for the dimension")

    dim = conn.execute("select embedding_dim()").fetchone()[0]
    check("embedding_dim() reports a dimension", dim is not None and dim > 0, str(dim))

    declared = {
        t: conn.execute(
            "select a.atttypmod from pg_attribute a join pg_class c on c.oid=a.attrelid "
            " where c.relname=%s and a.attname='embedding' and not a.attisdropped",
            (t,)).fetchone()[0] for t in TABLES}
    check("...read from the catalog, not from a literal",
          declared["knowledge_chunks"] == dim, str(declared))
    check("all five embedding columns agree on it",
          len(set(declared.values())) == 1, str(declared))

    # The copy that used to drift. .env.example is documentation of what the
    # database says; this is what makes it true rather than hopeful.
    env_example = (REPO / ".env.example").read_text(encoding="utf-8")
    m = re.search(r"^EMBEDDING_DIM=(\d+)", env_example, re.M)
    check(".env.example's EMBEDDING_DIM matches the database",
          m is not None and int(m.group(1)) == dim,
          f"{m.group(1) if m else 'absent'} vs {dim}")

    m = re.search(r"^MODEL_EMBEDDING=(\S+)", env_example, re.M)
    check(".env.example names an embedding model", m is not None and m.group(1),
          m.group(1) if m else "unset")

    # ------------------------------------------------------------------
    print("\na good vector is accepted and pins the column")

    model = "gemini-embedding-2"
    conn.execute(
        "insert into concepts (canonical_key, canonical_name, concept_type, status, "
        "                      embedding, embedding_model, embedding_dim) "
        "values (%s,'Emb one','PHYSIOLOGY','ACTIVE',%s::vector,%s,%s)",
        (PREFIX + "ONE", vec(dim), model, dim))

    got = conn.execute(
        "select sqrt(-(embedding <#> embedding)) from concepts where canonical_key=%s",
        (PREFIX + "ONE",)).fetchone()[0]
    tolerance = conn.execute("select embedding_norm_tolerance()").fetchone()[0]
    check("a genuine unit vector survives float4 storage inside the tolerance",
          abs(got - 1.0) < tolerance,
          f"norm {got}, error {abs(got - 1.0):.3g}, tolerance {tolerance}")

    pinned = conn.execute(
        "select embedding_model, embedding_dim, vectors_written "
        "  from embedding_provenance where table_name='concepts'").fetchone()
    check("the first write pins the model and dimensionality",
          pinned == (model, dim, 1), str(pinned))

    # ------------------------------------------------------------------
    print("\nthe failure the probe showed is possible")

    # gemini-embedding-001 truncated to 1536 returns exactly this shape.
    expect_error(
        conn,
        "insert into concepts (canonical_key, canonical_name, concept_type, status, "
        "                      embedding, embedding_model, embedding_dim) "
        "values (%s,'Bad norm','PHYSIOLOGY','ACTIVE',%s::vector,%s,%s)",
        (PREFIX + "BADNORM", vec(dim, norm=0.702191), model, dim),
        "a vector that was truncated and never re-normalised is REFUSED",
        "not 1")

    expect_error(
        conn,
        "insert into concepts (canonical_key, canonical_name, concept_type, status, "
        "                      embedding, embedding_model, embedding_dim) "
        "values (%s,'Bad norm','PHYSIOLOGY','ACTIVE',%s::vector,%s,%s)",
        (PREFIX + "BADNORM2", vec(dim, norm=0.702191), model, dim),
        "...and the message names the norm it actually had",
        "0.702")

    # ------------------------------------------------------------------
    print("\nprovenance is required, not requested")

    for column, value, name in (
            ("embedding_model", None, "a vector with no model is refused"),
            ("embedding_dim", None, "a vector with no dimensionality is refused")):
        params = {"embedding_model": model, "embedding_dim": dim}
        params[column] = value
        expect_error(
            conn,
            "insert into concepts (canonical_key, canonical_name, concept_type, status, "
            "                      embedding, embedding_model, embedding_dim) "
            "values (%s,'No provenance','PHYSIOLOGY','ACTIVE',%s::vector,%s,%s)",
            (PREFIX + "NOPROV_" + column.upper(), vec(dim),
             params["embedding_model"], params["embedding_dim"]),
            name, "must carry the model")

    expect_error(
        conn,
        "insert into concepts (canonical_key, canonical_name, concept_type, status, "
        "                      embedding, embedding_model, embedding_dim) "
        "values (%s,'Lying dim','PHYSIOLOGY','ACTIVE',%s::vector,%s,%s)",
        (PREFIX + "LYINGDIM", vec(dim), model, dim // 2),
        "a declared dimensionality that disagrees with the vector is refused",
        "dimensions")

    # ------------------------------------------------------------------
    print("\nmixing models in one index is impossible, not merely unlikely")

    expect_error(
        conn,
        "insert into concepts (canonical_key, canonical_name, concept_type, status, "
        "                      embedding, embedding_model, embedding_dim) "
        "values (%s,'Other model','PHYSIOLOGY','ACTIVE',%s::vector,%s,%s)",
        (PREFIX + "OTHERMODEL", vec(dim), "gemini-embedding-001", dim),
        "a second model into a pinned column is refused",
        "gemini-embedding-001")
    expect_error(
        conn,
        "insert into concepts (canonical_key, canonical_name, concept_type, status, "
        "                      embedding, embedding_model, embedding_dim) "
        "values (%s,'Other model','PHYSIOLOGY','ACTIVE',%s::vector,%s,%s)",
        (PREFIX + "OTHERMODEL2", vec(dim), "gemini-embedding-001", dim),
        "...and the message says what re-embedding would take",
        "re-embedding the whole column")

    # An UPDATE is the same write. A trigger on INSERT alone would leave the
    # obvious back door open.
    expect_error(
        conn,
        "update concepts set embedding=%s::vector, embedding_model=%s "
        " where canonical_key=%s",
        (vec(dim), "gemini-embedding-001", PREFIX + "ONE"),
        "...including by UPDATE, not just INSERT",
        "gemini-embedding-001")

    # ------------------------------------------------------------------
    print("\nre-pinning is possible, but only deliberately")

    expect_error(
        conn, "select reset_embedding_provenance('concepts')", (),
        "re-pinning is refused while vectors remain",
        "still holds")

    conn.execute("update concepts set embedding=null, embedding_model=null, "
                 "embedding_dim=null where canonical_key like %s", (PREFIX + "%",))
    conn.execute("select reset_embedding_provenance('concepts')")
    check("...and succeeds once the column is cleared — that clearing IS the re-embed",
          conn.execute("select count(*) from embedding_provenance "
                       " where table_name='concepts'").fetchone()[0] == 0)

    conn.execute(
        "update concepts set embedding=%s::vector, embedding_model=%s, embedding_dim=%s "
        " where canonical_key=%s",
        (vec(dim), "gemini-embedding-001", dim, PREFIX + "ONE"))
    check("a different model is accepted after a deliberate reset",
          conn.execute("select embedding_model from embedding_provenance "
                       " where table_name='concepts'").fetchone()[0]
          == "gemini-embedding-001")

    # ------------------------------------------------------------------
    print("\nthe state is readable without reading anyone's vectors")

    row = conn.execute(
        "select table_name, embedding_model, embedding_dim, dim_matches_column "
        "  from v_embedding_state where table_name='concepts'").fetchone()
    check("v_embedding_state reports what each column is pinned to",
          row is not None and row[3] is True, str(row))

    # ==================================================================
    # Modality pricing (D38)
    # ==================================================================
    print("\nthe rate belongs to a MODALITY, and is never borrowed")

    model = "gemini-embedding-2"
    rates = {}
    for modality in ("TEXT", "IMAGE", "AUDIO", "VIDEO"):
        cost, source = PR.price_call(model, 1_000_000, 0, modality)
        rates[modality] = cost
        sql = conn.execute(
            "select cost_usd, price_source::text from "
            "  price_call(%s, 1000000, 0, null, null, %s)", (model, modality)
        ).fetchone()
        check(f"{modality}: Python and SQL agree on the rate",
              sql[0] is not None and float(sql[0]) == cost and sql[1] == source,
              f"python {cost}/{source} vs sql {sql[0]}/{sql[1]}")

    check("the modalities really are priced far apart",
          rates["VIDEO"] / rates["TEXT"] >= 50,
          f"text {rates['TEXT']}, video {rates['VIDEO']}")
    check("...so charging audio at the text rate would under-report ~32x",
          round(rates["AUDIO"] / rates["TEXT"]) == 32,
          f"{rates['AUDIO'] / rates['TEXT']:.1f}x")

    # The whole point: an unpriced or unstated modality must NOT borrow.
    unstated = PR.price_call(model, 1_000_000, 0)
    check("a multimodal model with NO modality given is UNPRICED, not TEXT",
          unstated == (None, PR.UNPRICED), str(unstated))
    sql_unstated = conn.execute(
        "select cost_usd, price_source::text from price_call(%s, 1000000, 0)",
        (model,)).fetchone()
    check("...and SQL refuses to guess too",
          sql_unstated == (None, "UNPRICED"), str(sql_unstated))
    unknown = PR.price_call(model, 1_000_000, 0, "HOLOGRAM")
    check("an unpriced modality is UNPRICED, never another modality's rate",
          unknown == (None, PR.UNPRICED), str(unknown))

    single = PR.price_call("claude-sonnet-5", 1_000_000, 0)
    check("a single-modality model still prices with no modality given",
          single[1] == PR.PRICE_REGISTRY, str(single))

    check("v_unpriced_spend is empty for the embedding role",
          conn.execute("select count(*) from v_unpriced_spend "
                       " where model_role='MODEL_EMBEDDING'").fetchone()[0] == 0)

    # ==================================================================
    # K14 embeds TEXT ONLY (D38)
    # ==================================================================
    print("\nK14 embeds text only, and that is enforced twice")

    os.environ["MODEL_EMBEDDING"] = model
    calls: list[str] = []

    def fake_provider(model_name, text, dims):
        calls.append(text)
        value = 1.0 / math.sqrt(dims)
        return [value] * dims

    vector, used, dims = EM.embed(conn, "postprandial glycaemia and fibre",
                                  entity_type="test", call=fake_provider)
    check("text embeds", len(vector) == dims and used == model, str((used, dims)))
    check("...and is recorded at the TEXT rate",
          conn.execute(
              "select modality, price_source::text from cost_events "
              " where operation='EMBEDDING' order by cost_event_id desc limit 1"
          ).fetchone() == ("TEXT", "PRICE_REGISTRY"))

    for payload, label in (
            (b"\x89PNG\r\n\x1a\n" + b"\x00" * 40, "a PNG"),
            (b"\xff\xd8\xff\xe0" + b"\x00" * 40, "a JPEG"),
            (b"OggS" + b"\x00" * 40, "an Ogg audio stream"),
            (b"ID3" + b"\x00" * 40, "an MP3"),
            ("data:audio/mpeg;base64,SUQzBAAA", "a data: audio URL"),
            ("video/mp4", "a media MIME type"),
            (b"\xff\xfe\x00\x01\x02", "bytes that are not UTF-8"),
            (12345, "a number"),
            ("", "nothing at all")):
        before = len(calls)
        try:
            EM.embed(conn, payload, call=fake_provider)
            check(f"{label} is refused", False, "it embedded")
        except EM.NotText:
            check(f"{label} is refused", True)
        check(f"...and {label} never reached the provider",
              len(calls) == before, f"{len(calls) - before} call(s)")

    # The database refuses it too, so neither layer is the only guard.
    expect_error(
        conn,
        "insert into cost_events (operation, model_role, model_name, modality) "
        "values ('EMBEDDING','MODEL_EMBEDDING','x','AUDIO')", (),
        "the DATABASE refuses a non-text embedding cost row",
        "ck_embedding_text_only")
    conn.execute(
        "insert into cost_events (operation, model_role, model_name, modality) "
        "values ('ENGINE_RUN','MODEL_ANALYSIS','x','AUDIO')")
    check("...while a non-embedding role may record another modality",
          True)
    conn.execute("delete from cost_events where model_name='x'")

    # D34's norm guard, at the call boundary rather than only at the column.
    def bad_norm(model_name, text, dims):
        value = 0.702191 / math.sqrt(dims)
        return [value] * dims

    try:
        EM.embed(conn, "text", call=bad_norm)
        check("a non-unit-norm vector is refused before it is returned", False,
              "it was returned")
    except EM.BadVector as exc:
        check("a non-unit-norm vector is refused before it is returned",
              "0.702" in str(exc), str(exc)[:100])

    def wrong_dims(model_name, text, dims):
        value = 1.0 / math.sqrt(dims // 2)
        return [value] * (dims // 2)

    try:
        EM.embed(conn, "text", call=wrong_dims)
        check("a wrong-dimension vector is refused", False, "it was returned")
    except EM.BadVector as exc:
        check("a wrong-dimension vector is refused", "dimensions" in str(exc))

    conn.execute("delete from cost_events where operation='EMBEDDING' "
                 "  and entity_type='test'")

    clear(conn)

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""K07 + K08 — the Knowledge Inbox and the normalizer, exercised.

BUILD_GUIDE step 16. Engine 7 §16, §42, §43, §47, §48, §50, §52, §56, §57;
MASTER_SPEC A9.

Every assertion here is about BEHAVIOUR. There is no check that a table
exists; migration 006 created these tables months ago and their existing
has never been the question.

The suite runs against a temporary knowledge directory so it can drop real
files into a real inbox and read the real receipts back. It clears its own
fixtures and re-runs cleanly against a used database.

**No model is called.** K07 and K08 are deterministic, which is the whole
reason this suite needs no provider, no key and no budget.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import psycopg

FAILS: list[str] = []
PREFIX = "kftest-"


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
        check(name, fragment.lower() in str(exc).lower(), str(exc)[:160])
        return
    check(name, False, "no error was raised")


def clear(conn) -> None:
    """Fixtures only. Never touches anything this suite did not create."""
    conn.execute(
        "delete from source_items where title like %s or content_hash in "
        "  (select content_hash from source_envelopes where source_title like %s)",
        (PREFIX + "%", PREFIX + "%"))
    conn.execute("delete from source_envelopes where source_title like %s",
                 (PREFIX + "%",))
    conn.execute("delete from knowledge_sources where source_name like %s",
                 (PREFIX + "%",))
    conn.execute("delete from source_kinds where source_kind = 'KFTEST_ZINE'")


def drop(inbox: Path, name: str, body: str, meta: dict | None = None) -> Path:
    path = inbox / name
    path.write_text(body, encoding="utf-8")
    if meta is not None:
        (inbox / (path.stem + ".meta.json")).write_text(
            json.dumps(meta), encoding="utf-8")
    return path


def main() -> int:
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    clear(conn)

    root = Path(tempfile.mkdtemp(prefix="kf-"))
    os.environ["KNOWLEDGE_DIR"] = str(root)
    for name in ("inbox", "raw", "processed", "failed"):
        (root / name).mkdir(parents=True, exist_ok=True)

    # Imported AFTER KNOWLEDGE_DIR is set: the module reads it at import.
    import knowledge_ingest as KI  # noqa: E402

    inbox = root / "inbox"

    # ------------------------------------------------------------------
    print("\na document the practitioner dropped in")

    body = (
        f"# {PREFIX}Berberine and glycaemic control\n\n"
        "## Mechanism\n\n"
        "Berberine activates AMPK in hepatocytes and skeletal muscle.\n\n"
        "It also alters the gut microbiome.\n\n"
        "## Dosing in practice\n\n"
        "Typical trial dosing is 500 mg two or three times daily with meals.\n\n"
        "### Interactions\n\n"
        "Berberine inhibits CYP3A4. Anyone on a statin metabolised by that "
        "pathway warrants prescriber review before starting.\n"
    )
    path = drop(inbox, PREFIX + "berberine.md", body)
    original_bytes = path.read_bytes()
    receipt = KI.ingest_one(conn, path)

    check("it normalizes", receipt.outcome == "NORMALIZED", receipt.detail or "")
    check("the inbox is left empty", not path.exists())

    env = conn.execute(
        "select status::text, raw_preserved, raw_location, content_hash, "
        "       source_kind, source_role::text, send_to_e7 "
        "  from source_envelopes where envelope_id=%s",
        (receipt.envelope_id,)).fetchone()
    check("the envelope reaches NORMALIZED", env[0] == "NORMALIZED", str(env))
    check("the raw original is preserved and located", env[1] is True and env[2])

    stored = root / env[2]
    check("the ORIGINAL BYTES are what is stored, unmodified",
          stored.exists() and stored.read_bytes() == original_bytes)
    check("...at a path that is its own content hash",
          stored.stem == env[3], f"{stored.stem} vs {env[3]}")

    # §16/§42: a claim nobody can point back at a place in its source is a
    # claim nobody can check.
    chunks = conn.execute(
        "select c.chunk_index, c.metadata->>'location', c.metadata->>'envelope_id', c.text "
        "  from knowledge_chunks c join source_documents d on d.document_id=c.document_id "
        "  join source_items i on i.item_id=d.item_id where i.content_hash=%s "
        " order by c.chunk_index", (env[3],)).fetchall()
    check("chunks exist and are contiguously indexed",
          len(chunks) >= 3 and [c[0] for c in chunks] == list(range(len(chunks))),
          str(len(chunks)))
    check("every chunk carries its heading path",
          all(" > " in c[1] or c[1] == "(body)" for c in chunks),
          str([c[1] for c in chunks]))
    check("the nested heading is a PATH, not just the leaf",
          any(c[1].endswith("Dosing in practice > Interactions") for c in chunks),
          str([c[1] for c in chunks]))
    check("every chunk can be traced back to its envelope",
          all(c[2] == receipt.envelope_id for c in chunks))
    check("the interaction warning survives into a chunk verbatim",
          any("CYP3A4" in c[3] for c in chunks))

    # A9.
    receipt_file = root / "processed" / f"{PREFIX}berberine.md.receipt.json"
    check("the practitioner gets a receipt (A9)", receipt_file.exists())
    written = json.loads(receipt_file.read_text())
    check("...naming the hash, the outcome and where the original went",
          written["content_hash"] == env[3] and written["outcome"] == "NORMALIZED"
          and written["raw_location"] == env[2])

    # ------------------------------------------------------------------
    print("\nthe same content again (§57 — never pay for it twice)")

    documents_before = conn.execute(
        "select count(*) from source_documents").fetchone()[0]
    again = drop(inbox, PREFIX + "berberine-copy.md", body)
    dup_receipt = KI.ingest_one(conn, again)

    check("it is recognised as a duplicate", dup_receipt.outcome == "DUPLICATE",
          dup_receipt.detail or "")
    check("...pointing at the envelope it duplicates",
          dup_receipt.duplicate_of == receipt.envelope_id)
    check("no second document is produced",
          conn.execute("select count(*) from source_documents").fetchone()[0]
          == documents_before)
    check("the fact that they supplied it is still recorded",
          conn.execute("select status::text from source_envelopes where envelope_id=%s",
                       (dup_receipt.envelope_id,)).fetchone()[0] == "DEDUPED")

    # ------------------------------------------------------------------
    print("\na format with no extractor")

    pdf = inbox / (PREFIX + "handout.pdf")
    pdf.write_bytes(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n")
    pdf_receipt = KI.ingest_one(conn, pdf)

    check("it FAILS rather than inventing content", pdf_receipt.outcome == "FAILED",
          pdf_receipt.detail or "")
    check("...and says which extractor it needed",
          "PDF text extractor" in (pdf_receipt.detail or ""), pdf_receipt.detail or "")
    failed_env = conn.execute(
        "select status::text, raw_preserved, failure_reason from source_envelopes "
        " where envelope_id=%s", (pdf_receipt.envelope_id,)).fetchone()
    check("the envelope is FAILED with a reason", failed_env[0] == "FAILED"
          and failed_env[2], str(failed_env))
    check("the original is preserved anyway — nothing is thrown away",
          failed_env[1] is True)
    check("the failure notice reaches the practitioner (A9)",
          (root / "failed" / f"{PREFIX}handout.pdf.receipt.json").exists())
    check("no chunks were produced from a file nothing could read",
          conn.execute(
              "select count(*) from knowledge_chunks c "
              "  join source_documents d on d.document_id=c.document_id "
              "  join source_items i on i.item_id=d.item_id "
              " where i.content_hash=(select content_hash from source_envelopes "
              "                        where envelope_id=%s)",
              (pdf_receipt.envelope_id,)).fetchone()[0] == 0)

    # ------------------------------------------------------------------
    print("\na source kind nobody had heard of (D19, §48)")

    unknown = drop(inbox, PREFIX + "zine.md",
                   f"# {PREFIX}A zine\n\nSomething about fermented foods.\n",
                   meta={"source_kind": "KFTEST_ZINE", "source_title": PREFIX + "A zine"})
    unknown_receipt = KI.ingest_one(conn, unknown)
    check("an unregistered kind lands in OTHER rather than failing",
          unknown_receipt.source_kind == "OTHER", str(unknown_receipt.source_kind))
    check("...and the receipt says so instead of staying silent",
          any("KFTEST_ZINE" in n for n in unknown_receipt.notes),
          str(unknown_receipt.notes))
    check("the document still normalizes — an unknown kind is not a lost source",
          unknown_receipt.outcome == "NORMALIZED", unknown_receipt.detail or "")

    # And now register it. This is the whole point of D19: adding a source
    # kind is an INSERT, not a migration and not an enum edit.
    conn.execute(
        "insert into source_kinds (source_kind, display_name, default_role, "
        "                          adapter_hint, source_type, seeded) "
        "values ('KFTEST_ZINE','Test zine','DISCOVERY','KNOWLEDGE_INBOX','BLOG',false)")
    known = drop(inbox, PREFIX + "zine2.md",
                 f"# {PREFIX}Another zine\n\nSomething about millets.\n",
                 meta={"source_kind": "KFTEST_ZINE", "source_title": PREFIX + "Another zine"})
    known_receipt = KI.ingest_one(conn, known)
    check("once registered by INSERT alone, the kind routes — no code change",
          known_receipt.source_kind == "KFTEST_ZINE", str(known_receipt.source_kind))
    check("...and the registry, not a CASE expression, decides its source_type",
          conn.execute(
              "select s.source_type::text from knowledge_sources s "
              "  join source_envelopes e on e.source_id=s.source_id "
              " where e.envelope_id=%s", (known_receipt.envelope_id,)
          ).fetchone()[0] == "BLOG")

    # ------------------------------------------------------------------
    print("\nrights (§52 — internal learning is not client output)")

    licensed = drop(inbox, PREFIX + "paid.md",
                    f"# {PREFIX}A licensed handout\n\nProprietary protocol text.\n",
                    meta={"source_title": PREFIX + "A licensed handout",
                          "rights": "PAID_LICENSED_TO_PRACTITIONER"})
    lic_receipt = KI.ingest_one(conn, licensed)
    doc = conn.execute(
        "select d.excerpt_only, d.license_note, i.access_note "
        "  from source_documents d join source_items i on i.item_id=d.item_id "
        " where i.content_hash=(select content_hash from source_envelopes "
        "                        where envelope_id=%s)",
        (lic_receipt.envelope_id,)).fetchone()
    check("licensed material is marked excerpt_only", doc[0] is True, str(doc))
    check("...with the restriction recorded on the document and the item",
          doc[1] and "PAID_LICENSED" in doc[1] and doc[2] and "§52" in doc[2], str(doc))

    # ------------------------------------------------------------------
    print("\nthe constraint that makes §50 structural, not a convention")

    row = conn.execute(
        "insert into source_envelopes (source_kind, source_role, source_title, status) "
        "values ('OTHER','DISCOVERY',%s,'RECEIVED') returning envelope_id",
        (PREFIX + "no raw",)).fetchone()[0]
    expect_error(
        conn,
        "update source_envelopes set status='NORMALIZED' where envelope_id=%s",
        (row,),
        "derived knowledge cannot exist without the original it came from",
        "ck_raw_before_derived")

    # ------------------------------------------------------------------
    print("\nchunking")

    long_body = f"# {PREFIX}Long\n\n## One\n\n" + "\n\n".join(
        f"Paragraph {i} about postprandial glycaemia and fibre. " * 8
        for i in range(24))
    long_path = drop(inbox, PREFIX + "long.md", long_body)
    long_receipt = KI.ingest_one(conn, long_path)
    sizes = [r[0] for r in conn.execute(
        "select length(c.text) from knowledge_chunks c "
        "  join source_documents d on d.document_id=c.document_id "
        "  join source_items i on i.item_id=d.item_id "
        " where i.content_hash=(select content_hash from source_envelopes "
        "                        where envelope_id=%s) order by c.chunk_index",
        (long_receipt.envelope_id,)).fetchall()]
    check("a long section splits into several chunks", len(sizes) > 3, str(len(sizes)))
    check("no chunk is a stray trailing scrap",
          all(s >= KI.MIN_CHARS for s in sizes), str(sizes))
    check("chunks stay near the retrieval target rather than becoming chapters",
          max(sizes) < KI.TARGET_CHARS * 2, str(max(sizes)))

    # ------------------------------------------------------------------
    print("\nre-running is safe")

    before = conn.execute("select count(*) from knowledge_chunks").fetchone()[0]
    check("an empty inbox produces nothing", KI.inbox_files() == [])
    check("...and no chunk appeared from nowhere",
          conn.execute("select count(*) from knowledge_chunks").fetchone()[0] == before)

    clear(conn)
    shutil.rmtree(root, ignore_errors=True)

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

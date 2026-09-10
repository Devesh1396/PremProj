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
import run_engine as RE
import knowledge_extract as KX
import knowledge_research as KR
import knowledge_synthesize as KS

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
    conn.execute(
        "delete from claims where claim_id in "
        "  (select derived_id from envelope_derived_records)"
        "  and item_id is null")
    conn.execute("delete from concept_proposals where raw_phrase like %s",
                 ("SENT-%",))
    conn.execute("delete from knowledge_gaps where question like 'Strategy %'")
    conn.execute(
        "delete from strategies where name like %s or canonical_key like %s",
        (PREFIX + "%", "KFTEST_%"))
    conn.execute(
        "delete from strategies where name like %s", ("SENT-E7-SYNTHESIS-%",))
    conn.execute("delete from claims where claim_text like %s", (PREFIX + "%",))


def drop(inbox: Path, name: str, body: str, meta: dict | None = None) -> Path:
    path = inbox / name
    path.write_text(body, encoding="utf-8")
    if meta is not None:
        (inbox / (path.stem + ".meta.json")).write_text(
            json.dumps(meta), encoding="utf-8")
    return path


def main() -> int:
    # The fixture provider, always. K07 and K08 call no model at all and
    # K09's assertions are about the pipeline around the call, not about
    # what a model says — a suite that spends money to prove a provenance
    # edge is a suite nobody runs.
    os.environ["LLM_API_KEY"] = ""

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

    # ==================================================================
    # K09 — claim extraction (D35)
    # ==================================================================
    print("\nK09: one source through the whole loop")

    body = (
        f"# {PREFIX}Berberine\n\n## Mechanism\n\n"
        "Berberine activates AMPK and reduces hepatic gluconeogenesis.\n\n"
        "## Interactions\n\nIt inhibits CYP3A4.\n")
    path = drop(inbox, PREFIX + "k09.md", body)
    ingested = KI.ingest_one(conn, path)
    envelope = conn.execute(
        "select envelope_id, source_title, source_kind, source_role::text, "
        "       rights::text, content_hash, source_version "
        "  from source_envelopes where envelope_id=%s",
        (ingested.envelope_id,)).fetchone()

    out = KX.extract_one(conn, envelope)
    check("the envelope reaches EXTRACTED", out["outcome"] == "EXTRACTED", str(out))
    check("claims were written", out["claims"] >= 1, str(out))

    claim = conn.execute(
        "select c.claim_id, c.claim_text, c.claim_type, c.extraction_confidence, "
        "       c.evidence_referenced_by_source, c.item_id "
        "  from claims c join envelope_derived_records r "
        "    on r.derived_id = c.claim_id and r.derived_kind='CLAIM' "
        " where r.envelope_id=%s", (ingested.envelope_id,)).fetchone()
    check("...linked to the envelope they came from", claim is not None)
    check("...and to the source item, so they can be traced to a document",
          claim is not None and claim[5] is not None)

    # D10. The source of the IDEA is not the source of the EVIDENCE.
    edge = conn.execute(
        "select discovery_only from envelope_derived_records "
        " where envelope_id=%s and derived_kind='CLAIM'",
        (ingested.envelope_id,)).fetchone()
    check("the provenance edge is DISCOVERY ONLY — the source surfaced the "
          "claim, it does not evidence it (D10)", edge == (True,), str(edge))
    check("...and what the source cited stays TEXT, never an evidence record",
          claim is not None and claim[4] is not None
          and conn.execute(
              "select count(*) from envelope_derived_records "
              " where envelope_id=%s and derived_kind='EVIDENCE'",
              (ingested.envelope_id,)).fetchone()[0] == 0)

    # Hard rule 12: every derived object registers by trigger.
    check("the claim is registered in knowledge_entities by trigger",
          conn.execute(
              "select count(*) from knowledge_entities "
              " where entity_id=%s and entity_kind='CLAIM'",
              (claim[0],)).fetchone()[0] == 1)

    # K11 has not run. Nothing here may create a strategy.
    check("extraction creates NO strategy — that is K11's decision",
          conn.execute(
              "select count(*) from envelope_derived_records "
              " where envelope_id=%s and derived_kind='STRATEGY'",
              (ingested.envelope_id,)).fetchone()[0] == 0)

    run = conn.execute(
        "select engine, engine_mode, client_id, status::text from engine_runs "
        " where run_id=%s", (out["run_id"],)).fetchone()
    check("the extraction ran E7 in INBOX mode with NO client (D18, D27)",
          run == ("E7", "INBOX", None, "SUCCEEDED"), str(run))

    delta = conn.execute(
        "select classification::text, claims_extracted, genuinely_new_count "
        "  from source_delta_analyses where envelope_id=%s",
        (ingested.envelope_id,)).fetchone()
    check("a delta analysis is recorded (§54)", delta is not None, str(delta))
    check("...counting the claims that were actually WRITTEN",
          delta is not None and delta[1] == out["claims"], str(delta))
    check("...and never POTENTIAL_NEW_STRATEGY, which is K11's verdict",
          delta is not None and delta[0] != "POTENTIAL_NEW_STRATEGY", str(delta))

    # ------------------------------------------------------------------
    print("\nK09: extracting nothing is an answer, not a failure")

    def responder(blocks_json, inbox_extra=""):
        def provider(system_prompt, user_prompt, params):
            return (
                "the report\n"
                "<RESEARCH_PRACTICE_CLAIMS>\n"
                "MODE: INBOX\n"
                "SOURCE_REFERENCE: x\n"
                f"CLAIMS_JSON:\n{blocks_json}\n"
                "</RESEARCH_PRACTICE_CLAIMS>\n"
                "<RESEARCH_PRACTICE_INBOX_HANDOFF>\n"
                "MODE: INBOX\nSOURCE_REFERENCE: x\nSOURCE_KIND: OTHER\n"
                f"CLAIMS_IDENTIFIED: 0\n{inbox_extra}"
                "INFORMATION_GAIN_SUMMARY: none\n"
                "</RESEARCH_PRACTICE_INBOX_HANDOFF>\n"
                '<CONTROL_BLOCK>\n{"CASE_VERSION": 0, "ENGINE_RUN_STATUS": '
                '"SUCCEEDED"}\n</CONTROL_BLOCK>\n'), 10, 10
        return provider

    def with_provider(provider, envelope):
        original = RE.select_provider
        RE.select_provider = lambda: (provider, "fixture")
        try:
            return KX.extract_one(conn, envelope)
        finally:
            RE.select_provider = original

    empty = drop(inbox, PREFIX + "empty.md",
                 f"# {PREFIX}Nothing new\n\nA restatement of what we know.\n")
    e2 = KI.ingest_one(conn, empty)
    env2 = conn.execute(
        "select envelope_id, source_title, source_kind, source_role::text, "
        "       rights::text, content_hash, source_version "
        "  from source_envelopes where envelope_id=%s", (e2.envelope_id,)).fetchone()
    out2 = with_provider(responder("[]"), env2)
    check("an empty CLAIMS_JSON extracts zero claims and still succeeds",
          out2["outcome"] == "EXTRACTED" and out2["claims"] == 0, str(out2))
    check("...and is classified LOW_INFORMATION_GAIN, not a failure",
          conn.execute(
              "select classification::text from source_delta_analyses "
              " where envelope_id=%s", (e2.envelope_id,)).fetchone()[0]
          == "LOW_INFORMATION_GAIN")

    # ------------------------------------------------------------------
    print("\nK09: malformed extraction is refused, not half-kept")

    bad = drop(inbox, PREFIX + "bad.md", f"# {PREFIX}Bad\n\nSomething.\n")
    e3 = KI.ingest_one(conn, bad)
    env3 = conn.execute(
        "select envelope_id, source_title, source_kind, source_role::text, "
        "       rights::text, content_hash, source_version "
        "  from source_envelopes where envelope_id=%s", (e3.envelope_id,)).fetchone()
    claims_before = conn.execute("select count(*) from claims").fetchone()[0]
    try:
        with_provider(responder('[{"claim_text": "half a claim"'), env3)
        check("invalid CLAIMS_JSON raises rather than storing what parsed", False,
              "no error raised")
    except KX.ExtractionFailed as exc:
        check("invalid CLAIMS_JSON raises rather than storing what parsed",
              "not valid JSON" in str(exc), str(exc)[:120])
    check("...and NOTHING was written from it",
          conn.execute("select count(*) from claims").fetchone()[0] == claims_before)

    # ------------------------------------------------------------------
    print("\nK09: a held-out source is never synthesised from (A3)")

    ho = drop(inbox, PREFIX + "heldout.md", f"# {PREFIX}Held out\n\nAnswer key.\n")
    e4 = KI.ingest_one(conn, ho)
    conn.execute("update source_items set held_out=true, held_out_batch='KFTEST' "
                 " where content_hash=(select content_hash from source_envelopes "
                 "                      where envelope_id=%s)", (e4.envelope_id,))
    env4 = conn.execute(
        "select envelope_id, source_title, source_kind, source_role::text, "
        "       rights::text, content_hash, source_version "
        "  from source_envelopes where envelope_id=%s", (e4.envelope_id,)).fetchone()
    out4 = KX.extract_one(conn, env4)
    check("a held-out source is SKIPPED, not extracted",
          out4["outcome"] == "HELD_OUT" and out4["claims"] == 0, str(out4))
    check("...and produced no claims at all",
          conn.execute(
              "select count(*) from envelope_derived_records where envelope_id=%s",
              (e4.envelope_id,)).fetchone()[0] == 0)
    check("...with the reason on the envelope, not just in a log",
          "held out" in (conn.execute(
              "select failure_reason from source_envelopes where envelope_id=%s",
              (e4.envelope_id,)).fetchone()[0] or ""))

    # ==================================================================
    # K10 — evidence analysis (D36)
    # ==================================================================
    print("\nK10: high-value claims are researched, trivial ones are not")

    claim_row = conn.execute(
        "select claim_id, claim_text, claim_type, target, mechanism, context, "
        "       extraction_confidence from claims where claim_id=%s", (claim[0],)
    ).fetchone()
    check("the extracted claim is on the research list",
          claim_row[2] in KR.RESEARCH_TYPES, str(claim_row[2]))

    # A claim type NOT on the list must not be queued. The rule is a budget
    # decision and it has to be visible, not implicit in a model's taste.
    trivial = conn.execute(
        "insert into claims (item_id, claim_text, claim_type) "
        "values (%s,%s,'DEFINITIONAL') returning claim_id",
        (claim[5], PREFIX + "a definition")).fetchone()[0]
    queued = {str(r[0]) for r in KR.queue(conn, 50)}
    check("a DEFINITIONAL claim is NOT deep-researched", str(trivial) not in queued)
    check("...and the claim that matters IS", str(claim[0]) in queued)

    out10 = KR.research_one(conn, claim_row)
    check("evidence records are written", out10["evidence"] >= 1, str(out10))

    ev = conn.execute(
        "select e.citation, e.design::text, e.item_id, e.applicability "
        "  from evidence_records e order by e.created_at desc limit 1").fetchone()
    check("...with a citation and a study design", ev[0] and ev[1], str(ev[:2]))

    # D10, the whole point of this stage.
    check("evidence is NOT linked to the discovery envelope",
          conn.execute(
              "select count(*) from envelope_derived_records "
              " where envelope_id=%s and derived_kind='EVIDENCE'",
              (ingested.envelope_id,)).fetchone()[0] == 0)
    check("a study with no DOI, PMID or URL gets NO source_item rather than "
          "an invented one", ev[2] is None, str(ev[2]))

    researched = conn.execute(
        "select independent_evidence_findings, areas_overstated, "
        "       current_interpretation from claims where claim_id=%s",
        (claim[0],)).fetchone()
    check("the claim gains an independent reading", researched[0] is not None)
    check("...including where the claim is OVERSTATED (§12)",
          researched[1] is not None, str(researched[1]))

    check("a researched claim leaves the queue",
          str(claim[0]) not in {str(r[0]) for r in KR.queue(conn, 50)})

    run10 = conn.execute(
        "select engine, engine_mode, client_id from engine_runs where run_id=%s",
        (out10["run_id"],)).fetchone()
    check("K10 runs E7 EVIDENCE with no client",
          run10 == ("E7", "EVIDENCE", None), str(run10))

    # Finding nothing must be recorded AS a finding, or the claim loops.
    def evidence_provider(evidence_json, assessment_json):
        def provider(system_prompt, user_prompt, params):
            return (
                "report\n<RESEARCH_PRACTICE_EVIDENCE>\n"
                "MODE: EVIDENCE\nCLAIM_REFERENCE: x\n"
                f"EVIDENCE_JSON:\n{evidence_json}\n"
                f"CLAIM_ASSESSMENT_JSON:\n{assessment_json}\n"
                "</RESEARCH_PRACTICE_EVIDENCE>\n"
                '<CONTROL_BLOCK>\n{"CASE_VERSION": 0, "ENGINE_RUN_STATUS": '
                '"SUCCEEDED"}\n</CONTROL_BLOCK>\n'), 10, 10
        return provider

    empty_claim = conn.execute(
        "select claim_id, claim_text, claim_type, target, mechanism, context, "
        "       extraction_confidence from claims where claim_id=%s", (trivial,)
    ).fetchone()
    original = RE.select_provider
    RE.select_provider = lambda: (evidence_provider("[]", '{"evidence_confidence": "INSUFFICIENT"}'), "fixture")
    try:
        out_empty = KR.research_one(conn, empty_claim)
    finally:
        RE.select_provider = original
    check("finding no evidence writes none", out_empty["evidence"] == 0, str(out_empty))
    finding = conn.execute(
        "select independent_evidence_findings from claims where claim_id=%s",
        (trivial,)).fetchone()[0]
    check("...and is recorded AS a finding, so the claim does not loop",
          finding is not None and "No independent evidence" in finding, str(finding))

    # ==================================================================
    # K11 — strategy synthesis (D36)
    # ==================================================================
    print("\nK11: CREATE / UPDATE / MERGE / NO CHANGE, never a silent duplicate")

    conn.execute("delete from knowledge_gaps where question like 'Strategy %'")
    to_synth = conn.execute(
        """select c.claim_id, c.claim_text, c.claim_type, c.target, c.mechanism,
                  c.context, c.independent_evidence_findings,
                  c.current_interpretation, c.areas_supported,
                  c.areas_overstated, c.areas_uncertain
             from claims c where c.claim_id=%s""", (claim[0],)).fetchone()

    out11 = KS.synthesize_one(conn, to_synth)
    check("a decision is applied", sum(out11["outcomes"].values()) >= 1, str(out11))
    created = conn.execute(
        "select s.strategy_id, s.name, s.knowledge_status::text, s.provenance_note "
        "  from strategies s join strategy_claims sc "
        "    on sc.strategy_id = s.strategy_id where sc.claim_id=%s",
        (claim[0],)).fetchone()
    check("the strategy is linked to the claim it rests on", created is not None)
    check("...and lands at AI_DISCOVERED_CANDIDATE, never promoted (D11)",
          created is not None and created[2] == "AI_DISCOVERED_CANDIDATE",
          str(created[2] if created else None))
    check("...with no provenance note, because a candidate needs none",
          created is not None and created[3] is None)

    run11 = conn.execute(
        "select engine, engine_mode, client_id from engine_runs where run_id=%s",
        (out11["run_id"],)).fetchone()
    check("K11 runs E7 SYNTHESIS with no client",
          run11 == ("E7", "SYNTHESIS", None), str(run11))

    # §R13: a strategy nothing can retrieve is a gap the library must see.
    gap = conn.execute(
        "select severity::text, question from knowledge_gaps "
        " where status='OPEN' and question like %s",
        (f"%{created[0]}%",)).fetchone()
    check("a strategy with no canonical concepts is recorded as an OPEN gap",
          gap is not None and gap[0] == "HIGH", str(gap[0] if gap else None))
    check("...naming why nothing will retrieve it",
          gap is not None and "nothing will retrieve it" in gap[1])

    # NEVER SILENTLY DUPLICATE. The model proposing CREATE is not authority.
    strategies_before = conn.execute("select count(*) from strategies").fetchone()[0]
    conn.execute("delete from strategy_claims where claim_id=%s", (claim[0],))
    out11b = KS.synthesize_one(conn, to_synth)
    check("a second CREATE of the same name does NOT create a second card",
          conn.execute("select count(*) from strategies").fetchone()[0]
          == strategies_before, str(out11b))
    check("...it is converted to an UPDATE and the override is recorded",
          out11b["outcomes"]["UPDATE"] >= 1 and out11b["outcomes"]["CREATE"] == 0,
          str(out11b["outcomes"]))

    # The four decisions and no fifth.
    def synth_provider(decisions_json):
        def provider(system_prompt, user_prompt, params):
            return ("report\n<RESEARCH_PRACTICE_SYNTHESIS>\n"
                    f"MODE: SYNTHESIS\nSYNTHESIS_JSON:\n{decisions_json}\n"
                    "</RESEARCH_PRACTICE_SYNTHESIS>\n"
                    '<CONTROL_BLOCK>\n{"CASE_VERSION": 0, "ENGINE_RUN_STATUS": '
                    '"SUCCEEDED"}\n</CONTROL_BLOCK>\n'), 10, 10
        return provider

    def with_synth(decisions_json, row):
        original = RE.select_provider
        RE.select_provider = lambda: (synth_provider(decisions_json), "fixture")
        try:
            return KS.synthesize_one(conn, row)
        finally:
            RE.select_provider = original

    conn.execute("delete from strategy_claims where claim_id=%s", (claim[0],))
    try:
        with_synth('[{"decision": "PROMOTE", "rationale": "x"}]', to_synth)
        check("a fifth decision is refused", False, "no error raised")
    except KS.SynthesisFailed as exc:
        check("a fifth decision is refused — there are exactly four (§R13)",
              "not one of the four decisions" in str(exc), str(exc)[:100])

    conn.execute("delete from strategy_claims where claim_id=%s", (claim[0],))
    out_nc = with_synth('[{"decision": "NO_CHANGE", "rationale": "already covered"}]',
                        to_synth)
    check("NO_CHANGE is a decision, and writes no strategy",
          out_nc["outcomes"]["NO_CHANGE"] == 1
          and out_nc["outcomes"]["CREATE"] == 0, str(out_nc["outcomes"]))
    check("...and the claim is marked so it does not come back around",
          "NO_CHANGE" in (conn.execute(
              "select current_interpretation from claims where claim_id=%s",
              (claim[0],)).fetchone()[0] or ""))

    # A MERGE deprecates a strategy, and D11 will not allow that unexplained.
    other = conn.execute(
        "insert into strategies (name, canonical_key, knowledge_status) "
        "values (%s,%s,'AI_DISCOVERED_CANDIDATE') returning strategy_id",
        (PREFIX + "loser", "KFTEST_MERGE_LOSER")).fetchone()[0]
    conn.execute("delete from strategy_claims where claim_id=%s", (claim[0],))
    try:
        with_synth(json.dumps([{"decision": "MERGE", "strategy_id": str(other),
                                "merge_into": str(created[0])}]), to_synth)
        check("a MERGE with no rationale is refused", False, "no error raised")
    except KS.SynthesisFailed as exc:
        check("a MERGE with no rationale is refused — DEPRECATED needs a "
              "provenance note (D11)", "provenance note" in str(exc), str(exc)[:100])

    conn.execute("delete from strategy_claims where claim_id=%s", (claim[0],))
    with_synth(json.dumps([{"decision": "MERGE", "strategy_id": str(other),
                            "merge_into": str(created[0]),
                            "rationale": "same intervention, different words"}]),
               to_synth)
    merged = conn.execute(
        "select knowledge_status::text, provenance_note from strategies "
        " where strategy_id=%s", (other,)).fetchone()
    check("the merged-away strategy is DEPRECATED", merged[0] == "DEPRECATED",
          str(merged[0]))
    check("...with the merge rationale as its provenance note",
          merged[1] and "same intervention" in merged[1], str(merged[1]))

    conn.execute("delete from strategies where strategy_id=%s", (other,))

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

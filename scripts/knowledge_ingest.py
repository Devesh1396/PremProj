#!/usr/bin/env python3
"""K07 + K08 — the Knowledge Inbox and the content normalizer.

BUILD_GUIDE step 16. Engine 7 §16, §42, §43, §47, §48, §50, §56, §57;
MASTER_SPEC A9.

    python3 scripts/knowledge_ingest.py            # process the inbox
    python3 scripts/knowledge_ingest.py --status   # what is in flight

The practitioner drops a file into `knowledge/inbox/`. This turns it into a
`source_envelope`, an immutable original in the raw store, a
`source_document` and a set of `knowledge_chunks` — and leaves a receipt
saying what happened. **No model is called.** K07 and K08 are entirely
deterministic; the first LLM in this pipeline is K09.

That is deliberate, not an optimisation. It means the whole ingest path can
be tested with no provider, no key and no cost, and it means a failure here
is a bug in this file rather than something a model said.

### The directories

```
knowledge/inbox/                     the drop zone
knowledge/raw/<hh>/<sha256>.<ext>    the untouched original, content-addressed
knowledge/processed/<name>.receipt.json
knowledge/failed/<name>.receipt.json
```

**Originals are never deleted** (K07). They are MOVED into the raw store,
which is content-addressed and immutable, and the receipt in `processed/`
or `failed/` names where the bytes went. One copy of the bytes, one
human-readable record per thing the practitioner handed over.

The receipt is A9: supplying knowledge must not feel like a void. It says
received, hashed, duplicate or new, and later completed or failed.

### Routing is on format and declared role, never on a creator

Hard rule 13 and §47: nothing here may hard-code a creator or a source
type. A file is routed by its extension, its declared role and its access
level, all looked up against the `source_kinds` REGISTRY. An unrecognised
combination lands in `OTHER`, which is protected and always available, and
can be reclassified later without a migration.

A practitioner who knows more than the file extension does can say so in a
sidecar `<name>.meta.json`:

    {"source_kind": "BOOK", "source_title": "...", "source_url": "...",
     "source_date": "2024-03-01", "rights": "PAID_LICENSED_TO_PRACTITIONER",
     "creator": "...", "personal_note": "...", "topics": ["..."],
     "send_to_e7": true}

Every field is optional. An unknown `source_kind` is not an error and is
not invented — it lands in OTHER and the receipt says so.

### What is NOT extracted, and why that is not a failure of nerve

`.md`, `.txt`, `.text` and `.html` are normalized here. A `.pdf`, `.docx`
or `.epub` is stored, preserved and marked `FAILED` with a reason naming
the extractor it needs. That mirrors what §K05/§K06 say about transcripts:
**mark the status rather than inventing content.** Adding an extractor is a
dependency decision, and a wrong one silently produces plausible garbage
that the rest of the pipeline treats as a source.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parent.parent
KNOWLEDGE = Path(os.environ.get("KNOWLEDGE_DIR") or (REPO / "knowledge"))
INBOX = KNOWLEDGE / "inbox"
RAW = KNOWLEDGE / "raw"
PROCESSED = KNOWLEDGE / "processed"
FAILED = KNOWLEDGE / "failed"

PROCESSING_VERSION = "k08.v1"

# Extension -> the ROLE a file of that shape usually plays, not a source
# kind. The kind is resolved from the registry, so adding a kind stays an
# INSERT (D19). Anything not here is text-like or unreadable, and the
# distinction is made by trying to decode it, not by guessing.
TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".text", ".html", ".htm"}
BINARY_HINT = {
    ".pdf": "a PDF text extractor",
    ".docx": "a DOCX reader",
    ".doc": "a legacy Word reader",
    ".epub": "an EPUB reader",
    ".mobi": "a MOBI reader",
    ".mp3": "an audio transcriber (K05)",
    ".mp4": "a video transcriber (K06)",
    ".m4a": "an audio transcriber (K05)",
}

# Chunking. Long enough that a claim survives inside one chunk, short
# enough that retrieval returns a passage rather than a chapter.
TARGET_CHARS = 2400
MIN_CHARS = 400

SEED_SKIP = {"foundation_domains.md"}


class IngestError(RuntimeError):
    """A file cannot be ingested. Recorded on the envelope, never swallowed."""


@dataclass
class Receipt:
    """A9. What the practitioner gets back for handing over a document."""
    filename: str
    received_at: str
    content_hash: str | None = None
    envelope_id: str | None = None
    outcome: str = "RECEIVED"
    detail: str | None = None
    raw_location: str | None = None
    source_kind: str | None = None
    duplicate_of: str | None = None
    chunks: int = 0
    words: int = 0
    notes: list[str] = field(default_factory=list)

    def write(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.filename}.receipt.json"
        payload = {k: v for k, v in self.__dict__.items()}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        return path


def dsn() -> str:
    return os.environ["DATABASE_URL"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sidecar(path: Path) -> dict:
    """The practitioner's own metadata, if they supplied any."""
    meta = path.with_suffix(path.suffix + ".meta.json")
    if not meta.exists():
        meta = path.with_name(path.stem + ".meta.json")
    if not meta.exists():
        return {}
    try:
        loaded = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A malformed sidecar must not stop the document. The file is the
        # thing being ingested; the sidecar is a convenience.
        return {"_sidecar_error": f"{meta.name} is not readable JSON"}
    return loaded if isinstance(loaded, dict) else {}


# ---------------------------------------------------------------------
# K07 — the inbox
# ---------------------------------------------------------------------

def _other(conn) -> str:
    row = conn.execute(
        "select source_kind from source_kinds where source_kind='OTHER'").fetchone()
    if row is None:
        raise IngestError(
            "source_kinds has no OTHER row. It is the protected landing "
            "state for an unseen kind and migration 006 seeds it.")
    return row[0]


def resolve_kind(conn, declared: str | None, suffix: str) -> tuple[str, str, list[str]]:
    """Return (source_kind, source_role, notes). Registry-driven (§47, §48).

    Never hard-codes a creator or a source type. A declared kind is honoured
    when the registry knows it; an unknown one lands in OTHER, which is
    protected and always available, rather than being invented or rejected.
    """
    notes: list[str] = []
    if declared:
        row = conn.execute(
            "select source_kind, default_role::text from source_kinds "
            " where source_kind=%s and active", (declared.upper(),)).fetchone()
        if row:
            return row[0], row[1], notes
        notes.append(
            f"source_kind {declared!r} is not in the registry; landed in OTHER. "
            "Adding a kind is an INSERT into source_kinds, not a migration.")
        # Deliberately NOT falling back to the format route. The
        # practitioner said this is something in particular; routing it to
        # MANUAL_UPLOAD would file it as a plain upload and lose the one
        # piece of information they gave us. OTHER is the protected landing
        # state for exactly this (§48, hard rule 13), and it is honest:
        # unclassified, awaiting classification.
        return _other(conn), 'DISCOVERY', notes

    # Nothing declared: route on FORMAT, against the registry's own
    # adapter_hint. A file dropped into the inbox arrived by the inbox,
    # so that is the adapter that handled it.
    hint = "KNOWLEDGE_INBOX"
    row = conn.execute(
        "select source_kind, default_role::text from source_kinds "
        " where active and adapter_hint=%s and source_kind <> 'OTHER' "
        " order by source_kind limit 1", (hint,)).fetchone()
    if row and suffix in TEXT_SUFFIXES:
        return row[0], row[1], notes

    return _other(conn), 'DISCOVERY', notes


def preserve_raw(path: Path, digest: str) -> Path:
    """Move the original into the content-addressed store, before deriving.

    `ck_raw_before_derived` will not let an envelope past RECEIVED without
    this, which is §50 expressed as a constraint rather than a convention.
    """
    target_dir = RAW / digest[:2]
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{digest}{path.suffix.lower()}"
    if target.exists():
        # Same bytes already stored. The inbox copy is redundant, and
        # removing it is not "deleting an original" -- the original is the
        # one already in the raw store.
        path.unlink()
        return target
    shutil.move(str(path), str(target))
    return target


def open_envelope(conn, path: Path, digest: str, meta: dict) -> tuple[str, Receipt]:
    receipt = Receipt(filename=path.name, received_at=now(), content_hash=digest)

    if meta.get("_sidecar_error"):
        receipt.notes.append(meta["_sidecar_error"])

    kind, role, notes = resolve_kind(conn, meta.get("source_kind"), path.suffix.lower())
    receipt.notes.extend(notes)
    receipt.source_kind = kind

    # §57: the same content must not be paid for twice.
    dup = conn.execute(
        "select envelope_id from source_envelopes "
        " where content_hash=%s and duplicate_of is null", (digest,)).fetchone()

    rights = (meta.get("rights") or "PUBLIC").upper()
    if rights not in ("PUBLIC", "PRIVATE_INTERNAL",
                      "PAID_LICENSED_TO_PRACTITIONER", "RESTRICTED_INTERNAL"):
        receipt.notes.append(f"rights {rights!r} is not a known context; recorded as PUBLIC")
        rights = "PUBLIC"

    # §56: the same raw source, processed again. A monitored page keeps its
    # URL and changes its content, so a second envelope for one URL is a
    # NEW VERSION, not a collision -- and uq_envelope_url_version is what
    # says so. Without this, the first time a discovered page changed, K07
    # would crash on a unique violation.
    source_url = meta.get("source_url")
    version = 1
    if source_url:
        prior = conn.execute(
            "select max(source_version) from source_envelopes "
            " where source_url = %s", (source_url,)).fetchone()[0]
        if prior:
            version = prior + 1
            receipt.notes.append(
                f"version {version} of this URL — the source changed since it "
                "was last ingested, and neither version is lost (§56).")

    envelope_id = conn.execute(
        """insert into source_envelopes
             (source_kind, source_role, source_title, source_date, source_url,
              file_type, rights, rights_note, personal_note, topics,
              send_to_e7, status, ingestion_provider, processing_version,
              source_version)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'RECEIVED','KNOWLEDGE_INBOX',%s,%s)
           returning envelope_id""",
        (kind, meta.get("source_role", role).upper() if meta.get("source_role") else role,
         meta.get("source_title") or path.stem,
         meta.get("source_date"), meta.get("source_url"),
         path.suffix.lower().lstrip("."), rights, meta.get("rights_note"),
         meta.get("personal_note"), meta.get("topics"),
         bool(meta.get("send_to_e7", True)), PROCESSING_VERSION,
         version)).fetchone()[0]
    receipt.envelope_id = str(envelope_id)

    if dup is not None:
        # DEDUPED keeps the row: the practitioner handed this over and the
        # record that they did is worth as much as the content.
        conn.execute(
            "update source_envelopes set status='DEDUPED', duplicate_of=%s, "
            "       processed_at=now() where envelope_id=%s",
            (dup[0], envelope_id))
        receipt.outcome = "DUPLICATE"
        receipt.duplicate_of = str(dup[0])
        receipt.detail = ("Already ingested. Nothing was re-extracted and "
                          "nothing was paid for twice (§57).")
        return str(envelope_id), receipt

    conn.execute("update source_envelopes set content_hash=%s where envelope_id=%s",
                 (digest, envelope_id))
    return str(envelope_id), receipt


# ---------------------------------------------------------------------
# K08 — the normalizer
# ---------------------------------------------------------------------

TAG = re.compile(r"<[^>]+>")
HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def to_text(raw: bytes, suffix: str) -> str:
    text = raw.decode("utf-8", errors="replace")
    if suffix in (".html", ".htm"):
        text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
        text = re.sub(r"(?i)</(p|div|h[1-6]|li|tr|section)>", "\n\n", text)
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = TAG.sub("", text)
        for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                             ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
            text = text.replace(entity, char)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def segment(text: str) -> list[tuple[str, str]]:
    """Split into (location, body). Location is the heading path.

    §16 and §42: chapter, page and timestamp are part of the content, not
    decoration. A claim that cannot be pointed back at a place in its
    source is a claim nobody can check.
    """
    sections: list[tuple[str, str]] = []
    stack: list[str] = []
    body: list[str] = []

    def flush() -> None:
        joined = "\n".join(body).strip()
        if joined:
            sections.append((" > ".join(stack) if stack else "(body)", joined))
        body.clear()

    for line in text.split("\n"):
        m = HEADING.match(line)
        if m:
            flush()
            depth = len(m.group(1))
            del stack[depth - 1:]
            stack.append(m.group(2))
        else:
            body.append(line)
    flush()
    return sections or [("(body)", text.strip())]


def chunk_section(location: str, body: str) -> list[tuple[str, str]]:
    """Split one section into retrieval-sized pieces on paragraph boundaries."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    out: list[tuple[str, str]] = []
    current: list[str] = []
    size = 0
    for para in paragraphs:
        if size and size + len(para) > TARGET_CHARS:
            out.append((location, "\n\n".join(current)))
            current, size = [], 0
        current.append(para)
        size += len(para) + 2
    if current:
        tail = "\n\n".join(current)
        # A trailing scrap belongs with the passage before it, not alone.
        if out and len(tail) < MIN_CHARS:
            out[-1] = (out[-1][0], out[-1][1] + "\n\n" + tail)
        else:
            out.append((location, tail))
    return out


def normalize(conn, envelope_id: str, raw_path: Path, receipt: Receipt) -> None:
    suffix = raw_path.suffix.lower()
    if suffix in BINARY_HINT:
        raise IngestError(
            f"{suffix} needs {BINARY_HINT[suffix]}, which is not built. The "
            "original is preserved and the envelope is marked FAILED rather "
            "than the content being invented (K05/K06).")
    if suffix not in TEXT_SUFFIXES:
        try:
            raw_path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IngestError(
                f"{suffix or '(no extension)'} is not UTF-8 text and no "
                "extractor is registered for it.") from exc

    text = to_text(raw_path.read_bytes(), suffix)
    if not text.strip():
        raise IngestError("the file is empty once decoded.")

    env = conn.execute(
        "select source_kind, source_role::text, source_title, source_url, "
        "       source_date, rights::text, content_hash "
        "  from source_envelopes where envelope_id=%s", (envelope_id,)).fetchone()
    kind, role, title, url, source_date, rights, digest = env

    # The kind -> type mapping is REGISTRY DATA (migration 017), never a
    # CASE expression here. Hard rule 13: a new source kind is an INSERT,
    # and it must not also need a code change nobody remembers to make.
    source_type = conn.execute(
        "select source_type::text from source_kinds where source_kind=%s",
        (kind,)).fetchone()[0]

    source_id = conn.execute(
        """insert into knowledge_sources
             (source_name, source_type, source_roles, base_identifier,
              access_method, monitor_status, notes)
           values (%s,%s,%s::source_role[],%s,'KNOWLEDGE_INBOX',false,%s)
           on conflict (base_identifier) where base_identifier is not null and active
           do update set source_name = excluded.source_name
           returning source_id""",
        (title or raw_path.stem, source_type, [role],
         url or f"inbox:{digest[:16]}",
         "Ingested from knowledge/inbox. Adding a source kind is a data edit "
         "(D19); nothing here is keyed on a creator.")).fetchone()[0]

    access_note = (None if rights == "PUBLIC" else
                   f"rights: {rights}. Internal learning only; never reproduced "
                   "in client output (§52).")

    # ONE item, whose status progresses. Discovery (K02-K06) registers an
    # item when it FINDS something and hands the content to this pipeline,
    # so by the time normalization runs the row may already exist --
    # DISCOVERED or QUEUED, carrying the url. Inserting a second row for it
    # violates uq_item_url, and the two rows would be the same thing
    # counted twice: found, and then read.
    existing = None
    if url:
        existing = conn.execute(
            "select item_id from source_items where url = %s", (url,)).fetchone()
    if existing is None and digest:
        existing = conn.execute(
            "select item_id from source_items where content_hash = %s",
            (digest,)).fetchone()

    if existing is not None:
        item_id = existing[0]
        conn.execute(
            """update source_items
                  set source_id = coalesce(source_id, %s),
                      title = coalesce(nullif(title, ''), %s),
                      content_hash = coalesce(content_hash, %s),
                      ingestion_status = 'NORMALIZED',
                      access_note = coalesce(%s, access_note),
                      last_seen = now()
                where item_id = %s""",
            (source_id, title or raw_path.stem, digest, access_note, item_id))
    else:
        item_id = conn.execute(
            """insert into source_items
                 (source_id, title, url, content_hash, ingestion_status, access_note)
               values (%s,%s,%s,%s,'NORMALIZED',%s) returning item_id""",
            (source_id, title or raw_path.stem, url, digest, access_note)
        ).fetchone()[0]

    if source_date:
        conn.execute("update source_items set publication_date=%s where item_id=%s",
                     (source_date, item_id))

    sections = segment(text)
    pieces: list[tuple[str, str]] = []
    for location, body in sections:
        pieces.extend(chunk_section(location, body))

    words = len(text.split())
    document_id = conn.execute(
        """insert into source_documents
             (item_id, document_type, text_location, content_hash, word_count,
              excerpt_only, license_note)
           values (%s,%s,%s,%s,%s,%s,%s) returning document_id""",
        (item_id, kind, sections[0][0] if sections else None, digest, words,
         rights != "PUBLIC",
         None if rights == "PUBLIC" else f"{rights} — internal learning only")
    ).fetchone()[0]

    for index, (location, body) in enumerate(pieces):
        conn.execute(
            """insert into knowledge_chunks (document_id, chunk_index, text, metadata)
               values (%s,%s,%s,%s::jsonb)""",
            (document_id, index, body,
             json.dumps({"location": location, "source_kind": kind,
                         "envelope_id": envelope_id,
                         "processing_version": PROCESSING_VERSION})))

    conn.execute(
        "update source_envelopes set status='NORMALIZED', source_id=%s, "
        "       processed_at=now() where envelope_id=%s", (source_id, envelope_id))

    receipt.chunks = len(pieces)
    receipt.words = words
    receipt.outcome = "NORMALIZED"
    receipt.detail = (f"{len(sections)} section(s), {len(pieces)} chunk(s), "
                      f"{words} words. Ready for claim extraction (K09).")


# ---------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------

def deliver_to_inbox(name: str, data: bytes, meta: dict | None = None) -> Path:
    """Put discovered content where the inbox pipeline will find it.

    Discovery does NOT ingest. K07 and K08 already turn content into an
    envelope, a preserved original and heading-located chunks; a second
    path would be a second normalizer, a second dedup rule and a second
    place for rights handling to be forgotten. So an adapter DELIVERS to
    the inbox and the existing pipeline does the rest — which is also the
    honest description of what discovery is: another way things arrive.

    The filename is sanitised because it comes from a feed title or a URL,
    and neither is a promise about the filesystem.
    """
    INBOX.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")[:120] or "discovered"
    path = INBOX / safe
    counter = 1
    while path.exists():
        stem, dot, suffix = safe.partition(".")
        path = INBOX / f"{stem}-{counter}{dot}{suffix}"
        counter += 1
    path.write_bytes(data)
    if meta:
        (INBOX / (path.stem + ".meta.json")).write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def inbox_files() -> list[Path]:
    if not INBOX.exists():
        return []
    return sorted(
        p for p in INBOX.iterdir()
        if p.is_file() and not p.name.startswith(".")
        and not p.name.endswith(".meta.json")
        and p.name not in SEED_SKIP)


def ingest_one(conn, path: Path) -> Receipt:
    meta = sidecar(path)
    digest = sha256_file(path)
    envelope_id, receipt = open_envelope(conn, path, digest, meta)

    if receipt.outcome == "DUPLICATE":
        preserve_raw(path, digest)
        receipt.write(PROCESSED)
        return receipt

    raw_path = preserve_raw(path, digest)
    receipt.raw_location = str(raw_path.relative_to(KNOWLEDGE))
    conn.execute(
        "update source_envelopes set raw_location=%s, raw_preserved=true, "
        "       status='RAW_STORED' where envelope_id=%s",
        (receipt.raw_location, envelope_id))

    try:
        normalize(conn, envelope_id, raw_path, receipt)
    except IngestError as exc:
        conn.execute(
            "update source_envelopes set status='FAILED', failure_reason=%s, "
            "       processed_at=now() where envelope_id=%s",
            (str(exc)[:2000], envelope_id))
        receipt.outcome = "FAILED"
        receipt.detail = str(exc)
        receipt.write(FAILED)
        return receipt

    receipt.write(PROCESSED)
    return receipt


def status(conn) -> None:
    rows = conn.execute(
        "select status::text, count(*) from source_envelopes group by 1 "
        " order by 2 desc").fetchall()
    print("\nENVELOPES")
    if not rows:
        print("  none — the library is empty. That is expected until the "
              "Knowledge Factory has run (see PROGRESS.md).")
    for status_name, count in rows:
        print(f"  {status_name:16s} {count}")
    stuck = conn.execute(
        "select envelope_id, source_title, failure_reason from source_envelopes "
        " where status='FAILED' order by ingested_at desc limit 10").fetchall()
    if stuck:
        print("\nFAILED, most recent first")
        for envelope_id, title, reason in stuck:
            print(f"  {str(envelope_id)[:8]}  {(title or '(untitled)')[:40]:40s} {reason}")
    chunks = conn.execute(
        "select count(*), coalesce(sum(word_count),0) from source_documents"
    ).fetchone()
    print(f"\nDOCUMENTS  {chunks[0]}, {chunks[1]} words")
    print(f"CHUNKS     {conn.execute('select count(*) from knowledge_chunks').fetchone()[0]}")


def main() -> int:
    for directory in (INBOX, RAW, PROCESSED, FAILED):
        directory.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(dsn(), autocommit=True) as conn:
        if "--status" in sys.argv:
            status(conn)
            return 0

        files = inbox_files()
        if not files:
            print(f"nothing in {INBOX}")
            status(conn)
            return 0

        print(f"{len(files)} file(s) in the inbox\n")
        failures = 0
        for path in files:
            try:
                receipt = ingest_one(conn, path)
            except Exception as exc:  # noqa: BLE001 - one bad file must not
                # stop the batch, and the practitioner must be told which.
                failures += 1
                Receipt(filename=path.name, received_at=now(), outcome="FAILED",
                        detail=f"{type(exc).__name__}: {exc}").write(FAILED)
                print(f"  FAILED     {path.name}  {type(exc).__name__}: {exc}")
                continue
            if receipt.outcome == "FAILED":
                failures += 1
            print(f"  {receipt.outcome:10s} {receipt.filename}  {receipt.detail or ''}")

        status(conn)
        return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

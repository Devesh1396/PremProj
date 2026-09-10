#!/usr/bin/env python3
"""K02–K06 — discovery. Find sources; hand them to the inbox pipeline.

BUILD_GUIDE step 16. Engine 7 §18, §41, §47, §48, §49, §52; A3; D37.

    python3 scripts/knowledge_discover.py --source <id>   # one registered source
    python3 scripts/knowledge_discover.py --due           # every monitored source
    python3 scripts/knowledge_discover.py --status

| | |
|---|---|
| K02 | `PUBMED`, `CLINICAL_TRIALS` — documented APIs, structured |
| K03 | `WEB_HTTP` — a registered site, robots-respecting |
| K04 | `RSS` — feeds, with a cursor so old items are not reprocessed |
| K05 | `PODCAST` — the feed is structured; a transcript is used only if published |
| K06 | `YOUTUBE` — refused until an authorization is recorded |

### Discovery does not ingest

Every adapter ends the same way: `deliver_to_inbox()`, and K07/K08 take it
from there. There is one normalizer, one dedup rule and one place rights
are handled, and this file is not a second of any of them.

### Nothing here decides what a source IS

Hard rule 13 and §47: no creator and no source type is hard-coded. An
adapter is chosen by the source's registered `access_method`, the policy
comes from `acquisition_adapters`, and the kind of the resulting envelope
comes from `source_kinds`. Adding a source, an adapter or a kind is an
INSERT in all three cases.
"""
from __future__ import annotations

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import psycopg

import acquisition as AQ
import knowledge_ingest as KI
import youtube_apify as YT

PROCESSING_VERSION = "k02-06.v1"

# Feed namespaces we read. Adding one is an edit here because it is a
# parsing fact, not a policy — the policy is in acquisition_adapters.
ATOM = "{http://www.w3.org/2005/Atom}"
MEDIA = "{http://search.yahoo.com/mrss/}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"
ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"


class DiscoveryFailed(RuntimeError):
    """The source could not be read. The cursor is not advanced."""


def dsn() -> str:
    return os.environ["DATABASE_URL"]


def sources_due(conn) -> list[tuple]:
    return conn.execute(
        """select source_id, source_name, source_type::text, base_identifier,
                  access_method, array_to_string(source_roles, ',')
             from knowledge_sources
            where active and monitor_status
            order by coalesce(last_checked, 'epoch'::timestamptz)""").fetchall()


def one_source(conn, source_id: str) -> tuple:
    row = conn.execute(
        """select source_id, source_name, source_type::text, base_identifier,
                  access_method, array_to_string(source_roles, ',')
             from knowledge_sources where source_id = %s""", (source_id,)).fetchone()
    if row is None:
        raise DiscoveryFailed(f"no source {source_id}")
    return row


def text_of(element, *paths) -> str | None:
    for path in paths:
        found = element.find(path)
        if found is not None:
            value = (found.text or "").strip()
            if value:
                return value
            href = found.attrib.get("href")
            if href:
                return href.strip()
    return None


def already_known(conn, *, url=None, guid=None, doi=None, pmid=None) -> bool:
    # Explicit casts: every one of these is legitimately NULL on some
    # adapter, and Postgres cannot infer a type for a bare NULL parameter.
    return bool(conn.execute(
        """select 1 from source_items
            where (%s::text is not null and url = %s::text)
               or (%s::text is not null and external_id = %s::text)
               or (%s::text is not null and lower(doi) = lower(%s::text))
               or (%s::text is not null and pmid = %s::text)
            limit 1""",
        (url, url, guid, guid, doi, doi, pmid, pmid)).fetchone())


# Statuses a re-discovery may overwrite. Everything past QUEUED is a
# statement about work that has ALREADY happened -- finding the same video
# again must not reset a NORMALIZED item to QUEUED and invite the whole
# pipeline to run over it a second time.
REDISCOVERABLE = ("DISCOVERED", "QUEUED")


def register_item(conn, source_id: str, *, title, url=None, guid=None,
                  doi=None, pmid=None, status="DISCOVERED",
                  note=None) -> str:
    """One item per THING, whose status progresses. Re-discovery touches it.

    Seeing a source again is normal — a channel is polled, a feed repeats,
    a video is reachable from a playlist and from its own URL. Every one of
    those is the same item found again, so this looks the thing up by its
    identity before inserting: the canonical URL first (`uq_item_url`),
    then the platform id within this source (`uq_item_source_external`).

    Before this, a second sighting raised a unique violation and took the
    whole discovery run down with it.
    """
    existing = None
    if url:
        existing = conn.execute(
            "select item_id, ingestion_status::text from source_items "
            " where url = %s", (url,)).fetchone()
    if existing is None and guid and source_id:
        existing = conn.execute(
            "select item_id, ingestion_status::text from source_items "
            " where source_id = %s and external_id = %s",
            (source_id, guid)).fetchone()

    if existing is not None:
        item_id, current = existing
        conn.execute(
            """update source_items
                  set last_seen = now(),
                      title = coalesce(nullif(title,''), %s),
                      external_id = coalesce(external_id, %s),
                      url = coalesce(url, %s),
                      access_note = coalesce(%s, access_note),
                      ingestion_status = case when %s then %s::ingestion_status
                                              else ingestion_status end
                where item_id = %s""",
            ((title or "")[:500], guid, url, note,
             current in REDISCOVERABLE, status, item_id))
        return str(item_id)

    return str(conn.execute(
        """insert into source_items
             (source_id, title, url, external_id, doi, pmid,
              ingestion_status, access_note)
           values (%s,%s,%s,%s,%s,%s,%s::ingestion_status,%s)
           returning item_id""",
        (source_id, (title or "")[:500], url, guid, doi, pmid, status, note)
    ).fetchone()[0])


# ---------------------------------------------------------------------
# K04 / K05 — feeds
# ---------------------------------------------------------------------

def feed_entries(body: bytes) -> list[dict]:
    """RSS 2.0 and Atom, normalized to one shape.

    Parsed with the stdlib rather than a feed library: a feed is a
    documented format and this reads the five fields the pipeline needs.
    """
    root = ET.fromstring(body)
    entries: list[dict] = []

    for item in root.iter("item"):                      # RSS 2.0
        enclosure = item.find("enclosure")
        entries.append({
            "title": text_of(item, "title") or "(untitled)",
            "url": text_of(item, "link"),
            "guid": text_of(item, "guid") or text_of(item, "link"),
            "published": text_of(item, "pubDate"),
            "summary": text_of(item, "description", CONTENT + "encoded"),
            "media": (enclosure.attrib.get("url") if enclosure is not None else None),
            "transcript": text_of(item, ITUNES + "transcript", "transcript"),
        })

    for entry in root.iter(ATOM + "entry"):             # Atom
        link = entry.find(ATOM + "link")
        entries.append({
            "title": text_of(entry, ATOM + "title") or "(untitled)",
            "url": (link.attrib.get("href") if link is not None else None),
            "guid": text_of(entry, ATOM + "id"),
            "published": text_of(entry, ATOM + "published", ATOM + "updated"),
            "summary": text_of(entry, ATOM + "summary", ATOM + "content"),
            "media": None,
            "transcript": None,
        })
    return entries


def discover_feed(conn, source, adapter: str, transport=None) -> dict:
    """K04 and K05. The cursor is what stops old content being reprocessed."""
    source_id, name, _stype, base, _access, _roles = source
    if not base:
        raise DiscoveryFailed(f"{name} has no base_identifier to fetch")

    reply = AQ.fetch(conn, adapter, base, transport=transport,
                     accept="application/rss+xml, application/atom+xml, application/xml")
    try:
        entries = feed_entries(reply.body)
    except ET.ParseError as exc:
        raise DiscoveryFailed(f"{name} did not return parseable XML: {exc}") from exc

    seen_guid = AQ.cursor(conn, str(source_id), "FEED_GUID")
    delivered = fresh = 0
    newest = None

    for entry in entries:
        guid = entry["guid"] or entry["url"]
        if newest is None:
            newest = guid
        if seen_guid and guid == seen_guid:
            # Everything from here down was processed on a previous run.
            break
        if not guid or already_known(conn, url=entry["url"], guid=guid):
            continue
        fresh += 1

        transcript = entry.get("transcript")
        if adapter == "PODCAST" and not transcript:
            # K05: "Transcript where legitimately accessible. If none, mark
            # status rather than inventing content." The episode is
            # RECORDED so the practitioner can see it exists and so the
            # feed is not re-read for it; nothing is invented from the
            # title and the summary.
            register_item(conn, str(source_id), title=entry["title"],
                          url=entry["url"], guid=guid,
                          status="FULL_TEXT_NOT_AVAILABLE",
                          note="No transcript is published in the feed. The "
                               "episode is recorded so it is not rediscovered; "
                               "its content is not guessed at (K05).")
            continue

        body = transcript_or_summary(conn, adapter, entry, transport)
        if body is None:
            register_item(conn, str(source_id), title=entry["title"],
                          url=entry["url"], guid=guid,
                          status="FULL_TEXT_NOT_AVAILABLE",
                          note="Nothing legitimately readable was available "
                               "for this item.")
            continue

        register_item(conn, str(source_id), title=entry["title"],
                      url=entry["url"], guid=guid, status="QUEUED")
        KI.deliver_to_inbox(
            f"{entry['title']}.md", body.encode("utf-8"),
            {"source_title": entry["title"], "source_url": entry["url"],
             "source_kind": kind_for(conn, adapter),
             "personal_note": f"Discovered by {adapter} from {name}",
             "topics": [adapter]})
        delivered += 1

    if newest:
        AQ.advance_cursor(conn, str(source_id), "FEED_GUID", newest, fresh)
    conn.execute("update knowledge_sources set last_checked = now() where source_id = %s",
                 (source_id,))
    AQ.record_search(conn, adapter, f"feed:{base}", results=len(entries),
                     items_new=fresh, source_id=str(source_id))
    return {"adapter": adapter, "source": name, "entries": len(entries),
            "new": fresh, "delivered": delivered,
            "detail": f"{len(entries)} entries, {fresh} new, {delivered} delivered"}


def transcript_or_summary(conn, adapter: str, entry: dict, transport) -> str | None:
    """The item's readable content, or None if nothing is legitimately readable."""
    if entry.get("transcript"):
        try:
            reply = AQ.fetch(conn, adapter, entry["transcript"], transport=transport)
            return reply.body.decode("utf-8", errors="replace")
        except AQ.Refused:
            return None
    summary = (entry.get("summary") or "").strip()
    if not summary:
        return None
    return f"# {entry['title']}\n\n{summary}\n"


def kind_for(conn, adapter: str) -> str:
    """The source_kind an adapter's output should land as (§48, hard rule 13).

    Read from the registry, never decided here. An adapter with no
    registered kind lands in OTHER, which is protected and always
    available.
    """
    row = conn.execute(
        "select source_kind from source_kinds "
        " where active and adapter_hint = %s and source_kind <> 'OTHER' "
        " order by source_kind limit 1", (adapter,)).fetchone()
    return row[0] if row else "OTHER"


# ---------------------------------------------------------------------
# K02 — PubMed
# ---------------------------------------------------------------------

PUBMED = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def discover_pubmed(conn, source, query: str, transport=None,
                    retmax: int = 20) -> dict:
    """K02. A documented API, and the search history that stops repeats."""
    source_id, name = source[0], source[1]

    seen = AQ.searched_recently(conn, "PUBMED", query)
    if seen:
        return {"adapter": "PUBMED", "source": name, "entries": 0, "new": 0,
                "delivered": 0,
                "detail": (f"skipped — the same search ran at "
                           f"{seen['executed_at']:%Y-%m-%d %H:%M} and returned "
                           f"{seen['results_returned']}. K02: expensive "
                           "searches are not repeated.")}

    search_url = (f"{PUBMED}/esearch.fcgi?db=pubmed&retmode=json"
                  f"&retmax={retmax}&term={query.replace(' ', '+')}")
    reply = AQ.fetch(conn, "PUBMED", search_url, transport=transport,
                     accept="application/json")
    try:
        payload = json.loads(reply.body.decode("utf-8", errors="replace"))
        ids = list(payload["esearchresult"]["idlist"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        AQ.record_search(conn, "PUBMED", query, outcome="MALFORMED",
                         detail=str(exc)[:400], source_id=str(source_id))
        raise DiscoveryFailed(f"PubMed returned an unreadable result: {exc}") from exc

    fresh = 0
    for pmid in ids:
        if already_known(conn, pmid=pmid):
            continue
        # DISCOVERED, not QUEUED: an abstract is not the paper, and K02's
        # job is to find things. What is legitimately retrievable is a
        # separate decision and a separate fetch.
        register_item(conn, str(source_id), title=f"PMID {pmid}",
                      url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                      pmid=pmid, status="DISCOVERED",
                      note="Discovered via E-utilities. Full text retrieval is "
                           "a separate decision (§52).")
        fresh += 1

    AQ.record_search(conn, "PUBMED", query, results=len(ids), items_new=fresh,
                     source_id=str(source_id))
    conn.execute("update knowledge_sources set last_checked = now() where source_id = %s",
                 (source_id,))
    return {"adapter": "PUBMED", "source": name, "entries": len(ids),
            "new": fresh, "delivered": 0,
            "detail": f"{len(ids)} result(s), {fresh} new"}


# ---------------------------------------------------------------------
# K03 — a registered site
# ---------------------------------------------------------------------

TAG = re.compile(r"<[^>]+>")


def discover_web(conn, source, transport=None) -> dict:
    """K03. One registered page, robots-respecting. Never a crawl."""
    source_id, name, _stype, base, _access, _roles = source
    if not base:
        raise DiscoveryFailed(f"{name} has no base_identifier to fetch")
    if already_known(conn, url=base):
        return {"adapter": "WEB_HTTP", "source": name, "entries": 1, "new": 0,
                "delivered": 0, "detail": "already known"}

    reply = AQ.fetch(conn, "WEB_HTTP", base, transport=transport, accept="text/html")
    # The HTML is handed over WHOLE. K08 owns turning markup into located
    # text, and doing it here would be the second normalizer this file
    # exists not to be.
    register_item(conn, str(source_id), title=name, url=base, status="QUEUED")
    KI.deliver_to_inbox(
        f"{name}.html", reply.body,
        {"source_title": name, "source_url": base,
         "source_kind": kind_for(conn, "WEB_HTTP"),
         "personal_note": "Discovered by WEB_HTTP", "topics": ["WEB_HTTP"]})
    AQ.record_search(conn, "WEB_HTTP", f"page:{base}", results=1, items_new=1,
                     source_id=str(source_id))
    conn.execute("update knowledge_sources set last_checked = now() where source_id = %s",
                 (source_id,))
    return {"adapter": "WEB_HTTP", "source": name, "entries": 1, "new": 1,
            "delivered": 1, "detail": "delivered to the inbox"}


# ---------------------------------------------------------------------
# K06 — video
# ---------------------------------------------------------------------

def upsert_creator(conn, meta: dict) -> str | None:
    """The creator, keyed on the PLATFORM'S id (migration 030, D46).

    `channelName` can change and `channelId` cannot. §40 profiles
    accumulate across sources, so matching on a display name means a
    rename quietly starts a second profile holding half the history —
    and the first one stops growing without anybody noticing.
    """
    external = (meta.get("creator_external_id") or "").strip()
    namespace = (meta.get("creator_external_source") or "").strip()
    name = (meta.get("creator_name") or "").strip()
    if not external or not namespace:
        return None
    return str(conn.execute(
        # OTHER, not a guess. A channel id says who published, never
        # whether they are a researcher, a clinician or a coach — and
        # `creator_type` is what §12 weighs a claim against. The
        # practitioner classifies it; the adapter records that it exists.
        """insert into source_creators
             (name, creator_type, external_id, external_source, discovery_reason)
           values (%s,'OTHER',%s,%s,%s)
           on conflict (external_source, external_id)
             where external_id is not null
           do update set name = excluded.name,
                         last_reviewed = source_creators.last_reviewed
           returning creator_id""",
        (name or external, external, namespace,
         "Discovered by the YOUTUBE adapter; identity is the platform id, "
         "never the display name.")).fetchone()[0])


def discover_video(conn, source, transport=None, urls=None) -> dict:
    """K06. Apify if an authorization is recorded; ACCESS_DENIED if not.

    "Do not build brittle unauthorized scraping as a core dependency."
    There is still no scraper here: the transcript comes from Apify's
    documented API under the practitioner's own token, and that
    authorization is recorded on the `acquisition_adapters` row where the
    chokepoint reads it. Clear the note and this returns to refusing.

    Discovery still does not ingest (D37) — every video ends at
    `deliver_to_inbox()` and K07/K08 take it from there.
    """
    source_id, name, _stype, base, _access, _roles = source
    wanted = [u for u in (urls or ([base] if base else [])) if u]
    canonical = []
    for raw in wanted:
        vid = YT.video_id_of(raw)
        canonical.append(YT.canonical_url(vid) if vid else raw)

    try:
        if not canonical:
            raise DiscoveryFailed(
                f"{name} has no video URL to fetch. The YOUTUBE adapter reads "
                "videos, and a channel listing is not built — pass --url.")
        items = YT.run_actor(conn, canonical, transport=transport)
    except YT.ApifyUnavailable as exc:
        # A malformed dataset IS a failure — unlike a missing credential,
        # which `run_actor` records and re-raises as a refusal so it lands
        # on the ACCESS_DENIED path below.
        raise DiscoveryFailed(str(exc)) from exc
    except AQ.Refused as exc:
        item = register_item(
            conn, str(source_id), title=name, url=base, status="ACCESS_DENIED",
            note=f"{exc} Recorded so the source is visible and is not "
                 "rediscovered every run.")
        # Nothing was returned, so nothing is new -- ck_query_items_le_results
        # is right to refuse the alternative. The ACCESS_DENIED row below
        # records that the SOURCE exists and cannot be read; it is not a
        # discovered item and must not be counted as one.
        AQ.record_search(conn, "YOUTUBE", f"channel:{base}", results=0,
                         items_new=0, source_id=str(source_id),
                         outcome="REFUSED", detail=str(exc)[:400])
        conn.execute("update knowledge_sources set last_checked = now() "
                     " where source_id = %s", (source_id,))
        return {"adapter": "YOUTUBE", "source": name, "entries": 0, "new": 0,
                "delivered": 0, "item_id": item,
                "detail": "refused, and recorded as inaccessible (K06)"}
    delivered = 0
    unavailable = 0
    for item in items:
        try:
            ready = YT.prepare(item)
        except YT.NoTranscript as exc:
            # The honest outcome, and the ONLY one for a video whose
            # captions we could not read. Nothing is delivered, so nothing
            # downstream can mistake an empty string for a source that
            # taught us nothing.
            vid = (item.get("videoId") or "").strip()
            register_item(
                conn, str(source_id),
                title=item.get("videoTitle") or vid or name,
                url=YT.canonical_url(vid) if YT.VIDEO_ID.match(vid or "") else None,
                guid=vid or None,
                status="FULL_TEXT_NOT_AVAILABLE", note=str(exc)[:1000])
            unavailable += 1
            continue

        meta = dict(ready["meta"])
        creator_id = upsert_creator(conn, meta)
        if creator_id:
            meta["creator_id"] = creator_id

        # Identity is the videoId, so the row is keyed on the canonical URL
        # and the id — never on the URL this was found through, which
        # carried playlist and timestamp parameters on the live run.
        register_item(conn, str(source_id), title=meta["source_title"],
                      url=meta["source_url"], guid=ready["video_id"],
                      status="QUEUED")
        KI.deliver_to_inbox(f"{ready['video_id']}.md",
                            ready["markdown"].encode("utf-8"), meta)
        delivered += 1

    AQ.record_search(conn, "YOUTUBE", f"videos:{','.join(canonical)}",
                     results=len(items), items_new=delivered,
                     source_id=str(source_id))
    conn.execute("update knowledge_sources set last_checked = now() "
                 " where source_id = %s", (source_id,))
    detail = f"{delivered} transcript(s) delivered to the inbox"
    if unavailable:
        detail += f", {unavailable} with no usable transcript"
    return {"adapter": "YOUTUBE", "source": name, "entries": len(items),
            "new": delivered, "delivered": delivered,
            "unavailable": unavailable, "detail": detail}


# ---------------------------------------------------------------------
# Routing: the adapter comes from the SOURCE, never from this file
# ---------------------------------------------------------------------

def run_source(conn, source, *, query: str | None = None, transport=None,
               urls: list[str] | None = None) -> dict:
    adapter = (source[4] or "").strip().upper()
    if not adapter:
        raise DiscoveryFailed(
            f"{source[1]} has no access_method, so no adapter can be chosen. "
            "Routing is on the source's registered method, never on its name "
            "(hard rule 13).")
    AQ.policy(conn, adapter)          # raises AdapterUnknown if unregistered

    if adapter in ("RSS", "PODCAST"):
        return discover_feed(conn, source, adapter, transport=transport)
    if adapter == "WEB_HTTP":
        return discover_web(conn, source, transport=transport)
    if adapter == "YOUTUBE":
        return discover_video(conn, source, transport=transport, urls=urls)
    if adapter in ("PUBMED", "CLINICAL_TRIALS"):
        if not query:
            raise DiscoveryFailed(
                f"{adapter} is a search adapter and needs a query. Pass "
                "--query, or record one on the source.")
        return discover_pubmed(conn, source, query, transport=transport)
    raise DiscoveryFailed(
        f"{adapter} is registered but this file has no handler for it. That is "
        "a build gap, not a policy decision — and it fails loudly rather than "
        "silently doing nothing.")


def status(conn) -> None:
    rows = conn.execute(
        "select adapter, structured, requires_authorization, searches, fetched, "
        "       refused_or_failed, items_discovered from v_discovery_state").fetchall()
    print("\nADAPTERS            struct  auth?  searches  fetched  refused  found")
    for a, structured, auth, searches, fetched, refused, found in rows:
        print(f"  {a:18s} {'yes' if structured else 'NO ':>5}  "
              f"{'YES' if auth else '-':>5}  {searches:>8}  {fetched:>7}  "
              f"{refused:>7}  {found:>5}")
    print("\n  refused is not a fault: it counts robots.txt refusals, "
          "unauthorized\n  adapters and unavailable transcripts — the policy working.")
    monitored = conn.execute(
        "select count(*) from knowledge_sources where active and monitor_status"
    ).fetchone()[0]
    print(f"\nMONITORED SOURCES   {monitored}")
    stuck = conn.execute(
        """select ingestion_status::text, count(*) from source_items
            where ingestion_status in ('FULL_TEXT_NOT_AVAILABLE','ACCESS_DENIED')
            group by 1""").fetchall()
    for st, n in stuck:
        print(f"  {st:26s} {n}   (recorded, not guessed at)")


def main() -> int:
    with psycopg.connect(dsn(), autocommit=True) as conn:
        argv = sys.argv[1:]
        if "--status" in argv or not argv:
            status(conn)
            return 0

        query = None
        if "--query" in argv:
            query = argv[argv.index("--query") + 1]

        if "--source" in argv:
            sources = [one_source(conn, argv[argv.index("--source") + 1])]
        elif "--due" in argv:
            sources = sources_due(conn)
        else:
            print("pass --source <id>, --due, or --status")
            return 2

        if not sources:
            print("no monitored sources are due")
            status(conn)
            return 0

        failures = 0
        for source in sources:
            try:
                out = run_source(conn, source, query=query)
            except (DiscoveryFailed, AQ.Refused, AQ.AdapterUnknown) as exc:
                failures += 1
                print(f"  FAILED    {source[1]}  {exc}")
                continue
            print(f"  {out['adapter']:14s} {source[1]}  {out['detail']}")

        status(conn)
        return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

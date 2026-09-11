#!/usr/bin/env python3
"""K02–K06 — discovery, its access policy, and the two things it must not do.

BUILD_GUIDE step 16, DECISIONS.md D37, migration 021.

**The network is stubbed at the WIRE, and only there.** The adapters under
test are the real ones in `scripts/knowledge_discover.py`, driven through
the real chokepoint in `scripts/acquisition.py`; only `transport()` is
replaced, and the stub returns what a real one returns — a status, headers
and bytes. That is V2: the thing under test has to be the thing that ships.

It has to be stubbed. The build environment's egress proxy blocks
`eutils.ncbi.nlm.nih.gov`, `api.crossref.org` and `pubmed.ncbi.nlm.nih.gov`
alike — all three answered `000`. So **no adapter in this build has ever
spoken to its real API**, and `PROGRESS.md` says so rather than letting a
green suite imply otherwise.

What that DOES prove: the policy chokepoint, the query history, the
cursor, the refusal paths, the parsing, and that discovery hands off to the
one ingestion pipeline instead of growing a second.
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
PREFIX = "DISCTEST-"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


class Wire:
    """A transport. Returns what urllib_transport returns, nothing more.

    Records every URL it was ASKED for, which is how a refusal is proved:
    a policy that refuses must not have made the request first.
    """

    def __init__(self, responses: dict):
        self.responses = responses
        self.asked: list[str] = []
        # The full call, so a suite can assert the METHOD and that a
        # credential travelled in a header rather than in the URL.
        self.calls: list[dict] = []

    def __call__(self, url, headers, *, method="GET", body=None):
        import acquisition as AQ
        self.asked.append(url)
        self.calls.append({"url": url, "method": method, "body": body,
                           "headers": dict(headers)})
        if url not in self.responses:
            return AQ.Response(404, {}, b"not found")
        status, body = self.responses[url]
        if isinstance(body, str):
            body = body.encode("utf-8")
        return AQ.Response(status, {"Content-Type": "text/plain"}, body)


RSS_FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Feed</title>
  <item><title>DISCTEST-Newest</title><link>https://feed.test/3</link>
        <guid>guid-3</guid>
        <description>Fibre lowers postprandial glucose.</description></item>
  <item><title>DISCTEST-Middle</title><link>https://feed.test/2</link>
        <guid>guid-2</guid><description>Second item.</description></item>
  <item><title>DISCTEST-Oldest</title><link>https://feed.test/1</link>
        <guid>guid-1</guid><description>First item.</description></item>
</channel></rss>"""

PODCAST_FEED = """<?xml version="1.0"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
<channel><title>Pod</title>
  <item><title>DISCTEST-Episode with no transcript</title>
        <link>https://pod.test/ep1</link><guid>pod-1</guid>
        <description>An hour on insulin resistance.</description></item>
</channel></rss>"""


def clear(conn) -> None:
    conn.execute("delete from source_fetches where url like %s", ("%test%",))
    conn.execute(
        "delete from source_envelopes where source_url like %s or source_title like %s",
        ("%.test/%", PREFIX + "%"))
    conn.execute("delete from source_items where url like %s or title like %s",
                 ("%.test/%", PREFIX + "%"))
    conn.execute("delete from source_items where pmid in ('40000001','40000002')")
    conn.execute("delete from source_queries where query_text like %s", ("%test%",))
    conn.execute(
        "delete from source_items where source_id in "
        "  (select source_id from knowledge_sources where source_name like %s)",
        (PREFIX + "%",))
    conn.execute("delete from knowledge_sources where source_name like %s "
                 "   or base_identifier like %s", (PREFIX + "%", "%.test/%"))
    conn.execute("delete from acquisition_adapters where adapter like 'DISCTEST%'")


def make_source(conn, name, access_method, base) -> str:
    return str(conn.execute(
        """insert into knowledge_sources
             (source_name, source_type, source_roles, base_identifier,
              access_method, monitor_status)
           values (%s,'OTHER',array['DISCOVERY']::source_role[],%s,%s,true)
           returning source_id""", (PREFIX + name, base, access_method)).fetchone()[0])


def source_row(conn, source_id):
    import knowledge_discover as KD
    return KD.one_source(conn, source_id)


def main() -> int:
    os.environ["LLM_API_KEY"] = ""
    root = Path(tempfile.mkdtemp(prefix="disc-"))
    os.environ["KNOWLEDGE_DIR"] = str(root)
    for name in ("inbox", "raw", "processed", "failed"):
        (root / name).mkdir(parents=True, exist_ok=True)

    import acquisition as AQ
    import knowledge_discover as KD
    import knowledge_ingest as KI

    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    clear(conn)

    # ------------------------------------------------------------------
    print("\nthe policy lives in the registry, not in the adapters")

    check("every registered adapter that fetches declares a robots stance",
          conn.execute(
              "select count(*) from acquisition_adapters where respect_robots is null"
          ).fetchone()[0] == 0)
    try:
        AQ.policy(conn, "NOT_REGISTERED")
        check("an unregistered adapter is refused a policy", False, "returned one")
    except AQ.AdapterUnknown as exc:
        check("an unregistered adapter is refused a policy",
              "has no access policy" in str(exc))

    # ------------------------------------------------------------------
    print("\nK03: respect access restrictions")

    wire = Wire({
        "https://blocked.test/robots.txt": (200, "User-agent: *\nDisallow: /\n"),
        "https://blocked.test/article": (200, "<html><body>text</body></html>"),
    })
    try:
        AQ.fetch(conn, "WEB_HTTP", "https://blocked.test/article", transport=wire)
        check("robots.txt Disallow is respected", False, "it fetched anyway")
    except AQ.Refused as exc:
        check("robots.txt Disallow is respected", "robots.txt disallows" in str(exc))
    check("...and the page was never requested",
          "https://blocked.test/article" not in wire.asked, str(wire.asked))
    check("...with the refusal recorded, not just skipped",
          conn.execute(
              "select outcome from source_fetches where url=%s order by fetched_at desc "
              " limit 1", ("https://blocked.test/article",)).fetchone()[0]
          == "REFUSED_ROBOTS")

    # A robots.txt that ERRORS has not granted permission. (A 404 has: no
    # robots.txt means no restriction stated, which is the standard reading
    # and is exercised below.)
    erroring = Wire({"https://silent.test/robots.txt": (500, "boom"),
                     "https://silent.test/article": (200, "hello")})
    try:
        AQ.fetch(conn, "WEB_HTTP", "https://silent.test/article", transport=erroring)
        check("a robots.txt that errors is treated as a refusal", False, "it fetched")
    except AQ.Refused as exc:
        check("a robots.txt that errors is treated as a refusal",
              "robots.txt returned 500" in str(exc), str(exc))
    check("...and the article was never requested",
          "https://silent.test/article" not in erroring.asked, str(erroring.asked))

    class Dead:
        """A transport that cannot connect at all."""
        asked: list = []

        def __call__(self, url, headers, *, method="GET", body=None):
            self.asked.append(url)
            raise ConnectionError("no route to host")

    dead = Dead()
    try:
        AQ.fetch(conn, "WEB_HTTP", "https://dead.test/article", transport=dead)
        check("an unreachable robots.txt is treated as a refusal", False, "it fetched")
    except AQ.Refused as exc:
        check("an unreachable robots.txt is treated as a refusal",
              "could not be read" in str(exc), str(exc))

    ok_wire = Wire({
        "https://open.test/robots.txt": (404, ""),
        "https://open.test/article": (200, "<html><body><h1>Fibre</h1>"
                                           "<p>Lowers postprandial glucose.</p>"
                                           "</body></html>"),
    })
    web_source = make_source(conn, "site", "WEB_HTTP", "https://open.test/article")
    out = KD.discover_web(conn, source_row(conn, web_source), transport=ok_wire)
    check("no robots.txt means no stated restriction, and the page is read",
          out["delivered"] == 1, str(out))

    # ------------------------------------------------------------------
    print("\ndiscovery hands off to the ONE ingestion pipeline")

    delivered = list((root / "inbox").glob("*.html"))
    check("the page lands in the inbox rather than being normalized here",
          len(delivered) == 1, str([p.name for p in delivered]))
    receipt = KI.ingest_one(conn, delivered[0])
    check("...and K07/K08 process it exactly as a dropped file",
          receipt.outcome == "NORMALIZED", receipt.detail or "")
    check("...with the discovered URL carried onto the envelope",
          conn.execute(
              "select source_url from source_envelopes where envelope_id=%s",
              (receipt.envelope_id,)).fetchone()[0] == "https://open.test/article")

    # ------------------------------------------------------------------
    print("\nK04: do not reprocess old content")

    feed_wire = Wire({"https://feed.test/rss": (200, RSS_FEED)})
    feed_source = make_source(conn, "feed", "RSS", "https://feed.test/rss")
    first = KD.discover_feed(conn, source_row(conn, feed_source), "RSS",
                             transport=feed_wire)
    check("a first read takes every entry", first["new"] == 3, str(first))
    check("...and delivers them to the inbox", first["delivered"] == 3, str(first))

    second = KD.discover_feed(conn, source_row(conn, feed_source), "RSS",
                              transport=feed_wire)
    check("a second read of an unchanged feed takes NOTHING",
          second["new"] == 0 and second["delivered"] == 0, str(second))
    check("...because the cursor remembers the newest item",
          AQ.cursor(conn, feed_source, "FEED_GUID") == "guid-3")

    grown = RSS_FEED.replace(
        "<item><title>DISCTEST-Newest",
        "<item><title>DISCTEST-Brand new</title><link>https://feed.test/4</link>"
        "<guid>guid-4</guid><description>Fourth.</description></item>"
        "<item><title>DISCTEST-Newest")
    feed_wire.responses["https://feed.test/rss"] = (200, grown)
    third = KD.discover_feed(conn, source_row(conn, feed_source), "RSS",
                             transport=feed_wire)
    check("a new entry is taken, and only that one",
          third["new"] == 1 and third["delivered"] == 1, str(third))

    # ------------------------------------------------------------------
    print("\nK05: no transcript means say so, never invent")

    pod_wire = Wire({"https://pod.test/rss": (200, PODCAST_FEED)})
    pod_source = make_source(conn, "pod", "PODCAST", "https://pod.test/rss")
    pod = KD.discover_feed(conn, source_row(conn, pod_source), "PODCAST",
                           transport=pod_wire)
    check("an episode with no transcript is NOT delivered as content",
          pod["delivered"] == 0, str(pod))
    item = conn.execute(
        "select ingestion_status::text, access_note from source_items "
        " where external_id='pod-1'").fetchone()
    check("...it is recorded as FULL_TEXT_NOT_AVAILABLE",
          item[0] == "FULL_TEXT_NOT_AVAILABLE", str(item[0]))
    check("...and the note says the content was not guessed at",
          "not guessed at" in (item[1] or ""), str(item[1]))
    check("no inbox file was written from a title and a summary",
          not list((root / "inbox").glob("*Episode*")))

    # ------------------------------------------------------------------
    print("\nK06: the refusal is the ABSENCE of an authorization, not a hard-coded no")

    # The YOUTUBE adapter now HAS an authorization (migration 030, D46), so
    # what is worth asserting here is that the refusal is still one row
    # away — the policy lives in `acquisition_adapters` and nothing about
    # the refusal is compiled into the adapter. `test_youtube.py` covers
    # the authorized path in full; this is the registry half.
    video_wire = Wire({})
    video_source = make_source(conn, "channel", "YOUTUBE",
                               "https://video.test/channel")
    saved_note = conn.execute(
        "select authorization_note from acquisition_adapters "
        " where adapter='YOUTUBE'").fetchone()[0]
    try:
        conn.execute("update acquisition_adapters set authorization_note=null "
                     " where adapter='YOUTUBE'")
        vid = KD.discover_video(conn, source_row(conn, video_source),
                                transport=video_wire, urls=["https://video.test/x"])
        check("with no authorization recorded the adapter delivers nothing",
              vid["delivered"] == 0, str(vid))
        check("...and NOTHING was requested — not even robots.txt",
              video_wire.asked == [], str(video_wire.asked))
        vitem = conn.execute(
            "select ingestion_status::text, access_note from source_items "
            " where item_id=%s", (vid["item_id"],)).fetchone()
        check("...the item is ACCESS_DENIED, a true statement about our access",
              vitem[0] == "ACCESS_DENIED", str(vitem[0]))
        check("...explaining that no authorization is recorded",
              "authorization" in (vitem[1] or "").lower(), str(vitem[1]))
        conn.execute("delete from source_items where item_id=%s", (vid["item_id"],))
    finally:
        # Restored unconditionally. An earlier version left this NULL on a
        # committed transaction, and every later suite then ran against an
        # adapter that had quietly lost its authorization.
        conn.execute("update acquisition_adapters set authorization_note=%s "
                     " where adapter='YOUTUBE'", (saved_note,))

    # ------------------------------------------------------------------
    print("\nK02: expensive searches are not repeated")

    pubmed_source = make_source(conn, "pubmed", "PUBMED", None)
    search_url = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
                  "?db=pubmed&retmode=json&retmax=20&term=berberine+test")
    pub_wire = Wire({search_url: (200, json.dumps(
        {"esearchresult": {"idlist": ["40000001", "40000002"]}}))})
    run1 = KD.discover_pubmed(conn, source_row(conn, pubmed_source),
                              "berberine test", transport=pub_wire)
    check("a search registers what it found", run1["new"] == 2, str(run1))
    check("...as DISCOVERED, because an abstract is not the paper",
          conn.execute(
              "select ingestion_status::text from source_items where pmid='40000001'"
          ).fetchone()[0] == "DISCOVERED")

    calls_before = len(pub_wire.asked)
    run2 = KD.discover_pubmed(conn, source_row(conn, pubmed_source),
                              "  BERBERINE   Test ", transport=pub_wire)
    check("the same search — differently phrased — is NOT run again",
          len(pub_wire.asked) == calls_before, str(pub_wire.asked[calls_before:]))
    check("...and says why", "not repeated" in run2["detail"], run2["detail"])

    check("a PubMed host restriction is enforced",
          conn.execute(
              "select allowed_hosts from acquisition_adapters where adapter='PUBMED'"
          ).fetchone()[0] == ["eutils.ncbi.nlm.nih.gov"])
    try:
        AQ.fetch(conn, "PUBMED", "https://elsewhere.test/x", transport=pub_wire)
        check("...so another host is refused", False, "it fetched")
    except AQ.Refused as exc:
        check("...so another host is refused", "allowed_hosts" in str(exc)
              or "may only fetch" in str(exc), str(exc))

    # ------------------------------------------------------------------
    print("\nrouting comes from the source, never from this code")

    orphan = make_source(conn, "no-method", None, "https://x.test/")
    try:
        KD.run_source(conn, source_row(conn, orphan))
        check("a source with no access_method cannot be routed", False, "it ran")
    except KD.DiscoveryFailed as exc:
        check("a source with no access_method cannot be routed",
              "no access_method" in str(exc))

    unknown = make_source(conn, "unknown-method", "NOT_REGISTERED",
                          "https://x2.test/")
    try:
        KD.run_source(conn, source_row(conn, unknown))
        check("an unregistered adapter cannot be routed", False, "it ran")
    except AQ.AdapterUnknown:
        check("an unregistered adapter cannot be routed", True)

    # Adding one is an INSERT, and then it routes.
    conn.execute(
        "insert into acquisition_adapters (adapter, display_name, structured, "
        "                                  allowed_hosts, respect_robots) "
        "values ('DISCTEST_FEED','Test feed',true,null,true)")
    conn.execute("update knowledge_sources set access_method='RSS' where source_id=%s",
                 (unknown,))
    check("registering an adapter is an INSERT, with no code change",
          AQ.policy(conn, "DISCTEST_FEED")["adapter"] == "DISCTEST_FEED")

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

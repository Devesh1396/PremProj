#!/usr/bin/env python3
"""The acquisition chokepoint. Every discovery fetch goes through here.

BUILD_GUIDE step 16, K02–K06. Engine 7 §47, §49, §52; D37.

Three sentences of the specification are policy rather than code:

    K03  "Not indiscriminate scraping. Respect access restrictions."
    K06  "Do not build brittle unauthorized scraping as a core dependency."
    §49  acquisition is provider-independent and the adapter is replaceable

A policy that lives inside an adapter is a policy the next adapter gets to
reinterpret. It lives in `acquisition_adapters` (migration 021) and is
enforced HERE, once, for every family. Adding an adapter is a registry
INSERT (hard rule 13); what that adapter may do is a column, not an
argument someone remembered to pass.

### The transport is injected

`fetch()` takes a `transport` callable so a suite can drive the REAL
adapter code against recorded responses. It is the same reason
`testing/n8n_retry.js` runs the workflow's own source with the HTTP helper
stubbed: the thing under test has to be the thing that ships, and only the
wire underneath it may be replaced (V2).

### What "refused" means

A refusal is recorded in `source_fetches` as deliberately as a fetch.
"robots.txt disallowed this" and "no transcript is legitimately available"
are **findings about our access**, not failures — and a discovery layer
that logged them nowhere would look identical to one that was quietly
scraping.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import (parse_qsl, urlencode, urlparse, urlsplit,
                          urlunsplit)

import psycopg

USER_AGENT = os.environ.get(
    "ACQUISITION_USER_AGENT",
    "PremProj-KnowledgeFactory/1.0 (internal practitioner research tool)")

# The same discipline as the engine transport (D29), and deliberately the
# same numbers, imported rather than re-typed.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_engine as RE  # noqa: E402

MAX_ATTEMPTS = RE.MAX_TRANSPORT_ATTEMPTS
BACKOFF_BASE = RE.TRANSPORT_BACKOFF_BASE
BACKOFF_CAP = RE.TRANSPORT_BACKOFF_CAP
RETRYABLE = RE.RETRYABLE_HTTP_STATUS


class AdapterUnknown(RuntimeError):
    """No registry row. An unregistered adapter has no policy, so it fetches nothing."""


class Refused(RuntimeError):
    """The policy said no. Not an error in the usual sense — a correct outcome."""


@dataclass
class Response:
    status: int
    headers: dict
    body: bytes


# transport(url, headers) -> Response. Raises for network-level failure.
# (url, headers, *, method, body) -> Response. The keyword-only tail is
# why a transport written for GET still satisfies it.
Transport = Callable[..., Response]


def urllib_transport(url: str, headers: dict, *, method: str = "GET",
                     body: bytes | None = None) -> Response:
    """The transport contract: (url, headers, *, method, body) -> Response.

    `method` and `body` are keyword-only and default to a plain GET, so
    every transport written before POST existed still satisfies the
    contract. A POST is needed because an actor-run API takes its input in
    a request body -- and routing that through this same function is the
    point: there is one place a request leaves this process.
    """
    request = urllib.request.Request(url, headers=headers, data=body,
                                     method=method)
    try:
        with urllib.request.urlopen(request, timeout=180) as reply:
            return Response(reply.status, dict(reply.headers), reply.read())
    except urllib.error.HTTPError as exc:
        # An HTTP error is a RESPONSE, not a transport failure: 403 and 404
        # are answers, and the caller decides what they mean.
        return Response(exc.code, dict(exc.headers or {}), exc.read() or b"")


# Query parameters that carry a credential. `source_fetches.url` is a
# permanent record read by anyone with database access, and an API that
# accepts `?token=` will happily let one be written there forever.
SECRET_PARAMS = ("token", "key", "api_key", "apikey", "access_token",
                 "secret", "password", "auth")


def redact(url: str) -> str:
    """Strip credential-bearing query values before anything is recorded.

    Not a substitute for sending the credential in a header -- which is
    what this codebase does -- but a fetch log is exactly the kind of place
    a secret ends up by accident, and it is cheap to make that impossible
    for every adapter at once rather than for the one that thought of it.
    """
    parts = urlsplit(url)
    if not parts.query:
        return url
    kept = [(k, "REDACTED" if k.lower() in SECRET_PARAMS else v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(kept), parts.fragment))


def query_hash(text: str) -> str:
    """Normalized, so two phrasings of one search do not both get paid for."""
    collapsed = re.sub(r"\s+", " ", (text or "").strip().lower())
    return hashlib.sha256(collapsed.encode("utf-8")).hexdigest()


def policy(conn, adapter: str) -> dict:
    row = conn.execute(
        """select adapter, display_name, structured, allowed_hosts,
                  respect_robots, requires_authorization, authorization_note,
                  min_interval_seconds, repeat_after_hours, active
             from acquisition_adapters where adapter = %s""", (adapter,)).fetchone()
    if row is None:
        raise AdapterUnknown(
            f"{adapter!r} is not in acquisition_adapters. An adapter with no "
            "registry row has no access policy, and this layer will not fetch "
            "on behalf of one. Adding it is an INSERT (hard rule 13).")
    keys = ("adapter", "display_name", "structured", "allowed_hosts",
            "respect_robots", "requires_authorization", "authorization_note",
            "min_interval_seconds", "repeat_after_hours", "active")
    return dict(zip(keys, row))


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def record(conn, adapter: str, url: str, outcome: str, *, status=None,
           size=None, detail=None) -> None:
    conn.execute(
        """insert into source_fetches
             (adapter, host, url, status_code, bytes, outcome, detail)
           values (%s,%s,%s,%s,%s,%s,%s)""",
        (adapter, host_of(url), redact(url)[:2000], status, size, outcome,
         (detail or "")[:2000] or None))


def robots_allows(conn, rule: dict, url: str, transport: Transport) -> tuple[bool, str]:
    """Whether robots.txt permits this fetch. Failure to read it is a NO.

    "Respect access restrictions" cannot mean "respect them when they are
    conveniently available". A site whose robots.txt cannot be read has not
    granted permission, so the answer is no and the reason is recorded.
    """
    if not rule["respect_robots"]:
        return True, "adapter reads a documented API; robots.txt does not apply"
    parts = urlparse(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        reply = transport(robots_url, {"User-Agent": USER_AGENT})
    except Exception as exc:  # noqa: BLE001 - any transport failure is a no
        return False, f"robots.txt could not be read ({type(exc).__name__})"
    if reply.status == 404:
        # No robots.txt is the one honest "no restrictions stated".
        return True, "no robots.txt published"
    if reply.status != 200:
        return False, f"robots.txt returned {reply.status}"
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(reply.body.decode("utf-8", errors="replace").splitlines())
    allowed = parser.can_fetch(USER_AGENT, url)
    return allowed, ("robots.txt allows it" if allowed
                     else "robots.txt disallows this path for our agent")


def throttle(conn, rule: dict, url: str) -> None:
    """Wait out this adapter's minimum interval for the host, if needed."""
    if rule["min_interval_seconds"] <= 0:
        return
    row = conn.execute(
        "select max(fetched_at) from source_fetches "
        " where host = %s and outcome = 'FETCHED'", (host_of(url),)).fetchone()
    if not row or row[0] is None:
        return
    wait = rule["min_interval_seconds"] - (
        datetime.now(timezone.utc) - row[0]).total_seconds()
    if wait > 0:
        time.sleep(min(wait, rule["min_interval_seconds"]))


def fetch(conn, adapter: str, url: str, *, transport: Transport | None = None,
          accept: str | None = None, method: str = "GET",
          body: bytes | None = None, extra_headers: dict | None = None) -> Response:
    """Fetch, or refuse and say why. Every outcome is recorded.

    `method`, `body` and `extra_headers` exist so an adapter that needs a
    POST or an `Authorization` header still comes through HERE. The
    alternative -- an adapter making its own request because the chokepoint
    only did GETs -- is a second access path with no policy on it (D37).

    Neither the body nor the headers is ever recorded. A request body can
    carry anything the caller put in it, and headers are where credentials
    belong; `source_fetches` keeps the URL, the status and the size.
    """
    rule = policy(conn, adapter)
    transport = transport or urllib_transport

    if not rule["active"]:
        record(conn, adapter, url, "REFUSED_INACTIVE",
               detail="the adapter is registered but not active")
        raise Refused(f"{adapter} is not active.")

    if rule["requires_authorization"] and not (rule["authorization_note"] or "").strip():
        # K06, and the reason this column exists. Marking the item
        # ACCESS_DENIED is a TRUE statement about our access; building the
        # scraper anyway is what the specification says not to do.
        record(conn, adapter, url, "REFUSED_UNAUTHORIZED",
               detail="requires_authorization is set and no authorization is "
                      "recorded; nothing was requested")
        raise Refused(
            f"{adapter} requires an authorization nobody has recorded. The "
            "specification says not to build brittle unauthorized scraping as "
            "a core dependency, so this fetch does not happen and the item is "
            "marked as inaccessible rather than guessed at.")

    hosts = rule["allowed_hosts"]
    if hosts is not None and host_of(url) not in {h.lower() for h in hosts}:
        record(conn, adapter, url, "REFUSED_HOST",
               detail=f"{host_of(url)} is not in this adapter's allowed_hosts")
        raise Refused(
            f"{adapter} may only fetch from {', '.join(hosts)}; {host_of(url)} "
            "is not one of them.")

    allowed, why = robots_allows(conn, rule, url, transport)
    if not allowed:
        record(conn, adapter, url, "REFUSED_ROBOTS", detail=why)
        raise Refused(f"{url} was not fetched: {why}.")

    throttle(conn, rule, url)

    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    if extra_headers:
        headers.update(extra_headers)

    last: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            reply = transport(url, headers, method=method, body=body)
        except Exception as exc:  # noqa: BLE001 - network-level
            last = exc
            if attempt == MAX_ATTEMPTS:
                break
            time.sleep(min(BACKOFF_CAP, BACKOFF_BASE ** attempt))
            continue

        if reply.status in RETRYABLE and attempt < MAX_ATTEMPTS:
            time.sleep(min(BACKOFF_CAP, BACKOFF_BASE ** attempt))
            continue
        if 200 <= reply.status < 300:
            record(conn, adapter, url, "FETCHED", status=reply.status,
                   size=len(reply.body))
            return reply
        record(conn, adapter, url, "HTTP_ERROR", status=reply.status,
               size=len(reply.body), detail=f"{reply.status} after {attempt} attempt(s)")
        raise Refused(f"{url} returned {reply.status}.")

    record(conn, adapter, url, "TRANSPORT_FAILED",
           detail=f"{type(last).__name__}: {last}" if last else "no response")
    raise Refused(f"{url} could not be reached: {last}")


# ---------------------------------------------------------------------
# K02: do not pay for the same search twice
# ---------------------------------------------------------------------

def searched_recently(conn, adapter: str, query_text: str) -> dict | None:
    """The last run of this search inside the adapter's repeat window, or None."""
    rule = policy(conn, adapter)
    if rule["repeat_after_hours"] <= 0:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=rule["repeat_after_hours"])
    row = conn.execute(
        """select executed_at, results_returned, items_new, outcome
             from source_queries
            where adapter = %s and query_hash = %s and executed_at >= %s
            order by executed_at desc limit 1""",
        (adapter, query_hash(query_text), cutoff)).fetchone()
    if row is None:
        return None
    return {"executed_at": row[0], "results_returned": row[1],
            "items_new": row[2], "outcome": row[3]}


def record_search(conn, adapter: str, query_text: str, *, results: int = 0,
                  items_new: int = 0, source_id=None, outcome: str = "OK",
                  detail: str | None = None) -> str:
    return str(conn.execute(
        """insert into source_queries
             (adapter, query_text, query_hash, source_id, results_returned,
              items_new, outcome, detail)
           values (%s,%s,%s,%s,%s,%s,%s,%s) returning query_id""",
        (adapter, query_text, query_hash(query_text), source_id, results,
         items_new, outcome, detail)).fetchone()[0])


# ---------------------------------------------------------------------
# K04: do not reprocess old content
# ---------------------------------------------------------------------

def cursor(conn, source_id: str, kind: str) -> str | None:
    row = conn.execute(
        "select cursor_value from source_cursors "
        " where source_id = %s and cursor_kind = %s", (source_id, kind)).fetchone()
    return row[0] if row else None


def advance_cursor(conn, source_id: str, kind: str, value: str,
                   seen: int = 0) -> None:
    conn.execute(
        """insert into source_cursors (source_id, cursor_kind, cursor_value, items_seen)
           values (%s,%s,%s,%s)
           on conflict (source_id, cursor_kind) do update
             set cursor_value = excluded.cursor_value,
                 items_seen = source_cursors.items_seen + excluded.items_seen,
                 updated_at = now()""",
        (source_id, kind, value, seen))

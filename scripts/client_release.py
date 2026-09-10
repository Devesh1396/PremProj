#!/usr/bin/env python3
"""E5 and release. Step 20 — the only client-facing path in the system.

Hard rule 9, D6; migrations 004 and 026.

    python3 scripts/client_release.py --queue
    python3 scripts/client_release.py --approve REVIEW_ID --by "practitioner"
    python3 scripts/client_release.py --draft CLIENT_ID
    python3 scripts/client_release.py --release COMMUNICATION_ID --by "practitioner"

### Why this is not part of CLIENT_NEW

`CLIENT_NEW` stops at the review queue on purpose. A pipeline that ran E5
itself would either be bypassing the review it just asked for, or drafting
client-facing output nobody has looked at. The practitioner is the
professional decision-maker; this file is what happens *after* they decide.

### Three separate things, and none of them substitutes for another

| | |
|---|---|
| **Approval** | A practitioner accepted the analysis. Recorded in `practitioner_reviews`. |
| **Drafting** | E5 turns the approved plan into something a client can read. **Never gated** — hard rule 9 gates release, not analysis or drafting. |
| **Release** | The message is sent. Gated by `trg_block_unapproved_communication` on open HOLDs, and by this file on approval. |

Drafting before approval is allowed and sometimes useful; **releasing**
without it is not. The database enforces the HOLD half because a workflow
can be edited and a trigger cannot be forgotten; this file enforces the
approval half, and `v_release_readiness` shows both.

### The gate must not fire on ordinary clients

A client on metformin, a statin and an ACE inhibitor has no HOLD and
releases normally (D6). If this gate starts firing on most cases, the
correct response is to narrow the rules, not to teach the practitioner to
override — an override that becomes routine is the rubber stamp the whole
design rejects.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import psycopg

import run_engine as RE

COMMUNICATION_TAG = "CLIENT_COMMUNICATION_HANDOFF"
APPROVED = ("APPROVED", "APPROVED_WITH_EDITS")


class ReleaseRefused(RuntimeError):
    """A release this file will not perform."""


def dsn() -> str:
    return os.environ["DATABASE_URL"]


def scope(conn, client_id: str) -> None:
    """Client scope is transaction-local (hard rule 8, D25)."""
    conn.execute("select set_client_scope(%s::uuid)", (client_id,))


def queue(conn) -> list[tuple]:
    return conn.execute(
        "select review_id::text, client_id::text, display_name, open_holds, "
        "       open_notes, created_at from v_review_queue").fetchall()


def approve(conn, review_id: str, by: str, notes: str | None = None,
            with_edits: str | None = None) -> dict:
    """Record a practitioner decision. It does NOT release anything.

    Approval and the safety gate are independent: approving a case with an
    open HOLD is legitimate — the practitioner may be approving the
    analysis while the HOLD is still being resolved — and the release will
    still be refused until the flag is cleared by someone who can.
    """
    row = conn.execute(
        "select client_id::text, decision::text from practitioner_reviews "
        " where review_id=%s::uuid", (review_id,)).fetchone()
    if row is None:
        raise ReleaseRefused(f"no review {review_id}")
    client_id, decision = row
    if decision != "PENDING":
        raise ReleaseRefused(
            f"review {review_id} is already {decision}. Re-deciding a closed "
            "review would overwrite the record of what was actually decided.")

    conn.execute(
        "update practitioner_reviews set decision=%s, reviewed_by=%s, "
        "       notes=coalesce(%s, notes), edited_output=%s, decided_at=now() "
        " where review_id=%s::uuid",
        ("APPROVED_WITH_EDITS" if with_edits else "APPROVED", by, notes,
         with_edits, review_id))

    holds = conn.execute(
        "select count(*) from case_flags where client_id=%s::uuid "
        "  and severity='HOLD' and status='OPEN'", (client_id,)).fetchone()[0]
    return {"review_id": review_id, "client_id": client_id,
            "decision": "APPROVED_WITH_EDITS" if with_edits else "APPROVED",
            "open_holds": holds,
            "note": ("approved; release still blocked by an open HOLD"
                     if holds else "approved; releasable once drafted")}


def draft(conn, client_id: str, comm_type: str = "FIRST_ASSESSMENT") -> dict:
    """Run E5 and store the draft. Never gated (hard rule 9).

    Drafting a message for a client with an open HOLD is deliberately
    allowed: the practitioner may need to see what would be said in order
    to decide whether the HOLD matters. Sending it is what is refused.
    """
    state = conn.execute(
        "select get_current_client_state(%s::uuid)", (client_id,)).fetchone()[0]
    if state is None:
        raise ReleaseRefused(
            f"client {client_id} has no current case version; there is "
            "nothing to communicate.")

    cycle = conn.execute(
        "select cycle_id::text from case_cycles where client_id=%s::uuid "
        " order by opened_at desc limit 1", (client_id,)).fetchone()

    # What E5 is allowed to see. The plan as rows, plus the flags -- so a
    # NOTE the practitioner did not treat as blocking still reaches the
    # message as something to mention rather than being invisible to it.
    interventions = conn.execute(
        """select name, purpose, status::text from client_interventions
            where client_id=%s::uuid
              and status in ('PROPOSED','APPROVED','STARTED','ONGOING','MODIFIED')
            order by name""", (client_id,)).fetchall()
    flags = conn.execute(
        "select rule_key, severity::text, detail from case_flags "
        " where client_id=%s::uuid and status='OPEN' order by severity, rule_key",
        (client_id,)).fetchall()

    result = RE.run_engine(
        conn,
        RE.EngineRequest(
            engine="E5", client_id=client_id, model_role="MODEL_ANALYSIS",
            structured_input={
                "COMMUNICATION_TYPE": comm_type,
                "CLIENT_STATE": state,
                "PROPOSED_INTERVENTIONS": [
                    {"name": r[0], "purpose": r[1], "status": r[2]}
                    for r in interventions],
                # Flags are context for the message, never instructions to
                # the client. §9 and hard rule 9: no engine tells a client
                # to stop, reduce or change a prescribed medication; it may
                # say prescriber reassessment is warranted.
                "OPEN_FLAGS": [
                    {"rule": r[0], "severity": r[1], "detail": r[2]} for r in flags],
            },
            run_context={"stage": "E5_DRAFT", "comm_type": comm_type}))

    if result.status != "SUCCEEDED":
        raise ReleaseRefused(
            f"the E5 run did not succeed ({result.status}): {result.error}")

    content = (result.human_output or "").strip()
    if not content:
        raise ReleaseRefused(
            "E5 produced a handoff but no client-facing text. The handoff is "
            "what the runtime reasons with; the human-readable draft is what "
            "the client would read, and there is no message without it.")

    communication_id = str(conn.execute(
        """insert into client_communications
             (client_id, cycle_id, run_id, comm_type, content, released)
           values (%s::uuid,%s::uuid,%s::uuid,%s,%s,false)
           returning communication_id""",
        (client_id, cycle[0] if cycle else None, result.run_id, comm_type,
         content)).fetchone()[0])

    return {"communication_id": communication_id, "run_id": result.run_id,
            "characters": len(content), "released": False,
            "note": "drafted, not released. Drafting is never gated."}


def release(conn, communication_id: str, by: str) -> dict:
    """Send it. Refused without approval; refused by the DATABASE on a HOLD.

    The approval check is here and the HOLD check is a trigger, on purpose.
    A workflow can be edited, reordered or bypassed; a trigger cannot be
    forgotten. So the check that must never be missed lives where nothing
    can route around it, and this file's job is to fail earlier and more
    legibly.
    """
    row = conn.execute(
        "select client_id::text, released from client_communications "
        " where communication_id=%s::uuid", (communication_id,)).fetchone()
    if row is None:
        raise ReleaseRefused(f"no communication {communication_id}")
    client_id, already = row
    if already:
        return {"communication_id": communication_id, "released": True,
                "note": "already released; releasing twice is not a send"}

    approved = conn.execute(
        "select count(*) from practitioner_reviews where client_id=%s::uuid "
        "  and decision = any(%s)", (client_id, list(APPROVED))).fetchone()[0]
    if not approved:
        raise ReleaseRefused(
            "no practitioner approval on record for this client. The safety "
            "gate stops a HOLD; it does not stand in for the practitioner, "
            "and neither does this file stand in for the gate.")

    try:
        conn.execute(
            "update client_communications set released=true, released_at=now(), "
            "       released_by=%s where communication_id=%s::uuid",
            (by, communication_id))
    except psycopg.Error as exc:
        raise ReleaseRefused(str(exc).strip().splitlines()[0]) from exc

    return {"communication_id": communication_id, "released": True,
            "released_by": by, "note": "released"}


def status(conn) -> None:
    print(f"\n{'client':<28}{'HOLD':>6}{'NOTE':>6}{'pending':>9}"
          f"{'approved':>10}  releasable")
    for row in conn.execute(
            "select coalesce(display_name, client_id::text), open_holds, "
            "       open_notes, pending_reviews, approvals, releasable "
            "  from v_release_readiness order by open_holds desc, 1").fetchall():
        name, holds, notes, pending, approvals, ok = row
        print(f"{str(name)[:27]:<28}{holds:>6}{notes:>6}{pending:>9}"
              f"{approvals:>10}  {'YES' if ok else ''}")
    print("\nNOTE flags appear here and never block (hard rule 9).")
    print("A client on metformin, a statin and an ACE inhibitor shows 0 HOLDs.")


def main() -> int:
    ap = argparse.ArgumentParser(description="E5 draft and gated release")
    ap.add_argument("--queue", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--approve", metavar="REVIEW_ID")
    ap.add_argument("--draft", metavar="CLIENT_ID")
    ap.add_argument("--release", metavar="COMMUNICATION_ID")
    ap.add_argument("--by", default="practitioner")
    ap.add_argument("--notes")
    args = ap.parse_args()

    with psycopg.connect(dsn(), autocommit=True) as conn:
        if args.status:
            status(conn)
            return 0
        if args.queue:
            for row in queue(conn):
                print(f"  {row[0]}  {row[2] or row[1]:<24} "
                      f"HOLD {row[3]}  NOTE {row[4]}  {row[5]:%Y-%m-%d}")
            return 0
        if args.approve:
            print(f"  {approve(conn, args.approve, args.by, args.notes)}")
            return 0
        if args.draft:
            with conn.transaction():
                scope(conn, args.draft)
                print(f"  {draft(conn, args.draft)}")
            return 0
        if args.release:
            client = conn.execute(
                "select client_id::text from client_communications "
                " where communication_id=%s::uuid", (args.release,)).fetchone()
            if client is None:
                print(f"no communication {args.release}")
                return 1
            with conn.transaction():
                scope(conn, client[0])
                print(f"  {release(conn, args.release, args.by)}")
            return 0
        ap.error("nothing to do; try --status")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

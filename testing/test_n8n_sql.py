#!/usr/bin/env python3
"""The workflow's SQL, executed. Against the real database, as phi_runtime.

BUILD_GUIDE step 11, DECISIONS.md D26/D31.

`test_n8n_parity.py` proves the two implementations build the same request
and read the same response. It never touched the third thing the workflow
does, which is WRITE -- and that was the only part of the port nothing
executed. Three defects were sitting in it at once:

  * `Open run` did not send `engine_mode`, so every n8n run would have been
    rejected by the coherence trigger 015 had just added (D27).
  * `Dead letter` did not send `client_id`, so every n8n dead letter would
    have been the unscoped cross-client payload 015 had just fixed (D28).
  * `Record attempts` inserted into a column called `latency_ms`, which has
    never existed. The column is `duration_ms`.

None of the three could be seen by reading the JSON, and all three were
introduced in the same sitting as the migration that made them wrong. So:
execute it.

Two of the four things this suite checks are not about SQL at all. They are
about how n8n turns a queryReplacement expression into a parameter list,
which is documented nowhere and is surprising in three separate ways --
see testing/n8n_bind_params.js. Binding is done by a faithful port of
n8n's own algorithm, running the workflow's real expressions through Node.

Needs Node. SKIPS loudly when it is absent.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "testing"))

import psycopg

import preflight
import pricing
import run_engine as RE
from test_case_events import _role_password, _with_user  # noqa: E402

FAILS: list[str] = []
WORKFLOW = REPO / "workflows" / "run_engine.json"
BINDER = REPO / "testing" / "n8n_bind_params.js"
EXTERNAL_REF = "N8NSQL-"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def node(name: str) -> dict:
    doc = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    wf = doc[0] if isinstance(doc, list) else doc
    for n in wf["nodes"]:
        if n["name"] == name:
            return n
    raise AssertionError(f"no node named {name}")


def bind(name: str, ctx: dict) -> tuple[str, list]:
    """Bind a node's parameters the way n8n 2.5 does, using its own algorithm."""
    out = subprocess.run(
        ["node", str(BINDER), name],
        input=json.dumps(ctx), capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise AssertionError(f"binder failed for {name}: {out.stderr.strip()}")
    got = json.loads(out.stdout)
    return got["query"], got["values"]


def run_node(conn, name: str, ctx: dict) -> None:
    """Execute a node the way the Postgres node does: statements in one go."""
    query, values = bind(name, ctx)
    # n8n's driver sends the whole query text with $1..$n; psycopg speaks
    # %s and one statement per execute. Split on the statement terminator
    # every node in this workflow is written with, then rewrite each $n to
    # a %s in order of appearance -- the numbering is shared across the
    # whole node text, so a fragment's placeholders are not $1..$k.
    for statement in [s.strip() for s in query.split(";\n") if s.strip()]:
        params: list = []

        def take(m: re.Match) -> str:
            params.append(values[int(m.group(1)) - 1])
            return "%s"

        conn.execute(re.sub(r"\$(\d+)", take, statement), params)


INSERT_RE = re.compile(r"insert\s+into\s+(\w+)\s*\(([^)]*)\)", re.I)


def insert_columns(text: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for m in INSERT_RE.finditer(text):
        table = m.group(1).lower()
        cols = {c.strip().lower() for c in m.group(2).replace("\n", " ").split(",")}
        out.setdefault(table, set()).update(c for c in cols if c)
    return out


BIND_CTX = {
    "nodes": {
        "Inputs": {"CLIENT_ID": None, "ENGINE_ID": "E7", "MODE": "FOUNDATION",
                   "PASS": None, "MODEL_ROLE": "MODEL_RESEARCH", "RUN_CONTEXT": {}},
        "Build request": {"run_id": "r-1", "attempt": 1, "model_name": "m",
                          "totals": {"duration_ms": 1}},
        "Call provider": {"provider_failed": False},
    },
    "json": {"run_id": "r-1", "prompt_file": "p.md", "prompt_hash": "h",
             "model_name": "m", "ENGINE_ID": "E7", "input_tokens": 1,
             "output_tokens": 2, "raw": "x", "errors": ["e"],
             "transport_attempts": [], "human_output": "", "structured": {},
             "control": {}, "primary_tag": None, "secondary_handoffs": {}},
    "env": {},
}


def main() -> int:
    if shutil.which("node") is None:
        # Was a differently-worded line on STDERR, which run_all.sh's summary
        # never showed and no floor could grep -- so this suite could skip
        # its only real assertion and look identical to a full pass (V3).
        print()
        preflight.skip("node", "the workflow's SQL expressions cannot be "
                       "bound through n8n's own parameter algorithm, so NONE "
                       "of them was executed against the database.")
        print()
        return 0

    admin_dsn = os.environ["DATABASE_URL"]
    admin = psycopg.connect(admin_dsn, autocommit=True)
    admin.execute("delete from clients where external_ref like %s", (EXTERNAL_REF + "%",))

    runtime = psycopg.connect(_with_user(admin_dsn, "phi_runtime",
                                         _role_password("POSTGRES_RUNTIME_PASSWORD")))

    # ------------------------------------------------------------------
    print("\nhow n8n binds parameters, ON 2.11.4 (the part that is not SQL)")

    # These assertions describe n8n-nodes-base 2.11.2, which is what n8n
    # 2.11.4 ships and what this system runs on (D32). They are here so the
    # reason for an odd-looking binding form survives as a test rather than
    # as a comment somebody deletes -- and the first draft of that form was
    # deleted-by-accident in advance: it used an ARRAY branch that only
    # exists in later releases, and on 2.11.4 it bound ONE parameter where
    # the statement wanted twelve.

    # The check that would have caught it outright, applied to every node.
    doc0 = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    wf0 = doc0[0] if isinstance(doc0, list) else doc0
    pg_nodes = [n for n in wf0["nodes"] if n["type"].endswith("postgres")]

    arity_ok, arity_detail = True, []
    for n in pg_nodes:
        wanted = max((int(m) for m in re.findall(r"\$(\d+)", n["parameters"]["query"])),
                     default=0)
        _, bound = bind(n["name"], BIND_CTX)
        if len(bound) != wanted:
            arity_ok = False
            arity_detail.append(f"{n['name']}: binds {len(bound)}, statement needs {wanted}")
    check("every node binds exactly as many parameters as its statement uses",
          arity_ok, "; ".join(arity_detail))

    # The form itself. One resolvable per parameter, each a JSON literal.
    check("no node uses the array form, which 2.11.4 does not have",
          all("{{ [" not in (n["parameters"].get("options", {})
                             .get("queryReplacement") or "") for n in pg_nodes),
          str([n["name"] for n in pg_nodes
               if "{{ [" in (n["parameters"].get("options", {})
                             .get("queryReplacement") or "")]))

    _, v = bind("Handoff registry", {
        "nodes": {"Inputs": {"ENGINE_ID": "E7", "MODE": "FOUNDATION"}}})
    check("each parameter arrives as its own JSON literal",
          v == ['"E7"', '"FOUNDATION"'], str(v))

    _, v = bind("Open run", {
        "nodes": {"Inputs": {"CLIENT_ID": None, "ENGINE_ID": "E7", "MODE": "FOUNDATION",
                             "MODEL_ROLE": "MODEL_RESEARCH", "RUN_CONTEXT": {}}},
        "json": {"run_id": str(uuid.uuid4()), "prompt_file": "engine7.md",
                 "prompt_hash": "abc", "model_name": "m"}})
    # 2.11.2 turns a real null into the STRING 'null', which against a uuid
    # column is an error and against text is worse, because it succeeds. The
    # JSON literal `null` survives as four characters and SQL turns it back
    # into a real NULL with #>> '{}' -- proven at the database below, where
    # a knowledge-clock run opens with client_id IS NULL.
    check("a null binds as the JSON literal null, not a bare 'null'",
          v[0] == "null", repr(v[0]))
    check("...and every parameter is present, so the numbering cannot shift",
          len(v) == 12, str(len(v)))

    # An absent value is the trap: JSON.stringify(undefined) returns
    # undefined, not a string, and stringToArray('') drops it -- shifting
    # every parameter after it. `?? null` before stringify is what stops it.
    _, v = bind("Open run", {
        "nodes": {"Inputs": {"ENGINE_ID": "E7", "MODE": "FOUNDATION",
                             "MODEL_ROLE": "MODEL_RESEARCH"}},
        "json": {"run_id": str(uuid.uuid4()), "prompt_file": "e.md",
                 "prompt_hash": "abc", "model_name": "m"}})
    check("an ABSENT input still binds a parameter rather than vanishing",
          len(v) == 12 and v[0] == "null" and v[2] == "null", str(len(v)))

    # A free-text value with a comma. A bare string is not JSON, so 2.11.2
    # splits it on commas into several parameters and shifts everything
    # after it. As a JSON literal it is one value.
    _, v = bind("Dead letter", {
        "nodes": {"Inputs": {"CLIENT_ID": None, "ENGINE_ID": "E1"},
                  "Call provider": {"provider_failed": False},
                  "Build request": {"attempt": 2, "run_id": str(uuid.uuid4()),
                                    "totals": {"duration_ms": 10}}},
        "json": {"input_tokens": 1, "output_tokens": 2, "raw": "x",
                 "errors": ["CASE_VERSION: required, and ROUTE: bad"]}})
    check("a value containing a comma stays ONE parameter",
          len(v) == 10 and "," in v[6], f"{len(v)} params, [6]={v[6]!r}")
    check("...and the job_type keeps its literal prefix",
          v[8] == '"RUN_ENGINE_E1"', repr(v[8]))

    # An empty string is dropped by stringToArray; as a JSON literal it is
    # the two characters "" and survives.
    _, v = bind("Record success", {
        "nodes": {"Inputs": {"CLIENT_ID": None, "MODE": "INIT"},
                  "Build request": {"attempt": 1, "run_id": str(uuid.uuid4()),
                                    "totals": {"duration_ms": 1}}},
        "json": {"input_tokens": 1, "output_tokens": 2, "human_output": "",
                 "structured": {}, "control": {}, "primary_tag": None,
                 "secondary_handoffs": {}}})
    check("an EMPTY string binds as a parameter instead of disappearing",
          len(v) == 12 and v[6] == '""', f"{len(v)} params, [6]={v[6]!r}")

    print("\nthe columns each side writes")

    py = insert_columns((REPO / "scripts" / "run_engine.py").read_text(encoding="utf-8"))
    doc = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    wf = doc[0] if isinstance(doc, list) else doc
    n8 = insert_columns("\n".join(
        n["parameters"].get("query", "") for n in wf["nodes"]
        if n["type"].endswith("postgres")))

    for table in ("engine_runs", "engine_outputs", "cost_events", "dead_letter_jobs"):
        check(f"{table}: n8n writes the same columns as the reference",
              py.get(table) == n8.get(table),
              f"python only {sorted((py.get(table) or set()) - (n8.get(table) or set()))}, "
              f"n8n only {sorted((n8.get(table) or set()) - (py.get(table) or set()))}")

    # ------------------------------------------------------------------
    print("\nthe SQL, executed as phi_runtime")

    client = admin.execute(
        "insert into clients (external_ref, display_name, status) "
        "values (%s,'SQL node client','ACTIVE') returning client_id",
        (EXTERNAL_REF + "A",)).fetchone()[0]

    # The mode a REAL caller produces. E1 has one handoff mode -- SINGLE --
    # and its pass is a separate column; "PASS_A" is not a mode and no
    # caller emits it. The first draft of this suite used it anyway and then
    # hand-wrote a matching "reference" row, so the comparison proved that
    # two invented things agreed. It was the coherence trigger going strict
    # (020) that exposed it, not this suite.
    inputs = {"CLIENT_ID": str(client), "CASE_VERSION_ID": None, "CYCLE_ID": None,
              "ENGINE_ID": "E1", "PASS": "A", "MODE": "SINGLE",
              "MODEL_ROLE": "MODEL_ANALYSIS", "RUN_CONTEXT": {"reason": "test"}}
    run_id = str(uuid.uuid4())
    build = {"run_id": run_id, "prompt_file": "engine1_prevention.md",
             "prompt_hash": "f" * 12, "model_name": "claude-sonnet-5",
             "attempt": 1, "totals": {"duration_ms": 1234}}

    with runtime.transaction():
        run_node(runtime, "Open run", {"nodes": {"Inputs": inputs}, "json": build})
    row = admin.execute(
        "select engine, pass::text, engine_mode, client_id, prompt_hash, "
        "       schema_version, model_role, model_name, status::text "
        "  from engine_runs where run_id=%s", (run_id,)).fetchone()
    check("Open run inserts, so the coherence trigger accepted it", row is not None)
    check("...with the mode ON THE RUN, before any output exists",
          row is not None and row[2] == "SINGLE", str(row))

    # The reference row comes from the REFERENCE IMPLEMENTATION, not from a
    # second hand-written INSERT. Writing both by hand is how the first
    # draft of this suite compared two things it had invented.
    os.environ["LLM_API_KEY"] = ""
    ref_result = RE.run_engine(
        admin,
        RE.EngineRequest(engine="E1", pass_label="A", client_id=str(client),
                         structured_input={"CASE": "n8n SQL parity"},
                         model_role="MODEL_ANALYSIS",
                         run_context=inputs["RUN_CONTEXT"]))
    check("the reference implementation completed its own run",
          ref_result.status == "SUCCEEDED", str(ref_result.error))
    ref_id = ref_result.run_id
    ref = admin.execute(
        "select engine, pass::text, engine_mode, client_id, "
        "       schema_version, model_role, status::text "
        "  from engine_runs where run_id=%s", (ref_id,)).fetchone()
    row_cmp = admin.execute(
        "select engine, pass::text, engine_mode, client_id, "
        "       schema_version, model_role, status::text "
        "  from engine_runs where run_id=%s", (run_id,)).fetchone()
    # status differs by design -- the reference run completed, the workflow
    # row is still RUNNING until Record success -- so compare the fields
    # that describe WHAT was run, which is what parity is about.
    check("the reference and the workflow agree on the mode E1 runs in",
          ref[2] == row_cmp[2] == "SINGLE", f"{ref[2]} vs {row_cmp[2]}")
    check("the n8n row and the reference row agree field for field",
          row_cmp[:6] == ref[:6], f"{row_cmp[:6]} vs {ref[:6]}")

    # -- cost accounting, one row per physical attempt, priced ------------
    attempts = [{"ok": False, "ms": 40, "in_tok": 0, "out_tok": 0,
                 "error_class": "HTTPError503"},
                {"ok": True, "ms": 900, "in_tok": 68437, "out_tok": 12000,
                 "error_class": None}]
    with runtime.transaction():
        run_node(runtime, "Record attempts",
                 {"nodes": {"Inputs": inputs, "Build request": build},
                  "json": {"transport_attempts": attempts}, "env": {}})
    rows = admin.execute(
        "select operation::text, model_role, model_name, entity_type, entity_id, "
        "       workflow, input_tokens, output_tokens, cost_usd, price_source::text, "
        "       duration_ms, success, error_class "
        "  from cost_events where run_id=%s order by cost_event_id", (run_id,)).fetchall()
    check("one cost_events row per PHYSICAL attempt, the failure included",
          len(rows) == 2 and [r[11] for r in rows] == [False, True], str(len(rows)))
    check("the workflow name keeps its prefix",
          rows and rows[0][5] == "RUN_ENGINE_E1", str(rows[0][5] if rows else None))

    want_cost, want_source = pricing.price_call("claude-sonnet-5", 68437, 12000)
    check("n8n prices the call exactly as pricing.price_call() does",
          rows and float(rows[1][8]) == want_cost and rows[1][9] == want_source,
          f"{rows[1][8]},{rows[1][9]} vs {want_cost},{want_source}" if rows else "")

    unpriced = admin.execute(
        "select cost_usd, price_source::text from price_call('no-such-model', 10, 10)"
    ).fetchone()
    check("an unknown model is UNPRICED with a NULL cost, never zero",
          unpriced == (None, "UNPRICED"), str(unpriced))

    # -- the success path, which is the one most runs take ---------------
    ok_id = str(uuid.uuid4())
    ok_build = dict(build, run_id=ok_id)
    with runtime.transaction():
        run_node(runtime, "Open run", {"nodes": {"Inputs": inputs}, "json": ok_build})
    success = {"input_tokens": 68437, "output_tokens": 12000,
               "human_output": "the report",
               "structured": {"CASE_VERSION": "3", "_raw": "CASE_VERSION: 3"},
               "control": {"CASE_VERSION": 3, "ROUTE_NEXT": "E2"},
               "primary_tag": "PREVENTION_HANDOFF",
               "secondary_handoffs": {}}
    with runtime.transaction():
        run_node(runtime, "Record success",
                 {"nodes": {"Inputs": inputs, "Build request": ok_build}, "json": success})
    out = admin.execute(
        "select r.status::text, o.handoff_tag, o.handoff_mode, o.schema_valid, "
        "       o.structured->>'CASE_VERSION', o.control->>'ROUTE_NEXT' "
        "  from engine_runs r join engine_outputs o on o.run_id=r.run_id "
        " where r.run_id=%s", (ok_id,)).fetchone()
    check("Record success closes the run and stores all three outputs",
          out == ("SUCCEEDED", "PREVENTION_HANDOFF", "SINGLE", True, "3", "E2"), str(out))

    # -- the dead letter carries its client -----------------------------
    dl_ctx = {"nodes": {"Inputs": inputs, "Build request": build,
                        "Call provider": {"provider_failed": False}},
              "json": {"input_tokens": 10, "output_tokens": 20, "raw": "SENTINEL-RAW",
                       "errors": ["'CASE_VERSION' is a required property"]}}
    with runtime.transaction():
        runtime.execute("select set_client_scope(%s)", (client,))
        run_node(runtime, "Dead letter", dl_ctx)
    dl = admin.execute(
        "select client_id, job_type, entity_type, entity_id, failure_reason, "
        "       raw_payload->>'raw', attempts from dead_letter_jobs "
        " where entity_id=%s", (run_id,)).fetchone()
    err = admin.execute(
        "select status::text, error_class from engine_runs where run_id=%s",
        (run_id,)).fetchone()
    check("a contract failure is SCHEMA_INVALID, a transport failure is not",
          err == ("DEAD_LETTER", "SCHEMA_INVALID"), str(err))
    check("the dead letter records the client whose payload it holds",
          dl is not None and dl[0] == client, str(dl))
    check("...and the raw response is kept, not discarded",
          dl is not None and dl[5] == "SENTINEL-RAW", str(dl[5] if dl else None))

    # And it is scoped: another client cannot see it.
    other = admin.execute(
        "insert into clients (external_ref, display_name, status) "
        "values (%s,'Other','ACTIVE') returning client_id",
        (EXTERNAL_REF + "B",)).fetchone()[0]
    with runtime.transaction():
        runtime.execute("select set_client_scope(%s)", (other,))
        seen = runtime.execute(
            "select count(*) from dead_letter_jobs where entity_id=%s", (run_id,)
        ).fetchone()[0]
    check("under another client's scope that payload does not exist", seen == 0, str(seen))

    # -- a knowledge-clock run, which must have NO client ----------------
    clock_inputs = {"CLIENT_ID": None, "CASE_VERSION_ID": None, "CYCLE_ID": None,
                    "ENGINE_ID": "E7", "PASS": None, "MODE": "FOUNDATION",
                    "MODEL_ROLE": "MODEL_RESEARCH", "RUN_CONTEXT": {}}
    clock_id = str(uuid.uuid4())
    clock_build = dict(build, run_id=clock_id, prompt_file="engine7_research_practice.md")
    with runtime.transaction():
        run_node(runtime, "Open run", {"nodes": {"Inputs": clock_inputs}, "json": clock_build})
    got = admin.execute(
        "select client_id, engine_mode, pass::text from engine_runs where run_id=%s",
        (clock_id,)).fetchone()
    check("a knowledge-clock run opens with a NULL client and its mode recorded",
          got == (None, "FOUNDATION", "SINGLE"), str(got))

    check("no run the workflow opened is incoherent",
          admin.execute("select count(*) from v_engine_run_incoherent "
                        " where run_id in (%s,%s,%s)",
                        (run_id, ref_id, clock_id)).fetchone()[0] == 0)

    runtime.close()
    admin.execute("delete from clients where external_ref like %s", (EXTERNAL_REF + "%",))
    admin.execute("delete from engine_runs where run_id=%s", (clock_id,))

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

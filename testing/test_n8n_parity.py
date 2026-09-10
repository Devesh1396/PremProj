#!/usr/bin/env python3
"""RUN_ENGINE request parity: Python and n8n must be BYTE-IDENTICAL.

BUILD_GUIDE step 11, DECISIONS.md D26.

Not "behaviourally equivalent". The prompt hash plus the request IS the
call: two serializers that mean the same thing produce different model
behaviour and nothing downstream would notice. So the assertion is on
bytes -- the `<RUNTIME_INVOCATION>` envelope, key order, indentation,
whitespace, escaping, all of it.

One stored corpus, two implementations, identical output. The same shape
`test_contract_registry.py` uses for jsonschema-versus-ajv, and it is the
third time that pattern has been the right answer.

Both sides read the SAME registry rows: the Python side queries
`engine_handoffs` and passes the result to the JavaScript side, so neither
carries its own copy of what an engine owes.

Needs Node. SKIPS loudly when it is absent rather than passing quietly --
a check that cannot run must say so -- and CI has Node, so it is a real
gate there.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import psycopg
import load_handoffs as LH
import run_engine as RE

sys.path.insert(0, str(REPO / "testing"))
from test_contract_registry import find_ajv  # noqa: E402

FAILS: list[str] = []
CORPUS = REPO / "testing" / "fixtures" / "golden" / "run_engine_corpus.json"
JS_RUNNER = REPO / "testing" / "n8n_build_request.js"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def first_difference(a: str, b: str) -> str:
    """Where two strings diverge, with enough context to read it."""
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return (f"byte {i}: python {x!r} vs n8n {y!r}\n"
                    f"    python: ...{a[max(0, i - 40):i + 40]!r}\n"
                    f"    n8n   : ...{b[max(0, i - 40):i + 40]!r}")
    return f"same prefix, different length: python {len(a)} vs n8n {len(b)}"


def main() -> int:
    os.environ["LLM_API_KEY"] = ""
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    cases = corpus["cases"]

    print(f"\nthe golden corpus ({len(cases)} cases)")
    check("the corpus covers every engine",
          {c["engine"] for c in cases} == {"E1", "E2", "E3", "E4", "E5", "E6", "E7"},
          str(sorted({c["engine"] for c in cases})))
    check("...and every E6 mode",
          {c["mode"] for c in cases if c["engine"] == "E6"}
          == {"INIT", "REBUILD", "UPDATE"})
    check("...and all four E7 modes",
          {c["mode"] for c in cases if c["engine"] == "E7"}
          == {"CASE", "FOUNDATION", "UPDATE", "INBOX"})
    check("...and both Engine 1 passes",
          {c["pass_label"] for c in cases if c["engine"] == "E1"} == {"A", "B"})
    # These are the cases that exist because two serializers disagree. If
    # they are ever dropped the suite would pass while proving much less.
    for needed in ("non-ASCII", "integral floats", "empty containers",
                   "JSON escape", "nested", "large integers"):
        check(f"the corpus still covers: {needed}",
              any(needed.split()[0].lower() in c["name"].lower() for c in cases))

    # ------------------------------------------------------------------
    print("\nthe Python reference builds each request")
    resolved = []
    python_prompts = {}
    for case in cases:
        mode = LH.resolve_mode(case["engine"], case["mode"])
        expected = LH.expected(conn, case["engine"], mode)
        envelope = {
            "ENGINE": case["engine"],
            "MODE": mode,
            "PASS": case["pass_label"],
            "EXPECTED_HANDOFF_BLOCKS": [tag for tag, _r in expected],
            "REQUIRED_HANDOFF_BLOCKS": [tag for tag, r in expected if r],
            "CONTROL_BLOCK_REQUIRED": True,
        }
        python_prompts[case["name"]] = RE.build_user_prompt(
            envelope, case["structured_input"])
        resolved.append({**case, "resolved_mode": mode})
    check(f"all {len(cases)} requests built", len(python_prompts) == len(cases))

    # The envelope Python builds here must be the one run_engine builds. If
    # these drift, this suite would prove two test helpers agree.
    probe = RE.build_user_prompt(
        {"ENGINE": "E1", "MODE": "SINGLE", "PASS": "A",
         "EXPECTED_HANDOFF_BLOCKS": ["PREVENTION_INTELLIGENCE_HANDOFF"],
         "REQUIRED_HANDOFF_BLOCKS": ["PREVENTION_INTELLIGENCE_HANDOFF"],
         "CONTROL_BLOCK_REQUIRED": True},
        {"CASE_VERSION": 1})
    check("the reference's own builder is what is under test",
          probe.startswith(f"<{RE.ENVELOPE_TAG}>\n") and '"MODE": "SINGLE"' in probe)

    # ------------------------------------------------------------------
    print("\nn8n builds the same requests, byte for byte")
    node = shutil.which("node")
    # find_ajv() rather than a second copy of the same search. The copy that
    # used to live here did not honour AJV_MODULE_PATH, so setting it moved
    # one suite and not the other.
    ajv_modules = find_ajv()
    if node is None:
        print("  SKIP  node not available; the Python half above ran in full")
        print("        install Node to run the byte-parity comparison")
    else:
        expected_by_key = {}
        for engine, mode in LH.HANDOFFS:
            expected_by_key[f"{engine}/{mode}"] = [
                {"tag": tag, "required": req}
                for tag, req in LH.expected(conn, engine, mode)]
        proc = subprocess.run(
            [node, str(JS_RUNNER)],
            input=json.dumps({"cases": resolved,
                              "expected_handoffs": expected_by_key}),
            capture_output=True, text=True)
        if proc.returncode != 0:
            check("the n8n builder ran", False,
                  f"exit {proc.returncode}: {proc.stderr[:300]}")
        else:
            results = json.loads(proc.stdout)["results"]
            check("the n8n builder produced a request for every case",
                  len(results) == len(cases)
                  and not any("error" in r for r in results),
                  str([r.get("error") for r in results if "error" in r]))

            divergent = []
            for result in results:
                name = result["name"]
                if "error" in result:
                    continue
                if python_prompts[name] != result["user_prompt"]:
                    divergent.append(
                        f"{name}\n    "
                        + first_difference(python_prompts[name],
                                           result["user_prompt"]))
            check(f"all {len(cases)} requests are BYTE-IDENTICAL",
                  not divergent, "\n  ".join(divergent[:2]))

            # Byte-identical is only meaningful if the bytes are the right
            # ones. Spot-check the properties the parity is protecting.
            by_name = {r["name"]: r["user_prompt"] for r in results}
            check("the mode is in the request, per case",
                  all(f'"MODE": "{c["resolved_mode"]}"' in by_name[c["name"]]
                      for c in resolved))
            check("non-ASCII survives unescaped in BOTH",
                  "₹150" in by_name["non-ASCII: Python escaped these and "
                                    "JavaScript did not"]
                  and "\\u" not in by_name["non-ASCII: Python escaped these and "
                                           "JavaScript did not"])
            check("an integral float is written the same way by both",
                  '"weight_kg": 78,' in by_name[
                      "integral floats: Python wrote 78.0 and JavaScript wrote 78"])
            check("a non-integral float is untouched",
                  '"height_cm": 157.5' in by_name[
                      "integral floats: Python wrote 78.0 and JavaScript wrote 78"])
            check("the envelope opens the request in both",
                  all(p.startswith(f"<{RE.ENVELOPE_TAG}>\n") for p in by_name.values()))

    # ------------------------------------------------------------------
    print("\nboth implementations parse the same responses identically")
    # The other half of the request/response pair. The JS under test is
    # EXTRACTED FROM workflows/run_engine.json at run time -- a copy would
    # drift from the workflow it claims to test, and parity would then be
    # proving two test helpers agree.
    #
    # Every case is a way a real response goes wrong, and each maps to a
    # branch the reference already has.
    def response(engine, mode, *, control=None, handoffs=True, prose="the report"):
        blocks = RE.fixture_handoffs(engine, mode, {"case_version": 1}) if handoffs else {}
        body = prose + "\n\n"
        body += "".join(f"<{t}>\n{b}\n</{t}>\n\n" for t, b in blocks.items())
        if control is not None:
            body += f"<{RE.CONTROL_TAG}>\n{json.dumps(control, indent=2)}\n</{RE.CONTROL_TAG}>\n"
        return body

    good = {"CASE_VERSION": 1, "ENGINE_RUN_STATUS": "SUCCEEDED"}
    responses = [
        ("valid E6 INIT", "E6", "INIT", response("E6", "INIT", control=good)),
        ("valid E6 REBUILD, state plus delta", "E6", "REBUILD",
         response("E6", "REBUILD", control=good)),
        ("valid E7 CASE", "E7", "CASE", response("E7", "CASE", control=good)),
        ("valid E7 INBOX", "E7", "INBOX", response("E7", "INBOX", control=good)),
        ("invalid control: bad enum", "E1", "SINGLE",
         response("E1", "SINGLE",
                  control={"CASE_VERSION": 1, "ENGINE_RUN_STATUS": "MAYBE"})),
        ("invalid control: missing required field", "E1", "SINGLE",
         response("E1", "SINGLE", control={"ENGINE_RUN_STATUS": "SUCCEEDED"})),
        ("invalid control: routing with no reason", "E1", "SINGLE",
         response("E1", "SINGLE", control={**good, "ROUTING_RECOMMENDATION": "ENGINE2"})),
        ("no control block at all", "E1", "SINGLE",
         response("E1", "SINGLE", control=None)),
        ("control block is not JSON", "E1", "SINGLE",
         "prose\n<CONTROL_BLOCK>\n{not json}\n</CONTROL_BLOCK>"),
        ("missing the substantive handoff", "E6", "INIT",
         response("E6", "INIT", control=good, handoffs=False)),
        ("handoff present but empty", "E6", "INIT",
         f"prose\n<CASE_MEMORY_HANDOFF>\n\n</CASE_MEMORY_HANDOFF>\n"
         f"<{RE.CONTROL_TAG}>\n{json.dumps(good)}\n</{RE.CONTROL_TAG}>"),
        # The wrong block for the mode: an UPDATE that returned a full state
        # and no delta. Both must reject it, and neither may quietly accept
        # the state as though a delta had been asked for.
        # E6 UPDATE requires the DELTA and merely tolerates a state. A
        # response carrying only the state is the wrong block for the mode
        # and must fail -- my first version of this case emitted both,
        # which correctly passed and proved nothing.
        ("wrong mode/handoff: UPDATE returned only a state", "E6", "UPDATE",
         response("E6", "INIT", control=good)),
        ("fenced control block", "E1", "SINGLE",
         f"prose\n<PREVENTION_INTELLIGENCE_HANDOFF>\nCLIENT_PROFILE: x\n"
         f"</PREVENTION_INTELLIGENCE_HANDOFF>\n<{RE.CONTROL_TAG}>\n```json\n"
         f"{json.dumps(good)}\n```\n</{RE.CONTROL_TAG}>"),
        ("handoff with a value that looks like a key", "E1", "SINGLE",
         f"prose\n<PREVENTION_INTELLIGENCE_HANDOFF>\n"
         f"TOP_INTERVENTIONS: protein at breakfast\n"
         f"  IMPORTANT: this line is indented so it is a VALUE\n"
         f"Note: mixed case, also a value\n"
         f"NUTRITION_OBJECTIVES: fibre\n</PREVENTION_INTELLIGENCE_HANDOFF>\n"
         f"<{RE.CONTROL_TAG}>\n{json.dumps(good)}\n</{RE.CONTROL_TAG}>"),
        ("empty content: the whole budget went to reasoning", "E1", "SINGLE", ""),
    ]

    if node is None or ajv_modules is None:
        # The response parser IS the Validate control node, and that node
        # requires ajv. Without it the JavaScript returns an error per case
        # rather than a parse, and comparing a parse against an error dict
        # reports differences that are not differences -- then indexes a key
        # that is not there. Same shape as the pg_trgm floor: the degraded
        # branch has to be exercised, not assumed.
        missing = "node" if node is None else "ajv"
        print(f"  SKIP  {missing} not available; response parity not compared")
        print("        run `bash scripts/local_n8n.sh install` or set "
              "AJV_MODULE_PATH")
        print("        the Python half above ran in full; only the "
              "cross-implementation comparison was skipped")
    else:
        document, _hash = __import__("load_contracts").active(conn, RE.SCHEMA_VERSION)
        js_cases, py_results = [], {}
        for name, engine, mode, raw in responses:
            expected = LH.expected(conn, engine, mode)
            js_cases.append({
                "name": name, "raw": raw,
                "usage": {"prompt_tokens": 11, "completion_tokens": 22,
                          "total_tokens": 40},
                "expected_handoffs": [{"tag": t, "required": r} for t, r in expected],
            })
            # The Python reference's own functions, not a reimplementation.
            control = RE.extract_control(raw)
            errors = ([] if control is not None
                      else [f"no parseable <{RE.CONTROL_TAG}> block in response"])
            if control is not None:
                errors = RE.validate_control(conn, control)
            handoffs = {}
            for tag, _req in expected:
                parsed = RE.extract_handoff(raw, tag)
                if parsed is not None:
                    handoffs[tag] = parsed
            errors = errors + [
                f"no parseable <{tag}> block in response. The control block "
                "routes; this is the reasoning the next engine needs, and a "
                "response without it is not a completed run."
                for tag, req in expected if req and tag not in handoffs]
            boundaries = [raw.find(f"<{t}>") for t in
                          [RE.CONTROL_TAG] + [t for t, _ in expected]]
            first = min([b for b in boundaries if b >= 0], default=-1)
            primary = next((t for t, r in expected if r and t in handoffs),
                           next(iter(handoffs), None))
            py_results[name] = {
                "human_output": (raw[:first] if first >= 0 else raw).strip(),
                "control": control,
                "structured": handoffs.get(primary, {}) if primary else {},
                "primary_tag": primary,
                "secondary_handoffs": {t: b for t, b in handoffs.items()
                                       if t != primary},
                "errors": sorted(set(errors)),
                "valid": not errors,
                "input_tokens": 11,
                "output_tokens": 29,
            }

        proc = subprocess.run(
            [node, str(REPO / "testing" / "n8n_parse_response.js")],
            input=json.dumps({"cases": js_cases, "contract": document}),
            capture_output=True, text=True,
            env={**os.environ, **({"AJV_MODULE_PATH": ajv_modules}
                                  if ajv_modules else {})})
        if proc.returncode != 0:
            check("the workflow's parser ran", False,
                  f"exit {proc.returncode}: {proc.stderr[:400]}")
        else:
            js_results = {r["name"]: r for r in json.loads(proc.stdout)["results"]}
            broken = {n: r["error"] for n, r in js_results.items() if "error" in r}
            check("the workflow's parser handled every response", not broken,
                  "; ".join(f"{n}: {e}" for n, e in broken.items())[:300])

        if proc.returncode == 0 and not broken:
            # Only compare once every case actually produced a parse. An
            # error dict has none of the fields being compared, so indexing
            # into it raises rather than reporting -- which is how a missing
            # ajv turned a skippable condition into a crash.
            mismatches = []
            for name, _e, _m, _raw in responses:
                py, js = py_results[name], js_results.get(name, {})
                for field in ("human_output", "control", "structured",
                              "primary_tag", "secondary_handoffs", "valid",
                              "input_tokens", "output_tokens"):
                    if py[field] != js.get(field):
                        mismatches.append(
                            f"{name}.{field}: python={py[field]!r} "
                            f"n8n={js.get(field)!r}")
                if py["errors"] != js.get("errors"):
                    mismatches.append(
                        f"{name}.errors: python={py['errors']} n8n={js.get('errors')}")
            check(f"all {len(responses)} responses parse IDENTICALLY, field for field",
                  not mismatches, "\n  ".join(mismatches[:3])[:900])

            # The properties the parity is protecting, asserted directly.
            check("a valid response is valid in both",
                  py_results["valid E6 INIT"]["valid"]
                  and js_results["valid E6 INIT"]["valid"])
            check("a missing handoff fails in both",
                  not py_results["missing the substantive handoff"]["valid"]
                  and not js_results["missing the substantive handoff"]["valid"])
            check("an empty handoff block fails in both",
                  not py_results["handoff present but empty"]["valid"]
                  and not js_results["handoff present but empty"]["valid"])
            check("the wrong block for the mode fails in both",
                  not py_results[
                      "wrong mode/handoff: UPDATE returned only a state"]["valid"]
                  and not js_results[
                      "wrong mode/handoff: UPDATE returned only a state"]["valid"])
            check("...and the tolerated block is not mistaken for the required one",
                  py_results["wrong mode/handoff: UPDATE returned only a state"]
                  ["primary_tag"] == "CASE_MEMORY_HANDOFF")
            check("an indented or mixed-case line is a VALUE in both",
                  py_results["handoff with a value that looks like a key"]
                  ["structured"].get("TOP_INTERVENTIONS", "").count("\n") == 2)
            check("E6 REBUILD keeps the delta beside the state in both",
                  "CASE_MEMORY_DELTA" in py_results[
                      "valid E6 REBUILD, state plus delta"]["secondary_handoffs"]
                  and "CASE_MEMORY_DELTA" in js_results[
                      "valid E6 REBUILD, state plus delta"]["secondary_handoffs"])
            check("reasoning tokens are billed as output in both",
                  py_results["valid E6 INIT"]["output_tokens"] == 29
                  and js_results["valid E6 INIT"]["output_tokens"] == 29)

    # ------------------------------------------------------------------
    print("\ntransport retry: same semantics as the reference (D29)")
    # The HTTP node was configured with six retries at a FIXED 2000 ms while
    # its own note described exponential backoff. Python does exponential +
    # jitter + Retry-After, and the difference matters most where it is
    # least visible: Step 16's Knowledge Factory, at concurrency 3, on a
    # 2 vCPU box, where fixed-interval retries from concurrent workers all
    # return at the same instant and re-overload a provider already
    # shedding load.
    #
    # Deterministic. No network, no paid calls: fetch is stubbed, the
    # backoff base is set tiny through the same env var the node reads, and
    # setTimeout is captured rather than honoured, so the SHAPE of the
    # delays is what is asserted.
    retry_cases = [
        {"name": "success first time", "sequence": [{"status": 200}]},
        {"name": "429 then success",
         "sequence": [{"status": 429}, {"status": 200}]},
        {"name": "503 twice then success",
         "sequence": [{"status": 503}, {"status": 503}, {"status": 200}]},
        {"name": "400 is never retried", "sequence": [{"status": 400}]},
        {"name": "401 is never retried", "sequence": [{"status": 401}]},
        {"name": "404 is never retried", "sequence": [{"status": 404}]},
        {"name": "network error is retried",
         "sequence": [{"network_error": True}, {"status": 200}]},
        {"name": "attempts are bounded", "sequence": [{"status": 503}],
         "max_attempts": 4},
        {"name": "Retry-After is honoured",
         "sequence": [{"status": 429, "headers": {"Retry-After": "7"}},
                      {"status": 200}]},
        {"name": "an unparseable Retry-After falls back to backoff",
         "sequence": [{"status": 429, "headers": {"Retry-After": "soon"}},
                      {"status": 200}], "backoff_base": 100},
        {"name": "backoff grows with the attempt",
         "sequence": [{"status": 503}, {"status": 503}, {"status": 503},
                      {"status": 200}], "backoff_base": 10},
    ]

    if node is None:
        print("  SKIP  node not available; retry semantics not compared")
    else:
        proc = subprocess.run(
            [node, str(REPO / "testing" / "n8n_retry.js")],
            input=json.dumps({"cases": retry_cases}),
            capture_output=True, text=True)
        if proc.returncode != 0:
            check("the retry harness ran", False,
                  f"exit {proc.returncode}: {proc.stderr[:400]}")
        else:
            r = {x["name"]: x for x in json.loads(proc.stdout)["results"]}
            check("every retry case ran",
                  not [x for x in r.values() if "error" in x],
                  str([x.get("error") for x in r.values() if "error" in x])[:300])

            check("a success makes exactly one call",
                  r["success first time"]["calls"] == 1
                  and not r["success first time"]["result"]["provider_failed"])
            check("a 429 is retried and then succeeds",
                  r["429 then success"]["calls"] == 2
                  and not r["429 then success"]["result"]["provider_failed"])
            check("a 503 is retried until it succeeds",
                  r["503 twice then success"]["calls"] == 3)
            for status in ("400", "401", "404"):
                name = f"{status} is never retried"
                check(f"a {status} is not retried at all",
                      r[name]["calls"] == 1 and r[name]["waits"] == []
                      and r[name]["result"]["provider_failed"],
                      f'{r[name]["calls"]} calls, waits {r[name]["waits"]}')
            check("a network error IS retried",
                  r["network error is retried"]["calls"] == 2)
            check("attempts are bounded by the configured maximum",
                  r["attempts are bounded"]["calls"] == 4,
                  str(r["attempts are bounded"]["calls"]))
            check("...and the last attempt does not sleep afterwards",
                  len(r["attempts are bounded"]["waits"]) == 3)

            # Retry-After wins over our own backoff, exactly.
            check("Retry-After is honoured to the second",
                  r["Retry-After is honoured"]["waits"] == [7.0],
                  str(r["Retry-After is honoured"]["waits"]))
            # backoff_base 100 would give a huge jittered delay; an
            # unparseable header must fall back to it, not to zero.
            fallback = r["an unparseable Retry-After falls back to backoff"]["waits"]
            check("an unparseable Retry-After falls back to backoff, never to zero",
                  len(fallback) == 1 and fallback[0] > 0, str(fallback))

            # Exponential with jitter: each delay sits inside
            # [0.5, 1.5] x base**attempt, capped at 60.
            waits = r["backoff grows with the attempt"]["waits"]
            check("backoff is exponential, jittered and capped",
                  len(waits) == 3
                  and all(0.5 * min(60, 10 ** (i + 1)) <= w
                          <= 1.5 * min(60, 10 ** (i + 1)) and w <= 60
                          for i, w in enumerate(waits)),
                  str(waits))
            check("...and the cap actually binds",
                  waits[-1] <= 60, str(waits[-1]))

            # Every physical attempt is recorded, failures included.
            logged = r["503 twice then success"]["result"]["transport_attempts"]
            check("every physical attempt is recorded, failures included",
                  len(logged) == 3 and [a["ok"] for a in logged] == [False, False, True],
                  str(logged))
            check("...each with the error class that caused it",
                  logged[0]["error_class"] == "HTTPError503", str(logged[0]))

            # The reference's rule: transport failures never spend a repair
            # attempt. The node returns provider_failed, and the workflow's
            # own dead-letter branch handles it -- the repair loop is not
            # entered at all.
            check("a transport failure never consumes a repair attempt",
                  r["400 is never retried"]["result"]["provider_failed"] is True
                  and r["400 is never retried"]["result"]["error_class"]
                  == "HTTPError400")

            # Python's classification, on the same statuses, must agree.
            import urllib.error as _ue
            for status, want in ((429, True), (503, True), (500, True),
                                 (408, True), (400, False), (401, False),
                                 (404, False)):
                same = RE._is_retryable(
                    _ue.HTTPError("http://x", status, "", {}, None)) is want
                if not same:
                    check(f"Python agrees {status} is "
                          f"{'retryable' if want else 'permanent'}", False)
            check("Python and n8n classify the same statuses the same way", True)

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

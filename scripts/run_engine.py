#!/usr/bin/env python3
"""RUN_ENGINE — the single engine execution path.

Every engine call in the system goes through here. There is no per-engine
copy of this logic.

Responsibilities:
  1. Load the prompt file and hash it (provenance for the reasoning itself)
  2. Build the request from structured input
  3. Call the model, or a fixture provider when no API key is configured
  4. Validate the control block against the orchestration contract
  5. Retry once with a repair prompt on invalid structure
  6. Dead-letter after bounded retries; never insert malformed output
  7. Record the run, the outputs and the cost

This is the reference implementation. The n8n subworkflow mirrors it; both
are validated by the same test suite, so behaviour cannot drift silently.

Fixture mode is deliberate, per the master specification: when blocked by a
missing API key, build everything around the integration and continue.
Set LLM_API_KEY to switch to a live provider.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import psycopg
from jsonschema import Draft202012Validator

import pricing

REPO = Path(__file__).resolve().parent.parent
PROMPTS_DIR = REPO / "prompts"
SCHEMA_PATH = REPO / "schemas" / "orchestration" / "control_contract.v1.json"

MAX_ATTEMPTS = 3          # initial + repair + final
CONTROL_TAG = "CONTROL_BLOCK"

ENGINE_PROMPTS = {
    "E1": "engine1_prevention.md",
    "E2": "engine2_behaviour.md",
    "E3": "engine3_nutrition.md",
    "E4": "engine4_progress.md",
    "E5": "engine5_communication.md",
    "E6": "engine6_memory.md",
    "E7": "engine7_research_practice.md",
}


class PromptMissing(RuntimeError):
    """Raised when a canonical prompt file is absent.

    Deliberately fatal. Running an engine on a stub would produce output
    that looks plausible and is not traceable to any specification.
    """


@dataclass
class EngineRequest:
    engine: str
    structured_input: dict[str, Any]
    client_id: str | None = None
    case_version_id: str | None = None
    cycle_id: str | None = None
    pass_label: str = "SINGLE"
    model_role: str = "MODEL_ANALYSIS"
    run_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class EngineResult:
    run_id: str
    status: str
    control: dict[str, Any] | None
    human_output: str | None
    structured: dict[str, Any] | None
    attempts: int
    error: str | None = None


# ---------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------

_prompt_cache: dict[str, tuple[str, str]] = {}


def load_prompt(engine: str) -> tuple[str, str, str]:
    """Return (filename, content, sha256). Cached; content hash is provenance."""
    filename = ENGINE_PROMPTS[engine]
    if filename in _prompt_cache:
        content, digest = _prompt_cache[filename]
        return filename, content, digest

    path = PROMPTS_DIR / filename
    if not path.exists():
        raise PromptMissing(
            f"{path} is missing. Place the canonical master specification there. "
            "RUN_ENGINE will not fall back to a stub: an engine output that "
            "cannot be traced to a specification is worse than no output."
        )
    content = path.read_text()
    if not content.strip():
        raise PromptMissing(f"{path} is empty.")
    digest = hashlib.sha256(content.encode()).hexdigest()
    _prompt_cache[filename] = (content, digest)
    return filename, content, digest


# ---------------------------------------------------------------------
# Control block extraction and validation
# ---------------------------------------------------------------------

_validator: Draft202012Validator | None = None


def validator() -> Draft202012Validator:
    global _validator
    if _validator is None:
        _validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))
    return _validator


def extract_control(raw: str) -> dict[str, Any] | None:
    """Pull the JSON control block out of a model response.

    The engines produce a long human-readable report plus a machine block.
    Only the machine block is parsed here; the report is stored as-is.
    """
    open_tag, close_tag = f"<{CONTROL_TAG}>", f"</{CONTROL_TAG}>"
    if open_tag not in raw or close_tag not in raw:
        return None
    body = raw.split(open_tag, 1)[1].split(close_tag, 1)[0].strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def validate_control(control: dict[str, Any]) -> list[str]:
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
        for e in validator().iter_errors(control)
    ]


def repair_instruction(errors: list[str]) -> str:
    listed = "\n".join(f"  - {e}" for e in errors[:12])
    return (
        "Your previous response did not produce a valid control block.\n"
        f"Problems:\n{listed}\n\n"
        f"Re-emit the complete response. The <{CONTROL_TAG}> block must contain "
        "valid JSON conforming to the orchestration contract. Do not change your "
        "clinical reasoning; only correct the structured block."
    )


# ---------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------

Provider = Callable[[str, str, dict], tuple[str, int, int]]


def fixture_provider(system_prompt: str, user_prompt: str, params: dict) -> tuple[str, int, int]:
    """Deterministic stand-in used when no API key is configured.

    Returns a well-formed response so orchestration, validation, persistence
    and routing can all be exercised without a provider.
    """
    engine = params.get("engine", "E1")
    control = {
        "CASE_VERSION": params.get("case_version", 1),
        "ENGINE_RUN_STATUS": "SUCCEEDED",
        "REVIEW_REQUIRED": engine in ("E1", "E4"),
        "HOLD_FLAG_PRESENT": False,
        "MEDICAL_COORDINATION_PRESENT": False,
        "ROUTING_RECOMMENDATION": "NONE",
        "NEXT_ENGINE": {"E1": "E7", "E7": "E1", "E2": "E3", "E3": "REVIEW"}.get(engine, "NONE"),
        "LOOP_COUNT": 0,
    }
    if engine == "E1" and params.get("pass_label") == "A":
        control["RESEARCH_QUESTIONS"] = [
            "Interventions targeting hepatic fat that may act independently of large weight loss",
            "Vegetarian strategies raising protein without adding substantial energy",
        ]
        control["NORMALIZATION_PHRASES"] = [
            "large post-meal glucose excursions",
            "refined evening carbohydrate intake",
            "low muscle stimulus",
        ]
    if engine == "E7":
        control["KNOWLEDGE_SUFFICIENT"] = True
        control["LIVE_RESEARCH_REQUIRED"] = False

    body = (
        f"(fixture output for {engine})\n\n"
        f"<{CONTROL_TAG}>\n{json.dumps(control, indent=2)}\n</{CONTROL_TAG}>\n"
    )
    # Rough character-based estimate covering the WHOLE request. It counted
    # only the system prompt before, which silently omitted the structured
    # client payload -- the half that actually varies per case, and the half
    # the D5 call-size question is about. Still an estimate, and labelled as
    # one by the measurement report: only a live provider returns real
    # token counts.
    return body, (len(system_prompt) + len(user_prompt)) // 4, len(body) // 4


def openai_compatible_provider(system_prompt: str, user_prompt: str, params: dict):
    """Live provider. Deliberately thin; the interesting logic is above."""
    import urllib.request

    base = os.environ["LLM_BASE_URL"].rstrip("/")
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps({
            "model": params["model_name"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": params.get("temperature", 0.2),
        }).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ['LLM_API_KEY']}",
        },
    )
    with urllib.request.urlopen(req, timeout=params.get("timeout", 300)) as resp:
        payload = json.loads(resp.read())
    usage = payload.get("usage", {})
    return (
        payload["choices"][0]["message"]["content"],
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
    )


def select_provider() -> tuple[Provider, str]:
    key = os.environ.get("LLM_API_KEY", "").strip()
    if key and key != "change_me":
        return openai_compatible_provider, "live"
    return fixture_provider, "fixture"


# ---------------------------------------------------------------------
# RUN_ENGINE
# ---------------------------------------------------------------------

def run_engine(conn: psycopg.Connection, req: EngineRequest) -> EngineResult:
    prompt_file, prompt_content, prompt_hash = load_prompt(req.engine)
    provider, mode = select_provider()
    model_name = os.environ.get(req.model_role, "") or f"fixture:{mode}"

    run_id = str(uuid.uuid4())
    conn.execute(
        """insert into engine_runs
             (run_id, client_id, case_version_id, cycle_id, engine, pass,
              prompt_file, prompt_hash, schema_version, model_role, model_name,
              model_params, status, started_at)
           values (%s,%s,%s,%s,%s,%s,%s,%s,'control_contract.v1',%s,%s,%s,'RUNNING',now())""",
        (run_id, req.client_id, req.case_version_id, req.cycle_id, req.engine,
         req.pass_label, prompt_file, prompt_hash, req.model_role, model_name,
         json.dumps(req.run_context)),
    )

    user_prompt = json.dumps(req.structured_input, indent=2)
    params = {
        "engine": req.engine,
        "pass_label": req.pass_label,
        "model_name": model_name,
        "case_version": req.structured_input.get("CASE_VERSION", 1),
    }

    attempts = 0
    errors: list[str] = []
    raw = ""
    control: dict[str, Any] | None = None
    # engine_runs has carried input_tokens / output_tokens / duration_ms
    # since 004 and nothing ever wrote them. They are the per-run totals
    # across every attempt, which is what a repair retry actually cost.
    totals = {"input_tokens": 0, "output_tokens": 0, "duration_ms": 0}

    while attempts < MAX_ATTEMPTS:
        attempts += 1
        started = time.time()
        try:
            raw, in_tok, out_tok = provider(prompt_content, user_prompt, params)
        except Exception as exc:
            errors = [f"provider error: {exc}"]
            _record_cost(conn, req, model_name, run_id, 0, 0,
                         int((time.time() - started) * 1000), False, type(exc).__name__)
            continue

        duration_ms = int((time.time() - started) * 1000)
        _record_cost(conn, req, model_name, run_id, in_tok, out_tok, duration_ms, True, None)
        totals["input_tokens"] += in_tok
        totals["output_tokens"] += out_tok
        totals["duration_ms"] += duration_ms

        control = extract_control(raw)
        if control is None:
            errors = [f"no parseable <{CONTROL_TAG}> block in response"]
        else:
            errors = validate_control(control)
            if not errors:
                break

        conn.execute(
            "update engine_runs set status='REPAIR_RETRY', attempts=%s where run_id=%s",
            (attempts, run_id),
        )
        user_prompt = json.dumps(req.structured_input, indent=2) + "\n\n" + repair_instruction(errors)

    if errors or control is None:
        # Malformed output is never inserted into the knowledge or case
        # tables. It goes to the dead-letter queue for inspection.
        conn.execute(
            """update engine_runs
                  set status='DEAD_LETTER', attempts=%s, completed_at=now(),
                      input_tokens=%s, output_tokens=%s, duration_ms=%s,
                      error_class='SCHEMA_INVALID', error_detail=%s
                where run_id=%s""",
            (attempts, totals["input_tokens"], totals["output_tokens"],
             totals["duration_ms"], "; ".join(errors)[:2000], run_id),
        )
        conn.execute(
            """insert into dead_letter_jobs
                 (job_type, entity_type, entity_id, failure_reason, raw_payload, attempts)
               values (%s,'engine_run',%s,%s,%s,%s)""",
            (f"RUN_ENGINE_{req.engine}", run_id,
             "; ".join(errors)[:2000], json.dumps({"raw": raw[:8000]}), attempts),
        )
        return EngineResult(run_id, "DEAD_LETTER", None, raw, None, attempts,
                            "; ".join(errors))

    human_output = raw.split(f"<{CONTROL_TAG}>", 1)[0].strip()

    conn.execute(
        """update engine_runs
              set status='SUCCEEDED', attempts=%s, completed_at=now(),
                  input_tokens=%s, output_tokens=%s, duration_ms=%s
            where run_id=%s""",
        (attempts, totals["input_tokens"], totals["output_tokens"],
         totals["duration_ms"], run_id),
    )
    conn.execute(
        """insert into engine_outputs (run_id, human_output, structured, control, schema_valid)
           values (%s,%s,%s,%s,true)""",
        (run_id, human_output, json.dumps(req.structured_input.get("_echo", {})),
         json.dumps(control)),
    )
    return EngineResult(run_id, "SUCCEEDED", control, human_output, None, attempts)


def _record_cost(conn, req: EngineRequest, model_name: str, run_id: str,
                 in_tok: int, out_tok: int, ms: int, ok: bool, err: str | None) -> None:
    # entity_id is text because it is polymorphic across the system: client
    # ids, domain ids, strategy ids, document ids. Callers must stringify.
    # Passing a raw UUID inserts fine via assignment cast but then fails
    # every "entity_id = $1" comparison with "operator does not exist".
    #
    # run_id is separate and additional (migration 008). entity_id stays the
    # client, because without run_id the two Engine 1 calls in a cycle --
    # Pass A and Pass B, which share a client, a cycle and a prompt hash --
    # cannot be told apart in the cost table, and those are precisely the
    # two calls D5 asks us to measure.
    cost_usd, price_source = pricing.price_call(model_name, in_tok, out_tok)
    conn.execute(
        """insert into cost_events
             (operation, model_role, model_name, entity_type, entity_id, run_id,
              workflow, input_tokens, output_tokens, cost_usd, price_source,
              duration_ms, success, error_class)
           values ('ENGINE_RUN',%s,%s,'client',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (req.model_role, model_name,
         str(req.client_id) if req.client_id is not None else None,
         run_id, f"RUN_ENGINE_{req.engine}", in_tok, out_tok,
         cost_usd, price_source, ms, ok, err),
    )


if __name__ == "__main__":
    import sys
    provider, mode = select_provider()
    print(f"RUN_ENGINE ready. provider mode: {mode}")
    missing = [f for f in ENGINE_PROMPTS.values() if not (PROMPTS_DIR / f).exists()]
    if missing:
        print(f"prompt files absent ({len(missing)}): {', '.join(missing)}")
        print("RUN_ENGINE will raise PromptMissing for these engines until the "
              "canonical specifications are placed in prompts/.")
        sys.exit(0)
    print("all seven prompt files present")

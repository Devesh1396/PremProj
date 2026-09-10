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

import contextlib
import json
import os
import re
import random
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import psycopg
from jsonschema import Draft202012Validator

import load_contracts
import load_handoffs
import load_prompts
import pricing

REPO = Path(__file__).resolve().parent.parent

MAX_ATTEMPTS = 3          # initial + repair + final

# A 503 is not a malformed answer. Transport failures get their own budget
# and their own backoff, so one overloaded-provider window cannot silently
# spend the repair retries that exist for an invalid control block. Without
# this the three repair attempts fire within seconds of each other and a
# live run dies on a transient that a few seconds of waiting would clear.
# A provider demand spike lasts longer than a few seconds -- Gemini answers
# "This model is currently experiencing high demand" with a 503 for minutes
# at a time -- so the budget has to be minutes, not seconds. Six attempts
# backing off 2/4/8/16/32s (jittered, capped) rides out roughly a minute of
# unavailability. Env-tunable because the right ceiling is a property of the
# provider and the run, not of this code: a knowledge batch may want to give
# up early where a single measurement run should wait.
MAX_TRANSPORT_ATTEMPTS = int(os.environ.get("LLM_TRANSPORT_MAX_ATTEMPTS", "6"))
TRANSPORT_BACKOFF_BASE = 2.0    # seconds, exponentiated per attempt
TRANSPORT_BACKOFF_CAP = 60.0    # never sleep longer than this between tries
RETRYABLE_HTTP_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

CONTROL_TAG = "CONTROL_BLOCK"
# What the runtime is asking for on THIS call. Not part of any
# engine specification: the prompts say what a mode means, this says
# which one was requested.
ENVELOPE_TAG = "RUNTIME_INVOCATION"

# The engine -> specification map and the PromptMissing class live in
# load_prompts.py, which owns the registry. Keeping a second copy here
# would be two dictionaries that must agree, which is one dictionary and a
# latent bug. Re-exported so existing callers keep working.
ENGINE_PROMPTS = load_prompts.ENGINE_PROMPTS
PromptMissing = load_prompts.PromptMissing
HandoffMissing = load_handoffs.HandoffMissing
HandoffModeUnknown = load_handoffs.HandoffModeUnknown


class ModelRoleUnset(RuntimeError):
    """Raised when a live run has no model configured for its role.

    Without this the empty role fell through to the fixture placeholder and
    that placeholder was sent to the provider as the model id, so a missing
    MODEL_ANALYSIS surfaced as an opaque 400 from the API rather than as the
    configuration error it is.
    """


@dataclass
class EngineRequest:
    engine: str
    structured_input: dict[str, Any]
    client_id: str | None = None
    case_version_id: str | None = None
    cycle_id: str | None = None
    pass_label: str = "SINGLE"
    # What the engine was asked to do, which decides WHICH substantive
    # handoff it owes (D24). E1-E5 have one mode and default to it; E6 and
    # E7 have no safe default, because guessing means expecting a delta
    # where a full state was needed, or the reverse.
    mode: str | None = None
    model_role: str = "MODEL_ANALYSIS"
    run_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class EngineResult:
    run_id: str
    status: str
    control: dict[str, Any] | None
    human_output: str | None
    # The engine's substantive reasoning, parsed from its handoff block.
    # NEVER the control block: that is `control`, it is for routing and
    # gating, and the two are not interchangeable (D24).
    structured: dict[str, Any] | None
    attempts: int
    error: str | None = None
    handoff_tag: str | None = None
    handoff_mode: str | None = None
    # Registered blocks the same response carried beyond the primary one,
    # keyed by tag. E6 rebuilding state may also emit its delta.
    secondary_handoffs: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------

def load_prompt(conn: psycopg.Connection, engine: str) -> tuple[str, str, str]:
    """Return (filename, content, sha256) for an engine's active prompt.

    Read from `engine_prompts`, not from the working tree (D23). The n8n
    port issues the identical SELECT, so the two implementations cannot
    disagree about what an engine ran -- there is nothing for them to
    disagree about.

    Deliberately NOT cached in this process. A cache is what makes
    "prompts/ changed between Pass A and Pass B" survivable rather than
    loud, and it would let a long-lived worker keep serving a
    specification that has been superseded. The read is one indexed row.
    """
    return load_prompts.active(conn, engine)


# ---------------------------------------------------------------------
# Control block extraction and validation
# ---------------------------------------------------------------------

SCHEMA_VERSION = "control_contract.v1"

# The contract's ContractMissing, re-exported alongside PromptMissing.
ContractMissing = load_contracts.ContractMissing

# Keyed by document hash, not by schema_version. A cache keyed by version
# would keep serving a superseded contract after a load, which is exactly
# the failure mode 012 exists to make impossible; keying by hash means a
# new document is a new key and the old compiled validator is simply never
# asked for again. Compiling a 21-property schema is cheap; doing it per
# attempt on a 300-second engine call is not worth measuring.
_validators: dict[str, Draft202012Validator] = {}


def validator(conn: psycopg.Connection) -> Draft202012Validator:
    """The compiled validator for the active contract (D23, migration 012).

    Read from orchestration_contracts, not from the working tree. The n8n
    port issues the identical SELECT and hands the same document to ajv, so
    the two implementations cannot disagree about WHICH schema they are
    enforcing.
    """
    document, digest = load_contracts.active(conn, SCHEMA_VERSION)
    if digest not in _validators:
        _validators[digest] = Draft202012Validator(document)
    return _validators[digest]


# A handoff block is line-oriented KEY: text, not JSON, and that is the
# prompts' format rather than a choice made here. The parser therefore has
# to answer one question well: which lines are keys and which are the
# continuation of the previous value.
#
# The rule is a key is an ALL-CAPS identifier followed by a colon AT COLUMN
# ZERO. It is deliberately narrow, because the alternatives fail on real
# content:
#
#   "Note: take with food"      not a key -- mixed case
#   "  IMPORTANT: ..."          not a key -- indented, so it is a value line
#   "- STRATEGY_A: ..."         not a key -- prefixed
#   "HbA1c: 6.1"                not a key -- lowercase letters
#
# NOTHING IS DISCARDED. `_raw` keeps the block verbatim, so a value this
# parser splits wrongly is still recoverable, and anything before the first
# key is kept as `_preamble` rather than dropped. Unknown keys are kept as
# they come; the registry says which BLOCK is expected, never which fields
# are permitted inside it.
_HANDOFF_KEY = re.compile(r"^([A-Z][A-Z0-9_]{2,}):[ \t]*(.*)$")


def parse_handoff_block(body: str) -> dict[str, Any]:
    """A line-oriented handoff block as a dict. Lossless by construction."""
    fields: dict[str, Any] = {}
    order: list[str] = []
    preamble: list[str] = []
    current: str | None = None

    for line in body.splitlines():
        match = _HANDOFF_KEY.match(line)
        if match:
            current = match.group(1)
            first = match.group(2).strip()
            if current in fields:
                # A repeated key is a malformed block, not a reason to lose
                # half of it. Keep both, in order.
                fields[current] = f"{fields[current]}\n{first}".strip()
            else:
                fields[current] = first
                order.append(current)
            continue
        if current is None:
            if line.strip():
                preamble.append(line)
            continue
        fields[current] = (f"{fields[current]}\n{line}".strip()
                           if fields[current] else line.strip())

    # Lowercase, so these can never collide with a real ALL-CAPS field.
    fields["_field_order"] = order
    fields["_raw"] = body
    if preamble:
        fields["_preamble"] = "\n".join(preamble)
    return fields


def extract_handoff(raw: str, tag: str) -> dict[str, Any] | None:
    """The parsed `<tag>` block from a model response, or None if absent."""
    open_tag, close_tag = f"<{tag}>", f"</{tag}>"
    if open_tag not in raw or close_tag not in raw:
        return None
    body = raw.split(open_tag, 1)[1].split(close_tag, 1)[0]
    # A model that fenced the block is still emitting the block.
    stripped = body.strip()
    if stripped.startswith("```"):
        body = stripped.split("\n", 1)[1].rsplit("```", 1)[0]
    parsed = parse_handoff_block(body)
    # A block with a tag and nothing usable inside it is not a handoff. It
    # must fail like an absent one rather than record an empty dict as
    # though the engine had reasoned.
    if not [k for k in parsed if not k.startswith("_")]:
        return None
    return parsed


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


def _type_names(value: Any) -> str:
    """A JSON Schema `type` as a stable string, list or not."""
    if isinstance(value, (list, tuple)):
        return ", ".join(sorted(str(v) for v in value))
    return str(value)


def format_violation(field: str, keyword: str, detail: Any) -> str:
    """The ONE wording a contract violation has (D26).

    Deliberately not jsonschema's message, and deliberately not ajv's.
    Those two libraries phrase the same violation differently --

        jsonschema  "'CASE_VERSION' is a required property"
        ajv         "must have required property 'CASE_VERSION'"

    -- and this string is not cosmetic. It is persisted to
    `engine_runs.error_detail` AND it is what `repair_instruction()` sends
    the model on attempt two. Two implementations disagreeing here means
    n8n asks the model to fix something in different words than the
    reference does, on the one retry that matters, with nothing to notice.

    So the format is ours, both sides build it from their own library's
    STRUCTURED error data, and the parity suite proves they agree.
    """
    if keyword == "required":
        reason = "required property missing"
    elif keyword == "enum":
        reason = "not one of " + ", ".join(sorted(str(v) for v in detail))
    elif keyword == "type":
        reason = f"expected type {_type_names(detail)}"
    elif keyword == "const":
        reason = f"must be {json.dumps(detail)}"
    elif keyword == "minLength":
        reason = ("must not be empty" if detail == 1
                  else f"shorter than {detail} characters")
    elif keyword == "additionalProperties":
        reason = "not permitted by the contract"
    else:
        reason = str(keyword)
    return f"{field}: {reason}"


def validate_control(conn: psycopg.Connection, control: dict[str, Any]) -> list[str]:
    """Contract violations in a control block, in the shared wording.

    Sorted and de-duplicated, so the same block produces the same message
    list every time. Neither library guarantees iteration order, and an
    unstable order makes a repair prompt differ between attempts for no
    reason -- and makes the parity assertion flap.
    """
    violations = set()
    for err in validator(conn).iter_errors(control):
        keyword = err.validator
        if keyword in ("if", "then", "else", "allOf", "anyOf", "oneOf", "not"):
            # Applicator keywords are containers. They name no field, and
            # their child errors carry the real blame.
            continue
        if keyword == "required":
            field = err.message.split("'")[1]
        elif keyword == "additionalProperties":
            parts = err.message.split("'")
            field = parts[1] if len(parts) > 1 else "(root)"
        elif err.absolute_path:
            field = str(list(err.absolute_path)[0])
        else:
            field = "(root)"
        violations.add(format_violation(field, keyword, err.validator_value))
    return sorted(violations)


def _canonical(value: Any) -> Any:
    """Normalize the two things Python and JavaScript serialize differently.

    Measured, not guessed: over a corpus covering ASCII, non-ASCII, nested
    structures, empty containers, big integers and every JSON escape,
    `json.dumps(..., indent=2, ensure_ascii=False)` and
    `JSON.stringify(..., null, 2)` agree byte for byte on everything except
    INTEGRAL FLOATS. Python writes 78.0; JavaScript writes 78, because JSON
    has one number type and JS cannot tell them apart once parsed.

    So integral floats become ints here. A weight of 78.0 kg and a weight
    of 78 kg are the same measurement, and byte-identical requests are
    worth more than a trailing zero -- the prompt hash plus the request IS
    the call, and two serializers that "mean the same thing" produce
    different model behaviour with nothing to notice.

    2**53 is JavaScript's exact-integer limit. Above it the conversion
    would not survive the round trip, so it is left alone and the parity
    test is what would catch it.
    """
    if isinstance(value, bool):
        return value                      # bool is an int in Python
    if isinstance(value, float) and value.is_integer() and abs(value) < 2 ** 53:
        return int(value)
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def canonical_json(value: Any) -> str:
    """The serialization the model request is defined by (D26).

    `ensure_ascii=False` deliberately. Escaping "idli, sambar" or a rupee
    sign into backslash-u sequences costs tokens, makes the prompt less
    legible to the model, and is the other place Python and JavaScript
    disagree.
    """
    return json.dumps(_canonical(value), indent=2, ensure_ascii=False)


@contextlib.contextmanager
def client_scope(conn: psycopg.Connection, client_id: str | None):
    """One short transaction with transaction-local client scope set (D25).

    Every write RUN_ENGINE makes goes through this, and the n8n workflow
    mirrors it: each Postgres node runs `SELECT set_client_scope($1)` and
    its statement inside one transaction.

    SHORT is the operative word. Scope is transaction-local by design (005
    passes `true` to set_config) so a pooled connection cannot carry Client
    A's context into a later Client B query -- but that also means holding
    one transaction across a 300-second provider call would keep a
    connection idle-in-transaction for five minutes. So the transaction
    wraps the write, never the model call.

    None is legitimate and means a knowledge-clock run (Engine 7
    FOUNDATION / UPDATE / INBOX, D18). Migration 014 lets those write; it
    does not widen access to anything that has a client.
    """
    with conn.transaction():
        conn.execute("select set_client_scope(%s)", (client_id,))
        yield


def build_user_prompt(envelope: dict[str, Any], structured_input: dict[str, Any]) -> str:
    """The model request: what was asked for, then the case payload.

    One function so the request text has one definition. The n8n port
    builds the identical string from the identical registry rows, and the
    repair retry rebuilds it rather than dropping the envelope on attempt
    two -- which is how a retry would silently become a differently-shaped
    request.
    """
    return (f"<{ENVELOPE_TAG}>\n"
            f"{canonical_json(envelope)}\n"
            f"</{ENVELOPE_TAG}>\n\n"
            f"{canonical_json(structured_input)}")


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


def sentinel(engine: str, mode: str, what: str) -> str:
    """A value that exists in exactly one handoff block and nowhere else.

    `SENT-E7-CASE-STRATEGY` appearing in Engine 1 Pass B's input is proof
    that Engine 7's reasoning reached it. `{}` being non-empty is not.
    """
    return f"SENT-{engine}-{mode}-{what}"


def fixture_handoffs(engine: str, mode: str, params: dict) -> dict[str, str]:
    """Substantive handoff bodies for the fixture provider, keyed by tag.

    Shaped like the real blocks -- line-oriented KEY: values, the format
    every prompt specifies -- and carrying the fields the next engine
    actually consumes, not a token field per block.
    """
    s = lambda what: sentinel(engine, mode, what)  # noqa: E731 - reads better inline
    version = params.get("case_version", 1)

    if engine == "E6" and mode in ("INIT", "REBUILD"):
        state = (
            f"CLIENT_ID_IF_AVAILABLE: {params.get('client_id', 'unknown')}\n"
            f"CASE_VERSION: {version}\n"
            "CURRENT_PHASE: PHASE_1\n"
            f"PRIMARY_HEALTH_PROBLEM: {s('PRIMARY-PROBLEM')}\n"
            f"CONFIRMED_FACTS: {s('FACT')}\n"
            f"CURRENT_HYPOTHESIS: {s('HYPOTHESIS')}\n"
            f"ACTIVE_INTERVENTIONS: {s('INTERVENTION')}\n"
            f"OPEN_QUESTIONS: {s('OPEN-QUESTION')}\n"
            "ROUTING_RECOMMENDATION: NONE\n"
            "ROUTING_REASON: initial state established"
        )
        blocks = {"CASE_MEMORY_HANDOFF": state}
        if mode == "REBUILD":
            blocks["CASE_MEMORY_DELTA"] = (
                f"NEW_FACTS: {s('DELTA-NEW-FACT')}\n"
                f"UPDATED_FACTS: {s('DELTA-UPDATED-FACT')}\n"
                f"NEW_INTERVENTIONS: {s('DELTA-INTERVENTION')}\n"
                "RESOLVED_ITEMS:\n"
                "ROUTING_TRIGGERED: NONE"
            )
        return blocks

    if engine == "E6" and mode == "UPDATE":
        return {"CASE_MEMORY_DELTA": (
            f"NEW_FACTS: {s('DELTA-NEW-FACT')}\n"
            f"UPDATED_FACTS: {s('DELTA-UPDATED-FACT')}\n"
            "RESOLVED_ITEMS:\n"
            "ROUTING_TRIGGERED: NONE"
        )}

    if engine == "E7":
        if mode == "INBOX":
            # §R10, added by the build because §55 described the information
            # gain in prose and no machine block carried it -- and §R11, the
            # Claim Cards themselves, because §R10 reports the information
            # GAIN and deliberately not the claims. A sentinel claim rather
            # than an empty array: an empty array is legitimate output but it
            # proves nothing about the path from a claim to a claims row.
            claims = json.dumps([{
                "claim_text": s("CLAIM-TEXT"),
                "claim_type": "INTERVENTION_EFFECT",
                "target": s("CLAIM-TARGET"),
                "intervention": s("CLAIM-INTERVENTION"),
                "population": None,
                "magnitude": None,
                "mechanism": s("CLAIM-MECHANISM"),
                "context": s("CLAIM-CONTEXT"),
                "evidence_referenced_by_source": s("CLAIM-CITED"),
                "extraction_confidence": 0.77,
                "location": s("CLAIM-LOCATION"),
            }], indent=2)
            return {
                "RESEARCH_PRACTICE_CLAIMS": (
                    f"MODE: {mode}\n"
                    f"SOURCE_REFERENCE: {s('SOURCE')}\n"
                    f"CLAIMS_JSON:\n{claims}"
                ),
                "RESEARCH_PRACTICE_INBOX_HANDOFF": (
                f"MODE: {mode}\n"
                f"SOURCE_REFERENCE: {s('SOURCE')}\n"
                "SOURCE_KIND: OTHER\n"
                f"CONCEPTS_EXTRACTED: {s('CONCEPT')}\n"
                f"ALREADY_KNOWN: {s('ALREADY-KNOWN')}\n"
                f"GENUINELY_NEW: {s('GENUINELY-NEW')}\n"
                f"CLAIMS_IDENTIFIED: {s('CLAIM')}\n"
                f"SAFETY_ISSUES_IDENTIFIED: {s('SAFETY-ISSUE')}\n"
                f"CANDIDATE_STRATEGIES_CREATED: {s('CANDIDATE')}\n"
                f"INFORMATION_GAIN_SUMMARY: {s('INFORMATION-GAIN')}\n"
                "SOURCE_VERSION: 1\n"
                "PROCESSING_VERSION: 1\n"
                "REPROCESSING_OF:"
                ),
            }
        if mode == "EVIDENCE":
            # §R12. Independent evidence for ONE claim, plus what it does to
            # the claim. The sentinel citation is deliberately unmistakable:
            # a fixture that emitted a plausible-looking DOI would be
            # indistinguishable from the fabrication §R12 forbids.
            evidence = json.dumps([{
                "citation": s("EVIDENCE-CITATION"),
                "doi": None, "pmid": None, "url": None,
                "publication_year": 2024,
                "design": "RCT",
                "population": s("EVIDENCE-POPULATION"),
                "sample_size": 120,
                "intervention": s("EVIDENCE-INTERVENTION"),
                "comparator": s("EVIDENCE-COMPARATOR"),
                "exposure": None,
                "duration": "12 weeks",
                "outcomes": s("EVIDENCE-OUTCOME"),
                "results_summary": s("EVIDENCE-RESULT"),
                "magnitude_summary": s("EVIDENCE-MAGNITUDE"),
                "limitations": s("EVIDENCE-LIMITATION"),
                "applicability": s("EVIDENCE-APPLICABILITY"),
                "funding_conflict_notes": s("EVIDENCE-FUNDING"),
                "relationship": "PARTIALLY_SUPPORTS",
            }], indent=2)
            assessment = json.dumps({
                "independent_evidence_findings": s("ASSESS-FINDINGS"),
                "current_interpretation": s("ASSESS-INTERPRETATION"),
                "areas_supported": s("ASSESS-SUPPORTED"),
                "areas_overstated": s("ASSESS-OVERSTATED"),
                "areas_uncertain": s("ASSESS-UNCERTAIN"),
                "evidence_confidence": "MODERATE",
                "safety_relevant": False,
            }, indent=2)
            return {"RESEARCH_PRACTICE_EVIDENCE": (
                f"MODE: {mode}\n"
                f"CLAIM_REFERENCE: {params.get('claim_id', 'unknown')}\n"
                f"EVIDENCE_JSON:\n{evidence}\n"
                f"CLAIM_ASSESSMENT_JSON:\n{assessment}"
            )}

        if mode == "SYNTHESIS":
            # §R13. One decision per candidate. CREATE, because a fixture
            # that only ever said NO_CHANGE would exercise none of the
            # writing path -- the dedup and the merge cases get their own
            # scripted providers in the suite.
            decisions = json.dumps([{
                "decision": "CREATE",
                "name": s("STRATEGY-NAME"),
                "summary": s("STRATEGY-SUMMARY"),
                "intervention_category": s("STRATEGY-CATEGORY"),
                "mechanism": s("STRATEGY-MECHANISM"),
                "practical_implementation": s("STRATEGY-IMPLEMENTATION"),
                "dose_or_exposure": s("STRATEGY-DOSE"),
                "expected_effect_direction": "IMPROVES",
                "expected_magnitude_summary": s("STRATEGY-MAGNITUDE"),
                "evidence_summary": s("STRATEGY-EVIDENCE-SUMMARY"),
                "evidence_confidence": "LIMITED",
                "limitations": s("STRATEGY-LIMITATION"),
                "outcomes_to_track": s("STRATEGY-OUTCOME"),
                "rationale": s("STRATEGY-RATIONALE"),
                "claim_ids": params.get("claim_ids", []),
                "evidence_ids": [],
                "concepts": [{"phrase": s("STRATEGY-CONCEPT"), "role": "TARGETS"}],
            }], indent=2)
            return {"RESEARCH_PRACTICE_SYNTHESIS": (
                f"MODE: {mode}\nSYNTHESIS_JSON:\n{decisions}"
            )}

        # FOUNDATION and UPDATE share the foundation contract (§R8): an
        # UPDATE is a smaller foundation pass, not a different output.
        tag = ("RESEARCH_PRACTICE_CASE_HANDOFF" if mode == "CASE"
               else "RESEARCH_PRACTICE_FOUNDATION_HANDOFF")
        if mode == "CASE":
            return {tag: (
                f"MODE: {mode}\n"
                f"CASE_RESEARCH_QUESTION: {s('QUESTION')}\n"
                "EXISTING_KNOWLEDGE_SUFFICIENT: YES\n"
                "LIVE_RESEARCH_PERFORMED: NO\n"
                f"HIGHEST_PRIORITY_STRATEGIES: {s('STRATEGY')}\n"
                f"ALTERNATIVE_STRATEGIES: {s('ALT-STRATEGY')}\n"
                f"EVIDENCE_SUMMARY: {s('EVIDENCE')}\n"
                f"EXPECTED_EFFECTS: {s('EFFECT-MAGNITUDE')}\n"
                f"POPULATION_APPLICABILITY: {s('APPLICABILITY')}\n"
                f"IMPLEMENTATION_NOTES: {s('IMPLEMENTATION')}\n"
                f"OUTCOMES_TO_TRACK: {s('OUTCOME')}\n"
                f"IMPORTANT_LIMITATIONS: {s('LIMITATION')}\n"
                f"ENGINE1_HANDOFF: {s('TO-E1')}"
            )}
        return {tag: (
            f"MODE: {mode}\n"
            f"STRATEGIES_ADDED: {s('STRATEGY')}\n"
            f"KNOWLEDGE_GAPS: {s('GAP')}\n"
            "LAST_UPDATED: fixture"
        )}

    tag = {
        "E1": "PREVENTION_INTELLIGENCE_HANDOFF",
        "E2": "BEHAVIOUR_INTELLIGENCE_HANDOFF",
        "E3": "NUTRITION_IMPLEMENTATION_HANDOFF",
        "E4": "PROGRESS_INTELLIGENCE_HANDOFF",
        "E5": "CLIENT_COMMUNICATION_HANDOFF",
    }[engine]

    if engine == "E1":
        # Pass A and Pass B are the same specification (D4) and emit the
        # same block; the sentinel says which pass produced it, so a test
        # can prove Pass B's finalized picture reached E2, not Pass A's.
        p = params.get("pass_label", "SINGLE")
        return {tag: (
            f"CLIENT_PROFILE: {sentinel('E1', p, 'PROFILE')}\n"
            f"PRIMARY_HEALTH_PROBLEM: {sentinel('E1', p, 'PRIMARY-PROBLEM')}\n"
            f"MAJOR_MODIFIABLE_DRIVERS: {sentinel('E1', p, 'DRIVER')}\n"
            f"FOUR_WEEK_INTERNAL_TARGETS: {sentinel('E1', p, 'TARGET')}\n"
            f"TOP_INTERVENTIONS: {sentinel('E1', p, 'STRATEGY')}\n"
            f"NUTRITION_OBJECTIVES: {sentinel('E1', p, 'NUTRITION-OBJECTIVE')}\n"
            f"BEHAVIOUR_REQUIRED: {sentinel('E1', p, 'BEHAVIOUR-REQUIRED')}\n"
            f"MOVEMENT_OBJECTIVES: {sentinel('E1', p, 'MOVEMENT-OBJECTIVE')}\n"
            f"HIGH_PRIORITY_MISSING_DATA: {sentinel('E1', p, 'MISSING-DATA')}\n"
            f"ALTERNATIVE_HYPOTHESES: {sentinel('E1', p, 'ALT-HYPOTHESIS')}"
        )}

    if engine == "E2":
        # §60B. The plan as data as well as prose. A fixture that emitted
        # only the handoff would leave client_interventions empty, and the
        # deterministic safety rules would pass every fixture client clean
        # having inspected nothing (D6) -- a green suite proving the
        # opposite of what it claims.
        items = json.dumps([{
            "name": s("BEHAVIOUR-SYSTEM"),
            "purpose": s("BEHAVIOUR-PURPOSE"),
            "tier": "PRIMARY",
            "minimum_version": s("BEHAVIOUR-MINIMUM"),
        }], indent=2)
        return {
            tag: (
                f"BEHAVIOUR_PLAN: {s('BEHAVIOUR-PLAN')}\n"
                f"IMPLEMENTATION_STEPS: {s('IMPLEMENTATION-STEP')}\n"
                f"ADHERENCE_RISKS: {s('ADHERENCE-RISK')}\n"
                f"CLIENT_CAPACITY_NOTES: {s('CAPACITY')}"
            ),
            "BEHAVIOUR_PLAN_ITEMS": f"ITEMS_JSON:\n{items}",
        }

    if engine == "E3":
        # §70B. The fixture proposes a deliberately BLAND item: a sentinel
        # name matches no safety pattern, so a fixture client flags nothing
        # unless the suite arranges for it to. A fixture that proposed
        # "carbohydrate reduction" would make every run a HOLD and the
        # narrowness of D6 impossible to test.
        items = json.dumps([{
            "name": s("NUTRITION-INTERVENTION"),
            "purpose": s("NUTRITION-PURPOSE"),
            "tier": "PRIMARY",
            "kind": "PATTERN",
            "minimum_version": s("NUTRITION-MINIMUM"),
        }], indent=2)
        return {
            tag: (
                f"MEAL_STRUCTURE: {s('MEAL-STRUCTURE')}\n"
                f"PROTEIN_PLAN: {s('PROTEIN-PLAN')}\n"
                f"FOOD_SUBSTITUTIONS: {s('SUBSTITUTION')}\n"
                f"SHOPPING_IMPLICATIONS: {s('SHOPPING')}"
            ),
            "NUTRITION_PLAN_ITEMS": f"ITEMS_JSON:\n{items}",
        }

    if engine == "E4":
        return {tag: (
            f"RESPONSE_SUMMARY: {s('RESPONSE')}\n"
            f"CURRENT_DECISION_REASON: {s('DECISION-REASON')}\n"
            f"WHAT_WE_LEARNED: {s('LEARNING')}"
        )}

    return {tag: (
        f"CLIENT_MESSAGE: {s('MESSAGE')}\n"
        f"WHAT_TO_DO_THIS_WEEK: {s('ACTION')}\n"
        f"WHAT_TO_EXPECT: {s('EXPECTATION')}"
    )}


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

    # The substantive handoff, which is the whole point of a run and was
    # missing from this fixture until D24. A fixture that emits only a
    # control block cannot distinguish a pipeline that carries reasoning
    # downstream from one that carries routing metadata and calls it
    # reasoning -- which is exactly the bug that went unnoticed.
    #
    # Every value carries a SENTINEL derived from the engine and mode. The
    # sentinels exist nowhere else, so a test can prove that E7's strategies
    # reached Engine 1 Pass B rather than that something non-empty did.
    handoff_mode = params.get("handoff_mode") or "SINGLE"
    blocks = fixture_handoffs(engine, handoff_mode, params)

    body = (
        f"(fixture output for {engine})\n\n"
        + "".join(f"<{tag}>\n{fields}\n</{tag}>\n\n"
                  for tag, fields in blocks.items())
        + f"<{CONTROL_TAG}>\n{json.dumps(control, indent=2)}\n</{CONTROL_TAG}>\n"
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
    return parse_completion(payload)


def parse_completion(payload: Any) -> tuple[str, int, int]:
    """Pull content and BILLED token counts out of a chat-completion payload.

    Separated from the HTTP call so the shapes a real provider returns can be
    asserted without a network round trip -- the payloads in
    test_run_engine.py are recorded from live responses, not invented.
    """
    # Some providers wrap the object in a single-element list.
    if isinstance(payload, list):
        payload = payload[0]

    choice = payload["choices"][0]
    # `content` is ABSENT, not empty, when a reasoning model spends its whole
    # budget thinking and finishes with reason "length". Subscripting it
    # raises KeyError, which RUN_ENGINE would report as a provider transport
    # failure -- a misleading diagnosis for a response that arrived intact.
    # Return the empty string and let control-block extraction fail honestly.
    content = choice.get("message", {}).get("content") or ""

    usage = payload.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    total_tokens = usage.get("total_tokens", 0)

    # REASONING TOKENS ARE BILLED AS OUTPUT AND ARE NOT IN completion_tokens.
    # Measured against this provider: prompt 8, completion 1, total 75 -- 66
    # tokens generated, billed, and invisible to the obvious accounting.
    # Taking completion_tokens as output would have understated the cost of
    # this cycle by most of it, and D5 is a decision made on these numbers.
    #
    # total - prompt is what was generated and charged at the output rate.
    # max() guards a provider whose total omits reasoning: never report less
    # than it explicitly told us.
    billed_output = max(completion_tokens, total_tokens - prompt_tokens)
    return content, prompt_tokens, billed_output


def select_provider() -> tuple[Provider, str]:
    key = os.environ.get("LLM_API_KEY", "").strip()
    if key and key != "change_me":
        return openai_compatible_provider, "live"
    return fixture_provider, "fixture"


def _is_retryable(exc: Exception) -> bool:
    """Is this the provider being busy, or the request being wrong?

    A 503 or a 429 means the same request will very likely succeed shortly.
    A 400 or a 401 means it will not, ever: retrying that spends wall-clock
    and, on a metered endpoint, money. Anything unrecognised is treated as
    permanent -- a retry loop that fires on unknown errors is how a bad
    request turns into a bill.
    """
    import urllib.error

    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in RETRYABLE_HTTP_STATUS
    # URLError covers DNS failure, connection refused, and the socket
    # timeouts urlopen surfaces through it.
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError))


def _retry_after(exc: Exception) -> float | None:
    """Seconds the provider asked us to wait, if it said so.

    Only the delta-seconds form is honoured. The HTTP-date form is legal but
    needs clock-skew handling to be safe, and no provider here sends it; an
    unparseable value falls back to our own backoff rather than to zero.
    """
    headers = getattr(exc, "headers", None)
    if headers is None:
        return None
    try:
        return max(0.0, float(headers.get("Retry-After", "")))
    except (TypeError, ValueError):
        return None


def _call_provider(conn, req: EngineRequest, provider: Provider, system_prompt: str,
                   user_prompt: str, params: dict, model_name: str, run_id: str):
    """One logical model call, retrying transient transport failures.

    Every PHYSICAL attempt is recorded in cost_events, failures included: a
    retry invisible in the cost table makes the measurement understate what
    a call really costs, and D5 is a decision made on those numbers.

    Returns (raw, in_tok, out_tok, duration_ms, error). `error` is None on
    success; on failure it is the last exception and the rest is empty.
    """
    last_exc: Exception | None = None
    for attempt in range(1, MAX_TRANSPORT_ATTEMPTS + 1):
        started = time.time()
        try:
            raw, in_tok, out_tok = provider(system_prompt, user_prompt, params)
        except Exception as exc:
            _record_cost(conn, req, model_name, run_id, 0, 0,
                         int((time.time() - started) * 1000), False,
                         type(exc).__name__)
            last_exc = exc
            if not _is_retryable(exc) or attempt == MAX_TRANSPORT_ATTEMPTS:
                break
            # Exponential, capped, with jitter so that concurrent
            # knowledge-batch calls do not all return at the same instant and
            # re-overload a provider that is already shedding load. A
            # Retry-After from the provider wins: it knows when it will be
            # back and we do not.
            delay = min(TRANSPORT_BACKOFF_CAP, TRANSPORT_BACKOFF_BASE ** attempt)
            delay *= 0.5 + random.random()
            time.sleep(min(TRANSPORT_BACKOFF_CAP, _retry_after(exc) or delay))
            continue
        return raw, in_tok, out_tok, int((time.time() - started) * 1000), None
    return "", 0, 0, 0, last_exc


# ---------------------------------------------------------------------
# RUN_ENGINE
# ---------------------------------------------------------------------

def run_engine(conn: psycopg.Connection, req: EngineRequest) -> EngineResult:
    prompt_file, prompt_content, prompt_hash = load_prompt(conn, req.engine)

    # Which substantive handoff this run owes, resolved BEFORE the provider
    # is called (D24). An unregistered engine/mode is a build error, and
    # discovering it after a 300-second call has been paid for helps nobody.
    handoff_mode = load_handoffs.resolve_mode(req.engine, req.mode)
    expected_handoffs = load_handoffs.expected(conn, req.engine, handoff_mode)

    # `provider_mode` is fixture-vs-live. Named apart from `handoff_mode`
    # because they are unrelated and one of them used to be called `mode`.
    provider, provider_mode = select_provider()
    # A fixture run is recorded under a `fixture:` model name even when a
    # real model is configured, and that prefix is load-bearing rather than
    # cosmetic.
    #
    # The fixture provider's token counts are character estimates. Recording
    # them under the real model name means the price registry matches, and
    # the run is costed -- so a cycle that never left this machine reports a
    # dollar figure, printed directly beneath the banner saying the counts
    # are estimates. Prefixing means no registry entry matches, the call is
    # UNPRICED, and cost stays NULL. It also keeps UNPRICED's meaning
    # exactly what migration 008 documents: no rate configured for THIS
    # model name.
    configured = os.environ.get(req.model_role, "").strip()
    if provider_mode == "live":
        if not configured:
            raise ModelRoleUnset(
                f"{req.model_role} is not set, but LLM_API_KEY is. A live run "
                f"needs a model for its role. Set {req.model_role} in .env, or "
                "clear LLM_API_KEY to use the fixture provider."
            )
        model_name = configured
    else:
        model_name = f"fixture:{configured or provider_mode}"

    run_id = str(uuid.uuid4())
    with client_scope(conn, req.client_id):
        conn.execute(
            """insert into engine_runs
                 (run_id, client_id, case_version_id, cycle_id, engine, pass,
                  engine_mode, prompt_file, prompt_hash, schema_version,
                  model_role, model_name, model_params, status, started_at)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'RUNNING',now())""",
            (run_id, req.client_id, req.case_version_id, req.cycle_id, req.engine,
             req.pass_label, handoff_mode, prompt_file, prompt_hash,
             SCHEMA_VERSION, req.model_role, model_name,
             json.dumps(req.run_context)),
        )

    # THE RUNTIME ENVELOPE.
    #
    # RUN_ENGINE resolved the mode and then never told the model. The
    # fixture provider got it as a param and a live provider ignored
    # params entirely, so `mode="INIT"` versus `mode="REBUILD"` -- the
    # difference between Engine 6 emitting a full state and emitting a
    # delta -- reached the wire as nothing at all. The fixture could not
    # catch it: it was reading the param the live path throws away.
    #
    # Injected here, once, for every engine. E1 already transmitted its
    # mode because client_new.py hand-wrote "MODE": "PASS_A" into the
    # structured input, and that is the accident this replaces: a key a
    # caller has to remember is a key a caller will forget, and E6 and E7
    # duly did. Callers now pass `mode=` and nothing else.
    #
    # Generic on purpose -- no engine-specific branches. The envelope says
    # what was requested; the PROMPT says what each mode means.
    envelope = {
        "ENGINE": req.engine,
        "MODE": handoff_mode,
        "PASS": req.pass_label,
        "EXPECTED_HANDOFF_BLOCKS": [tag for tag, _r in expected_handoffs],
        "REQUIRED_HANDOFF_BLOCKS": [tag for tag, r in expected_handoffs if r],
        "CONTROL_BLOCK_REQUIRED": True,
    }
    user_prompt = build_user_prompt(envelope, req.structured_input)
    params = {
        "engine": req.engine,
        "pass_label": req.pass_label,
        "model_name": model_name,
        "case_version": req.structured_input.get("CASE_VERSION", 1),
        # The fixture provider needs the mode to know which block to emit;
        # a live provider ignores it, because the PROMPT tells the model
        # which block to produce.
        "handoff_mode": handoff_mode,
        "client_id": req.client_id,
    }

    attempts = 0
    errors: list[str] = []
    raw = ""
    control: dict[str, Any] | None = None
    handoffs: dict[str, dict[str, Any]] = {}
    # engine_runs has carried input_tokens / output_tokens / duration_ms
    # since 004 and nothing ever wrote them. They are the per-run totals
    # across every attempt, which is what a repair retry actually cost.
    totals = {"input_tokens": 0, "output_tokens": 0, "duration_ms": 0}

    provider_failed = False

    while attempts < MAX_ATTEMPTS:
        attempts += 1
        raw, in_tok, out_tok, duration_ms, exc = _call_provider(
            conn, req, provider, prompt_content, user_prompt, params,
            model_name, run_id)
        if exc is not None:
            # Transport retries are exhausted. The payload is fine and the
            # provider is not, so a repair retry -- which resends the same
            # request with repair instructions bolted on -- would only fail
            # the same way. Stop and dead-letter with an honest error class.
            errors = [f"provider error: {exc}"]
            provider_failed = True
            break

        _record_cost(conn, req, model_name, run_id, in_tok, out_tok, duration_ms, True, None)
        totals["input_tokens"] += in_tok
        totals["output_tokens"] += out_tok
        totals["duration_ms"] += duration_ms

        control = extract_control(raw)
        if control is None:
            errors = [f"no parseable <{CONTROL_TAG}> block in response"]
        else:
            errors = validate_control(conn, control)

        # The substantive reasoning, which is a SEPARATE thing from the
        # control block and not a substitute for it. A response can route
        # perfectly and contain no thinking at all; before D24 that counted
        # as a successful run.
        #
        # A missing required handoff joins the same `errors` list as a
        # contract violation on purpose: it then travels the repair retry
        # and the dead-letter path that already exist, rather than adding a
        # third way for a run to fail.
        handoffs = {}
        for tag, _required in expected_handoffs:
            parsed = extract_handoff(raw, tag)
            if parsed is not None:
                handoffs[tag] = parsed
        errors = errors + [
            f"no parseable <{tag}> block in response. The control block "
            "routes; this is the reasoning the next engine needs, and a "
            "response without it is not a completed run."
            for tag, required in expected_handoffs
            if required and tag not in handoffs
        ]

        if control is not None and not errors:
            break

        with client_scope(conn, req.client_id):
            conn.execute(
                "update engine_runs set status='REPAIR_RETRY', attempts=%s "
                "where run_id=%s", (attempts, run_id))
        user_prompt = (build_user_prompt(envelope, req.structured_input)
                       + "\n\n" + repair_instruction(errors))

    if errors or control is None:
        # Malformed output is never inserted into the knowledge or case
        # tables. It goes to the dead-letter queue for inspection.
        with client_scope(conn, req.client_id):
            conn.execute(
                """update engine_runs
                      set status='DEAD_LETTER', attempts=%s, completed_at=now(),
                          input_tokens=%s, output_tokens=%s, duration_ms=%s,
                          error_class=%s, error_detail=%s
                    where run_id=%s""",
                (attempts, totals["input_tokens"], totals["output_tokens"],
                 totals["duration_ms"],
                 "PROVIDER_ERROR" if provider_failed else "SCHEMA_INVALID",
                 "; ".join(errors)[:2000], run_id))
            # The dead letter carries the CLIENT (015). raw_payload holds up
            # to 8,000 characters of the failed response, and for a case
            # run that is the client's clinical record in a different
            # shape -- labs, conditions, medications. It is not telemetry
            # and it is not global: same scope, same transaction as the run
            # it belongs to.
            conn.execute(
                """insert into dead_letter_jobs
                     (job_type, entity_type, entity_id, client_id,
                      failure_reason, raw_payload, attempts)
                   values (%s,'engine_run',%s,%s,%s,%s,%s)""",
                (f"RUN_ENGINE_{req.engine}", run_id, req.client_id,
                 "; ".join(errors)[:2000], json.dumps({"raw": raw[:8000]}),
                 attempts))
        return EngineResult(run_id, "DEAD_LETTER", None, raw, None, attempts,
                            "; ".join(errors))

    # The human-readable report is what precedes the FIRST machine block,
    # whichever that is. Splitting on the control tag alone left every
    # handoff block sitting inside `human_output`, so the practitioner view
    # ended with a wall of KEY: lines.
    boundaries = [raw.find(f"<{t}>") for t in
                  [CONTROL_TAG] + [tag for tag, _ in expected_handoffs]]
    first = min([b for b in boundaries if b >= 0], default=-1)
    human_output = (raw[:first] if first >= 0 else raw).strip()

    # The primary handoff is the first REQUIRED tag the registry lists;
    # anything else the response carried is kept beside it rather than
    # dropped. E6 rebuilding state emits the full state and may also report
    # what changed, and that delta is the only record of the change.
    primary_tag = next((tag for tag, required in expected_handoffs
                        if required and tag in handoffs),
                       next(iter(handoffs), None))
    structured = handoffs.get(primary_tag, {}) if primary_tag else {}
    secondary = {tag: body for tag, body in handoffs.items() if tag != primary_tag}

    # One transaction for both writes: a run marked SUCCEEDED with no output
    # row is a lie the next reader would believe.
    with client_scope(conn, req.client_id):
        conn.execute(
            """update engine_runs
                  set status='SUCCEEDED', attempts=%s, completed_at=now(),
                      input_tokens=%s, output_tokens=%s, duration_ms=%s
                where run_id=%s""",
            (attempts, totals["input_tokens"], totals["output_tokens"],
             totals["duration_ms"], run_id))
    # `structured` held json.dumps(structured_input.get("_echo", {})) from
    # 004 until D24 -- the INPUT's `_echo` key, which nothing has ever set,
    # so every run since the engine layer was built stored `{}`. It holds
    # the engine's own reasoning now.
        conn.execute(
            """insert into engine_outputs
                 (run_id, human_output, structured, control, schema_valid,
                  handoff_tag, handoff_mode, secondary_handoffs)
               values (%s,%s,%s,%s,true,%s,%s,%s)""",
            (run_id, human_output, json.dumps(structured), json.dumps(control),
             primary_tag, handoff_mode, json.dumps(secondary)))
    return EngineResult(run_id, "SUCCEEDED", control, human_output, structured,
                        attempts, handoff_tag=primary_tag,
                        handoff_mode=handoff_mode, secondary_handoffs=secondary)


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
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        registered = {r[0] for r in conn.execute(
            "select engine from engine_prompts where active").fetchall()}
    missing = [e for e in ENGINE_PROMPTS if e not in registered]
    if missing:
        print(f"no active prompt registered for: {', '.join(sorted(missing))}")
        print("RUN_ENGINE will raise PromptMissing for these engines. Run "
              "`python3 scripts/load_prompts.py`.")
        sys.exit(0)
    print("all seven engine prompts registered and active")

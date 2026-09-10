// The n8n half of RUN_ENGINE's request construction.
//
// Byte-identical to scripts/run_engine.py's build_user_prompt(). Not
// "equivalent" -- identical. The prompt hash plus the request IS the call,
// and two serializers that mean the same thing produce different model
// behaviour with nothing to notice.
//
// Two things Python and JavaScript disagree about, both measured rather
// than assumed:
//
//   non-ASCII      Python escapes by default; JS does not. Python now
//                  passes ensure_ascii=False, which is better anyway --
//                  escaping "idli, sambar" wastes tokens and hides the
//                  text from the model.
//   integral float Python writes 78.0, JS writes 78. JSON has one number
//                  type and JS cannot tell them apart once parsed, so
//                  Python normalizes integral floats to ints (D26).
//
// Everything else -- key order, indentation, empty containers, big
// integers, every JSON escape -- already agrees.
'use strict';

const ENVELOPE_TAG = 'RUNTIME_INVOCATION';

// JSON.stringify(x, null, 2) is already Python's
// json.dumps(x, indent=2, ensure_ascii=False) for every shape the corpus
// covers. Kept as a named function so the parity test has one thing to
// point at, and so a future divergence has one place to be fixed.
function canonicalJson(value) {
    return JSON.stringify(value, null, 2);
}

function buildUserPrompt(envelope, structuredInput) {
    return `<${ENVELOPE_TAG}>\n`
        + `${canonicalJson(envelope)}\n`
        + `</${ENVELOPE_TAG}>\n\n`
        + `${canonicalJson(structuredInput)}`;
}

// The envelope, built from the SAME registry rows Python reads. Key order
// is part of the contract: JSON.stringify preserves insertion order for
// string keys, so this literal must list them in the reference's order.
function buildEnvelope({ engine, mode, passLabel, expectedHandoffs }) {
    return {
        ENGINE: engine,
        MODE: mode,
        PASS: passLabel || 'SINGLE',
        EXPECTED_HANDOFF_BLOCKS: expectedHandoffs.map((h) => h.tag),
        REQUIRED_HANDOFF_BLOCKS: expectedHandoffs
            .filter((h) => h.required)
            .map((h) => h.tag),
        CONTROL_BLOCK_REQUIRED: true,
    };
}

module.exports = { ENVELOPE_TAG, canonicalJson, buildUserPrompt, buildEnvelope };

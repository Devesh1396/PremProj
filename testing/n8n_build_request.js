// Runs the n8n-side request builder over the golden corpus and prints the
// results, so the Python parity suite can compare byte for byte.
//
// Reads {"cases":[...], "expected_handoffs":{...}} on stdin -- the handoff
// expectations come from the DATABASE, passed in by the Python side, so
// both implementations are reading the same registry rows rather than two
// copies of a map.
'use strict';

const path = require('node:path');
const { buildEnvelope, buildUserPrompt } = require(
    path.join(__dirname, '..', 'workflows', 'build_request.js'));

let input = '';
process.stdin.on('data', (c) => { input += c; });
process.stdin.on('end', () => {
    const payload = JSON.parse(input);
    const out = payload.cases.map((c) => {
        const key = `${c.engine}/${c.resolved_mode}`;
        const expected = payload.expected_handoffs[key];
        if (!expected) {
            return { name: c.name, error: `no registry entry for ${key}` };
        }
        const envelope = buildEnvelope({
            engine: c.engine,
            mode: c.resolved_mode,
            passLabel: c.pass_label,
            expectedHandoffs: expected,
        });
        return { name: c.name, user_prompt: buildUserPrompt(envelope, c.structured_input) };
    });
    process.stdout.write(JSON.stringify({ results: out }));
});

// Runs the WORKFLOW'S OWN transport-retry code against a scripted sequence
// of provider responses, with fetch stubbed and time compressed.
//
// Extracted from workflows/run_engine.json at run time, like the parser --
// a copy would drift from the workflow it claims to test.
//
// No network, no paid calls, and no real sleeping: the backoff base is set
// tiny through the same env var the node reads, so the exponential shape
// is exercised at millisecond scale.
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const WORKFLOW = path.join(__dirname, '..', 'workflows', 'run_engine.json');

function nodeCode(name) {
    const wf = JSON.parse(fs.readFileSync(WORKFLOW, 'utf8'))[0];
    const node = wf.nodes.find((n) => n.name === name);
    if (!node) throw new Error(`no node named ${name}`);
    return node.parameters.jsCode;
}

async function runCase(testCase) {
    const calls = [];
    const waits = [];

    // Scripted responses, one per physical attempt.
    let i = 0;
    globalThis.fetch = async (url, init) => {
        const step = testCase.sequence[Math.min(i, testCase.sequence.length - 1)];
        i += 1;
        calls.push({ url, body: init.body });
        if (step.network_error) {
            const err = new Error('connect ECONNREFUSED');
            err.name = 'NetworkError';
            throw err;
        }
        const headers = new Map(Object.entries(step.headers || {}));
        return {
            ok: step.status === 200,
            status: step.status,
            headers: { get: (k) => headers.get(k) ?? null },
            json: async () => step.body || {
                choices: [{ message: { content: 'ok' } }],
                usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
            },
        };
    };

    // setTimeout is captured rather than honoured: the SHAPE of the delays
    // is what is under test, not the wall-clock.
    const realTimeout = globalThis.setTimeout;
    globalThis.setTimeout = (fn, ms) => { waits.push(ms / 1000); return realTimeout(fn, 0); };

    const env = {
        LLM_BASE_URL: 'https://example.invalid/v1',
        LLM_API_KEY: 'test-key',
        LLM_TRANSPORT_MAX_ATTEMPTS: String(testCase.max_attempts ?? 6),
        LLM_TRANSPORT_BACKOFF_BASE: String(testCase.backoff_base ?? 2),
    };
    const build = { json: { model_name: 'test-model', system_prompt: 'sys',
                            user_prompt: 'usr', run_id: 'r' } };
    const $ = () => ({ first: () => build, item: build, all: () => [build] });

    const src = nodeCode('Call provider');
    const fn = new Function('$', '$env', 'fetch',
        `return (async () => { ${src} })();`);
    try {
        const out = await fn($, env, globalThis.fetch);
        return { name: testCase.name, calls: calls.length, waits,
                 result: out[0].json };
    } finally {
        globalThis.setTimeout = realTimeout;
    }
}

let input = '';
process.stdin.on('data', (c) => { input += c; });
process.stdin.on('end', async () => {
    const payload = JSON.parse(input);
    const results = [];
    for (const c of payload.cases) {
        try {
            results.push(await runCase(c));
        } catch (err) {
            results.push({ name: c.name, error: err.message });
        }
    }
    process.stdout.write(JSON.stringify({ results }));
});

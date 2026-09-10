// Runs the WORKFLOW'S OWN transport-retry code against a scripted sequence
// of provider responses, with the HTTP helper stubbed and time compressed.
//
// Extracted from workflows/run_engine.json at run time, like the parser --
// a copy would drift from the workflow it claims to test.
//
// RUN INSIDE A RESTRICTED CONTEXT, and that is the point.
//
// The first version of this harness ran the extracted source with
// `new Function(...)` in plain Node, where `fetch` is a global. The node
// was written with `fetch`, every assertion passed, and the code could
// never have run: n8n's Code node executes inside vm2, whose sandbox has
// no `fetch` and no `URL`. Verified empirically against the installed
// vm2 -- on 2.11.4 and 2.35.7 alike -- which reports:
//
//   setTimeout function   Promise function   Math object
//   JSON object           Date function      helpers object
//   fetch UNDEFINED       URL   UNDEFINED
//
// So the code runs in `node:vm` with a context carrying exactly the
// host-provided globals vm2 gives it and nothing else. A fresh vm context
// has the JS intrinsics and none of Node's additions, which is the same
// shape -- so a node reaching for `fetch` throws ReferenceError here just
// as it would in n8n. node:vm is built in; vm2 is not a dependency of this
// repository and must not become one for a test to run. See D33.
//
// No network, no paid calls, and no real sleeping: the backoff base is set
// tiny through the same env var the node reads, so the exponential shape
// is exercised at millisecond scale.
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const WORKFLOW = path.join(__dirname, '..', 'workflows', 'run_engine.json');

function nodeCode(name) {
    const wf = JSON.parse(fs.readFileSync(WORKFLOW, 'utf8'))[0];
    const node = wf.nodes.find((n) => n.name === name);
    if (!node) throw new Error(`no node named ${name}`);
    return node.parameters.jsCode;
}

// n8n-core 2.11.1 `httpRequest`, as read from
//   dist/execution-engine/node-execution-context/utils/request-helper-functions.js
//
//   returnFullResponse       -> { body, headers, statusCode, statusMessage }
//   ignoreHttpStatusErrors   -> axios validateStatus = () => true, so a
//                               4xx/5xx RETURNS instead of throwing
//   a network-level failure  -> still throws
//
// Header names arrive lowercased, because axios lowercases them.
function makeHelpers(testCase, calls) {
    let i = 0;
    return {
        httpRequest: async (options) => {
            const step = testCase.sequence[Math.min(i, testCase.sequence.length - 1)];
            i += 1;
            calls.push({ url: options.url, body: options.body, options });
            if (step.network_error) {
                // Axios attaches `code` on a transport failure; that code
                // is what the node classifies on, so the stub must carry
                // one or the test would prove nothing about the rule.
                const err = new Error('connect ECONNREFUSED');
                err.name = 'AxiosError';
                err.code = step.network_error === true ? 'ECONNREFUSED' : step.network_error;
                throw err;
            }
            if (step.throw_programming_error) {
                // No `code`. This is what a bug in the node itself looks
                // like from here, and it must NOT be retried.
                const err = new ReferenceError('fetch is not defined');
                throw err;
            }
            const headers = {};
            for (const [k, v] of Object.entries(step.headers || {})) headers[k.toLowerCase()] = v;
            const body = step.body || {
                choices: [{ message: { content: 'ok' } }],
                usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
            };
            if (!options.returnFullResponse) {
                // The node must ask for the full response; without it there
                // is no status to branch on and no Retry-After to honour.
                throw new Error('the node did not set returnFullResponse');
            }
            if (!options.ignoreHttpStatusErrors && (step.status < 200 || step.status >= 300)) {
                // What n8n really does without that option: axios throws.
                const err = new Error(`Request failed with status code ${step.status}`);
                err.name = 'AxiosError';
                throw err;
            }
            return { body, headers, statusCode: step.status, statusMessage: 'x' };
        },
    };
}

async function runCase(testCase) {
    const calls = [];
    const waits = [];

    const env = {
        LLM_BASE_URL: 'https://example.invalid/v1',
        LLM_API_KEY: 'test-key',
        LLM_TRANSPORT_MAX_ATTEMPTS: String(testCase.max_attempts ?? 6),
        LLM_TRANSPORT_BACKOFF_BASE: String(testCase.backoff_base ?? 2),
    };
    const build = { json: { model_name: 'test-model', system_prompt: 'sys',
                            user_prompt: 'usr', run_id: 'r' } };

    // Exactly the host globals vm2 provides. setTimeout is captured rather
    // than honoured: the SHAPE of the delays is under test, not wall-clock.
    const context = {
        helpers: makeHelpers(testCase, calls),
        $: () => ({ first: () => build, item: build, all: () => [build] }),
        $env: env,
        console,
        setTimeout: (fn, ms) => { waits.push(ms / 1000); return setTimeout(fn, 0); },
        clearTimeout,
    };

    const src = nodeCode('Call provider');
    const out = await vm.runInNewContext(
        `(async () => { ${src} })()`, vm.createContext(context),
        { filename: 'Call provider', timeout: 30000 });
    return { name: testCase.name, calls: calls.length, waits, result: out[0].json };
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

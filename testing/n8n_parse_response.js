// Runs the WORKFLOW'S OWN parsing and validation code over a corpus of raw
// model responses, so the Python parity suite can compare field by field.
//
// The jsCode is EXTRACTED FROM workflows/run_engine.json at run time, not
// copied here. A copy would drift from the workflow it claims to test, and
// then parity would be proving two test helpers agree.
//
// n8n's Code node runs with $json, $() and require available. Those are
// shimmed here exactly as n8n provides them for this workflow's use.
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');

const WORKFLOW = path.join(__dirname, '..', 'workflows', 'run_engine.json');

function nodeCode(name) {
    const wf = JSON.parse(fs.readFileSync(WORKFLOW, 'utf8'))[0];
    const node = wf.nodes.find((n) => n.name === name);
    if (!node) throw new Error(`no node named ${name} in run_engine.json`);
    return node.parameters.jsCode;
}

// Run one Code node's source with n8n's globals shimmed.
function runCodeNode(name, { json, nodes }) {
    const src = nodeCode(name);
    const $ = (nodeName) => {
        const items = nodes[nodeName];
        if (!items) throw new Error(`shim has no node ${nodeName}`);
        return {
            first: () => items[0],
            item: items[0],
            all: () => items,
        };
    };
    // ajv resolves from AJV_MODULE_PATH, the way scripts/local_n8n.sh sets
    // NODE_FUNCTION_ALLOW_EXTERNAL for the real Code node.
    const base = process.env.AJV_MODULE_PATH;
    const req = (id) => (base && (id === 'ajv/dist/2020' || id === 'ajv-formats')
        ? require(path.join(base, id))
        : require(id));
    const fn = new Function('$json', '$', 'require', 'crypto', `${src}`);
    return fn(json, $, req, require('node:crypto'));
}

let input = '';
process.stdin.on('data', (c) => { input += c; });
process.stdin.on('end', () => {
    const payload = JSON.parse(input);
    const results = payload.cases.map((c) => {
        const buildItem = { json: {
            run_id: '00000000-0000-4000-8000-000000000000',
            expected_handoffs: c.expected_handoffs,
            contract: payload.contract,
            attempt: 1,
        } };
        // The provider response, in the shape the HTTP node yields.
        const providerJson = {
            choices: [{ message: { content: c.raw } }],
            usage: c.usage,
        };
        try {
            const parsed = runCodeNode('Parse three outputs', {
                json: providerJson,
                nodes: { 'Build request': [buildItem] },
            })[0].json;
            const validated = runCodeNode('Validate control', {
                json: parsed,
                nodes: { 'Build request': [buildItem] },
            })[0].json;
            return {
                name: c.name,
                human_output: validated.human_output,
                control: validated.control,
                structured: validated.structured,
                primary_tag: validated.primary_tag,
                secondary_handoffs: validated.secondary_handoffs,
                errors: validated.errors,
                valid: validated.valid,
                input_tokens: validated.input_tokens,
                output_tokens: validated.output_tokens,
            };
        } catch (err) {
            return { name: c.name, error: `${err.message}` };
        }
    });
    process.stdout.write(JSON.stringify({ results }));
});

// The n8n half of the control-contract parity check.
//
// Reads {"schema": <document>, "cases": [<control block>, ...]} on stdin and
// writes {"ajv": "<version>", "results": [{"valid": bool, "paths": [...]}]}.
//
// This is deliberately the SAME shape the n8n Code node will use: ajv's
// 2020 build, allErrors so a repair prompt can list every problem at once,
// and ajv-formats registered because the contract may grow a "format".
// ajv ships inside n8n, which is why the port needs no bundled validator
// and why parity is worth asserting -- the schema is single-sourced in
// PostgreSQL (migration 012) and only the LIBRARY differs.
//
// `paths` is what makes the comparison meaningful. Two implementations of
// JSON Schema will never phrase a message identically, and asserting they
// do would be asserting the wrong thing. What has to match is the verdict
// and WHICH field is at fault, because that is what routes a case and what
// goes into the repair prompt.
'use strict';

const path = require('node:path');

function resolveAjv() {
    // AJV_MODULE_PATH points at a node_modules directory containing ajv --
    // an n8n install locally, a plain `npm i ajv` in CI. Falling back to a
    // bare require keeps this usable if ajv is on NODE_PATH.
    const base = process.env.AJV_MODULE_PATH;
    if (base) {
        return {
            Ajv: require(path.join(base, 'ajv', 'dist', '2020')),
            addFormats: require(path.join(base, 'ajv-formats')),
            version: require(path.join(base, 'ajv', 'package.json')).version,
        };
    }
    return {
        Ajv: require('ajv/dist/2020'),
        addFormats: require('ajv-formats'),
        version: require('ajv/package.json').version,
    };
}

let input = '';
process.stdin.on('data', (chunk) => { input += chunk; });
process.stdin.on('end', () => {
    let payload;
    try {
        payload = JSON.parse(input);
    } catch (err) {
        console.error(`stdin was not JSON: ${err.message}`);
        process.exit(2);
    }

    let Ajv, addFormats, version;
    try {
        ({ Ajv, addFormats, version } = resolveAjv());
    } catch (err) {
        console.error(`ajv not available: ${err.message}`);
        process.exit(3);
    }

    // strict:false because the contract carries `description` on its allOf
    // branches, which ajv's strict mode rejects as an unknown keyword in
    // that position. The document is the reviewed artefact; ajv's opinion
    // about where prose may live is not a reason to edit it.
    const ajv = new Ajv({ allErrors: true, strict: false });
    addFormats(ajv);

    let validate;
    try {
        validate = ajv.compile(payload.schema);
    } catch (err) {
        console.error(`schema did not compile: ${err.message}`);
        process.exit(4);
    }

    const results = (payload.cases || []).map((testCase) => {
        const valid = validate(testCase);
        const paths = new Set();
        // Applicator keywords are CONTAINERS. When an if/then branch fails,
        // ajv reports the branch itself at the document root as well as the
        // specific failure inside it; jsonschema reports only the specific
        // one. Both agree the block is invalid and both blame the same real
        // field -- the container error names no field and would be noise in
        // a repair prompt. Skipping it compares the two libraries on what
        // they actually disagree about rather than on how they summarise.
        const CONTAINERS = new Set(['if', 'then', 'else', 'allOf', 'anyOf', 'oneOf', 'not']);
        for (const error of validate.errors || []) {
            if (CONTAINERS.has(error.keyword)) continue;
            // ajv reports a missing required property against the PARENT
            // with the name in params; jsonschema reports the parent too.
            // Normalising to the field name is what makes the two
            // comparable at all.
            if (error.keyword === 'required') {
                paths.add(error.params.missingProperty);
            } else if (error.keyword === 'additionalProperties') {
                paths.add(error.params.additionalProperty);
            } else if (error.instancePath) {
                paths.add(error.instancePath.replace(/^\//, '').split('/')[0]);
            } else {
                paths.add('(root)');
            }
        }
        return { valid, paths: [...paths].sort() };
    });

    process.stdout.write(JSON.stringify({ ajv: version, results }));
});

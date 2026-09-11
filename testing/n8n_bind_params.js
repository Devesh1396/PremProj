// Bind a Postgres node's query parameters EXACTLY as n8n does at v2.5,
// ON THE VERSION THIS SYSTEM RUNS: n8n 2.11.4 (n8n-nodes-base 2.11.2).
//
// The workflow's SQL was the one part of the port nothing executed, and
// three defects were hiding in it at once. Two of them were not SQL
// mistakes at all -- they were mistakes about how n8n turns a
// queryReplacement expression into a parameter list, and no amount of
// reading the SQL would have found them.
//
// So this is a faithful port of the v2.5 branch of
//   n8n-nodes-base/dist/nodes/Postgres/v2/actions/database/executeQuery.operation.js
// together with stringToArray / isJSON / evaluateExpression from that
// node's helpers, READ FROM 2.11.2 -- not from a later release.
//
// That distinction is not pedantry. The first draft of this file was
// ported from 2.35.7, which has an ARRAY BRANCH that 2.11.2 does not:
//
//   2.35.7   an expression evaluating to an array pushes one value per
//            element, preserving null and passing strings through whole
//   2.11.2   there is no such branch. An array is JSON.stringify'd like
//            any other object and pushed as ONE value
//
// Every queryReplacement had been written as a single {{ [a, b, c] }} to
// use that branch. On 2.11.4 that binds ONE parameter where the statement
// wants twelve, and every Postgres node in the workflow fails on the first
// run. See DECISIONS.md D32.
//
// The behaviours that survive in BOTH versions, all three of which the
// original draft got wrong:
//
//   1. Literal text OUTSIDE {{ }} is discarded. "RUN_ENGINE_{{ engine }}"
//      binds "E1", not "RUN_ENGINE_E1".
//   2. null becomes the STRING 'null'. Bound to a uuid column that is an
//      error; bound to text it is worse, because it succeeds.
//   3. A resolved string that is not JSON is SPLIT ON COMMAS into several
//      parameters -- and an EMPTY string is dropped entirely, which shifts
//      every parameter after it.
//
// The form that is exact on both versions is one resolvable per parameter,
// each evaluating to a JSON LITERAL:
//
//   ={{ JSON.stringify(a) }},{{ JSON.stringify(b) }}
//
// isJSON() is then true for every one of them, so each is pushed whole --
// commas, empty strings and all -- and JSON null arrives as the four
// characters "null" which SQL unwraps to a real NULL with `#>> '{}'`.
// Nothing depends on a branch that only one of the two versions has.
//
//   node testing/n8n_bind_params.js '<node name>' <<< '<context json>'
//
// Context: { "nodes": { "<name>": {...json...} }, "json": {...}, "env": {...} }

const fs = require('fs');
const path = require('path');

const WORKFLOW = path.join(__dirname, '..', 'workflows', 'run_engine.json');

function loadNode(name) {
  const doc = JSON.parse(fs.readFileSync(WORKFLOW, 'utf8'));
  const wf = Array.isArray(doc) ? doc[0] : doc;
  const node = wf.nodes.find((n) => n.name === name);
  if (!node) throw new Error(`no node named ${name} in run_engine.json`);
  return node;
}

// utils/utilities.js
function getResolvables(expression) {
  if (!expression) return [];
  const out = [];
  const re = /({{[\s\S]*?}})/g;
  let m;
  while ((m = re.exec(expression)) !== null) if (m[1]) out.push(m[1]);
  return out;
}

// Postgres/v2/helpers/utils.js
const isJSON = (str) => { try { JSON.parse(String(str).trim()); return true; } catch { return false; } };
const evaluateToString = (v) =>
  v === undefined ? '' : v === null ? 'null'
  : typeof v === 'object' ? JSON.stringify(v) : v.toString();
const stringToArray = (str) =>
  str === undefined ? []
  : String(str).split(',').filter((e) => e).map((e) => e.trim());

function evaluate(resolvable, ctx) {
  const body = resolvable.slice(2, -2);
  const $ = (name) => {
    if (!(name in ctx.nodes)) throw new Error(`node ${name} not in test context`);
    return { item: { json: ctx.nodes[name] }, first: () => ({ json: ctx.nodes[name] }) };
  };
  // eslint-disable-next-line no-new-func
  return new Function('$', '$json', '$env', `return (${body});`)($, ctx.json || {}, ctx.env || {});
}

function bind(node, ctx) {
  const raw = node.parameters?.options?.queryReplacement;
  const values = [];
  if (raw) {
    const rawValues = String(raw).replace(/^=+/, '');
    const resolvables = getResolvables(rawValues);
    if (resolvables.length) {
      for (const resolvable of resolvables) {
        // 2.11.2 has NO array branch. Whatever the expression evaluates to
        // is coerced to a string here and then either kept whole (if it
        // parses as JSON) or split on commas.
        const evaluated = evaluateToString(evaluate(resolvable, ctx));
        const parts = isJSON(evaluated) ? [evaluated] : stringToArray(evaluated);
        if (parts.length) values.push(...parts);
      }
    } else {
      values.push(...stringToArray(rawValues));
    }
  }
  return { query: node.parameters.query, values };
}

if (require.main === module) {
  const name = process.argv[2];
  const ctx = JSON.parse(fs.readFileSync(0, 'utf8') || '{}');
  process.stdout.write(JSON.stringify(bind(loadNode(name), ctx)));
}

module.exports = { bind, loadNode, getResolvables, stringToArray, isJSON, evaluateToString };

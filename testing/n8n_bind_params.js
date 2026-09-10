// Bind a Postgres node's query parameters EXACTLY as n8n does at v2.5.
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
// node's helpers. Ported rather than imported: n8n is not a dependency of
// this repository and must not become one for a test to run. Same
// reasoning as scripts/trigram.py, which reimplements pg_trgm rather than
// requiring the extension in order to test the no-extension floor.
//
// The three behaviours that matter, all of which the first draft got wrong:
//
//   1. Literal text OUTSIDE {{ }} is discarded. "RUN_ENGINE_{{ engine }}"
//      binds "E1", not "RUN_ENGINE_E1".
//   2. null becomes the STRING 'null'. Bound to a uuid column that is an
//      error; bound to text it is worse, because it succeeds.
//   3. A resolved string that is not JSON is SPLIT ON COMMAS into several
//      parameters. One comma in an error message shifts every parameter
//      after it.
//
// The array form -- a single {{ [a, b, c] }} -- takes a different branch
// that has none of these behaviours: values pass through whole, null stays
// null, and objects are JSON.stringify'd. That is why every node uses it.
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
        const rawEvaluated = evaluate(resolvable, ctx);
        if (Array.isArray(rawEvaluated)) {
          for (const item of rawEvaluated) {
            if (item === undefined) continue;
            values.push(typeof item === 'object' && item !== null ? JSON.stringify(item) : item);
          }
          continue;
        }
        const asString = evaluateToString(rawEvaluated);
        const evaluated = isJSON(asString) ? [asString] : stringToArray(asString);
        if (evaluated.length) values.push(...evaluated);
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

// Runs the browser engine in Node on eval/questions.json and compares it with
// the Python pipeline's answers (from the latest `python -m eval.e2e` traces).
//
//   cd fieldmind-ui && node scripts/parity.mjs [embedDtype] [rerankDtype]   (default fp32 q8)
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createEngine } from "../src/engine/fieldmind.js";
import { loadModels } from "../src/engine/models.js";

const here = dirname(fileURLToPath(import.meta.url));
const ui = join(here, ".."), root = join(ui, "..");
const embedDtype = process.argv[2] || "fp32", rerankDtype = process.argv[3] || "q8";
const dtype = `${embedDtype}/${rerankDtype}`;

const { meta, chunks } = JSON.parse(readFileSync(join(ui, "public/data/chunks.json"), "utf8"));
const buf = readFileSync(join(ui, "public/data/embeddings.bin"));
const embeddings = new Float32Array(buf.buffer, buf.byteOffset, buf.byteLength / 4);
const qs = JSON.parse(readFileSync(join(root, "eval/questions.json"), "utf8"));

// Python reference: last e2e trace per question
const ref = new Map();
for (const line of readFileSync(join(root, "logs/traces.jsonl"), "utf8").split("\n")) {
  if (!line.trim()) continue;
  const t = JSON.parse(line);
  if (t.channel === "e2e") ref.set(t.question, t);
}

const norm = s => s.toLowerCase().split(/\s+/).filter(Boolean).join(" ");
function grade(answer, c) {
  const a = norm(answer);
  const contradicted = (c.must_not || []).some(p => a.includes(norm(p)));
  const groups = c.answer_facts || [[c.must_contain.at(-1)]];
  return groups.every(g => g.some(alt => a.includes(norm(alt)))) && !contradicted;
}

const t0 = Date.now();
const models = await loadModels({ embedDtype, rerankDtype });
console.log(`models (${dtype}) loaded in ${((Date.now() - t0) / 1000).toFixed(1)} s`);
const fm = createEngine({ chunks, embeddings, meta, ...models });

let facts = 0, same = 0, refused = 0, dDense = 0, n = 0;
const lat = [];
const cases = [...qs.in_scope.map(c => [c.q, c]), ...qs.out_of_scope.map(q => [q, null])];
for (const [q, c] of cases) {
  const r = await fm.ask(q);
  const answer = r.sentences.join(" ");
  const py = ref.get(q);
  lat.push(r.latencyMs);
  const match = py && norm(py.answer || "") === norm(answer);
  same += !!match;
  if (py?.retrieval && r.topDense !== undefined) { dDense = Math.max(dDense, Math.abs(py.retrieval.top_dense - r.topDense)); n++; }
  if (c) facts += r.reason === "ok" && grade(answer, c);
  else refused += r.escalate;
  if (!match) console.log(`DIFF ${q}\n   js: ${answer.slice(0, 160)}\n   py: ${(py?.answer || "?").slice(0, 160)}`);
}
lat.sort((a, b) => a - b);
console.log(`key fact ${facts}/${qs.in_scope.length}, out-of-scope refused ${refused}/${qs.out_of_scope.length}, ` +
  `same answer as Python ${same}/${cases.length}, max |top_dense diff| ${dDense.toFixed(4)} over ${n}, ` +
  `median ${lat[lat.length >> 1]} ms`);

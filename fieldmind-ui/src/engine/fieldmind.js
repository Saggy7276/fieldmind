// FieldMind answer engine for the browser: a line-by-line port of the Python
// extractive pipeline (rag/retriever.py, rag/guardrails.py, rag/extract.py,
// rag/pipeline.py). Keep the two in step; eval/web_parity.mjs compares them.
//
//   const fm = createEngine({ chunks, embeddings, meta, embed, rerank })
//   const r  = await fm.ask("how often do the pump bearings need lubricating")
//   r = { sentences: [...], escalate, reason, sources: [...], latencyMs }
//
// embed(texts) -> Float32Array[] (L2-normalised MiniLM vectors)
// rerank(question, passages) -> number[] (cross-encoder logits)

// ── text helpers (rag/chunking.py, rag/retriever.py) ─────────────────────────
const STOPWORDS = new Set(
  ("a an and are as at be by can do does for from how i if in is it its me my of on or " +
   "should so that the their there these this to was what when where which who why will " +
   "with you your we our").split(" "));
const TOKEN_RE = /[a-z0-9]+(?:[-./][a-z0-9]+)*/g;

export function tokenize(text) {
  return (text.toLowerCase().match(TOKEN_RE) || []).filter(t => !STOPWORDS.has(t));
}

const words = s => s.split(/\s+/).filter(Boolean);
const SENT_RE = /(?<=[.!?])\s+(?=[A-Z0-9"([])/;
const LIST_RE = /^\s*(?:[-*+]|\d+\.)\s+/;
const TABLE_RE = /^\s*\|/;
const HEADING_RE = /^(#{1,6})\s+(.*)$/;
const isStructural = line => LIST_RE.test(line) || TABLE_RE.test(line) || HEADING_RE.test(line.trim());

function logicalLines(text) {
  const out = [], para = [];
  const flush = () => { if (para.length) { out.push(para.join(" ")); para.length = 0; } };
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) flush();
    else if (isStructural(raw)) { flush(); out.push(line); }
    else para.push(line.replace(/^[> ]+/, "").trim());
  }
  flush();
  return out;
}

export function splitSentences(text) {
  const units = [];
  for (const line of logicalLines(text)) {
    if (isStructural(line)) units.push(line);
    else for (const s of line.split(SENT_RE)) if (s.trim()) units.push(s.trim());
  }
  return units;
}

// ── retrieval (rag/retriever.py) ─────────────────────────────────────────────
class BM25 {
  constructor(docs, k1 = 1.5, b = 0.75) {
    this.k1 = k1; this.b = b;
    this.tfs = docs.map(d => {
      const tf = new Map();
      for (const t of tokenize(d)) tf.set(t, (tf.get(t) || 0) + 1);
      return tf;
    });
    this.lens = this.tfs.map(tf => [...tf.values()].reduce((a, c) => a + c, 0));
    this.avgLen = this.lens.reduce((a, c) => a + c, 0) / (docs.length || 1);
    const df = new Map();
    for (const tf of this.tfs) for (const t of tf.keys()) df.set(t, (df.get(t) || 0) + 1);
    const n = docs.length;
    this.idf = new Map([...df].map(([t, f]) => [t, Math.log(1 + (n - f + 0.5) / (f + 0.5))]));
  }
  scores(query) {
    const out = new Float64Array(this.tfs.length);
    for (const term of new Set(tokenize(query))) {
      const idf = this.idf.get(term);
      if (idf === undefined) continue;
      this.tfs.forEach((tf, i) => {
        const f = tf.get(term) || 0;
        if (!f) return;
        const norm = this.k1 * (1 - this.b + this.b * this.lens[i] / (this.avgLen || 1));
        out[i] += idf * f * (this.k1 + 1) / (f + norm);
      });
    }
    return out;
  }
}

function rrf(rankings, k = 60) {
  const fused = new Map();
  for (const ranking of rankings)
    ranking.forEach((idx, rank) => fused.set(idx, (fused.get(idx) || 0) + 1 / (k + rank + 1)));
  return fused;
}

const argsortDesc = arr => [...arr.keys()].sort((a, b) => arr[b] - arr[a]);
const argmax = arr => arr.reduce((best, v, i) => (v > arr[best] ? i : best), 0);
const dot = (a, b) => { let s = 0; for (let i = 0; i < a.length; i++) s += a[i] * b[i]; return s; };

function citation(chunk) { return chunk.cite; }

// ── guardrails (rag/guardrails.py) ───────────────────────────────────────────
export const ESCALATE_MESSAGE = "I can't answer that reliably from the manuals. I'm passing this to a specialist.";
const EMERGENCY_MESSAGE = "This sounds like an emergency. Stop work, move to a safe place, " +
  "and call your site emergency number now.";
const EMERGENCY_RE = new RegExp(
  "\\b(fire|smoke|burning smell|injur\\w*|bleeding|unconscious|not breathing|" +
  "electric(?:al)? shock|electrocut\\w*|gas leak|explosion|collapsed|trapped|chemical spill)\\b", "i");
const INJECTION_RE = new RegExp(
  "(ignore (all |any |the |your )?(previous |above |prior )?(instructions|rules|prompt)|" +
  "disregard (the |all |your )?(previous |above )?(instructions|rules)|" +
  "(reveal|print|show|repeat) (me )?(your|the) (system )?(prompt|instructions)|" +
  "you are now|pretend (to be|you are)|jailbreak|developer mode)", "i");

export function checkInput(question, maxWords = 60) {
  const q = (question || "").trim();
  if (q.length < 3) return { ok: false, escalate: false, reason: "empty_input",
    message: "I didn't catch that. Please repeat the question." };
  if (EMERGENCY_RE.test(q)) return { ok: false, escalate: true, reason: "emergency_keyword", message: EMERGENCY_MESSAGE };
  if (INJECTION_RE.test(q)) return { ok: false, escalate: false, reason: "prompt_injection",
    message: "I can only answer questions about the equipment documentation." };
  if (words(q).length > maxWords) return { ok: false, escalate: false, reason: "input_too_long",
    message: "Please ask one short question at a time." };
  return { ok: true };
}

// ── extractive answers (rag/extract.py) ──────────────────────────────────────
const MIN_WORDS = 5, MERGE_BELOW = 12, MAX_NOISE = 0.4;
const WORD_RE = /^[A-Za-z][A-Za-z'’-]+[.,;:!?)]*$/;
const CONNECTIVE_RE = /^(consequently|however|therefore|thus|in addition|additionally|also|similarly|for example|in general|as a result|accordingly)\s*,\s*/i;
const LIST_ITEM_RE = /^\s*(?:[-*+•]|\d+[.)])\s+/;
const END_RE = /[.!?:;)"'”]$/;
const GLOSSARY_RE = /^[a-z][\w\s()/,-]{0,60} [–—-] [A-Z]/;
const GLOSSARY_SPLIT_RE = /(?<=[.)])\s+(?=[a-z][\w\s()/,-]{0,60} [–—] [A-Z])/;
const CAPTION_RE = /(?<!see )(?<!See )\bFigure \d+\.(?!\d)/;
const ANAPHOR_RE = /^(this|these|that|those|it|they|such)\b/i;
const isLower = c => !!c && c === c.toLowerCase() && c !== c.toUpperCase();

function bodyAndCrumb(text) {
  if (text.startsWith("[") && text.includes("\n")) {
    const i = text.indexOf("\n");
    return [text.slice(i + 1), text.slice(0, i).replace(/^[[\]]+|[[\]]+$/g, "")];
  }
  return [text, ""];
}

function split(body) {
  const out = [];
  for (const s of splitSentences(body)) for (const p of s.split(GLOSSARY_SPLIT_RE)) if (p.trim()) out.push(p);
  return out;
}

export function units(body) {
  const out = [];
  let afterList = false;
  for (let s of split(body)) {
    s = s.trim();
    if (LIST_ITEM_RE.test(s)) {
      const item = s.replace(LIST_ITEM_RE, "").replace(/[;, ]+$/, "");
      out.push(/[.!?]$/.test(item) ? item : item + ".");
      afterList = true;
      continue;
    }
    const complete = END_RE.test(s) && !s.endsWith(":");
    const last = out[out.length - 1];
    if (out.length && complete && !afterList && /[.!?]$/.test(last) &&
        (words(s).length < MERGE_BELOW || ANAPHOR_RE.test(s))) {
      out[out.length - 1] = last + " " + s;
    } else out.push(s);
    afterList = false;
  }
  return out;
}

export function noiseRatio(text) {
  const toks = words(text);
  return toks.length ? toks.filter(t => !WORD_RE.test(t)).length / toks.length : 1;
}

export function isFragment(unit) {
  const u = unit.trim();
  if (u.endsWith(":") || u.startsWith("(")) return true;
  if (noiseRatio(words(u).slice(0, 8).join(" ")) > MAX_NOISE) return true;
  if (isLower(u[0]) && !GLOSSARY_RE.test(u)) return true;
  return CAPTION_RE.test(u);
}

export function speakable(sentence) {
  let s = sentence.trim().replace(CONNECTIVE_RE, "");
  const i = s.lastIndexOf(":");
  if (i > 0 && noiseRatio(s.slice(i + 1)) > MAX_NOISE) s = s.slice(0, i).trimEnd() + ".";
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

function similar(a, b, threshold = 0.7) {
  const ta = new Set(tokenize(a)), tb = new Set(tokenize(b));
  if (!ta.size || !tb.size) return false;
  let inter = 0;
  for (const t of ta) if (tb.has(t)) inter++;
  return inter / Math.min(ta.size, tb.size) >= threshold;
}

// ── the engine ───────────────────────────────────────────────────────────────
export function createEngine({ chunks, embeddings, meta, embed, rerank }) {
  const dim = meta.dim;
  const texts = chunks.map(c => c.text);
  const vec = i => embeddings.subarray(i * dim, (i + 1) * dim);
  const bm25 = new BM25(texts);

  async function search(query, topK) {
    const [q] = await embed([query]);
    const dense = chunks.map((_, i) => dot(vec(i), q));
    const sparse = bm25.scores(query);
    const c = 20;
    const denseRank = argsortDesc(dense).slice(0, c);
    const sparseRank = argsortDesc(Array.from(sparse)).slice(0, c).filter(i => sparse[i] > 0);
    const fused = rrf([denseRank, sparseRank]);
    const order = [...fused.keys()].sort((a, b) => fused.get(b) - fused.get(a)).slice(0, topK);
    const terms = new Set(tokenize(query));
    let keywordMatch = false;
    if (terms.size && Math.max(...sparse) > 0) {
      const top = argmax(dense);
      keywordMatch = top === argmax(Array.from(sparse)) && [...terms].every(t => bm25.tfs[top].has(t));
    }
    return { hits: order.map(i => ({ index: i, ...chunks[i] })), topDense: Math.max(...dense), keywordMatch };
  }

  async function candidates(question, hits, n) {
    const cands = [], keys = [], seen = new Set();
    for (const h of hits) {
      const [body, crumb] = bodyAndCrumb(h.text);
      const us = units(body);
      us.forEach((u, pos) => {
        if (words(u).length < MIN_WORDS || seen.has(u) || isFragment(u) || noiseRatio(speakable(u)) > MAX_NOISE) return;
        if (pos === us.length - 1 && !END_RE.test(u)) return;
        seen.add(u);
        cands.push({ text: u, hit: h, position: pos, crumb });
        keys.push(`${crumb} ${u}`.trim());
      });
    }
    if (!cands.length) return [];
    const [qv, ...sv] = await embed([question, ...keys]);
    const dense = sv.map(v => dot(v, qv));
    const terms = new Set(tokenize(question));
    const overlap = keys.map(k => { const ks = new Set(tokenize(k)); let n = 0; for (const t of terms) if (ks.has(t)) n++; return n; });
    const fused = rrf([argsortDesc(dense), argsortDesc(overlap)]);
    return [...fused.keys()].sort((a, b) => fused.get(b) - fused.get(a)).slice(0, n).map(i => cands[i]);
  }

  async function rerankPicks(question, cands, maxPicks = 2, maxGap = 1.0) {
    const passages = cands.map(c => `${c.crumb.split(" > ").pop()}: ${c.text}`.replace(/^[: ]+/, ""));
    const scores = await rerank(question, passages);
    const order = [...scores.keys()].sort((a, b) => scores[b] - scores[a]);
    const picks = [];
    for (const i of order) {
      if (picks.length === maxPicks || scores[order[0]] - scores[i] >= maxGap) break;
      if (!picks.some(j => similar(cands[i].text, cands[j].text))) picks.push(i);
    }
    let chosen = picks.map(i => cands[i]);
    if (chosen.length === 2 && chosen[0].hit.id === chosen[1].hit.id) chosen = [...chosen].sort((a, b) => a.position - b.position);
    return { chosen, scores: picks.map(i => scores[i]) };
  }

  async function ask(question) {
    const t0 = performance.now();
    const done = (fields) => ({ sentences: [], escalate: false, sources: [], ...fields,
      latencyMs: Math.round(performance.now() - t0) });
    const q = (question || "").trim();

    const input = checkInput(q);
    if (!input.ok) return done({ sentences: [input.message], escalate: input.escalate, reason: input.reason });

    const result = await search(q, meta.top_k);
    const sources = [...new Set(result.hits.map(citation))];
    const retrievalOk = result.topDense >= meta.min_score ||
      (result.keywordMatch && result.topDense >= meta.keyword_floor);
    if (!retrievalOk)
      return done({ sentences: [ESCALATE_MESSAGE], escalate: true, reason: "low_retrieval_confidence",
        topDense: result.topDense });

    const cands = await candidates(q, result.hits, meta.candidates);
    if (!cands.length) return done({ sentences: [ESCALATE_MESSAGE], escalate: true, reason: "empty_answer", sources });

    const { chosen, scores } = await rerankPicks(q, cands, meta.max_picks);
    const sentences = chosen.map((c, i) => {
      let t = speakable(c.text).replace(/\[\/?INST\]|<<\/?SYS>>|<\/?s>/g, "").replace(/\s+/g, " ").trim();
      if (i === 0) t = t.replace(/^[^a-zA-Z0-9"'(]+/, "");
      return t;
    }).filter(Boolean);
    return done({ sentences, reason: "ok", topDense: result.topDense, scores,
      sources: [...new Set([...chosen.map(c => citation(c.hit)), ...sources])] });
  }

  return { ask, search };
}

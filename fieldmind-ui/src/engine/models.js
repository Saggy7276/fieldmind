// Loads the two small models with transformers.js (ONNX, runs in the browser
// or in Node). Same models as the Python server:
//   embedder  all-MiniLM-L6-v2            (question + sentence vectors)
//   reranker  ms-marco-MiniLM-L-6-v2      (picks the sentence to read out)
import { AutoModelForSequenceClassification, AutoTokenizer, pipeline } from "@huggingface/transformers";

export const EMBED_REPO = "Xenova/all-MiniLM-L6-v2";
export const RERANK_REPO = "Xenova/ms-marco-MiniLM-L-6-v2";

// The embedder stays fp32 so cosine scores - and therefore the refusal
// thresholds - match the Python index exactly; q8 drifts by up to 0.04.
// The reranker only orders sentences, where q8 is indistinguishable.
export async function loadModels({ embedDtype = "fp32", rerankDtype = "q8", onProgress } = {}) {
  const progress_callback = onProgress;
  const [extractor, tokenizer, model] = await Promise.all([
    pipeline("feature-extraction", EMBED_REPO, { dtype: embedDtype, progress_callback }),
    AutoTokenizer.from_pretrained(RERANK_REPO, { progress_callback }),
    AutoModelForSequenceClassification.from_pretrained(RERANK_REPO, { dtype: rerankDtype, progress_callback }),
  ]);

  async function embed(texts) {
    const out = [];
    for (let i = 0; i < texts.length; i += 32) {  // small batches keep memory flat on phones
      const t = await extractor(texts.slice(i, i + 32), { pooling: "mean", normalize: true });
      const [n, d] = t.dims;
      for (let j = 0; j < n; j++) out.push(t.data.subarray(j * d, (j + 1) * d));
    }
    return out;
  }

  async function rerank(question, passages) {
    const inputs = tokenizer(new Array(passages.length).fill(question), {
      text_pair: passages, padding: true, truncation: true,
    });
    const { logits } = await model(inputs);
    return Array.from(logits.data);
  }

  return { embed, rerank };
}

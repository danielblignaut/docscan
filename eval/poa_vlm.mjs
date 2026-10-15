// Zero-shot proof-of-address extraction with a small off-the-shelf VLM, in
// Node on the CPU (onnxruntime-node), for comparison with the trained tagger.
// Generation is constrained to the same JSON schema the demo's result uses,
// with @huggingface/transformers-structured-output; greedy decoding.
//
//   node eval/poa_vlm.mjs --model smolvlm-256m --items /tmp/docscan-poa/eval/items.json --out /tmp/docscan-poa/eval/vlm-smolvlm-256m.jsonl [--long 1024]
//
// `items.json`: [{"id", "image", "truth"}] (eval/poa_eval.py --make-items
// writes it). The models download from the Hugging Face Hub into
// $HF_CACHE (default /tmp/poa-vlm/hf-cache) on first use; this script is an
// offline benchmark, not part of the app, which never calls a third party.
//
// Needs @huggingface/transformers 4.3.1 and
// @huggingface/transformers-structured-output 4.3.1 (eval/vlm/package.json).
import { appendFileSync, readFileSync, writeFileSync } from "node:fs";
import {
  AutoModelForVision2Seq,
  AutoProcessor,
  env,
  Qwen3_5ForConditionalGeneration,
  RawImage,
} from "@huggingface/transformers";
import { StructuredOutputProcessor } from "@huggingface/transformers-structured-output";

const arg = (name, def) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : def;
};

env.cacheDir = process.env.HF_CACHE ?? "/tmp/poa-vlm/hf-cache";

// dtypes per model: the smallest quantisations that run on the CPU provider
// (q4 = MatMulNBits, q8 = int8 weights). fp16 weights are WebGPU-oriented.
const MODELS = {
  "smolvlm-256m": { id: "HuggingFaceTB/SmolVLM-256M-Instruct", cls: AutoModelForVision2Seq, dtype: { embed_tokens: "q8", vision_encoder: "q8", decoder_model_merged: "q4" } },
  "smolvlm-500m": { id: "HuggingFaceTB/SmolVLM-500M-Instruct", cls: AutoModelForVision2Seq, dtype: { embed_tokens: "q8", vision_encoder: "q8", decoder_model_merged: "q4" } },
  "qwen3.5-0.8b": { id: "onnx-community/Qwen3.5-0.8B-ONNX", cls: Qwen3_5ForConditionalGeneration, dtype: { embed_tokens: "q4", vision_encoder: "q4", decoder_model_merged: "q4" }, template: { enable_thinking: false } },
};

const PROVINCES = ["Eastern Cape", "Free State", "Gauteng", "KwaZulu-Natal", "Limpopo", "Mpumalanga", "North West", "Northern Cape", "Western Cape"];
// Nullable values are `type: [..., "null"]`: in 4.3.1 a `maxLength` inside
// an `anyOf` branch is not enforced (measured: the model then runs on inside
// a string until max_new_tokens), while one beside a type array is.
const str = (max, min = 0) => ({ type: ["string", "null"], maxLength: max, ...(min ? { minLength: min } : {}) });
// The JSON engine cannot enforce `pattern` or `format` incrementally (its
// README), so the 4-digit code and ISO dates are bounded by length here and
// validated afterwards by the same checks the app runs.
export const SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["holder_name", "address", "document_date", "statement_period", "issuer", "account_number", "document_type"],
  properties: {
    holder_name: str(60),
    address: {
      type: "object",
      additionalProperties: false,
      required: ["street", "suburb", "city", "province", "postal_code"],
      properties: {
        street: str(60),
        suburb: str(40),
        city: str(40),
        province: { enum: [...PROVINCES, null] },
        postal_code: str(4, 4),
      },
    },
    document_date: str(10, 10),
    statement_period: {
      type: ["object", "null"],
      additionalProperties: false,
      required: ["from", "to"],
      properties: { from: str(10, 10), to: str(10, 10) },
    },
    issuer: str(60),
    account_number: str(30),
    document_type: { enum: ["utility_bill", "bank_statement", "municipal_account", "cellphone_account", "lease_agreement", "insurance_statement", "other"] },
  },
};

const PROMPT =
  "This is a South African proof-of-address document (a bill, statement or lease). " +
  "Extract the account holder's name and the holder's own residential address (the address the document is sent to, " +
  "not the issuer's head office, branch or PO Box), the document's issue date and statement period as YYYY-MM-DD, " +
  "the issuer's name and the account number. Use null for anything not printed. Answer in JSON.";

function vmHwmMb() {
  const m = readFileSync("/proc/self/status", "utf8").match(/VmHWM:\s+(\d+) kB/);
  return m ? Math.round(Number(m[1]) / 1024) : null;
}

async function main() {
  const name = arg("model", "smolvlm-256m");
  const cfg = MODELS[name];
  if (!cfg) throw new Error(`unknown model ${name}: ${Object.keys(MODELS)}`);
  const items = JSON.parse(readFileSync(arg("items"), "utf8"));
  const out = arg("out");
  const long = Number(arg("long", "1024"));
  const limit = Number(arg("limit", "0"));
  writeFileSync(out, "");

  const t0 = performance.now();
  const processor = await AutoProcessor.from_pretrained(cfg.id);
  const model = await cfg.cls.from_pretrained(cfg.id, { dtype: cfg.dtype, device: "cpu" });
  StructuredOutputProcessor.warmup(processor.tokenizer);
  const loadMs = performance.now() - t0;
  console.error(`${name} loaded in ${Math.round(loadMs)} ms, rss ${vmHwmMb()} MB`);

  const messages = [{ role: "user", content: [{ type: "image" }, { type: "text", text: PROMPT }] }];
  const text = processor.apply_chat_template(messages, { add_generation_prompt: true, ...(cfg.template ?? {}) });
  for (const [n, item] of items.entries()) {
    if (limit && n >= limit) break;
    let image = await RawImage.read(item.image);
    const k = Math.min(1, long / Math.max(image.width, image.height));
    if (k < 1) image = await image.resize(Math.round(image.width * k), Math.round(image.height * k));
    const t1 = performance.now();
    const inputs = await processor(text, image);
    const logits_processor = new StructuredOutputProcessor(processor.tokenizer, { type: "json_schema", json_schema: SCHEMA });
    const outputs = await model.generate({ ...inputs, max_new_tokens: 320, do_sample: false, logits_processor });
    const decoded = processor.batch_decode(outputs.slice(null, [inputs.input_ids.dims.at(-1), null]), { skip_special_tokens: true })[0];
    const ms = performance.now() - t1;
    let fields = null;
    try {
      fields = JSON.parse(decoded);
    } catch {}
    const rec = { id: item.id, image: item.image, model: name, long, ms: Math.round(ms), input_tokens: inputs.input_ids.dims.at(-1), raw: decoded, fields, rss_peak_mb: vmHwmMb() };
    appendFileSync(out, `${JSON.stringify(rec)}\n`);
    console.error(`${n + 1}/${items.length} ${item.id} ${Math.round(ms)} ms ${rec.input_tokens} tokens`);
  }
  console.error(JSON.stringify({ model: name, load_ms: Math.round(loadMs), rss_peak_mb: vmHwmMb() }));
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});

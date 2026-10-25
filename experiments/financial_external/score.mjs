#!/usr/bin/env node
// financial-external-v1 referee. Runs one extractor snapshot on frozen OCR or native text inputs and scores rows, cells,
// summary values and checks against the frozen gold (protocol.json). Aggregates (counts, document ids) go to
// results/; values, alignments and reports stay private under DATA/financial-external-v1/scores/.
//
//   node experiments/financial_external/score.mjs --engine=DIR --arm=ocr --ocr=KEY [--sets=a,b] [--label=name]
//   node experiments/financial_external/score.mjs --engine=DIR --arm=native [--label=name]
import { registerHooks } from "node:module";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve as resolvePath } from "node:path";
import { pathToFileURL } from "node:url";
import { scoreDocument } from "./scoring.mjs";

registerHooks({ resolve(specifier, context, next) {
  if (specifier.startsWith("./") && specifier.endsWith(".js") && context.parentURL?.startsWith("file:")) {
    const ts = new URL(specifier.slice(0, -3) + ".ts", context.parentURL);
    if (existsSync(ts)) return next(ts.href, context);
  }
  return next(specifier, context);
} });

const arg = (name, fallback) => process.argv.find((a) => a.startsWith(`--${name}=`))?.slice(name.length + 3) ?? fallback;
const DATA = process.env.DOCSCAN_PUBLIC_DATA ?? "/tmp/docscan-public-data";
const ROOT = `${DATA}/financial-external-v1`;
const HERE = new URL("./", import.meta.url);
const sha = (b) => createHash("sha256").update(b).digest("hex");
process.umask(0o077);

const engineDir = resolvePath(arg("engine", `${ROOT}/engines/baseline`));
const arm = arg("arm", "ocr");
const label = arg("label", "run");
const ENGINE = pathToFileURL(engineDir + "/");
const engineSha = sha(readdirSync(engineDir).filter((f) => f.endsWith(".ts")).sort().map((f) => `${f}\n${readFileSync(`${engineDir}/${f}`, "utf8")}`).join("\n"));
const { extractFinancialTables, linesFromPdfTextItems } = await import(new URL("index.ts", ENGINE).href);

const freeze = JSON.parse(readFileSync(new URL("freeze.json", HERE), "utf8"));
const goldBytes = readFileSync(`${ROOT}/gold.json`);
if (sha(goldBytes) !== freeze.gold_sha256) throw new Error("gold.json differs from freeze");
const sets = arg("sets", arm === "native" ? "synthesized,bankstatemently" : "synthesized,bankstatemently,fatura_dev").split(",");
const docs = JSON.parse(goldBytes).documents.filter((d) => sets.includes(d.set) && (arm !== "native" || d.pdf));

let ocrDir = null, ocrProvenance = null;
if (arm === "ocr") {
  ocrDir = `${ROOT}/ocr/${arg("ocr")}`;
  ocrProvenance = JSON.parse(readFileSync(`${ocrDir}/complete.json`, "utf8"));
  if (ocrProvenance.gold_sha256 !== freeze.gold_sha256) throw new Error("OCR run was made for another gold");
}

function inputs(doc) {
  const pages = [], failedPages = [];
  if (arm === "ocr") {
    doc.images.forEach((image, pageIndex) => {
      const out = JSON.parse(readFileSync(`${ocrDir}/${doc.id}.p${pageIndex}.json`, "utf8"));
      if (out.image_sha256 !== sha(readFileSync(image))) throw new Error(`${doc.id} p${pageIndex} OCR is for another image`);
      if (out.error) { failedPages.push({ pageIndex, fileIndex: 0, reason: "ocr_failed" }); return; }
      const lines = (out.words?.length ? out.words : out.lines).map((l) => ({ text: l.text, x: l.x, y: l.y, w: l.w, h: l.h, ...(typeof l.line === "number" ? { line: l.line } : {}) }));
      pages.push({ pageIndex, fileIndex: 0, lines, width: out.page_size[0], height: out.page_size[1], source: "ppocr_v6_tiny_lines_original_pixels", trust: "extracted_unverified" });
    });
    return { pages, options: { failedPages, source: "ocr", trustStatus: "extracted_unverified" } };
  }
  const native = JSON.parse(readFileSync(`${ROOT}/native/${doc.id}.json`, "utf8"));
  if (native.pdf_sha256 !== sha(readFileSync(doc.pdf))) throw new Error(`${doc.id} native text is for another PDF`);
  for (const p of native.pages) {
    const { lines } = linesFromPdfTextItems(p.items, p.height);
    pages.push({ pageIndex: p.pageIndex, fileIndex: 0, lines, width: p.width, height: p.height, source: "pdf_text_layer_pdfjs", trust: "extracted_unverified" });
  }
  return { pages, options: { source: "pdf_text_layer", trustStatus: "extracted_unverified" } };
}

const perDoc = [], privateDetail = [];
for (const doc of docs) {
  const { pages, options } = inputs(doc);
  const report = extractFinancialTables(pages, options);
  const { counts, detail } = scoreDocument(doc, report, options.failedPages ?? []);
  perDoc.push({ set: doc.set, id: doc.id, ...counts });
  privateDetail.push({ id: doc.id, detail, report });
}

const SUM_SKIP = new Set(["set", "id", "document_kind"]);
const bySet = {};
for (const row of perDoc) {
  const agg = (bySet[row.set] ??= { documents: 0, document_kinds: {} });
  agg.documents++;
  agg.document_kinds[row.document_kind] = (agg.document_kinds[row.document_kind] ?? 0) + 1;
  for (const [k, v] of Object.entries(row)) if (!SUM_SKIP.has(k) && typeof v === "number") agg[k] = (agg[k] ?? 0) + v;
}
const result = {
  protocol: freeze.protocol, arm, label, engine_sha256: engineSha, gold_sha256: freeze.gold_sha256,
  scorer_sha256: sha(readFileSync(new URL("score.mjs", HERE))), scoring_sha256: sha(readFileSync(new URL("scoring.mjs", HERE))),
  ocr: ocrProvenance && { binary_sha256: ocrProvenance.binary_sha256, models: ocrProvenance.models },
  sets: bySet, documents: perDoc,
  note: arm === "native" ? "Native PDF text-layer diagnostic: untrusted, not pooled with OCR, not authentication." : "Image OCR arm.",
};
const name = `${label}-${arm}-${engineSha.slice(0, 12)}`;
mkdirSync(new URL("results/", HERE), { recursive: true });
const out = new URL(`results/${name}.json`, HERE);
const body = JSON.stringify(result, null, 1) + "\n";
if (existsSync(out) && readFileSync(out, "utf8") !== body) throw new Error(`${out.pathname} exists with different content`);
writeFileSync(out, body);
mkdirSync(`${ROOT}/scores`, { recursive: true });
writeFileSync(`${ROOT}/scores/${name}.json`, JSON.stringify(privateDetail) + "\n");
const show = ["documents", "gold_rows", "aligned_rows", "row_exact", "extra_rows", "cells_correct", "cells_total", "direction_unknown",
  "summary_correct", "summary_wrong", "summary_total", "consistent_supported", "consistent_false", "consistent_unverifiable",
  "false_credit_rows", "false_income_candidates", "abstentions", "failed_pages"];
for (const [set, agg] of Object.entries(bySet)) console.log(set, JSON.stringify(Object.fromEntries(show.filter((k) => k in agg).map((k) => [k, agg[k]]))));

#!/usr/bin/env node
// Native PDF text-layer diagnostic input: PDF.js getTextContent items, kept as PDF.js gives them. score.mjs converts them
// with the extractor's own linesFromPdfTextItems. Diagnostic only: untrusted, never pooled with OCR, never authentication.
//   node experiments/financial_external/native_text.mjs
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";

const DATA = process.env.DOCSCAN_PUBLIC_DATA ?? "/tmp/docscan-public-data";
const ROOT = `${DATA}/financial-external-v1`;
const HERE = new URL("./", import.meta.url);
const require = createRequire(new URL("../../demo/package.json", import.meta.url));
const pdfjs = await import(require.resolve("pdfjs-dist/legacy/build/pdf.mjs"));
const sha = (b) => createHash("sha256").update(b).digest("hex");
process.umask(0o077);

const freeze = JSON.parse(readFileSync(new URL("freeze.json", HERE), "utf8"));
const goldBytes = readFileSync(`${ROOT}/gold.json`);
if (sha(goldBytes) !== freeze.gold_sha256) throw new Error("gold.json differs from freeze");
const docs = JSON.parse(goldBytes).documents.filter((d) => d.pdf);
mkdirSync(`${ROOT}/native`, { recursive: true });
for (const d of docs) {
  const bytes = new Uint8Array(readFileSync(d.pdf));
  const pdf = await pdfjs.getDocument({ data: bytes.slice(), isEvalSupported: false, disableFontFace: true, verbosity: 0 }).promise;
  const pages = [];
  for (let n = 1; n <= pdf.numPages; n++) {
    const page = await pdf.getPage(n);
    const view = page.view; // [x0, y0, x1, y1] in PDF points
    const content = await page.getTextContent();
    const items = content.items.filter((it) => "str" in it).map((it) => ({ text: it.str, transform: it.transform, width: it.width, height: it.height }));
    pages.push({ pageIndex: n - 1, width: view[2] - view[0], height: view[3] - view[1], items });
  }
  writeFileSync(`${ROOT}/native/${d.id}.json`, JSON.stringify({ pdf_sha256: sha(bytes), pdfjs: pdfjs.version, pages }) + "\n");
  console.log(d.id, pdf.numPages, "pages", pages.reduce((s, p) => s + p.items.length, 0), "items");
}

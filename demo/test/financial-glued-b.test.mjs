// Shipped-engine regressions; frozen experiment originals are retained separately.
// Paired authored check for candidate B (label and value glued at a colon by OCR). Invented values only.
import assert from "node:assert/strict";
import { test } from "node:test";
import { registerHooks } from "node:module";
import { existsSync } from "node:fs";
import { pathToFileURL } from "node:url";

registerHooks({ resolve(specifier, context, next) {
  if (specifier.startsWith("./") && specifier.endsWith(".js") && context.parentURL?.startsWith("file:")) {
    const ts = new URL(specifier.slice(0, -3) + ".ts", context.parentURL);
    if (existsSync(ts)) return next(ts.href, context);
  }
  return next(specifier, context);
} });
const engine = new URL("../../demo/src/financial-tables/", import.meta.url).pathname;
const { extractFinancialTables } = await import(new URL("index.ts", pathToFileURL(engine.replace(/\/?$/, "/"))).href);

// Line-level OCR boxes, one per printed line, as PP-OCR returns them.
const box = (text, x, y) => ({ text, x, y, w: text.length * 11, h: 22 });
const invoice = (tail) => [{ pageIndex: 0, fileIndex: 0, lines: [
  box("Description", 80, 100), box("Qty", 600, 100), box("Unit Price", 760, 100), box("Amount", 1000, 100),
  box("Toy widget", 80, 140), box("2", 600, 140), box("50.00", 760, 140), box("100.00", 1000, 140),
  box("Toy gadget", 80, 180), box("1", 600, 180), box("20.00", 760, 180), box("20.00", 1000, 180),
  ...tail.map((t, i) => box(t, 700, 260 + i * 40)),
] }];
const value = (r, key) => r.summaryFields.filter((f) => f.key === key).map((f) => f.value?.value);

test("glued 'TOTAL:', 'SUB TOTAL:' and 'GST(n%):' values are read, with the rate kept", () => {
  const r = extractFinancialTables(invoice(["SUB TOTAL:120.00 USD", "GST(10%):12.00", "TOTAL:132.00 USD"]), { documentType: "invoice" });
  assert.deepEqual(value(r, "subtotal"), ["120.00"]);
  assert.deepEqual(value(r, "tax_total"), ["12.00"]);
  assert.deepEqual(value(r, "invoice_total"), ["132.00"]);
  assert.equal(r.summaryFields.find((f) => f.key === "tax_total").rate?.value, "10");
  assert.ok(r.summaryFields.find((f) => f.key === "invoice_total").source.parts.every((p) => p.approximate));
  assert.deepEqual(r.checks.filter((c) => c.code === "invoice_total").map((c) => c.status), ["consistent"]);
});

test("glued labels with wrong arithmetic are read and reported inconsistent, never consistent", () => {
  const r = extractFinancialTables(invoice(["SUB TOTAL:120.00", "GST(10%):12.00", "TOTAL:140.00"]), { documentType: "invoice" });
  assert.deepEqual(r.checks.filter((c) => c.code === "invoice_total").map((c) => c.status), ["inconsistent"]);
});

test("dates, references and unknown labels glued at a colon are not read as amounts", () => {
  const r = extractFinancialTables(invoice(["Due Date:12-Mar-2026", "Ref:2026", "Note:15.00", "TOTAL : 120.00"]), { documentType: "invoice" });
  assert.deepEqual(value(r, "invoice_total"), ["120.00"]);
  assert.equal(r.summaryFields.filter((f) => f.key !== "invoice_total" && f.key !== "page_number").length, 0);
});

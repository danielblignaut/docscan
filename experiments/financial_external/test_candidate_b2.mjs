// Authored preservation gates for candidate B2 (glued labels, with item rows guarded). Invented values only.
//   FT_ENGINE=/path/to/engine node --test experiments/financial_external/test_candidate_b2.mjs
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
const engine = process.env.FT_ENGINE ?? new URL("../../demo/src/financial-tables/", import.meta.url).pathname;
const { extractFinancialTables } = await import(new URL("index.ts", pathToFileURL(engine.replace(/\/?$/, "/"))).href);

const box = (text, x, y) => ({ text, x, y, w: text.length * 11, h: 22 });
// An item row prints description, quantity, unit price and amount in their header columns.
const item = (desc, qty, unit, amount, y) => [box(desc, 80, y), ...(qty ? [box(qty, 600, y)] : []), ...(unit ? [box(unit, 760, y)] : []), box(amount, 1000, y)];
const invoice = (items, footers = []) => [{ pageIndex: 0, fileIndex: 0, lines: [
  box("Description", 80, 100), box("Qty", 600, 100), box("Unit Price", 760, 100), box("Amount", 1000, 100),
  ...items.flatMap((it, i) => item(...it, 140 + i * 40)),
  ...footers.map((t, i) => box(t, 700, 140 + items.length * 40 + 40 + i * 40)),
] }];
const run = (items, footers) => extractFinancialTables(invoice(items, footers), { documentType: "invoice" });
const lineItems = (r) => r.tables.flatMap((t) => t.rows.filter((x) => x.kind === "line_item"));
const descs = (r) => lineItems(r).map((x) => x.cells.find((c) => c.role === "description")?.text);
const value = (r, key) => r.summaryFields.filter((f) => f.key === key).map((f) => f.value?.value);

for (const desc of ["Shipping:15.00 kit", "Tax:0.00 adjustment", "Shipping: 15.00 kit", "Total:12 pack"]) {
  const items = [["Toy widget", "2", "50.00", "100.00"], [desc, "1", "15.00", "15.00"], ["Toy gadget", "1", "20.00", "20.00"]];
  test(`preservation: an item described "${desc}" with quantity, unit price and amount stays an item, and later items are kept`, () => {
    const r = run(items, ["TOTAL : 135.00"]);
    assert.equal(lineItems(r).length, 3);
    assert.equal(descs(r)[2], "Toy gadget");
    assert.deepEqual(value(r, "shipping"), []);
  });
  test(`explicit: the "${desc}" item is flagged, and a glued footer after it is still read`, () => {
    const r = run(items, ["TOTAL:135.00"]);
    assert.ok(lineItems(r)[1]?.issues.includes("summary_label_in_line_item_description"));
    assert.deepEqual(value(r, "invoice_total"), ["135.00"]);
  });
}

test("genuine glued summary footers are still read and end the table", () => {
  const r = run([["Toy widget", "2", "50.00", "100.00"], ["Toy gadget", "1", "20.00", "20.00"]], ["SUB TOTAL:120.00", "Shipping:15.00", "GST(10%):12.00", "TOTAL:147.00"]);
  assert.equal(lineItems(r).length, 2);
  assert.deepEqual(value(r, "subtotal"), ["120.00"]);
  assert.deepEqual(value(r, "shipping"), ["15.00"]);
  assert.deepEqual(value(r, "tax_total"), ["12.00"]);
  assert.deepEqual(value(r, "invoice_total"), ["147.00"]);
});

test("a whole-unit glued footer 'Total:12' is read as the invoice total", () => {
  const r = run([["Toy pencil", "2", "5.00", "10.00"], ["Toy eraser", "1", "2.00", "2.00"]], ["Total:12"]);
  assert.equal(lineItems(r).length, 2);
  assert.deepEqual(value(r, "invoice_total").map(Number), [12]);
});

test("a label-like row with an amount and only a quantity is ambiguous: it ends the table and the table says so", () => {
  const r = run([["Toy widget", "2", "50.00", "100.00"], ["Shipping:15.00", "1", null, "15.00"], ["Toy gadget", "1", "20.00", "20.00"]]);
  assert.ok(r.tables[0].issues.some((x) => x.startsWith("summary_label_row_may_be_line_item")));
  assert.equal(r.tables[0].status, "partial");
});

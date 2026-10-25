// node --test experiments/financial_external/test_scoring_v2.mjs — scorer v2 rules (v1 tests plus the v2 gaps) on invented toy reports (no source data).
import assert from "node:assert/strict";
import { test } from "node:test";
import { alignRows, canonical, decimalEq, scoreDocument } from "./scoring_v2.mjs";

const money = (role, value) => ({ role, text: value, value: { type: "money", status: "parsed", value } });
const row = (id, { date = null, amount, role = "amount", direction = "debit", balance, desc = "", kind = "transaction" }) => ({
  id, kind, direction, issues: [],
  cells: [{ role: "date", text: date ?? "", value: { type: "date", iso: date } }, { role: "description", text: desc, value: { type: "text", text: desc } },
    ...(amount ? [money(role, amount)] : []), ...(balance ? [money("balance", balance)] : [])],
});
const report = (rows, extra = {}) => ({ documentKind: "bank_statement", tables: [{ kind: "bank_transactions", rows }], summaryFields: [], checks: [],
  observations: [], classifications: [], abstentions: [], ...extra });
const doc = (rows, summary = {}) => ({ kind: "bank", tables: [{ rows, has_balance: rows.every((r) => r.balance), summary }] });
const G = [{ date: "2026-01-02", alt_date: "2026-01-02", description: ["Toy pay"], amount: "100.00", balance: "150.00" },
  { date: "2026-01-03", alt_date: "2026-01-03", description: ["Toy shop"], amount: "-20.00", balance: "130.00" }];

test("decimals compare exactly without floats", () => {
  assert.equal(canonical("-0012.500"), "-12.5");
  assert.equal(canonical("0.00"), "0");
  assert.ok(decimalEq("14.8", "14.80"));
  assert.ok(!decimalEq("1,234.00", "1234"));
});

test("alignment is order-preserving and one-to-one, never a bag of values", () => {
  const pred = [row("a", { amount: "20.00" }), row("b", { amount: "100.00" })];
  assert.equal(alignRows(G, pred).length, 1); // swapped order aligns only one row
});

test("every gold cell stays in the denominator and a direction-less amount is not correct", () => {
  const pred = [row("a", { date: "2026-01-02", amount: "100.00", direction: "unknown", balance: "150.00", desc: "TOY PAY ref" })];
  const { counts } = scoreDocument(doc(G), report(pred), []);
  assert.equal(counts.gold_rows, 2); assert.equal(counts.aligned_rows, 1); assert.equal(counts.missed_rows, 1);
  assert.equal(counts.cells_total, 8); assert.equal(counts.cells_correct, 3); assert.equal(counts.direction_unknown, 1); assert.equal(counts.row_exact, 0);
});

test("a charge read as a credit is a false credit and makes income claims on it false", () => {
  const pred = [row("a", { amount: "100.00", direction: "credit" }), row("b", { amount: "20.00", direction: "credit" })];
  const rep = report(pred, { classifications: [{ rowId: "b", label: "salary_like" }, { rowId: "a", label: "salary_like" }] });
  const { counts } = scoreDocument(doc(G), rep, []);
  assert.equal(counts.false_credit_rows, 1); assert.equal(counts.income_like_emitted, 2); assert.equal(counts.false_income_candidates, 1);
});

test("consistent claims citing an extra row or a wrong summary value are false; correct ones are supported", () => {
  const pred = [row("a", { amount: "100.00", direction: "credit", balance: "150.00", date: "2026-01-02", desc: "toy pay" }), row("x", { amount: "5.00" })];
  const rep = report(pred, {
    summaryFields: [{ id: "s1", key: "opening_balance", value: { status: "parsed", value: "50.00" } }, { id: "s2", key: "closing_balance", value: { status: "parsed", value: "999.00" } }],
    checks: [{ code: "running_balance", status: "consistent", rowIds: ["a"], summaryIds: ["s1"] },
      { code: "running_balance", status: "consistent", rowIds: ["x"], summaryIds: [] },
      { code: "opening_plus_credits_minus_debits_equals_closing", status: "consistent", rowIds: [], summaryIds: ["s1", "s2"] }],
  });
  const { counts } = scoreDocument(doc(G, { opening: "50.00", closing: "130.00" }), rep, []);
  assert.equal(counts.consistent_supported, 1); assert.equal(counts.consistent_false, 2);
  assert.equal(counts.extra_rows, 1); assert.equal(counts.summary_correct, 1); assert.equal(counts.summary_wrong, 1);
});

test("invoice: totals the gold says do not add up can never be consistent; line-item checks are unverifiable", () => {
  const inv = { kind: "invoice", invoice: { summary: { subtotal: ["10.00"], invoice_total: ["12.00"] }, total_arithmetic: "inconsistent" } };
  const rep = { ...report([]), tables: [], summaryFields: [{ id: "s", key: "subtotal", value: { status: "parsed", value: "10.00" } }],
    checks: [{ code: "invoice_total", status: "consistent", rowIds: [], summaryIds: ["s"] }, { code: "invoice_subtotal", status: "consistent", rowIds: [], summaryIds: ["s"] }] };
  const { counts } = scoreDocument(inv, rep, []);
  assert.equal(counts.consistent_false, 1); assert.equal(counts.consistent_unverifiable, 1);
  assert.equal(counts.summary_total, 2); assert.equal(counts.summary_correct, 1); assert.equal(counts.summary_missing, 1);
});

test("v2: a running_balance citing only details[] is verified through each link, so a wrong linked balance is false", () => {
  const pred = [row("a", { amount: "100.00", direction: "credit", balance: "150.00", date: "2026-01-02", desc: "toy pay" }),
    row("b", { amount: "20.00", direction: "debit", balance: "131.00", date: "2026-01-03", desc: "toy shop" })];
  const link = (rowId, previousRowId) => ({ rowId, previousRowId, status: "consistent" });
  const rep = report(pred, { checks: [
    { code: "running_balance", status: "consistent", rowIds: [], summaryIds: [], details: [link("b", "a")] },
    { code: "running_balance", status: "consistent", rowIds: [], summaryIds: [], details: [{ ...link("b", "a"), status: "not_evaluable" }, link("a", null)] },
  ] });
  const { counts } = scoreDocument(doc(G), rep, []);
  assert.equal(counts.consistent_false, 1, "the link to the misread 131.00 balance makes the claim false");
  assert.equal(counts.consistent_supported, 1, "a not_evaluable link is not a claim");
});

test("v2: a consistent check citing no row, link or summary value is unverifiable, not supported", () => {
  const rep = report([], { checks: [{ code: "running_balance", status: "consistent", rowIds: [], summaryIds: [], details: [] }] });
  const { counts } = scoreDocument(doc(G), rep, []);
  assert.equal(counts.consistent_unverifiable, 1); assert.equal(counts.consistent_supported, 0);
});

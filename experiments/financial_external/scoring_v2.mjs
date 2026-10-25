// Pure scoring rules for financial-external-v1, scorer v2 (protocol.json "scoring" plus "scorer_v2"). v1 (scoring.mjs) is
// kept unchanged with its outputs. v2 differs in two places only: a check's per-link details[].rowId/previousRowId are
// cited rows like rowIds (v1 ignored them, so a running_balance citing only details was never verified), and a
// "consistent" check that cites nothing at all is unverifiable, not supported. No extractor import: the referee reads only
// the report's emitted values (ISO dates, decimal strings, text) and the frozen gold.

/** Canonical decimal string (no float): "-0012.500" -> "-12.5", "0.00" -> "0". Null for anything else. */
export function canonical(value) {
  if (typeof value !== "string") return null;
  const m = /^([+-]?)(\d+)(?:\.(\d+))?$/.exec(value.trim());
  if (!m) return null;
  const int = m[2].replace(/^0+(?=\d)/, "");
  const frac = (m[3] ?? "").replace(/0+$/, "");
  const zero = /^0*$/.test(int) && !frac;
  return zero ? "0" : `${m[1] === "-" ? "-" : ""}${int}${frac ? "." + frac : ""}`;
}
export const decimalEq = (a, b) => canonical(a) !== null && canonical(a) === canonical(b);
const abs = (v) => (canonical(v) ?? "").replace(/^-/, "");
const neg = (v) => { const c = canonical(v); return c === null ? null : c === "0" ? "0" : c.startsWith("-") ? c.slice(1) : "-" + c; };
export const normText = (s) => (s ?? "").normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();

const cellsOf = (row, roles) => row.cells.filter((c) => roles.includes(c.role));
const parsedMoney = (c) => (c?.value?.type === "money" && c.value.status === "parsed" ? c.value.value : null);

/** The predicted magnitude a row moves by: the nonzero parsed amount, debit or credit cell. */
export function rowMagnitude(row) {
  const values = cellsOf(row, ["amount", "debit", "credit"]).map(parsedMoney).filter((v) => v !== null && canonical(v) !== "0");
  return values.length === 1 ? abs(values[0]) : null;
}
export function rowSigned(row) {
  const m = rowMagnitude(row);
  if (m === null) return null;
  return row.direction === "credit" ? m : row.direction === "debit" ? neg(m) : null;
}

/** Order-preserving one-to-one alignment (LCS) on exact magnitude. Returns [goldIndex, predIndex] pairs. */
export function alignRows(gold, pred) {
  const g = gold.map((r) => abs(r.amount)), p = pred.map(rowMagnitude);
  const n = g.length, m = p.length;
  const L = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    L[i][j] = p[j] !== null && g[i] === p[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const pairs = [];
  for (let i = 0, j = 0; i < n && j < m;) {
    if (p[j] !== null && g[i] === p[j] && L[i][j] === L[i + 1][j + 1] + 1) { pairs.push([i, j]); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) i++; else j++;
  }
  return pairs;
}

const OPENING = ["opening_balance", "brought_forward"], CLOSING = ["closing_balance", "carried_forward"];
const SUMMARY_KEYS = { opening: OPENING, closing: CLOSING, total_debits: ["total_debits"], total_credits: ["total_credits"],
  subtotal: ["subtotal"], tax_total: ["tax_total"], discount: ["discount"], invoice_total: ["invoice_total"] };
const MAGNITUDE_KEYS = new Set(["discount", "total_debits", "total_credits"]);

function scoreSummary(goldSummary, report, counts) {
  for (const [key, goldValues] of Object.entries(goldSummary)) {
    const values = [].concat(goldValues);
    const fields = report.summaryFields.filter((f) => SUMMARY_KEYS[key].includes(f.key) && f.value?.status === "parsed");
    const predicted = fields.map((f) => (MAGNITUDE_KEYS.has(key) ? abs(f.value.value) : canonical(f.value.value)));
    const used = new Set();
    for (const g of values) {
      counts.summary_total++;
      const target = MAGNITUDE_KEYS.has(key) ? abs(g) : canonical(g);
      const hit = predicted.findIndex((v, i) => !used.has(i) && v === target);
      if (hit >= 0) { used.add(hit); counts.summary_correct++; }
      else if (fields.length) counts.summary_wrong++;
      else counts.summary_missing++;
    }
    if (new Set(predicted).size > values.length) counts.summary_conflicting++;
  }
}

function goldSummaryValue(goldSummary, summaryKey) {
  for (const [key, keys] of Object.entries(SUMMARY_KEYS)) if (keys.includes(summaryKey) && goldSummary && key in goldSummary) return { key, value: goldSummary[key] };
  return null;
}

export function scoreDocument(doc, report, failedPages) {
  const counts = { document_kind: report.documentKind, gold_rows: 0, aligned_rows: 0, row_exact: 0, missed_rows: 0, extra_rows: 0,
    cells_total: 0, cells_correct: 0, date_correct: 0, amount_correct: 0, balance_correct: 0, balance_total: 0, description_correct: 0,
    description_strict: 0, direction_unknown: 0, false_credit_rows: 0, false_debit_rows: 0,
    summary_total: 0, summary_correct: 0, summary_wrong: 0, summary_missing: 0, summary_conflicting: 0,
    checks_emitted: 0, consistent_supported: 0, consistent_false: 0, consistent_unverifiable: 0, inconsistent_claims: 0, inconsistent_false_alarm: 0,
    gold_relations: 0, relation_consistent: 0, relation_inconsistent: 0, relation_not_evaluable: 0, relation_absent: 0,
    income_like_emitted: 0, false_income_candidates: 0, tables: report.tables.length, bank_tables: 0, invoice_tables: 0, other_tables: 0,
    line_item_rows_unscored: 0, abstentions: report.abstentions.length, failed_pages: failedPages.length,
    total_arithmetic_gold_inconsistent: 0, invoice_total_check_consistent: 0 };
  const detail = { rows: [], extra: [], checks: [] };
  const rowInfo = new Map(); // predicted row id -> { aligned: bool, amountOk, balanceOk, goldAmount }
  for (const t of report.tables) {
    if (t.kind === "bank_transactions") counts.bank_tables++; else if (t.kind === "invoice_line_items") counts.invoice_tables++; else counts.other_tables++;
  }

  if (doc.kind === "bank") {
    const goldTable = doc.tables[0];
    const gold = goldTable.rows;
    const pred = report.tables.filter((t) => t.kind === "bank_transactions").flatMap((t) => t.rows.filter((r) => r.kind === "transaction"));
    const pairs = alignRows(gold, pred);
    counts.gold_rows = gold.length; counts.aligned_rows = pairs.length; counts.missed_rows = gold.length - pairs.length;
    counts.extra_rows = pred.length - pairs.length;
    const alignedPred = new Set(pairs.map(([, j]) => j));
    pred.forEach((r, j) => { if (!alignedPred.has(j)) { rowInfo.set(r.id, { aligned: false }); detail.extra.push({ rowId: r.id, magnitude: rowMagnitude(r), kind: r.kind }); } });
    const perCellTotal = 3 + (goldTable.has_balance ? 1 : 0);
    counts.cells_total = gold.length * perCellTotal;
    counts.balance_total = goldTable.has_balance ? gold.length : 0;
    for (const [i, j] of pairs) {
      const g = gold[i], r = pred[j];
      const dates = cellsOf(r, ["date"]).length ? cellsOf(r, ["date"]) : cellsOf(r, ["value_date"]);
      const dateOk = dates.some((c) => c.value?.iso && (c.value.iso === g.date || c.value.iso === g.alt_date));
      const signed = rowSigned(r);
      const amountOk = signed !== null && decimalEq(signed, g.amount);
      if (signed === null) counts.direction_unknown++;
      else if (!amountOk && decimalEq(neg(signed), g.amount)) { if (r.direction === "credit") counts.false_credit_rows++; else counts.false_debit_rows++; }
      const balanceCell = cellsOf(r, ["balance"]).map(parsedMoney).find((v) => v !== null) ?? null;
      const balanceOk = goldTable.has_balance ? decimalEq(balanceCell, g.balance) : null;
      const desc = normText(cellsOf(r, ["description"]).map((c) => c.text).join(" "));
      const descOk = desc.includes(normText(g.description[0]));
      const descStrict = desc === normText(g.description.join(" "));
      counts.date_correct += +dateOk; counts.amount_correct += +amountOk; counts.description_correct += +descOk; counts.description_strict += +descStrict;
      if (goldTable.has_balance) counts.balance_correct += +balanceOk;
      counts.cells_correct += +dateOk + +amountOk + +descOk + (goldTable.has_balance ? +balanceOk : 0);
      const exact = dateOk && amountOk && descOk && (balanceOk !== false);
      counts.row_exact += +exact;
      rowInfo.set(r.id, { aligned: true, amountOk, balanceOk, goldAmount: g.amount, hasBalanceCell: balanceCell !== null });
      detail.rows.push({ gold: i, rowId: r.id, dateOk, amountOk, balanceOk, descOk, direction: r.direction, directionSource: r.directionSource, issues: r.issues });
    }
    // Opening/closing/forward/total rows cited by checks are verified against the gold summary.
    for (const t of report.tables) for (const r of t.rows) if (r.kind !== "transaction" && !rowInfo.has(r.id)) {
      const kindKey = OPENING.includes(r.kind) ? "opening" : CLOSING.includes(r.kind) ? "closing" : null;
      const bal = cellsOf(r, ["balance"]).map(parsedMoney).find((v) => v !== null) ?? null;
      rowInfo.set(r.id, kindKey && goldTable.summary?.[kindKey] !== undefined ? { aligned: true, amountOk: decimalEq(bal, goldTable.summary[kindKey]), balanceOk: decimalEq(bal, goldTable.summary[kindKey]), summaryRow: true }
        : { unverifiable: true });
    }
    scoreSummary(goldTable.summary ?? {}, report, counts);
    // Gold relations: every listed bank statement closes by construction (checked in prepare.py).
    const relations = ["opening_plus_credits_minus_debits_equals_closing", ...(goldTable.has_balance ? ["running_balance"] : []), ...(goldTable.summary?.total_debits ? ["statement_totals"] : [])];
    for (const code of relations) {
      counts.gold_relations++;
      const cs = report.checks.filter((c) => c.code === code);
      const status = !cs.length ? "absent" : cs.some((c) => c.status === "inconsistent") ? "inconsistent" : cs.every((c) => c.status === "consistent") ? "consistent" : "not_evaluable";
      counts[`relation_${status}`]++;
    }
  } else {
    scoreSummary(doc.invoice.summary, report, counts);
    counts.line_item_rows_unscored = report.tables.filter((t) => t.kind === "invoice_line_items").reduce((s, t) => s + t.rows.filter((r) => r.kind === "line_item").length, 0);
    if (doc.invoice.total_arithmetic === "inconsistent") counts.total_arithmetic_gold_inconsistent++;
  }

  // Checks: every "consistent" claim is supported, false, or unverifiable; "inconsistent" claims on gold-closing bank
  // documents are false alarms only when every cited value is correct (otherwise the misread is the cause, already counted).
  for (const c of report.checks) {
    counts.checks_emitted++;
    if (c.status === "not_evaluable") continue;
    let wrong = false, unverifiable = false;
    const linked = (c.details ?? []).filter((x) => x.status !== "not_evaluable").flatMap((x) => [x.rowId, x.previousRowId]).filter(Boolean);
    const cited = [...new Set([...c.rowIds, ...linked])];
    if (!cited.length && !c.summaryIds.length) unverifiable = true;
    for (const id of cited) {
      const info = rowInfo.get(id);
      if (!info || info.unverifiable) { unverifiable = true; continue; }
      if (!info.aligned || !info.amountOk || info.balanceOk === false) wrong = true;
    }
    for (const id of c.summaryIds) {
      const f = report.summaryFields.find((s) => s.id === id);
      const g = f && goldSummaryValue(doc.kind === "bank" ? doc.tables[0].summary : doc.invoice.summary, f.key);
      if (!g) { if (f && !["page_number", "currency_declaration", "statement_period"].includes(f.key)) unverifiable = true; continue; }
      const gv = [].concat(g.value);
      const pv = f.value?.status === "parsed" ? f.value.value : null;
      if (!gv.some((v) => (MAGNITUDE_KEYS.has(g.key) ? abs(pv) === abs(v) : decimalEq(pv, v)))) wrong = true;
    }
    if (doc.kind === "invoice" && c.code === "invoice_total") {
      if (c.status === "consistent") counts.invoice_total_check_consistent++;
      if (doc.invoice.total_arithmetic === "inconsistent" && c.status === "consistent") wrong = true;
      if (doc.invoice.total_arithmetic === null) unverifiable = true;
    }
    if (doc.kind === "invoice" && ["invoice_subtotal", "line_quantity_times_unit_price", "line_tax"].includes(c.code)) unverifiable = true;
    if (c.status === "consistent") {
      if (wrong) counts.consistent_false++; else if (unverifiable) counts.consistent_unverifiable++; else counts.consistent_supported++;
    } else {
      counts.inconsistent_claims++;
      if (doc.kind === "bank" && !wrong && !unverifiable) counts.inconsistent_false_alarm++;
    }
    detail.checks.push({ id: c.id, code: c.code, status: c.status, wrong, unverifiable });
  }

  // Income-like outputs citing anything but an aligned gold credit row are false.
  const goldCredit = (id) => { const info = rowInfo.get(id); return info?.aligned && !info.summaryRow && info.goldAmount && !info.goldAmount.startsWith("-"); };
  const incomeLike = [
    ...report.observations.filter((o) => o.code === "recurring_credit_candidate").map((o) => o.rowIds),
    ...report.classifications.filter((c) => c.label === "salary_like").map((c) => [c.rowId]),
  ];
  counts.income_like_emitted = incomeLike.length;
  counts.false_income_candidates = incomeLike.filter((ids) => !ids.length || ids.some((id) => !goldCredit(id))).length;
  return { counts, detail };
}

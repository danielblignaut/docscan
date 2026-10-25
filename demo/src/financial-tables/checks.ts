/** Arithmetic agreement between printed numbers. `consistent` never means valid, complete or authentic. */
import { abs, add, cmp, dec, eq, isZero, mul, neg, percentOf, round, sub, sum, toDecimalString, type Dec } from "./decimal.js";
import { currencyKey, moneyDec } from "./money.js";
import { cellDec, cellOf, rowDelta } from "./tables.js";
import type { CheckCode, CheckDetail, FinancialCheck, FinancialTable, MoneyValue, SummaryField, SummaryKey, TableCell, TableRow } from "./types.js";
import { pushTo } from "./util.js";

const s = (d: Dec | null) => (d ? toDecimalString(d) : null);

let seq = 0;
function check(code: CheckCode, tableId: string | null, init: Partial<FinancialCheck>): FinancialCheck {
  return { id: `k${++seq}`, code, status: "not_evaluable", tableId, completeness: "unknown", currency: null, expected: null, observed: null, difference: null,
    basis: null, reason: "", rowIds: [], summaryIds: [], ...init };
}
export function resetCheckIds() { seq = 0; }

/** Compare a printed value with a computed one: exact, or equal after rounding the computed value to the printed scale. */
function agree(printed: Dec, computed: Dec): string | null {
  if (eq(printed, computed)) return "exact";
  if (computed.s > printed.s) {
    if (eq(round(computed, printed.s, "half_up"), printed)) return "half_up_rounding";
    if (eq(round(computed, printed.s, "half_even"), printed)) return "half_even_rounding";
  }
  return null;
}

function moneyOf(cell: TableCell | undefined): MoneyValue | null {
  return cell && cell.value.type === "money" ? cell.value : null;
}
/** A balance: `DR` means overdrawn (negative), `CR` or no marker positive. */
function balanceDec(cell: TableCell | undefined): Dec | null {
  const m = moneyOf(cell);
  const d = moneyDec(m);
  if (!d || !m) return null;
  if (m.marker === "DR" && !m.negative) return neg(d);
  return d;
}
/** The value a balance-style row carries: its balance cell, else the one amount it prints. */
function rowBalance(row: TableRow): Dec | null {
  return balanceDec(cellOf(row, "balance")) ?? balanceDec(cellOf(row, "amount")) ?? balanceDec(cellOf(row, "credit")) ?? balanceDec(cellOf(row, "debit"));
}

function currencies(values: (MoneyValue | null | undefined)[]): { key: string | null; mixed: boolean } {
  const keys = new Set(values.map((v) => (v ? currencyKey(v.currency) : null)).filter((k): k is string => !!k));
  return { key: keys.size === 1 ? [...keys][0] : null, mixed: keys.size > 1 };
}

const fieldsOf = (fields: SummaryField[], tableId: string, key: SummaryKey) => fields.filter((f) => f.tableId === tableId && f.key === key && f.value?.status === "parsed");

export interface CheckContext {
  /** Tables whose pages are known to be incomplete (missing pages, header-less pages that did not parse). */
  incompleteTables: Set<string>;
  /** Tables of a document with pages that failed to read: their total-level checks are not evaluated. */
  totalsBlocked?: Set<string>;
}

const TOTAL_LEVEL = new Set<CheckCode>(["opening_plus_credits_minus_debits_equals_closing", "statement_totals", "invoice_subtotal", "invoice_tax", "invoice_total", "payslip_gross", "payslip_deductions", "payslip_net"]);

function completeness(table: FinancialTable, ctx: CheckContext): FinancialCheck["completeness"] {
  return table.status === "parsed" && !ctx.incompleteTables.has(table.id) ? "complete" : "incomplete";
}

// ---------------------------------------------------------------- bank

function runningBalance(table: FinancialTable, reverse: boolean, apply: boolean): { details: CheckDetail[]; bad: number } {
  const rows = (reverse ? [...table.rows].reverse() : table.rows).filter((r) => r.kind !== "total");
  const details: CheckDetail[] = [];
  let anchor: { row: TableRow; bal: Dec } | null = null;
  let pending: TableRow[] = [];
  let bad = 0;
  for (const row of rows) {
    const isBalanceRow = row.kind !== "transaction";
    const bal = isBalanceRow ? rowBalance(row) : balanceDec(cellOf(row, "balance"));
    // Reversed, a newest-first table reads oldest-first, so one rule fits both: balance = previous + movements since.
    if (!isBalanceRow) pending.push(row);
    if (!bal) continue;
    if (!anchor) { anchor = { row, bal }; pending = []; continue; }
    const deltas = pending.map((r) => ({ r, d: rowDelta(r) }));
    const unknown = deltas.filter((x) => !x.d);
    const known = sum(deltas.filter((x) => x.d).map((x) => x.d as Dec));
    const fromBal = anchor.bal;
    const toBal = bal;
    const detail: CheckDetail = { rowId: row.id, previousRowId: anchor.row.id, status: "not_evaluable", expected: s(toBal), observed: null };
    const assumed = pending.some((r) => r.directionSource === "sign_convention");
    if (!unknown.length && assumed) {
      // Unmarked amounts were read as credits by the minus convention. A statement whose balance is an amount
      // owed (a credit card) fits the same arithmetic with the opposite meaning, so this is not independent.
      const computed = add(fromBal, known);
      detail.observed = s(computed);
      detail.basis = "direction_from_sign_convention";
      detail.reason = eq(computed, toBal) ? "agrees_only_under_the_assumed_sign_convention" : "disagrees_under_the_assumed_sign_convention";
    } else if (!unknown.length) {
      const computed = add(fromBal, known);
      detail.observed = s(computed);
      detail.status = eq(computed, toBal) ? "consistent" : "inconsistent";
      detail.basis = "printed_directions";
    } else if (unknown.length === 1) {
      // One unsigned amount: the balance change says which way it moved. Only the magnitude is then checked.
      const u = unknown[0].r;
      const mag = abs(cellDec(cellOf(u, "amount")) ?? cellDec(cellOf(u, "debit")) ?? cellDec(cellOf(u, "credit")) ?? dec(0n, 0));
      const change = sub(sub(toBal, fromBal), known);
      if (!isZero(mag) && eq(abs(change), mag)) {
        // The direction is read off this very balance change, so agreement is by construction: not independent evidence.
        detail.status = "not_evaluable"; detail.basis = "magnitude_only_direction_from_balance"; detail.observed = s(toBal);
        detail.reason = "direction_taken_from_this_balance_change";
        if (apply && u.direction === "unknown") {
          u.direction = change.u < 0n ? "debit" : "credit"; u.directionSource = "balance_delta";
          // An amount whose debit/credit column was a guess moves to the side the balance shows, and says so.
          if (u.issues.includes("debit_credit_column_ambiguous")) {
            const target = table.columns.find((c) => c.role === u.direction);
            const cell = u.cells.find((c) => c.role === "debit" || c.role === "credit");
            if (target && cell && cell.role !== target.role) { cell.role = target.role; cell.column = target.key; u.issues.push("moved_to_side_shown_by_balance"); }
          }
        }
      } else if (isZero(mag)) { detail.reason = "amount_unreadable"; }
      else { detail.status = "inconsistent"; detail.basis = "magnitude_only"; detail.observed = s(add(fromBal, add(known, mag))); }
    } else detail.reason = "several_amounts_without_direction";
    if (detail.status === "inconsistent") bad++;
    details.push(detail);
    anchor = { row, bal };
    pending = [];
  }
  return { details, bad };
}

function bankChecks(table: FinancialTable, fields: SummaryField[], ctx: CheckContext): FinancialCheck[] {
  const out: FinancialCheck[] = [];
  const comp = completeness(table, ctx);
  const cur = currencies(table.rows.flatMap((r) => r.cells.map(moneyOf)));
  const currency = table.currency.status === "single" ? currencyKey(table.currency.marks[0]) : null;
  // Running balance, in the printed order the dates establish (or the one the balances agree with).
  const hasBalances = table.rows.filter((r) => cellOf(r, "balance")).length >= 2;
  if (!hasBalances) out.push(check("running_balance", table.id, { reason: "Fewer than two printed balances: there is nothing to chain.", completeness: comp }));
  else if (cur.mixed) out.push(check("running_balance", table.id, { reason: "Amounts are in more than one currency; balances are not chained across currencies.", completeness: comp }));
  else {
    let reverse = table.order === "descending";
    if (table.order === "unknown" || table.order === "unordered") {
      const up = runningBalance(table, false, false), down = runningBalance(table, true, false);
      if (down.bad < up.bad && down.details.some((d) => d.status === "consistent")) { reverse = true; table.order = "descending"; table.orderSource = "balance_progression"; }
    }
    const { details } = runningBalance(table, reverse, true);
    const counts = { consistent: 0, inconsistent: 0, not_evaluable: 0 };
    for (const d of details) counts[d.status]++;
    const status = counts.inconsistent ? "inconsistent" : counts.consistent && !counts.not_evaluable ? "consistent" : "not_evaluable";
    out.push(check("running_balance", table.id, {
      status, completeness: comp, currency, details, counts, rowIds: details.filter((d) => d.status === "inconsistent").map((d) => d.rowId),
      basis: details.some((d) => d.basis?.startsWith("magnitude")) ? "some_links_magnitude_only" : details.some((d) => d.basis === "direction_from_sign_convention") ? "some_links_sign_convention" : "printed_directions",
      reason: status === "consistent" ? `Each of ${counts.consistent} printed balances follows from the previous one and the amounts between them.`
        : status === "inconsistent" ? `${counts.inconsistent} of ${details.length} balance links do not follow from the previous balance and the amounts between them.`
          : `${counts.not_evaluable} balance links could not be evaluated independently (unreadable amounts, or directions taken from the balances themselves)${counts.consistent ? `; ${counts.consistent} others agree` : ""}.`,
    }));
  }
  // Opening + credits - debits = closing.
  const openingRow = table.rows.find((r) => r.kind === "opening_balance");
  const closingRow = [...table.rows].reverse().find((r) => r.kind === "closing_balance");
  const openingField = fieldsOf(fields, table.id, "opening_balance")[0] ?? (table.order === "descending" ? undefined : undefined);
  const closingField = fieldsOf(fields, table.id, "closing_balance").slice(-1)[0];
  const opening = (openingRow && rowBalance(openingRow)) ?? moneyDec(openingField?.value);
  const closing = (closingRow && rowBalance(closingRow)) ?? moneyDec(closingField?.value);
  const txns = table.rows.filter((r) => r.kind === "transaction");
  const deltas = txns.map(rowDelta);
  const summaryIds = [openingField, closingField].filter((f) => f && (!openingRow || f !== openingField) && (!closingRow || f !== closingField)).map((f) => (f as SummaryField).id);
  const base = { completeness: comp, currency, summaryIds, rowIds: [openingRow?.id, closingRow?.id].filter((x): x is string => !!x) };
  const sumCurr = currencies([moneyOf(openingRow && (cellOf(openingRow, "balance") ?? cellOf(openingRow, "amount"))), openingField?.value, closingField?.value, ...table.rows.flatMap((r) => r.cells.map(moneyOf))]);
  const startsBf = table.issues.includes("starts_with_brought_forward_earlier_pages_not_supplied");
  const endsCf = table.issues.includes("ends_with_carried_forward_later_pages_not_supplied");
  // Pages before or after were not supplied: even a page-level opening or closing printed in a summary box is
  // not the statement's, so the statement's totals are not evaluated.
  if (startsBf || endsCf) out.push(check("opening_plus_credits_minus_debits_equals_closing", table.id, { ...base, completeness: "incomplete",
    reason: startsBf ? "The table starts with a brought-forward balance: earlier pages were not supplied, so the statement's totals cannot be checked."
      : "The table ends with a carried-forward balance: later pages were not supplied, so the statement's totals cannot be checked." }));
  else if (!opening || !closing) out.push(check("opening_plus_credits_minus_debits_equals_closing", table.id, { ...base, completeness: startsBf || endsCf ? "incomplete" : base.completeness,
    reason: !opening && startsBf ? "The table starts with a brought-forward balance and no opening balance: earlier pages were not supplied, so the statement's totals cannot be checked."
      : !closing && endsCf ? "The table ends with a carried-forward balance and no closing balance: later pages were not supplied, so the statement's totals cannot be checked."
        : `No readable ${!opening ? "opening" : "closing"} balance was found for this table.` }));
  else if (sumCurr.mixed) out.push(check("opening_plus_credits_minus_debits_equals_closing", table.id, { ...base, reason: "Opening, closing and transaction amounts are not all in one currency." }));
  else if (txns.some((r) => r.directionSource === "balance_delta" || r.directionSource === "sign_convention")) {
    const inferred = txns.filter((r) => r.directionSource === "balance_delta").map((r) => r.id);
    const convention = txns.filter((r) => r.directionSource === "sign_convention").map((r) => r.id);
    out.push(check("opening_plus_credits_minus_debits_equals_closing", table.id, { ...base, rowIds: [...inferred, ...convention],
      basis: inferred.length ? "some_directions_inferred_from_balance_changes" : "some_directions_from_sign_convention",
      reason: inferred.length ? `${inferred.length} transaction directions were taken from the running balance, so a total built from them would agree with the balances by construction.`
        : `${convention.length} unmarked amounts were read as credits only by the minus convention; a statement of an amount owed (a credit card) fits the same arithmetic with the opposite meaning.` }));
  } else if (deltas.some((d) => !d)) {
    const missing = txns.filter((_, i) => !deltas[i]).map((r) => r.id);
    out.push(check("opening_plus_credits_minus_debits_equals_closing", table.id, { ...base, rowIds: missing, reason: `${missing.length} transaction amounts are unreadable or have no established direction, so the sum is unknown.` }));
  } else {
    const credits = sum(deltas.filter((d) => (d as Dec).u > 0n) as Dec[]);
    const debits = abs(sum(deltas.filter((d) => (d as Dec).u < 0n) as Dec[]));
    const computed = sub(add(opening, credits), debits);
    const ok = eq(computed, closing);
    const inferred = txns.some((r) => r.directionSource === "balance_delta");
    out.push(check("opening_plus_credits_minus_debits_equals_closing", table.id, {
      ...base, status: ok ? "consistent" : "inconsistent", expected: s(closing), observed: s(computed), difference: s(sub(closing, computed)),
      basis: inferred ? "some_directions_inferred_from_balance_changes" : "printed_directions",
      reason: `${s(opening)} opening + ${s(credits)} credits - ${s(debits)} debits = ${s(computed)}; printed closing ${s(closing)}.` + (ok ? "" : " Rows or pages may be missing, mis-read or altered.")
        + (comp === "incomplete" ? " Some rows had reading issues, so agreement covers only what was read." : ""),
    }));
  }
  if (openingRow && openingField && rowBalance(openingRow) && moneyDec(openingField.value) && !eq(rowBalance(openingRow) as Dec, moneyDec(openingField.value) as Dec))
    out.push(check("opening_plus_credits_minus_debits_equals_closing", table.id, { status: "inconsistent", completeness: comp, expected: s(moneyDec(openingField.value)), observed: s(rowBalance(openingRow)), rowIds: [openingRow.id], summaryIds: [openingField.id], basis: "opening_row_vs_summary", reason: "The opening balance in the table differs from the opening balance printed in the summary." }));
  // Printed totals.
  const totalRow = table.rows.find((r) => r.kind === "total");
  for (const [key, dir] of [["total_debits", "debit"], ["total_credits", "credit"]] as const) {
    const f = fieldsOf(fields, table.id, key)[0];
    const printed = moneyDec(f?.value) ?? (totalRow ? cellDec(cellOf(totalRow, dir)) : null);
    if (!printed) continue;
    const ds = txns.filter((r) => r.direction === dir).map(rowDelta);
    const unknown = txns.some((r) => r.direction === "unknown" || r.directionSource === "balance_delta" || r.directionSource === "sign_convention" || !rowDelta(r));
    const computed = abs(sum(ds.filter((d): d is Dec => !!d)));
    out.push(check("statement_totals", table.id, unknown ? { completeness: comp, currency, reason: `Some transactions have no readable amount or direction; ${key.replace("_", " ")} cannot be summed.`, summaryIds: f ? [f.id] : [], rowIds: totalRow ? [totalRow.id] : [] } : {
      status: eq(abs(printed), computed) ? "consistent" : "inconsistent", completeness: comp, currency, expected: s(abs(printed)), observed: s(computed), difference: s(sub(abs(printed), computed)),
      basis: key, reason: `Printed ${key.replace("_", " ")} ${s(abs(printed))}; the ${dir} rows sum to ${s(computed)}.`, summaryIds: f ? [f.id] : [], rowIds: totalRow ? [totalRow.id] : [],
    }));
  }
  // Carried forward at the foot of a page = brought forward at the top of the next.
  for (let i = 0; i < table.rows.length; i++) {
    const cf = table.rows[i];
    if (cf.kind !== "carried_forward") continue;
    const bf = table.rows.slice(i + 1).find((r) => r.kind === "brought_forward" || r.kind === "transaction");
    if (!bf || bf.kind !== "brought_forward") { out.push(check("page_carry_forward", table.id, { completeness: comp, currency, rowIds: [cf.id], reason: "A carried-forward balance has no brought-forward balance on the next page." })); continue; }
    const a = rowBalance(cf), b = rowBalance(bf);
    out.push(check("page_carry_forward", table.id, a && b ? { status: eq(a, b) ? "consistent" : "inconsistent", completeness: comp, currency, expected: s(a), observed: s(b), difference: s(sub(a, b)), rowIds: [cf.id, bf.id], basis: "exact",
      reason: eq(a, b) ? `Page ${cf.pageIndex + 1} carries forward ${s(a)} and page ${bf.pageIndex + 1} brings forward the same.` : `Page ${cf.pageIndex + 1} carries forward ${s(a)} but page ${bf.pageIndex + 1} brings forward ${s(b)}.` }
      : { completeness: comp, currency, rowIds: [cf.id, bf.id], reason: "A carried- or brought-forward balance is unreadable." }));
  }
  return out;
}

// ---------------------------------------------------------------- invoice

function lineArithmetic(code: CheckCode, rows: TableRow[], tableId: string, comp: FinancialCheck["completeness"], currency: string | null): FinancialCheck {
  const details: CheckDetail[] = [];
  for (const r of rows) {
    const q = cellDec(cellOf(r, "quantity")), p = cellDec(cellOf(r, "unit_price")), a = cellDec(cellOf(r, "amount"));
    if (!cellOf(r, "quantity") && !cellOf(r, "unit_price")) continue;
    if (!q || !p || !a) { details.push({ rowId: r.id, status: "not_evaluable", expected: s(a), observed: null, reason: "quantity, unit price or amount unreadable or missing" }); continue; }
    const product = mul(q, p);
    let basis = agree(a, product);
    let observed = product;
    const t = cellDec(cellOf(r, "tax"));
    if (!basis && t) { const incl = add(product, t); const b2 = agree(a, incl); if (b2) { basis = `amount_includes_line_tax_${b2}`; observed = incl; } }
    details.push({ rowId: r.id, status: basis ? "consistent" : "inconsistent", expected: s(a), observed: s(observed), basis });
  }
  const counts = { consistent: 0, inconsistent: 0, not_evaluable: 0 };
  for (const d of details) counts[d.status]++;
  if (!details.length) return check(code, tableId, { completeness: comp, currency, reason: "No line prints both a quantity and a unit price." });
  const status = counts.inconsistent ? "inconsistent" : counts.not_evaluable ? (counts.consistent ? "not_evaluable" : "not_evaluable") : "consistent";
  return check(code, tableId, { status, completeness: counts.not_evaluable ? "incomplete" : comp, currency, details, counts, rowIds: details.filter((d) => d.status === "inconsistent").map((d) => d.rowId),
    reason: `${counts.consistent} lines agree (quantity × unit price = amount), ${counts.inconsistent} disagree, ${counts.not_evaluable} could not be evaluated.` });
}

function invoiceChecks(table: FinancialTable, fields: SummaryField[], ctx: CheckContext): FinancialCheck[] {
  const out: FinancialCheck[] = [];
  const comp = completeness(table, ctx);
  const lines = table.rows.filter((r) => r.kind === "line_item");
  const allMoney = [...lines.flatMap((r) => r.cells.map(moneyOf)), ...fields.filter((f) => f.tableId === table.id).map((f) => f.value)];
  const cur = currencies(allMoney);
  const currency = cur.key;
  if (cur.mixed) {
    out.push(check("invoice_total", table.id, { completeness: comp, reason: "Line items or totals are in more than one currency; no totals are computed across currencies." }));
    return out;
  }
  out.push(lineArithmetic("line_quantity_times_unit_price", lines, table.id, comp, currency));
  // Line tax from a printed rate.
  const taxed = lines.filter((r) => cellOf(r, "tax_rate") && cellOf(r, "tax"));
  if (taxed.length) {
    const details: CheckDetail[] = taxed.map((r) => {
      const rate = cellDec(cellOf(r, "tax_rate")), tax = cellDec(cellOf(r, "tax")), amount = cellDec(cellOf(r, "amount"));
      if (!rate || !tax || !amount) return { rowId: r.id, status: "not_evaluable", expected: s(tax), observed: null, reason: "rate, tax or amount unreadable" };
      const computed = percentOf(amount, rate);
      const b = agree(tax, computed);
      return { rowId: r.id, status: b ? "consistent" : "inconsistent", expected: s(tax), observed: s(round(computed, tax.s, "half_up")), basis: b };
    });
    const bad = details.filter((d) => d.status === "inconsistent").length, ne = details.filter((d) => d.status === "not_evaluable").length;
    out.push(check("line_tax", table.id, { status: bad ? "inconsistent" : ne ? "not_evaluable" : "consistent", completeness: comp, currency, details, rowIds: details.filter((d) => d.status === "inconsistent").map((d) => d.rowId),
      reason: `${details.length - bad - ne} line tax amounts agree with amount × rate, ${bad} disagree, ${ne} unreadable.` }));
  }
  const amounts = lines.map((r) => cellDec(cellOf(r, "amount")));
  const unreadable = lines.filter((_, i) => !amounts[i]).map((r) => r.id);
  const lineSum = unreadable.length ? null : sum(amounts as Dec[]);
  const f = (k: SummaryKey) => fieldsOf(fields, table.id, k).slice(-1)[0];
  const subtotalF = f("subtotal"), taxF = f("tax_total"), totalF = f("invoice_total"), discountF = f("discount"), shippingF = f("shipping");
  const subtotal = moneyDec(subtotalF?.value), tax = moneyDec(taxF?.value), total = moneyDec(totalF?.value);
  const discount = moneyDec(discountF?.value), shipping = moneyDec(shippingF?.value);
  const notReadable = `${unreadable.length} line amounts are unreadable or missing, so the line total is unknown.`;
  if (subtotal) {
    out.push(check("invoice_subtotal", table.id, lineSum ? { status: eq(lineSum, subtotal) ? "consistent" : "inconsistent", completeness: comp, currency, expected: s(subtotal), observed: s(lineSum), difference: s(sub(subtotal, lineSum)), basis: "sum_of_line_amounts", summaryIds: [subtotalF.id], reason: `Line amounts sum to ${s(lineSum)}; printed subtotal ${s(subtotal)}.` }
      : { completeness: "incomplete", currency, rowIds: unreadable, summaryIds: [subtotalF.id], reason: notReadable }));
  }
  if (tax) {
    const lineTaxes = lines.map((r) => cellDec(cellOf(r, "tax")));
    const rate = taxF.rate?.status === "parsed" && taxF.rate.units !== null && taxF.rate.scale !== null ? dec(taxF.rate.units, taxF.rate.scale) : null;
    const base = subtotal ?? lineSum;
    if (lines.some((r) => cellOf(r, "tax")) && lineTaxes.every((t) => t)) {
      const st = sum(lineTaxes as Dec[]);
      out.push(check("invoice_tax", table.id, { status: eq(st, tax) ? "consistent" : "inconsistent", completeness: comp, currency, expected: s(tax), observed: s(st), difference: s(sub(tax, st)), basis: "sum_of_line_tax", summaryIds: [taxF.id], reason: `Line tax sums to ${s(st)}; printed tax ${s(tax)}.` }));
    } else if (rate && base) {
      const computed = percentOf(base, rate);
      let basis = agree(tax, computed);
      const diff = sub(tax, round(computed, tax.s, "half_up"));
      // Tax rounded per line can differ from tax on the subtotal by up to half a minor unit per line.
      if (!basis && lines.length > 1 && cmp(abs(mul(diff, dec(2n, 0))), dec(BigInt(lines.length), tax.s)) <= 0) basis = `within_per_line_rounding_${lines.length}_lines`;
      out.push(check("invoice_tax", table.id, { status: basis ? "consistent" : "inconsistent", completeness: comp, currency, expected: s(tax), observed: s(round(computed, tax.s, "half_up")), difference: s(diff), basis, summaryIds: [taxF.id],
        reason: `${s(base)} × ${s(rate)}% = ${s(computed)}; printed tax ${s(tax)}.` }));
    } else out.push(check("invoice_tax", table.id, { completeness: comp, currency, summaryIds: [taxF.id], reason: "No tax rate is printed with the tax total and no line prints tax, so the tax cannot be recomputed." }));
  }
  if (total) {
    const base = subtotal ?? (tax ? lineSum : null);
    if (base) {
      let computed = base;
      if (tax) computed = add(computed, tax);
      if (discount) computed = sub(computed, abs(discount));
      if (shipping) computed = add(computed, shipping);
      const parts = [subtotal ? "subtotal" : "sum_of_line_amounts", tax && "tax", discount && "discount", shipping && "shipping"].filter(Boolean).join("+");
      out.push(check("invoice_total", table.id, { status: eq(computed, total) ? "consistent" : "inconsistent", completeness: comp, currency, expected: s(total), observed: s(computed), difference: s(sub(total, computed)), basis: parts,
        summaryIds: [subtotalF, taxF, discountF, shippingF, totalF].filter((x): x is SummaryField => !!x).map((x) => x.id), reason: `${parts.replace(/\+/g, " + ").replace(/_/g, " ")} = ${s(computed)}; printed total ${s(total)}.` }));
    } else if (lineSum) {
      out.push(check("invoice_total", table.id, { status: eq(lineSum, total) ? "consistent" : "inconsistent", completeness: comp, currency, expected: s(total), observed: s(lineSum), difference: s(sub(total, lineSum)), basis: "sum_of_line_amounts_no_tax_printed", summaryIds: [totalF.id], reason: `No subtotal or tax is printed; line amounts sum to ${s(lineSum)}, printed total ${s(total)}.` }));
    } else out.push(check("invoice_total", table.id, { completeness: "incomplete", currency, rowIds: unreadable, summaryIds: [totalF.id], reason: notReadable }));
  } else out.push(check("invoice_total", table.id, { completeness: comp, currency, reason: "No invoice total was found for this table." }));
  return out;
}

// ---------------------------------------------------------------- payslip

function payslipChecks(tables: FinancialTable[], fields: SummaryField[], ctx: CheckContext): FinancialCheck[] {
  const out: FinancialCheck[] = [];
  const ids = new Set(tables.map((t) => t.id));
  const tableId = tables[0].id;
  const comp = tables.every((t) => completeness(t, ctx) === "complete") ? "complete" : "incomplete";
  const rows = tables.flatMap((t) => t.rows);
  const earnings = rows.filter((r) => r.kind === "earning"), deductions = rows.filter((r) => r.kind === "deduction");
  const mine = fields.filter((f) => f.tableId && ids.has(f.tableId));
  const f = (k: SummaryKey) => mine.filter((x) => x.key === k && x.value?.status === "parsed").slice(-1)[0];
  const cur = currencies([...rows.flatMap((r) => r.cells.map(moneyOf)), ...mine.map((x) => x.value)]);
  if (cur.mixed) return [check("payslip_net", tableId, { completeness: comp, reason: "Payslip amounts are in more than one currency." })];
  const currency = cur.key;
  out.push(lineArithmetic("payslip_rate_times_quantity", earnings, tableId, comp, currency));
  const amountsOf = (rs: TableRow[]) => rs.map((r) => cellDec(cellOf(r, "amount")));
  const ea = amountsOf(earnings), da = amountsOf(deductions).map((d) => (d ? abs(d) : null));
  const eSum = ea.length && ea.every((x) => x) ? sum(ea as Dec[]) : null;
  // No deduction lines read is not a zero deduction: only a printed total (even an explicit 0.00) stands in.
  const dSum = da.length && da.every((x) => x) ? sum(da as Dec[]) : null;
  const grossF = f("gross_pay"), dedF = f("total_deductions"), netF = f("net_pay");
  const gross = moneyDec(grossF?.value), ded = moneyDec(dedF?.value), net = moneyDec(netF?.value);
  if (gross) out.push(check("payslip_gross", tableId, eSum ? { status: eq(eSum, gross) ? "consistent" : "inconsistent", completeness: comp, currency, expected: s(gross), observed: s(eSum), difference: s(sub(gross, eSum)), basis: "sum_of_earnings", summaryIds: [grossF.id], reason: `Earnings lines sum to ${s(eSum)}; printed gross ${s(gross)}.` }
    : { completeness: "incomplete", currency, summaryIds: [grossF.id], reason: earnings.length ? "Some earnings amounts are unreadable." : "No earnings lines were read." }));
  if (ded) out.push(check("payslip_deductions", tableId, dSum && deductions.length ? { status: eq(dSum, abs(ded)) ? "consistent" : "inconsistent", completeness: comp, currency, expected: s(abs(ded)), observed: s(dSum), difference: s(sub(abs(ded), dSum)), basis: "sum_of_deductions", summaryIds: [dedF.id], reason: `Deduction lines sum to ${s(dSum)}; printed total deductions ${s(abs(ded))}.` }
    : { completeness: "incomplete", currency, summaryIds: [dedF.id], reason: deductions.length ? "Some deduction amounts are unreadable." : "No deduction lines were read." }));
  if (net) {
    const g = gross ?? eSum, d = ded ? abs(ded) : dSum;
    if (g && d) {
      const computed = sub(g, d);
      out.push(check("payslip_net", tableId, { status: eq(computed, net) ? "consistent" : "inconsistent", completeness: comp, currency, expected: s(net), observed: s(computed), difference: s(sub(net, computed)),
        basis: `${gross ? "printed_gross" : "sum_of_earnings"}-${ded ? "printed_deductions" : "sum_of_deductions"}`, summaryIds: [grossF, dedF, netF].filter((x): x is SummaryField => !!x).map((x) => x.id),
        reason: `${s(g)} gross - ${s(d)} deductions = ${s(computed)}; printed net ${s(net)}. Employer contributions are not deducted.` }));
    } else out.push(check("payslip_net", tableId, { completeness: "incomplete", currency, summaryIds: [netF.id],
      reason: !d && !deductions.length ? "No deduction lines were read and no total deductions is printed, so net pay cannot be recomputed." : "Gross or deductions are unreadable or missing." }));
  } else out.push(check("payslip_net", tableId, { completeness: comp, currency, reason: "No net pay was found." }));
  return out;
}

export function runChecks(tables: FinancialTable[], fields: SummaryField[], ctx: CheckContext): FinancialCheck[] {
  resetCheckIds();
  const out: FinancialCheck[] = [];
  for (const t of tables) {
    if (t.documentKind === "bank_statement") out.push(...bankChecks(t, fields, ctx));
    if (t.documentKind === "invoice") out.push(...invoiceChecks(t, fields, ctx));
  }
  // A payslip is the payslip tables of one page (earnings, deductions, contributions).
  const byPage = new Map<string, FinancialTable[]>();
  for (const t of tables.filter((x) => x.documentKind === "payslip")) { const k = `${t.segments[0].fileIndex}:${t.pages[0]}`; pushTo(byPage, k, t); }
  for (const ts of byPage.values()) out.push(...payslipChecks(ts, fields, ctx));
  // Pages of the document failed to read: a total over what was read is not a total of the document.
  return out.map((c) => (c.tableId && ctx.totalsBlocked?.has(c.tableId) && TOTAL_LEVEL.has(c.code)
    ? { ...c, status: "not_evaluable", completeness: "incomplete", basis: null, reason: `Not evaluated: pages of this document failed to read. (Over the pages read: ${c.status}; ${c.reason})` }
    : c));
}

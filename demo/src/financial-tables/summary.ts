/** Labelled values printed outside (or as rows of) tables: balances, totals, periods, page numbers, currency. */
import { recognizeDate, type RawDate } from "./dates.js";
import { type Row, type Token } from "./layout.js";
import { currencyFromToken, isPercentToken, looksNumeric } from "./money.js";
import type { CurrencyMark, FinancialDocumentKind, SummaryKey } from "./types.js";

const LABELS: { key: SummaryKey; kinds: FinancialDocumentKind[] | "all"; phrases: string[] }[] = [
  { key: "opening_balance", kinds: ["bank_statement"], phrases: ["opening balance", "previous balance", "opening bal", "balance at start of period"] },
  { key: "brought_forward", kinds: ["bank_statement"], phrases: ["brought forward", "b/f", "balance forward", "balance brought forward", "balance b/f", "bal b/f", "bal brought forward", "bal brought fwd", "balance brought fwd", "brought fwd", "b/fwd"] },
  { key: "closing_balance", kinds: ["bank_statement"], phrases: ["closing balance", "closing bal", "balance at end of period"] },
  { key: "carried_forward", kinds: ["bank_statement"], phrases: ["carried forward", "c/f", "balance carried forward", "balance c/f", "bal c/f", "bal carried forward", "bal carried fwd", "balance carried fwd", "carried fwd", "c/fwd"] },
  { key: "total_debits", kinds: ["bank_statement"], phrases: ["total debits", "total debit", "total withdrawals", "total money out", "total paid out", "debits total", "total payments"] },
  { key: "total_credits", kinds: ["bank_statement"], phrases: ["total credits", "total credit", "total deposits", "total money in", "total paid in", "credits total"] },
  { key: "statement_period", kinds: ["bank_statement"], phrases: ["statement period", "period", "statement from", "for the period", "statement date range"] },
  { key: "subtotal", kinds: ["invoice"], phrases: ["subtotal", "sub total", "sub-total", "total excl vat", "total excl. vat", "total excluding vat", "total before tax", "net total", "total exclusive", "total excl"] },
  { key: "tax_total", kinds: ["invoice"], phrases: ["vat", "tax", "gst", "total vat", "total tax", "vat amount", "tax amount", "sales tax"] },
  { key: "discount", kinds: ["invoice"], phrases: ["discount", "less discount"] },
  { key: "shipping", kinds: ["invoice"], phrases: ["shipping", "delivery", "freight", "postage"] },
  { key: "invoice_total", kinds: ["invoice"], phrases: ["total", "total due", "amount due", "balance due", "grand total", "invoice total", "total incl vat", "total incl. vat", "total including vat", "total payable", "amount payable", "total incl"] },
  { key: "gross_pay", kinds: ["payslip"], phrases: ["gross pay", "gross earnings", "total earnings", "gross salary", "gross", "gross remuneration", "total income"] },
  { key: "total_deductions", kinds: ["payslip"], phrases: ["total deductions", "deductions total", "total deduction"] },
  { key: "net_pay", kinds: ["payslip"], phrases: ["net pay", "net salary", "nett pay", "net amount", "take home pay", "net payment", "nett salary", "net amount paid"] },
  { key: "pay_period", kinds: ["payslip"], phrases: ["pay period", "period"] },
  { key: "currency_declaration", kinds: "all", phrases: ["currency", "all amounts in", "amounts in", "account currency", "amounts shown in", "currency code"] },
  { key: "page_number", kinds: "all", phrases: ["page"] },
];

/**
 * OCR often drops the space after a label's colon (`TOTAL:1,250.00`, `GST(9%):45.10`). A single-box token of that shape
 * is split into the label, its bracketed rate, the colon and the value, with boxes interpolated from character offsets
 * and marked approximate. Nothing else is split: the label must be letters only and the value numeric, so dates
 * (`Date:12-Mar-2024`), times and references stay whole, and a split label still has to match a phrase below.
 */
const GLUED_LABEL = /^([A-Za-z][A-Za-z_-]*)(\(\d{1,3}(?:[.,]\d{1,4})?\s?%\))?:(.+)$/;
function splitGluedLabel(t: Token): Token[] {
  const m = GLUED_LABEL.exec(t.text);
  if (!m || t.parts.length !== 1 || looksNumeric(m[3]) === null || recognizeDate(m[3])) return [t];
  let offset = 0;
  return [m[1], ...(m[2] ? [m[2]] : []), ":", m[3]].map((text) => {
    const x = Math.round((t.x + offset * t.cw) * 100) / 100, w = Math.round(text.length * t.cw * 100) / 100;
    offset += text.length;
    return { ...t, text, x, w, parts: [{ ...t.parts[0], text, bbox: { ...t.parts[0].bbox, x, w }, approximate: true }] };
  });
}

const norm = (s: string) => s.toLowerCase().replace(/[:]+$/, "").replace(/^[(]+|[)]+$/g, "");
const right = (t: Token) => t.x + t.w;

export interface RawSummary {
  key: SummaryKey;
  label: Token[];
  valueTokens: Token[];
  dates: RawDate[];
  dateTokens: Token[];
  rateToken: Token | null;
  page: { number: number; of: number | null } | null;
  currency: CurrencyMark | null;
  row: Row;
}

/** Does a numeric token look like a printed amount (cents, or a currency mark) rather than a count or reference? */
export function amountShaped(text: string): boolean {
  return /[.,]\d{2}\)?(?:\s?(?:CR|DR|Cr|Dr|-|[A-Z]{3}))?$/.test(text.trim()) || /^[-(]?\s?(?:R|\$|€|£|[A-Z]{3})\s?\d/.test(text.trim());
}

function matchLabelAt(tokens: Token[], j: number, kinds: Set<FinancialDocumentKind>): { key: SummaryKey; n: number } | null {
  let best: { key: SummaryKey; n: number } | null = null;
  for (const l of LABELS) {
    if (l.kinds !== "all" && !l.kinds.some((k) => kinds.has(k))) continue;
    for (const p of l.phrases) {
      const words = p.split(" ");
      if (best && words.length <= best.n) continue;
      const win = tokens.slice(j, j + words.length);
      if (win.length === words.length && win.every((t, k) => norm(t.text) === words[k])) best = { key: l.key, n: words.length };
    }
  }
  return best;
}

/** Every label → value pair in a row. A label must start a phrase and its value must follow with only marks in between. */
export function summariesInRow(row: Row, kinds: Set<FinancialDocumentKind>): RawSummary[] {
  const out: RawSummary[] = [];
  const ts = row.tokens.flatMap(splitGluedLabel);
  for (let j = 0; j < ts.length; j++) {
    const prev = ts[j - 1];
    const startsPhrase = !prev || looksNumeric(prev.text) !== null || ts[j].x - right(prev) > 2.5 * Math.max(prev.cw, ts[j].cw);
    if (!startsPhrase) continue;
    const m = matchLabelAt(ts, j, kinds);
    if (!m) continue;
    const label = ts.slice(j, j + m.n);
    const after = ts.slice(j + m.n);
    const s: RawSummary = { key: m.key, label, valueTokens: [], dates: [], dateTokens: [], rateToken: null, page: null, currency: null, row };
    if (m.key === "page_number") {
      const text = after.slice(0, 3).map((t) => t.text).join(" ");
      const pm = /^(\d{1,4})(?:\s*(?:of|\/)\s*(\d{1,4}))?/i.exec(text);
      if (pm) {
        s.page = { number: +pm[1], of: pm[2] ? +pm[2] : null };
        s.valueTokens = after.slice(0, /^\d+\/\d+$/.test(after[0].text) || !pm[2] ? 1 : 3);
        out.push(s);
      }
      continue;
    }
    if (m.key === "currency_declaration") {
      const next = after.find((t) => !/^[:\-–]$/.test(t.text));
      const mark = next ? currencyFromToken(next.text.replace(/[():.]/g, ""), "document_declaration") : null;
      if (mark && mark.code) { s.currency = mark; s.valueTokens = [next as Token]; out.push(s); }
      continue;
    }
    if (m.key === "statement_period" || m.key === "pay_period") {
      for (const t of after) {
        if (/^(to|-|–|until|from|:)$/i.test(t.text)) continue;
        const d = recognizeDate(t.text);
        if (!d) break;
        s.dates.push(d); s.dateTokens.push(t);
        if (s.dates.length === 2) break;
      }
      if (s.dates.length === 2) out.push(s);
      continue;
    }
    // A money value, with only marks (%, @, currency, colon, a rate in brackets) between label and value.
    let k = 0;
    for (; k < after.length; k++) {
      const t = after[k];
      const bare = t.text.replace(/^[(]|[)]$/g, "");
      if (/^[:@=]$/.test(t.text) || /^(at|@)$/i.test(t.text)) continue;
      if (isPercentToken(bare)) { s.rateToken = t; continue; }
      if (/^(incl|excl|incl\.|excl\.|vat)$/i.test(t.text) && m.key !== "tax_total") continue;
      if (currencyFromToken(bare, "cell") && !looksNumeric(t.text)) { continue; }
      break;
    }
    const v = after[k];
    // Totals may print whole units (`Total 3,500`); a tax label needs an amount-shaped value so `VAT 4123456789` is not a tax total.
    const wholeUnits = WHOLE_UNIT_KEYS.has(m.key) && /^[-(]?(\d{1,3}(?:[ ,.']\d{3})+|\d{2,9})\)?$/.test(v?.text ?? "");
    if (!v || !looksNumeric(v.text) || !(amountShaped(v.text) || wholeUnits || looksNumeric(v.text) === "numeric_malformed")) continue;
    // Count tokens of a currency symbol printed separately just before the value.
    const pre = after[k - 1] && currencyFromToken(after[k - 1].text, "cell") && !looksNumeric(after[k - 1].text) ? [after[k - 1]] : [];
    s.valueTokens = [...pre, v];
    out.push(s);
    j += m.n + k;
  }
  return out;
}

const WHOLE_UNIT_KEYS = new Set<SummaryKey>(["subtotal", "invoice_total", "gross_pay", "total_deductions", "net_pay", "total_debits", "total_credits"]);

/** Rows a summary-row label ends a table with (subtotal/total, gross/net, total debits). Bank balance rows stay table rows. */
export const ENDING_KEYS = new Set<SummaryKey>(["subtotal", "tax_total", "discount", "shipping", "invoice_total", "gross_pay", "total_deductions", "net_pay", "total_debits", "total_credits"]);

/** Is this text, and nothing else, a label that ends a table ("Total", "Shipping:", "Sub total")? */
export function isEndingLabelOnly(text: string, kinds: Set<FinancialDocumentKind>): boolean {
  const t = text.toLowerCase().replace(/[:\s]+$/, "").replace(/\s+/g, " ").trim();
  return !!t && LABELS.some((l) => ENDING_KEYS.has(l.key) && (l.kinds === "all" || l.kinds.some((k) => kinds.has(k))) && l.phrases.includes(t));
}

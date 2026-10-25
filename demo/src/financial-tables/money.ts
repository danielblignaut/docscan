/** Exact money, quantity and percentage parsing. A token that is not unambiguous is reported, not guessed. */
import { MAX_DIGITS, dec, rescale, toDecimalString, type Dec } from "./decimal.js";
import type { CurrencyMark, MoneyValue, PercentValue, QuantityValue } from "./types.js";

/** ISO 4217 minor-unit exponents that differ from 2, plus codes we recognise as text. */
const EXPONENT: Record<string, number> = { JPY: 0, KRW: 0, VND: 0, CLP: 0, ISK: 0, UGX: 0, XOF: 0, XAF: 0, RWF: 0,
  BHD: 3, KWD: 3, OMR: 3, JOD: 3, TND: 3, IQD: 3, LYD: 3 };
const KNOWN_CODES = new Set(["ZAR", "USD", "EUR", "GBP", "AUD", "CAD", "NZD", "CHF", "JPY", "CNY", "INR", "BWP", "NAD", "LSL",
  "SZL", "MZN", "ZMW", "ZWL", "KES", "NGN", "GHS", "TZS", "UGX", "MUR", "AED", "SAR", "BRL", "MXN", "SEK", "NOK", "DKK",
  "PLN", "CZK", "HUF", "SGD", "HKD", "KRW", "BHD", "KWD", "OMR", "JOD", "TND", "IQD", "LYD", "VND", "CLP", "ISK", "XOF", "XAF", "RWF"]);
/** Symbols that name exactly one currency in practice. */
const UNAMBIGUOUS_SYMBOLS: Record<string, string> = { "€": "EUR", "₦": "NGN", "₹": "INR", "₩": "KRW", "₱": "PHP", "₺": "TRY",
  "US$": "USD", "A$": "AUD", "AU$": "AUD", "C$": "CAD", "CA$": "CAD", "NZ$": "NZD", "HK$": "HKD", "S$": "SGD", "R$": "BRL", "KSh": "KES", "N$": "NAD" };
/** Symbols shared by several currencies: kept as printed, code left null. */
const AMBIGUOUS_SYMBOLS = new Set(["$", "£", "¥", "R", "Rs", "kr", "Fr"]);

/** Which ISO codes an ambiguous symbol can stand for: used only to reconcile a symbol with a declared code. */
const SYMBOL_CODES: Record<string, string[]> = { "$": ["USD", "AUD", "CAD", "NZD", "NAD", "HKD", "SGD", "MXN"], "£": ["GBP"], "¥": ["JPY", "CNY"],
  R: ["ZAR"], Rs: ["INR"], kr: ["SEK", "NOK", "DKK", "ISK"], Fr: ["CHF"] };
export const symbolFits = (symbol: string | null, code: string | null): boolean => !!symbol && !!code && (SYMBOL_CODES[symbol] ?? []).includes(code);

export const currencyExponent = (code: string | null): number | null => (code && KNOWN_CODES.has(code) ? EXPONENT[code] ?? 2 : null);

export const NO_CURRENCY: CurrencyMark = { code: null, symbol: null, source: "none", ambiguous: false };

export function currencyFromToken(token: string, source: CurrencyMark["source"]): CurrencyMark | null {
  const t = token.trim();
  if (KNOWN_CODES.has(t.toUpperCase()) && /^[A-Za-z]{3}$/.test(t) && t === t.toUpperCase()) return { code: t.toUpperCase(), symbol: t, source, ambiguous: false };
  if (UNAMBIGUOUS_SYMBOLS[t]) return { code: UNAMBIGUOUS_SYMBOLS[t], symbol: t, source, ambiguous: false };
  if (AMBIGUOUS_SYMBOLS.has(t)) return { code: null, symbol: t, source, ambiguous: true };
  return null;
}

/** The identity used to keep currencies apart: an ISO code, else the printed symbol, else null (unmarked). */
export const currencyKey = (c: CurrencyMark | null): string | null => (c ? c.code ?? (c.symbol ? `symbol:${c.symbol}` : null) : null);

// Prefix/suffix currency: codes, multi-char symbols first so `US$` wins over `$`.
const SYMBOL_ALTERNATION = [...Object.keys(UNAMBIGUOUS_SYMBOLS), ...AMBIGUOUS_SYMBOLS]
  .sort((a, b) => b.length - a.length).map((s) => s.replace(/[$]/g, "\\$")).join("|");
const PREFIX = new RegExp(`^(?:([A-Z]{3})|(${SYMBOL_ALTERNATION}))\\s*`);
const SUFFIX = new RegExp(`\\s*(?:([A-Z]{3})|(${SYMBOL_ALTERNATION}))$`);
const MINUS = /^[-−‒–—]/;
const LOOKALIKE = /[OoIlSB]/;

export interface NumberContext {
  /** The separator a document/option established, for tokens a lone `,` or `.` + 3 digits leaves open. */
  decimal: "." | "," | null;
  decimalSource: "option" | "document_evidence" | "none";
}

interface Core {
  status: "parsed" | "ambiguous" | "malformed";
  dec?: Dec;
  candidates?: Dec[];
  separator: "." | "," | null;
  separatorSource: MoneyValue["decimalSeparatorSource"];
  issue?: string;
}

/** What a bare numeric core says about its decimal separator, without any context. */
export function separatorEvidence(core: string): "." | "," | "ambiguous" | "none" | "invalid" {
  const c = core.replace(/[\s  ']/g, " ");
  const seps = [...c.matchAll(/[.,]/g)].map((m) => m[0]);
  if (!seps.length) return "none";
  const last = c.lastIndexOf(seps[seps.length - 1]);
  const distinct = new Set(seps);
  if (distinct.size === 2) return seps[seps.length - 1] as "." | ",";
  const sep = seps[0] as "." | ",";
  if (seps.length > 1) return sep === "." ? "," : "."; // repeated separator: thousands groups
  const after = c.slice(last + 1).replace(/ /g, "").length;
  if (after !== 3) return sep;
  // `1 234,567`-style space grouping before the separator makes the separator the decimal.
  if (/\d \d{3}[.,]/.test(c)) return sep;
  return "ambiguous";
}

function parseCore(raw: string, ctx: NumberContext): Core {
  const core = raw.replace(/[   ]/g, " ").trim();
  if (!core) return { status: "malformed", separator: null, separatorSource: null, issue: "no_digits" };
  if (/[^\d.,' ]/.test(core)) {
    return { status: "malformed", separator: null, separatorSource: null, issue: LOOKALIKE.test(core) && /\d/.test(core) ? "ocr_lookalike_characters" : "invalid_characters" };
  }
  const digits = core.replace(/\D/g, "");
  if (!digits) return { status: "malformed", separator: null, separatorSource: null, issue: "no_digits" };
  if (digits.length > MAX_DIGITS) return { status: "malformed", separator: null, separatorSource: null, issue: "too_many_digits" };
  const evidence = separatorEvidence(core);
  const read = (decimal: "." | "," | null): Dec | null => {
    const thousands = decimal === "." ? "," : decimal === "," ? "." : null;
    let s = core;
    let frac = "";
    if (decimal) {
      const i = s.lastIndexOf(decimal);
      if (i >= 0) { frac = s.slice(i + 1); s = s.slice(0, i); }
      if (!/^\d+$/.test(frac) && frac !== "") return null;
      if (s.includes(decimal)) return null;
    }
    // Integer part: plain digits, or 1-3 digits then groups of exactly 3 using one grouping character.
    const groupChar = thousands ? `[${thousands === "." ? "." : ","} ']` : "[ ']";
    if (!new RegExp(`^(\\d+|\\d{1,3}(${groupChar}\\d{3})+)$`).test(s)) return null;
    const usedGroups = new Set([...s.matchAll(/[^\d]/g)].map((m) => m[0]));
    if (usedGroups.size > 1) return null;
    const int = s.replace(/\D/g, "") || "0";
    return dec(BigInt(int + frac), frac.length);
  };
  if (evidence === "none") {
    const d = read(null);
    return d ? { status: "parsed", dec: d, separator: null, separatorSource: null } : { status: "malformed", separator: null, separatorSource: null, issue: "invalid_grouping" };
  }
  if (evidence === "." || evidence === ",") {
    const d = read(evidence);
    return d ? { status: "parsed", dec: d, separator: evidence, separatorSource: "unambiguous_token" } : { status: "malformed", separator: null, separatorSource: null, issue: "invalid_grouping" };
  }
  if (evidence === "invalid") return { status: "malformed", separator: null, separatorSource: null, issue: "invalid_grouping" };
  // A lone separator followed by exactly three digits: 1,234 is 1234 or 1.234.
  const asDecimalDot = read(core.includes(".") ? "." : ",");
  const asThousands = read(core.includes(".") ? "," : ".");
  const sep = core.includes(".") ? "." : ",";
  if (ctx.decimal) {
    const d = ctx.decimal === sep ? asDecimalDot : asThousands;
    if (d) return { status: "parsed", dec: d, separator: ctx.decimal, separatorSource: ctx.decimalSource === "option" ? "option" : "document_evidence" };
  }
  return { status: "ambiguous", candidates: [asThousands, asDecimalDot].filter((d): d is Dec => !!d), separator: null, separatorSource: "none", issue: "decimal_separator_unresolved" };
}

interface Stripped { core: string; negative: boolean; signSource: MoneyValue["signSource"]; marker: "CR" | "DR" | null; currency: CurrencyMark | null; issue?: string }

function stripMoneyDecoration(text: string): Stripped {
  let s = text.trim();
  let negative = false;
  let signSource: MoneyValue["signSource"] = "none";
  let marker: "CR" | "DR" | null = null;
  let currency: CurrencyMark | null = null;
  const m = /\s*(?<![A-Za-z])(CR|DR|Cr|Dr|cr|dr)\.?$/.exec(s);
  if (m) { marker = m[1].toUpperCase() as "CR" | "DR"; s = s.slice(0, m.index).trim(); }
  if (/^\(.*\)$/.test(s)) { negative = true; signSource = "parentheses"; s = s.slice(1, -1).trim(); }
  if (MINUS.test(s)) { negative = !negative; signSource = "minus"; s = s.slice(1).trim(); }
  else if (/^\+/.test(s)) { signSource = "plus"; s = s.slice(1).trim(); }
  for (let i = 0; i < 2; i++) {
    const p = PREFIX.exec(s);
    if (p && /\d/.test(s.slice(p[0].length, p[0].length + 2))) {
      const mark = currencyFromToken(p[1] ?? p[2], "cell");
      if (mark) { currency = mark; s = s.slice(p[0].length).trim(); }
    }
    if (MINUS.test(s) && signSource === "none") { negative = true; signSource = "minus"; s = s.slice(1).trim(); }
    if (/^\(.*\)$/.test(s) && signSource === "none") { negative = true; signSource = "parentheses"; s = s.slice(1, -1).trim(); }
  }
  const x = SUFFIX.exec(s);
  if (x && /\d$/.test(s.slice(0, x.index).trim())) {
    const mark = currencyFromToken(x[1] ?? x[2], "cell");
    if (mark) { if (!currency) currency = mark; s = s.slice(0, x.index).trim(); }
  }
  if (/[-−]$/.test(s) && signSource === "none") { negative = true; signSource = "trailing_minus"; s = s.slice(0, -1).trim(); }
  if (marker && signSource === "none") signSource = marker === "DR" ? "dr_marker" : "cr_marker";
  return { core: s, negative, signSource, marker, currency };
}

/** Parse a printed amount. Currency marks are kept, never converted; a missing mark stays `none` here. */
export function parseMoney(text: string, ctx: NumberContext): MoneyValue {
  const t = text.trim();
  const base: MoneyValue = { type: "money", status: "empty", text: t, value: null, units: null, scale: null, minorUnits: null,
    negative: false, signSource: "none", marker: null, currency: NO_CURRENCY, decimalSeparator: null, decimalSeparatorSource: null };
  if (!t || /^[-–—.]+$/.test(t) || /^nil$/i.test(t)) return base;
  const d = stripMoneyDecoration(t);
  const core = parseCore(d.core, ctx);
  const out: MoneyValue = { ...base, status: core.status, negative: d.negative, signSource: d.signSource, marker: d.marker,
    currency: d.currency ?? NO_CURRENCY, decimalSeparator: core.separator, decimalSeparatorSource: core.separatorSource };
  // A DR marker on an amount says debit; we record the marker and leave the sign to the column's meaning.
  if (core.status === "parsed" && core.dec) {
    const signed = d.negative ? { u: -core.dec.u, s: core.dec.s } : core.dec;
    out.value = toDecimalString(signed);
    out.units = signed.u.toString();
    out.scale = signed.s;
    const exp = currencyExponent(out.currency.code);
    if (exp !== null && signed.s <= exp) out.minorUnits = rescale(signed, exp).u.toString();
  } else if (core.status === "ambiguous") {
    out.candidates = (core.candidates ?? []).map((c) => toDecimalString(d.negative ? { u: -c.u, s: c.s } : c));
    out.issue = core.issue;
  } else out.issue = core.issue;
  return out;
}

/** Apply a currency the cell itself does not print (column header, declaration, option). */
export function withCurrency(m: MoneyValue, mark: CurrencyMark | null): MoneyValue {
  if (!mark || m.currency.source === "cell") return m;
  const out = { ...m, currency: mark };
  const exp = currencyExponent(mark.code);
  if (m.status === "parsed" && m.units !== null && m.scale !== null && exp !== null && m.scale <= exp)
    out.minorUnits = rescale(dec(m.units, m.scale), exp).u.toString();
  return out;
}

export function parseQuantity(text: string, ctx: NumberContext): QuantityValue {
  const t = text.trim();
  const out: QuantityValue = { type: "quantity", status: "empty", text: t, value: null, units: null, scale: null };
  if (!t) return out;
  let s = t.replace(/\s*(x|hrs?|hours?|units?|days?|ea)\.?$/i, "");
  let negative = false;
  if (MINUS.test(s)) { negative = true; s = s.slice(1).trim(); }
  const core = parseCore(s, ctx);
  out.status = core.status;
  if (core.status === "parsed" && core.dec) {
    const v = negative ? { u: -core.dec.u, s: core.dec.s } : core.dec;
    out.value = toDecimalString(v); out.units = v.u.toString(); out.scale = v.s;
  } else if (core.status === "ambiguous") { out.candidates = (core.candidates ?? []).map(toDecimalString); out.issue = core.issue; }
  else out.issue = core.issue;
  return out;
}

export function parsePercent(text: string, ctx: NumberContext): PercentValue {
  const t = text.trim();
  const m = /^(.*?)\s*%$/.exec(t);
  const core = parseCore(m ? m[1] : t, ctx);
  if (core.status === "parsed" && core.dec) return { type: "percent", status: "parsed", text: t, value: toDecimalString(core.dec), units: core.dec.u.toString(), scale: core.dec.s };
  return { type: "percent", status: "malformed", text: t, value: null, units: null, scale: null, issue: core.issue ?? "decimal_separator_unresolved" };
}

/** Is this token shaped like a number a table cell would hold (money, quantity), possibly mis-read? */
export function looksNumeric(token: string): "numeric" | "numeric_malformed" | null {
  const t = token.trim();
  if (!t) return null;
  const s = stripMoneyDecoration(t).core;
  if (/^\d[\d.,'  ]*$/.test(s) && /\d/.test(s)) return "numeric";
  // Mis-read digits (O for 0, l for 1) inside an otherwise numeric token: at least half digits, has a separator.
  const digits = (s.match(/\d/g) ?? []).length;
  if (s.length >= 3 && digits / s.length >= 0.5 && /[.,]/.test(s) && /^[\dOoIlSB.,' ]+$/.test(s)) return "numeric_malformed";
  return null;
}

export const isPercentToken = (t: string): boolean => /^\d{1,3}(?:[.,]\d{1,4})?\s*%$/.test(t.trim());

/** Money value as an exact decimal, or null when it did not parse. */
export function moneyDec(m: MoneyValue | QuantityValue | PercentValue | null | undefined): Dec | null {
  if (!m || m.status !== "parsed" || m.units === null || m.scale === null) return null;
  return dec(m.units, m.scale);
}

/** On a balance, `Dr` means overdrawn: the balance itself is negative (on an amount the marker is a direction). */
export function balanceSemantics(m: MoneyValue): MoneyValue {
  if (m.status !== "parsed" || m.marker !== "DR" || m.negative || m.units === null) return m;
  const flip = (x: string | null) => (x === null ? null : x.startsWith("-") ? x.slice(1) : `-${x}`);
  return { ...m, negative: true, value: flip(m.value), units: flip(m.units), minorUnits: flip(m.minorUnits) };
}

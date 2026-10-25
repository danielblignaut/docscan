/** Date tokens: recognised, then resolved only as far as the printed text and stated evidence allow. */
import type { DateOrder, DateValue } from "./types.js";

const MONTHS: Record<string, number> = { jan: 1, january: 1, feb: 2, february: 2, mar: 3, march: 3, apr: 4, april: 4, may: 5,
  jun: 6, june: 6, jul: 7, july: 7, aug: 8, august: 8, sep: 9, sept: 9, september: 9, oct: 10, october: 10, nov: 11,
  november: 11, dec: 12, december: 12 };

export interface RawDate {
  text: string;
  kind: "iso" | "numeric" | "textual";
  /** numeric: first and second printed numbers; textual: day and month. */
  a: number;
  b: number;
  year: number | null;
  yearDigits: 0 | 2 | 4;
}

const ISO = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/;
const NUMERIC_YEAR = /^(\d{1,2})([-/.])(\d{1,2})\2(\d{4}|\d{2})$/;
const NUMERIC_NO_YEAR = /^(\d{1,2})\/(\d{1,2})$/;
const DAY_MONTH = /^(\d{1,2})(?:st|nd|rd|th)?[\s\-./]*([A-Za-z]{3,9})\.?(?:[\s\-./,]+(\d{4}|\d{2}))?$/;
const DAY_MONTH_COMPACT = /^(\d{1,2})([A-Za-z]{3})(\d{2}|\d{4})$/;
const MONTH_DAY = /^([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?$/;

/** Recognise a date-shaped token. Returns null for anything else (including money like `12.50`). */
export function recognizeDate(text: string): RawDate | null {
  const t = text.trim();
  let m = ISO.exec(t);
  if (m) return { text: t, kind: "iso", a: +m[2], b: +m[3], year: +m[1], yearDigits: 4 };
  m = NUMERIC_YEAR.exec(t);
  if (m) return { text: t, kind: "numeric", a: +m[1], b: +m[3], year: +m[4], yearDigits: m[4].length as 2 | 4 };
  m = NUMERIC_NO_YEAR.exec(t);
  if (m && +m[1] >= 1 && +m[2] >= 1 && +m[1] <= 31 && +m[2] <= 31) return { text: t, kind: "numeric", a: +m[1], b: +m[2], year: null, yearDigits: 0 };
  m = DAY_MONTH.exec(t) ?? DAY_MONTH_COMPACT.exec(t);
  if (m && MONTHS[m[2].toLowerCase()]) return { text: t, kind: "textual", a: +m[1], b: MONTHS[m[2].toLowerCase()], year: m[3] ? +m[3] : null, yearDigits: (m[3]?.length ?? 0) as 0 | 2 | 4 };
  m = MONTH_DAY.exec(t);
  if (m && MONTHS[m[1].toLowerCase()]) return { text: t, kind: "textual", a: +m[2], b: MONTHS[m[1].toLowerCase()], year: m[3] ? +m[3] : null, yearDigits: (m[3]?.length ?? 0) as 0 | 4 };
  return null;
}

/** The day/month order one numeric token proves on its own, if any. */
export function orderEvidence(raw: RawDate): "DMY" | "MDY" | null {
  if (raw.kind !== "numeric") return null;
  if (raw.a > 12 && raw.b <= 12) return "DMY";
  if (raw.b > 12 && raw.a <= 12) return "MDY";
  return null;
}

export interface DateContext {
  order: DateOrder | null;
  orderSource: "option" | "document_evidence" | "none";
  century: number | null;
  centurySource: "option" | "document_evidence" | "none";
  /** A statement period whose years can supply a missing year. */
  period: { start: { y: number; m: number }; end: { y: number; m: number } } | null;
}

const pad = (n: number, w = 2) => String(n).padStart(w, "0");
const daysIn = (y: number, m: number) => new Date(Date.UTC(y, m, 0)).getUTCDate();
const valid = (y: number, m: number, d: number) => m >= 1 && m <= 12 && d >= 1 && d <= daysIn(y, m);
const iso = (y: number, m: number, d: number) => `${pad(y, 4)}-${pad(m)}-${pad(d)}`;

export function resolveDate(raw: RawDate, ctx: DateContext): DateValue {
  const out: DateValue = { type: "date", status: "parsed", text: raw.text, iso: null, order: null, orderSource: "none", yearSource: "none" };
  // Year.
  let years: number[] = [];
  if (raw.yearDigits === 4 && raw.year !== null) { years = [raw.year]; out.yearSource = "printed"; }
  else if (raw.yearDigits === 2 && raw.year !== null) {
    if (ctx.century !== null) { years = [ctx.century + raw.year]; out.yearSource = ctx.centurySource === "option" ? "two_digit_option" : "two_digit_document_evidence"; }
    else years = [1900 + raw.year, 2000 + raw.year];
  }
  // Day and month.
  let pairs: { d: number; m: number; order: DateOrder | null }[] = [];
  if (raw.kind === "iso") { pairs = [{ m: raw.a, d: raw.b, order: "YMD" }]; out.orderSource = "iso_token"; }
  else if (raw.kind === "textual") { pairs = [{ d: raw.a, m: raw.b, order: null }]; out.orderSource = "month_name"; }
  else {
    const own = orderEvidence(raw);
    if (raw.a > 12 && raw.b > 12) { out.status = "invalid"; out.issue = "no_valid_day_month_order"; return out; }
    if (own) { pairs = [own === "DMY" ? { d: raw.a, m: raw.b, order: own } : { d: raw.b, m: raw.a, order: own }]; out.orderSource = "unambiguous_token"; }
    else if (raw.a === raw.b) { pairs = [{ d: raw.a, m: raw.a, order: null }]; out.orderSource = "unambiguous_token"; }
    else if (ctx.order === "DMY" || ctx.order === "MDY") {
      pairs = [ctx.order === "DMY" ? { d: raw.a, m: raw.b, order: "DMY" } : { d: raw.b, m: raw.a, order: "MDY" }];
      out.orderSource = ctx.orderSource === "option" ? "option" : "document_evidence";
    } else pairs = [{ d: raw.a, m: raw.b, order: "DMY" }, { d: raw.b, m: raw.a, order: "MDY" }];
  }
  if (pairs.length === 1) out.order = pairs[0].order;
  if (!years.length) {
    if (ctx.period) {
      const m = pairs.length === 1 ? pairs[0].m : null;
      const { start, end } = ctx.period;
      if (start.y === end.y) years = [start.y];
      else if (m !== null && end.y === start.y + 1) years = [m >= start.m ? start.y : end.y];
      if (years.length) out.yearSource = "statement_period";
    }
    if (!years.length) {
      const okPairs = pairs.filter((p) => valid(2000, p.m, p.d));
      if (!okPairs.length) { out.status = "invalid"; out.issue = "no_valid_day_month_order"; return out; }
      out.status = "partial"; out.issue = "year_missing"; return out;
    }
  }
  const candidates: string[] = [];
  for (const y of years) for (const p of pairs) if (valid(y, p.m, p.d)) candidates.push(iso(y, p.m, p.d));
  if (!candidates.length) { out.status = "invalid"; out.issue = "not_a_calendar_date"; return out; }
  if (candidates.length === 1) { out.iso = candidates[0]; if (pairs.length > 1) out.order = null; return out; }
  out.status = "ambiguous";
  out.candidates = candidates;
  out.issue = pairs.length > 1 ? "day_month_order_unresolved" : "two_digit_year_century_unresolved";
  return out;
}

/** Whole days from one ISO date to another (UTC calendar arithmetic). */
export function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);
}
export function addDays(a: string, n: number): string {
  return new Date(Date.parse(`${a}T00:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10);
}
export const monthIndex = (isoDate: string): number => +isoDate.slice(0, 4) * 12 + (+isoDate.slice(5, 7) - 1);

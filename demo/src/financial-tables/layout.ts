/** Geometry: input boxes → word tokens → rows → header columns → cells. */
import { recognizeDate } from "./dates.js";
import { currencyFromToken, isPercentToken, looksNumeric } from "./money.js";
import type { Box, ColumnRole, CurrencyMark, FinancialDocumentKind, SourcePart, SourceRef } from "./types.js";
import { pushTo } from "./util.js";

export interface Token {
  text: string;
  pageIndex: number;
  fileIndex: number | null;
  /** Index of the input box in the page's `lines`. Composite tokens keep every part. */
  parts: SourcePart[];
  x: number; y: number; w: number; h: number;
  /** Width of one character in this token's box: the scale for every gap test. */
  cw: number;
  /** The OCR line id, or a synthetic id for the input box. */
  lineKey: string;
}

export interface Row {
  pageIndex: number;
  fileIndex: number | null;
  /** Index among the page's rows, top to bottom. */
  index: number;
  tokens: Token[];
  yc: number;
  top: number;
  bottom: number;
  h: number;
}

export interface PageLayout { pageIndex: number; fileIndex: number | null; rows: Row[]; medianH: number }

export interface CleanLine { text: string; x: number; y: number; w: number; h: number; line: number | null; index: number }

const right = (t: { x: number; w: number }) => t.x + t.w;
const median = (xs: number[]) => { const s = [...xs].sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : 0; };

export function unionBox(boxes: Box[]): Box {
  const x0 = Math.min(...boxes.map((b) => b.x)), y0 = Math.min(...boxes.map((b) => b.y));
  const x1 = Math.max(...boxes.map((b) => b.x + b.w)), y1 = Math.max(...boxes.map((b) => b.y + b.h));
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

export function sourceOf(tokens: Token[]): SourceRef {
  const parts = tokens.flatMap((t) => t.parts);
  return {
    pageIndex: tokens[0].pageIndex,
    fileIndex: tokens[0].fileIndex,
    lineIndices: [...new Set(parts.map((p) => p.lineIndex))].sort((a, b) => a - b),
    bbox: unionBox(parts.map((p) => p.bbox)),
    parts,
    approximate: parts.some((p) => p.approximate),
  };
}

export function mergeSources(sources: SourceRef[]): SourceRef {
  const parts = sources.flatMap((s) => s.parts);
  return { pageIndex: sources[0].pageIndex, fileIndex: sources[0].fileIndex, lineIndices: [...new Set(parts.map((p) => p.lineIndex))].sort((a, b) => a - b),
    bbox: unionBox(parts.map((p) => p.bbox)), parts, approximate: parts.some((p) => p.approximate) };
}

const round2 = (n: number) => Math.round(n * 100) / 100;

/** Split a box into word tokens. A box whose whole text is one number (`1 234.56`) stays one token. */
function tokensOfLine(line: CleanLine, pageIndex: number, fileIndex: number | null): Token[] {
  const text = line.text;
  const lineKey = line.line !== null ? `l${line.line}` : `b${line.index}`;
  const cw = text.length ? line.w / text.length : line.h * 0.5;
  const whole = (): Token => ({ text: text.trim(), pageIndex, fileIndex, x: line.x, y: line.y, w: line.w, h: line.h, cw, lineKey,
    parts: [{ lineIndex: line.index, text: text.trim(), bbox: { x: line.x, y: line.y, w: line.w, h: line.h }, approximate: false }] });
  const words = [...text.matchAll(/\S+/g)];
  if (words.length <= 1 || looksNumeric(text) === "numeric" || recognizeDate(text)) return words.length ? [whole()] : [];
  return words.map((m) => {
    const x = round2(line.x + (m.index ?? 0) * cw), w = round2(m[0].length * cw);
    return { text: m[0], pageIndex, fileIndex, x, y: line.y, w, h: line.h, cw, lineKey,
      parts: [{ lineIndex: line.index, text: m[0], bbox: { x, y: line.y, w, h: line.h }, approximate: true }] };
  });
}

function joinTokens(a: Token[], text: string): Token {
  const box = unionBox(a);
  return { text, pageIndex: a[0].pageIndex, fileIndex: a[0].fileIndex, ...box, cw: Math.min(...a.map((t) => t.cw)), lineKey: a[0].lineKey, parts: a.flatMap((t) => t.parts) };
}
const gap = (a: Token, b: Token) => b.x - right(a);
const close = (a: Token, b: Token, chars: number) => gap(a, b) <= chars * Math.max(a.cw, b.cw) && gap(a, b) > -Math.max(a.cw, b.cw) * 2;

/** Join tokens that one value was split into: multi-word dates, a currency symbol and its number, `CR`/`DR`, space-grouped thousands. */
function mergeComposites(tokens: Token[]): Token[] {
  let out = [...tokens];
  // Dates written with a month name over several words.
  for (const n of [4, 3, 2]) {
    const next: Token[] = [];
    for (let i = 0; i < out.length; i++) {
      const win = out.slice(i, i + n);
      if (win.length === n && win.every((t, k) => k === 0 || close(win[k - 1], t, 2.5))) {
        const text = win.map((t) => t.text).join(" ");
        const raw = recognizeDate(text);
        if (raw && raw.kind === "textual") { next.push(joinTokens(win, text)); i += n - 1; continue; }
      }
      next.push(out[i]);
    }
    out = next;
  }
  const merged: Token[] = [];
  for (const t of out) {
    const prev = merged[merged.length - 1];
    if (prev && close(prev, t, 2)) {
      const prevCurrency = currencyFromToken(prev.text, "cell") || /^[-(]$/.test(prev.text) || /^[-(](R|\$|€|£|[A-Z]{3})$/.test(prev.text);
      if (prevCurrency && looksNumeric(t.text)) { merged[merged.length - 1] = joinTokens([prev, t], `${prev.text} ${t.text}`); continue; }
      if (looksNumeric(prev.text) && /^(CR|DR|Cr|Dr|cr|dr)\.?$|^-$|^\)$/.test(t.text)) { merged[merged.length - 1] = joinTokens([prev, t], `${prev.text} ${t.text}`); continue; }
      if (looksNumeric(prev.text) && currencyFromToken(t.text, "cell") && /^[A-Z]{3}$/.test(t.text)) { merged[merged.length - 1] = joinTokens([prev, t], `${prev.text} ${t.text}`); continue; }
      // `1 234.56` read as two words of one OCR line: only when the gap is about one space.
      if (prev.lineKey === t.lineKey && close(prev, t, 1.5) && /^[-(]?(?:R|\$|€|£)?\s?\d{1,3}$/.test(prev.text) && /^\d{3}(?:[ ,.]\d{3})*(?:[.,]\d{1,4})?\)?(?:\s?(?:CR|DR))?$/i.test(t.text)) {
        merged[merged.length - 1] = joinTokens([prev, t], `${prev.text} ${t.text}`); continue;
      }
    }
    merged.push(t);
  }
  return merged;
}

/** Tokens of one page grouped into rows by vertical centre (and OCR line id when given). */
export function layoutPage(lines: CleanLine[], pageIndex: number, fileIndex: number | null): PageLayout {
  const tokens = lines.flatMap((l) => tokensOfLine(l, pageIndex, fileIndex));
  const medianH = median(lines.map((l) => l.h)) || 1;
  // Units: tokens of one OCR line (if it is flat) or of one box.
  const byKey = new Map<string, Token[]>();
  for (const t of tokens) { const k = t.lineKey; pushTo(byKey, k, t); }
  const units: Token[][] = [];
  for (const [k, ts] of byKey) {
    const ycs = ts.map((t) => t.y + t.h / 2);
    if (k.startsWith("l") && Math.max(...ycs) - Math.min(...ycs) > medianH) {
      // An OCR "line" that is not flat: fall back to its boxes.
      const byBox = new Map<number, Token[]>();
      for (const t of ts) pushTo(byBox, t.parts[0].lineIndex, t);
      units.push(...byBox.values());
    } else units.push(ts);
  }
  const unitYc = (u: Token[]) => median(u.map((t) => t.y + t.h / 2));
  const unitH = (u: Token[]) => median(u.map((t) => t.h));
  units.sort((a, b) => unitYc(a) - unitYc(b) || Math.min(...a.map((t) => t.x)) - Math.min(...b.map((t) => t.x)));
  const groups: { yc: number; h: number; tokens: Token[]; n: number }[] = [];
  for (const u of units) {
    const yc = unitYc(u), h = unitH(u);
    const g = groups[groups.length - 1];
    if (g && Math.abs(yc - g.yc) <= 0.5 * Math.min(h, g.h)) {
      g.tokens.push(...u); g.yc = (g.yc * g.n + yc) / (g.n + 1); g.n++; g.h = Math.max(g.h, h);
    } else groups.push({ yc, h, tokens: [...u], n: 1 });
  }
  const rows: Row[] = groups.map((g, index) => {
    const ts = mergeComposites(g.tokens.sort((a, b) => a.x - b.x));
    return { pageIndex, fileIndex, index, tokens: ts, yc: g.yc, top: Math.min(...ts.map((t) => t.y)), bottom: Math.max(...ts.map((t) => t.y + t.h)), h: median(ts.map((t) => t.h)) };
  });
  return { pageIndex, fileIndex, rows, medianH };
}

export const rowText = (r: Row) => r.tokens.map((t) => t.text).join(" ");

// ---------------------------------------------------------------- header vocabulary

type Group = "earnings" | "deductions" | "contributions";
interface VocabEntry { words: string[]; role: ColumnRole; group?: Group; head?: boolean }

const v = (role: ColumnRole, phrases: string[], extra: Partial<VocabEntry> = {}): VocabEntry[] => phrases.map((p) => ({ words: p.split(" "), role, ...extra }));

export const VOCAB: Record<FinancialDocumentKind, VocabEntry[]> = {
  bank_statement: [
    ...v("date", ["date", "txn date", "trans date", "transaction date", "tran date", "posting date", "post date", "processed date", "effective date", "book date"]),
    ...v("value_date", ["value date"]),
    ...v("description", ["description", "details", "transaction details", "narrative", "particulars", "transaction", "transactions", "transaction description", "memo"]),
    ...v("reference", ["reference", "ref", "cheque no", "cheque number", "ref no"]),
    ...v("debit", ["debit", "debits", "debit amount", "withdrawal", "withdrawals", "money out", "paid out", "payments out"]),
    ...v("credit", ["credit", "credits", "credit amount", "deposit", "deposits", "money in", "paid in", "payments in"]),
    ...v("amount", ["amount", "transaction amount", "value"]),
    ...v("balance", ["balance", "running balance", "balance amount"]),
  ],
  invoice: [
    ...v("description", ["description", "item", "items", "item description", "product", "products", "service", "services", "details", "particulars", "product description"]),
    ...v("code", ["code", "item code", "sku", "product code", "part no", "item no", "#", "line"]),
    ...v("quantity", ["qty", "quantity", "units", "hours", "hrs", "qty.", "quantity ordered"]),
    ...v("unit_price", ["unit price", "price", "rate", "unit cost", "unit rate", "price each", "each", "unit price excl vat", "unit price excl", "price excl vat", "unit price excl. vat", "unit"]),
    ...v("tax_rate", ["vat %", "tax %", "vat rate", "tax rate", "gst %", "%"]),
    ...v("tax", ["vat", "tax", "gst", "vat amount", "tax amount"]),
    ...v("amount", ["amount", "line total", "total", "net amount", "amount excl vat", "amount excl", "amount incl vat", "amount incl", "total excl vat", "total incl vat", "ext price", "extended price", "net", "line amount", "amount excl. vat", "amount incl. vat"]),
    ...v("date", ["date", "service date"]),
  ],
  payslip: [
    ...v("description", ["earnings", "earning", "income", "payments", "allowances"], { group: "earnings", head: true }),
    ...v("description", ["deductions", "deduction"], { group: "deductions", head: true }),
    ...v("description", ["company contributions", "employer contributions", "contributions", "employer contribution"], { group: "contributions", head: true }),
    ...v("description", ["description", "item", "details"]),
    ...v("code", ["code"]),
    ...v("quantity", ["hours", "hrs", "units", "qty", "days", "quantity"]),
    ...v("unit_price", ["rate"]),
    ...v("amount", ["amount", "current", "this period", "current period", "value", "amount (current)"]),
    ...v("ytd", ["ytd", "year to date", "ytd amount", "cumulative", "ytd total"]),
  ],
};

const norm = (s: string) => s.toLowerCase().replace(/^[^\p{L}\p{N}%#]+|[^\p{L}\p{N}%.#]+$/gu, "").replace(/\.$/, "").replace(/:$/, "");

export interface HeaderColumn {
  role: ColumnRole;
  label: string;
  group: Group | null;
  x0: number;
  x1: number;
  currency: CurrencyMark | null;
  tokens: Token[];
}

export interface HeaderCandidate {
  kind: FinancialDocumentKind;
  rows: Row[];
  columns: HeaderColumn[];
  score: number;
  matchedFraction: number;
}

const QUALIFIER = /^\(?([A-Z]{3}|R|\$|€|£|US\$)\)?$/;

/** Split one row into labelled columns with the kind's vocabulary (longest match first). */
function segmentRow(tokens: Token[], vocab: VocabEntry[]): { columns: HeaderColumn[]; matched: number; counted: number } {
  const columns: HeaderColumn[] = [];
  let matched = 0, counted = 0;
  let i = 0;
  while (i < tokens.length) {
    const t = tokens[i];
    const q = QUALIFIER.exec(t.text);
    const prev = columns[columns.length - 1];
    const qMark = q ? currencyFromToken(q[1], "column_header") : null;
    if (qMark && prev && close(prev.tokens[prev.tokens.length - 1], t, 2.5)) {
      prev.currency = qMark; prev.tokens.push(t); prev.x1 = Math.max(prev.x1, right(t)); i++; continue;
    }
    let best: { entry: VocabEntry; n: number } | null = null;
    for (const entry of vocab) {
      const n = entry.words.length;
      if (best && n <= best.n) continue;
      const win = tokens.slice(i, i + n);
      if (win.length < n || !win.every((w, k) => k === 0 || close(win[k - 1], w, 2.5))) continue;
      if (win.every((w, k) => norm(w.text) === entry.words[k])) best = { entry, n };
    }
    counted++;
    if (best) {
      const win = tokens.slice(i, i + best.n);
      matched++;
      columns.push({ role: best.entry.role, label: win.map((w) => w.text).join(" "), group: best.entry.head ? best.entry.group ?? null : null,
        x0: Math.min(...win.map((w) => w.x)), x1: Math.max(...win.map(right)), currency: null, tokens: win });
      i += best.n;
    } else {
      // Unrecognised words: join neighbours into one unknown column.
      if (prev && prev.role === "unknown" && close(prev.tokens[prev.tokens.length - 1], t, 1.5)) { prev.label += ` ${t.text}`; prev.tokens.push(t); prev.x1 = right(t); counted--; }
      else columns.push({ role: "unknown", label: t.text, group: null, x0: t.x, x1: right(t), currency: null, tokens: [t] });
      i++;
    }
  }
  return { columns, matched, counted };
}

function isDataLike(row: Row): boolean {
  return row.tokens.some((t) => (looksNumeric(t.text) === "numeric" && /\d[.,]\d|\d{2,}/.test(t.text) && !/^#?\d{1,2}$/.test(t.text)) || recognizeDate(t.text) !== null);
}

function scoreKind(kind: FinancialDocumentKind, columns: HeaderColumn[], precedingGroup: Group | null): number | null {
  const roles = new Set(columns.map((c) => c.role));
  const has = (r: ColumnRole) => roles.has(r);
  if (kind === "bank_statement") {
    if (!(has("date") && has("description") && (has("debit") || has("credit") || has("amount")))) return null;
    if (has("quantity") || has("unit_price")) return null;
    return roles.size + (has("balance") ? 2 : 0) + (has("debit") && has("credit") ? 1 : 0);
  }
  if (kind === "invoice") {
    if (!has("description")) return null;
    if (!((has("amount") && (has("quantity") || has("unit_price"))) || (has("quantity") && has("unit_price")))) return null;
    if (has("balance") || has("debit") || has("credit")) return null;
    return roles.size + 1;
  }
  const heads = columns.filter((c) => c.group).length;
  if (!(heads || precedingGroup) || !(has("amount") || has("ytd"))) return null;
  return roles.size + heads + 1;
}

function assignGroups(columns: HeaderColumn[], precedingGroup: Group | null) {
  let g: Group | null = precedingGroup;
  for (const c of columns) { if (c.group) g = c.group; else c.group = g; }
}

/** Payslip tables are often titled by a lone `Earnings` / `Deductions` row above a generic header. */
export function groupTitle(row: Row | undefined): Group | null {
  if (!row || row.tokens.length > 3) return null;
  const t = norm(rowText(row));
  for (const e of VOCAB.payslip) if (e.head && e.words.join(" ") === t) return e.group ?? null;
  return null;
}

/** Score a row (and optionally the row below it, for two-line headers) as a table header of each kind. */
export function headerCandidates(rows: Row[], i: number, kinds: FinancialDocumentKind[]): HeaderCandidate[] {
  const row = rows[i];
  if (!row || isDataLike(row) || row.tokens.length < 2 && !rows[i + 1]) return [];
  const out: HeaderCandidate[] = [];
  const below = rows[i + 1];
  const twoLine = below && !isDataLike(below) && below.top - row.bottom < 0.9 * row.h && below.tokens.length <= row.tokens.length + 1;
  const preceding = groupTitle(rows[i - 1]) ?? groupTitle(rows[i - 2]);
  for (const kind of kinds) {
    const vocab = VOCAB[kind];
    const tries: { rows: Row[]; columns: HeaderColumn[]; matched: number; counted: number }[] = [];
    const one = segmentRow(row.tokens, vocab);
    tries.push({ rows: [row], ...one });
    if (twoLine) {
      // Hang each lower token under the upper column it overlaps most, then re-read the combined labels.
      const cols = one.columns.map((c) => ({ ...c, tokens: [...c.tokens] }));
      let attached = 0;
      for (const t of below.tokens) {
        let best = -1, bestOverlap = 0;
        cols.forEach((c, k) => { const o = Math.min(c.x1, right(t)) - Math.max(c.x0, t.x); if (o > bestOverlap) { bestOverlap = o; best = k; } });
        if (best < 0) { cols.push({ role: "unknown", label: t.text, group: null, x0: t.x, x1: right(t), currency: null, tokens: [t] }); continue; }
        const c = cols[best];
        const q = QUALIFIER.exec(t.text);
        const qMark = q ? currencyFromToken(q[1], "column_header") : null;
        if (qMark) c.currency = qMark;
        else c.label = `${c.label} ${t.text}`;
        c.tokens.push(t); c.x0 = Math.min(c.x0, t.x); c.x1 = Math.max(c.x1, right(t)); attached++;
      }
      let matched = 0;
      for (const c of cols) {
        const words = c.label.split(/\s+/).map(norm);
        const entry = vocab.filter((e) => e.words.join(" ") === words.join(" "))[0];
        if (entry) { c.role = entry.role; c.group = entry.head ? entry.group ?? null : c.group; matched++; }
        else if (c.role !== "unknown") matched++;
      }
      cols.sort((a, b) => a.x0 - b.x0);
      if (attached) tries.push({ rows: [row, below], columns: cols, matched, counted: cols.length });
    }
    for (const t of tries) {
      const fraction = t.counted ? t.matched / t.counted : 0;
      if (fraction < 0.6 || t.columns.length < 2) continue;
      const score = scoreKind(kind, t.columns, kind === "payslip" ? preceding : null);
      if (score === null) continue;
      if (kind === "payslip") assignGroups(t.columns, preceding);
      out.push({ kind, rows: t.rows, columns: t.columns.sort((a, b) => a.x0 - b.x0), score: score + fraction + (t.rows.length > 1 ? 0.5 : 0), matchedFraction: fraction });
    }
  }
  return out.sort((a, b) => b.score - a.score);
}

// ---------------------------------------------------------------- data rows

export const NUMERIC_ROLES = new Set<ColumnRole>(["debit", "credit", "amount", "balance", "quantity", "unit_price", "tax", "tax_rate", "ytd"]);
export const TEXT_ROLES = new Set<ColumnRole>(["description", "reference", "code", "unknown"]);
const DATE_ROLES = new Set<ColumnRole>(["date", "value_date"]);

export interface Assigned { column: number; tokens: Token[] }
/** `unresolved`: values whose column no rule settles (reported on the row, never placed by a guess). */
export interface Assignment { cells: Assigned[]; ambiguous: { token: Token; columns: number[] }[]; unassigned: Token[]; unresolved: Token[] }

const overlap = (t: Token, c: HeaderColumn) => Math.min(c.x1, right(t)) - Math.max(c.x0, t.x);

/** Put a row's tokens into the header's columns by type and geometry. */
export function assignRow(tokens: Token[], columns: HeaderColumn[]): Assignment {
  const byCol = new Map<number, Token[]>();
  const ambiguous: Assignment["ambiguous"] = [];
  const unassigned: Token[] = [];
  const unresolved: Token[] = [];
  const put = (k: number, t: Token) => pushTo(byCol, k, t);
  const idx = (pred: (c: HeaderColumn) => boolean) => columns.map((c, k) => (pred(c) ? k : -1)).filter((k) => k >= 0);
  const numericCols = idx((c) => NUMERIC_ROLES.has(c.role) && c.role !== "tax_rate");
  const textCols = idx((c) => TEXT_ROLES.has(c.role));
  const dateCols = idx((c) => DATE_ROLES.has(c.role));
  const best = (t: Token, cands: number[], reach: number): number | null => {
    if (!cands.length) return null;
    const scored = cands.map((k) => {
      const c = columns[k];
      const o = overlap(t, c);
      return { k, ratio: o / Math.max(1e-6, Math.min(t.w, c.x1 - c.x0)), dist: o > 0 ? 0 : Math.min(Math.abs(t.x - c.x1), Math.abs(c.x0 - right(t))), dRight: Math.abs(right(t) - c.x1) };
    });
    const over = scored.filter((s) => s.ratio > 0).sort((a, b) => b.ratio - a.ratio || a.dRight - b.dRight);
    if (over.length) {
      if (over.length > 1 && over[1].ratio > 0.25 && (t.parts.some((p) => p.approximate) || over[0].ratio - over[1].ratio < 0.2))
        ambiguous.push({ token: t, columns: [over[0].k, over[1].k] });
      return over[0].k;
    }
    const near = scored.sort((a, b) => a.dist - b.dist)[0];
    return near.dist <= reach * t.cw ? near.k : null;
  };
  // A box spanning several columns (line-level OCR) has interpolated word positions: assign it by type order
  // instead. Its last amount goes to the rightmost money column; an amount that could sit in more than one of
  // the remaining columns (debit or credit) is reported ambiguous rather than placed by a guessed position.
  const handled = new Set<Token>();
  const boxes = new Map<number, Token[]>();
  for (const t of tokens) if (t.parts.every((p) => p.approximate && p.lineIndex === t.parts[0].lineIndex)) pushTo(boxes, t.parts[0].lineIndex, t);
  for (const group of boxes.values()) {
    if (group.length < 2) continue;
    const span = { x0: Math.min(...group.map((t) => t.x)), x1: Math.max(...group.map(right)) };
    const spanned = columns.map((c, k) => ({ c, k })).filter(({ c }) => Math.min(c.x1, span.x1) - Math.max(c.x0, span.x0) > 0);
    if (spanned.length < 3) continue;
    const seq = [...group].sort((a, b) => a.x - b.x);
    const moneyCols = spanned.filter(({ c }) => NUMERIC_ROLES.has(c.role)).map(({ k }) => k);
    const strict = !moneyCols.some((k) => columns[k].role === "quantity");
    const isValue = (t: Token) => (looksNumeric(t.text) !== null || isPercentToken(t.text)) && (!strict || /[.,]\d{2}\)?(\s?(CR|DR|Cr|Dr|-))?$|^[-(]?\s?(R|\$|€|£|[A-Z]{3})\s?\d/.test(t.text));
    let j = seq.length - 1;
    const nums: Token[] = [];
    while (j >= 0 && isValue(seq[j]) && nums.length < moneyCols.length) { nums.unshift(seq[j]); j--; }
    if (nums.length && moneyCols.length) {
      if (nums.length === moneyCols.length) nums.forEach((t, i) => { put(moneyCols[i], t); handled.add(t); });
      else {
        const last = nums[nums.length - 1];
        put(moneyCols[moneyCols.length - 1], last); handled.add(last);
        // Fewer values than columns: optional columns (quantity, rate) are the ones left empty, so the values pack
        // to the right of the rest. Debit vs credit has no such rule; that choice stays a reported guess.
        const rest = moneyCols.slice(0, -1);
        const OPTIONAL = new Set<ColumnRole>(["quantity", "unit_price", "tax_rate"]);
        const required = rest.filter((k) => !OPTIONAL.has(columns[k].role));
        const others = nums.slice(0, -1);
        const pair = required.some((k) => columns[k].role === "debit") && required.some((k) => columns[k].role === "credit");
        if (nums.length === 1 && required.length > 0) {
          // One value and several columns it could be (an amount, or a balance printed only on some rows): no rule
          // settles it, so it is left unresolved and reported rather than assumed to be the rightmost column.
          handled.add(last); unresolved.push(last); ambiguous.push({ token: last, columns: moneyCols });
          const lastCol = moneyCols[moneyCols.length - 1];
          const cells = byCol.get(lastCol);
          if (cells) { cells.splice(cells.indexOf(last), 1); if (!cells.length) byCol.delete(lastCol); }
        } else
        if (!pair && others.length <= required.length) others.forEach((t, i) => { put(required[required.length - others.length + i], t); handled.add(t); ambiguous.push({ token: t, columns: rest }); });
        else for (const t of others.reverse()) {
          const k = best(t, rest, 1e9) ?? rest[rest.length - 1];
          ambiguous.push({ token: t, columns: rest });
          put(k, t); handled.add(t);
        }
      }
    }
    for (const t of seq.slice(0, j + 1)) {
      if (recognizeDate(t.text) && dateCols.length) { put(dateCols[0], t); handled.add(t); continue; }
      const desc = textCols.find((n) => columns[n].role === "description") ?? textCols[0];
      if (desc !== undefined) { put(desc, t); handled.add(t); }
    }
  }
  for (const t of tokens) {
    if (handled.has(t)) continue;
    const isDash = /^[-–—]$/.test(t.text);
    const date = recognizeDate(t.text);
    const num = looksNumeric(t.text);
    let k: number | null = null;
    if (date && dateCols.length) k = best(t, dateCols, 6) ?? (dateCols.length === 1 ? dateCols[0] : null);
    else if (isPercentToken(t.text)) k = best(t, idx((c) => c.role === "tax_rate"), 4) ?? best(t, idx((c) => c.role === "tax"), 2);
    else if (num || isDash) {
      k = best(t, numericCols, 3);
      if (k === null && isDash) continue;
    }
    if (k === null) {
      // Text: inside a numeric column's own span it belongs there (and will be reported unparseable).
      const inNumeric = numericCols.find((n) => { const c = columns[n]; const mid = t.x + t.w / 2; return mid >= c.x0 - 0.5 * t.cw && mid <= c.x1 + 0.5 * t.cw && overlap(t, c) > 0.5 * t.w; });
      if (inNumeric !== undefined && !(textCols.some((n) => overlap(t, columns[n]) > 0))) k = inNumeric;
      else if (textCols.length) {
        const left = textCols.filter((n) => columns[n].x0 <= t.x + 2 * t.cw).sort((a, b) => columns[b].x0 - columns[a].x0)[0];
        k = left ?? textCols[0];
      } else if (date && !dateCols.length) k = null;
    }
    if (k === null) unassigned.push(t);
    else put(k, t);
  }
  const cells = [...byCol.entries()].sort((a, b) => a[0] - b[0]).map(([column, ts]) => ({ column, tokens: ts.sort((a, b) => a.x - b.x) }));
  return { cells, ambiguous, unassigned, unresolved };
}

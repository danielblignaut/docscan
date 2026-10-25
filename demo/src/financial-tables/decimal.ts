/** Exact decimal arithmetic on BigInt: a value is `units / 10^scale`. No float ever touches money. */
export interface Dec { u: bigint; s: number }

/** Longest digit run a money or quantity token may have: bounds BigInt work on untrusted text. */
export const MAX_DIGITS = 24;

const TEN = 10n;
const pow10 = (n: number): bigint => TEN ** BigInt(n);

export function dec(units: bigint | string, scale: number): Dec {
  return { u: typeof units === "bigint" ? units : BigInt(units), s: scale };
}
export function rescale(a: Dec, s: number): Dec {
  if (s < a.s) throw new RangeError("rescale would drop digits; use round()");
  return { u: a.u * pow10(s - a.s), s };
}
function align(a: Dec, b: Dec): [bigint, bigint, number] {
  const s = Math.max(a.s, b.s);
  return [rescale(a, s).u, rescale(b, s).u, s];
}
export const add = (a: Dec, b: Dec): Dec => { const [x, y, s] = align(a, b); return { u: x + y, s }; };
export const sub = (a: Dec, b: Dec): Dec => { const [x, y, s] = align(a, b); return { u: x - y, s }; };
export const mul = (a: Dec, b: Dec): Dec => ({ u: a.u * b.u, s: a.s + b.s });
export const neg = (a: Dec): Dec => ({ u: -a.u, s: a.s });
export const abs = (a: Dec): Dec => ({ u: a.u < 0n ? -a.u : a.u, s: a.s });
export const cmp = (a: Dec, b: Dec): number => { const [x, y] = align(a, b); return x < y ? -1 : x > y ? 1 : 0; };
export const eq = (a: Dec, b: Dec): boolean => cmp(a, b) === 0;
export const isZero = (a: Dec): boolean => a.u === 0n;
export const sum = (values: Dec[]): Dec => values.reduce(add, { u: 0n, s: 0 });

/** Round to `s` decimals. `half_up` rounds ties away from zero; `half_even` to the even neighbour. */
export function round(a: Dec, s: number, mode: "half_up" | "half_even"): Dec {
  if (s >= a.s) return rescale(a, s);
  const d = pow10(a.s - s);
  const negative = a.u < 0n;
  const m = negative ? -a.u : a.u;
  let q = m / d;
  const r = m % d;
  const twice = r * 2n;
  if (twice > d || (twice === d && (mode === "half_up" || q % 2n === 1n))) q += 1n;
  return { u: negative ? -q : q, s };
}

/** Divide by 100 exactly (for percentages): only a scale change. */
export const percentOf = (a: Dec, rate: Dec): Dec => ({ u: a.u * rate.u, s: a.s + rate.s + 2 });

export function toDecimalString(a: Dec): string {
  const negative = a.u < 0n;
  const digits = (negative ? -a.u : a.u).toString().padStart(a.s + 1, "0");
  const body = a.s ? `${digits.slice(0, -a.s)}.${digits.slice(-a.s)}` : digits;
  return negative ? `-${body}` : body;
}

/** Parse a signed decimal string we produced (`-12.50`). */
export function fromDecimalString(text: string): Dec | null {
  const m = /^(-?)(\d{1,24})(?:\.(\d{1,24}))?$/.exec(text);
  if (!m) return null;
  const frac = m[3] ?? "";
  const u = BigInt(m[2] + frac);
  return { u: m[1] ? -u : u, s: frac.length };
}

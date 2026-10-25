// Procedural, fictional item-stress sequences with ground truth. No images,
// no real identifiers, no TEST/reserved data: every value is invented here.
// GTIN-13s use the 200 restricted-circulation prefix, IMEIs start 001 (the 00
// test range) with a Luhn check, serials start FICT.
//
// A sequence is a fixed set of physical units (boxes) on a shelf, seen by a
// camera script. Each frame is what the readers would return: barcodes (as
// read_all: one per format + text) and the label reader's fields, plus, beside
// them, the ground truth of every observation: its physical unit, true role,
// true value, the value as read, and its provenance (code / text / both).
// Specimen conditions (what is printed and how it misreads) and camera
// conditions (where it is, what is visible) are separate factors.
import { createHash } from "node:crypto";

export const SPECIMENS = ["clean", "same_model", "sparse", "gs1", "serial_adversarial", "imei_adversarial"];
export const CAMERAS = ["static", "pan", "contact", "contact_rotated", "occlusion", "rotation", "missing_points", "repeat", "zoom", "dense"];
export const SPLITS = { dev: [0, 1, 2], holdout: [3, 4, 5] };
export const MAX_VIEWS = 6; // ItemsCapture's saved camera views

// ---------------------------------------------------------------- values

export function mulberry32(a) {
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const seedOf = s => createHash("sha256").update(s).digest().readUInt32LE(0);

/** Independent of the module under test: the standard Luhn and GS1 mod-10 rules. */
export function luhnCheck(body) {
  let sum = 0;
  for (let i = 0; i < body.length; i++) { let d = +body[body.length - 1 - i]; if (i % 2 === 0) { d *= 2; if (d > 9) d -= 9; } sum += d; }
  return String((10 - (sum % 10)) % 10);
}
export const luhnOk = v => /^\d{15}$/.test(v) && luhnCheck(v.slice(0, 14)) === v[14];
export function gtinCheck(body) {
  let sum = 0;
  for (let i = 0; i < body.length; i++) sum += +body[body.length - 1 - i] * (i % 2 === 0 ? 3 : 1);
  return String((10 - (sum % 10)) % 10);
}
export const gtinOk = v => /^\d+$/.test(v) && [8, 12, 13, 14].includes(v.length) && gtinCheck(v.slice(0, -1)) === v.at(-1);

const digits = (rng, n) => Array.from({ length: n }, () => Math.floor(rng() * 10)).join("");
const SERIAL_ALPHABET = "ACDEFGHJKLMNPQRTUVWXY34679"; // no OCR-confusable characters
const CONFUSABLE = { 0: "O", O: "0", 8: "B", B: "8", 5: "S", S: "5", 1: "I", I: "1", 2: "Z", Z: "2" };
const pick = (rng, s) => s[Math.floor(rng() * s.length)];

/** A model's GTIN-13 (prefix 200). */
export const modelGtin = m => { const b = `200${String(m).padStart(9, "0")}`; return b + gtinCheck(b); };

class Values {
  constructor(rng) { this.rng = rng; this.taken = new Set(); }
  imei(force) {
    for (;;) {
      const b = ("001" + digits(this.rng, 11)).split("");
      for (const [i, d] of Object.entries(force ?? {})) b[i] = d;
      const v = b.join("") + luhnCheck(b.join(""));
      if (!this.taken.has(v)) { this.taken.add(v); return v; }
    }
  }
  serial(pairPos) {
    for (;;) {
      const c = Array.from({ length: 5 }, () => pick(this.rng, SERIAL_ALPHABET));
      if (pairPos !== undefined) c[pairPos] = pick(this.rng, "08512");
      const v = "FICT" + c.join("");
      if (!this.taken.has(v) && (pairPos === undefined || !this.taken.has(swapAt(v, 4 + pairPos)))) { this.taken.add(v); return v; }
    }
  }
}
const swapAt = (s, i) => s.slice(0, i) + (CONFUSABLE[s[i]] ?? s[i]) + s.slice(i + 1);
/** The 09/90 transposition at i (Luhn-preserving: 0 doubled is 0, 9 doubled is 9). */
const transpose = (s, i) => s.slice(0, i) + s[i + 1] + s[i] + s.slice(i + 2);

// ---------------------------------------------------------------- units

/**
 * A unit: one physical box. `lines` are what is printed on its label, in
 * label-local pixels at scale 1: 200 px wide, stacked 15 px apart, as the
 * existing tests' fictional boxes.
 */
function makeUnits(spec, n, rng) {
  const V = new Values(rng), units = [];
  const sameModel = spec !== "clean" && spec !== "sparse";
  for (let k = 0; k < n; k++) {
    const u = { id: `u${k + 1}`, index: k, model: sameModel ? 1 : spec === "sparse" ? 1 + Math.floor(rng() * 3) : k + 1, imei1: null, imei2: null, serial: null, accessory: false, partner: null, transposeAt: {} };
    u.gtin = modelGtin(u.model);
    const pairB = (spec === "serial_adversarial" || spec === "imei_adversarial") && k % 2 === 1;
    if (pairB) u.partner = k - 1, units[k - 1].partner = k;
    if (spec === "imei_adversarial") {
      if (pairB) {
        const a = units[k - 1];
        u.imei1 = transpose(a.imei1, 6); V.taken.add(u.imei1);
        u.transposeAt.imei1 = 6;
      } else u.imei1 = V.imei({ 6: "0", 7: "9" }), u.transposeAt.imei1 = 6;
      u.imei2 = V.imei({ 9: "0", 10: "9" }); u.transposeAt.imei2 = 9;
      u.serial = V.serial();
    } else if (spec === "serial_adversarial") {
      u.imei1 = V.imei(); u.imei2 = V.imei();
      if (pairB) {
        const a = units[k - 1];
        u.serial = swapAt(a.serial, a.pairPos); u.pairPos = a.pairPos; V.taken.add(u.serial);
      } else { const p = Math.floor(rng() * 5); u.serial = V.serial(p); u.pairPos = 4 + p; }
    } else {
      u.imei1 = V.imei(); u.imei2 = V.imei(); u.serial = V.serial();
      if (spec === "sparse") {
        const r = rng();
        if (r < 0.15) { u.accessory = true; u.imei1 = u.imei2 = u.serial = null; }
        else {
          if (rng() < 0.3) u.serial = null;
          if (rng() < 0.3) u.imei2 = null;
        }
      }
    }
    u.lines = layout(u, spec);
    units.push(u);
  }
  return units;
}

function layout(u, spec) {
  const lines = [];
  let y = 10;
  const add = (role, h, bars, text, label) => { lines.push({ role, x: 10, y, w: 200, h, bars, text, label }); y += h + 15; };
  if (u.gtin) add("gtin", 60, "ean13", true, null);
  if (u.imei1) add("imei1", 50, "code128", true, u.imei2 ? "IMEI1" : "IMEI");
  if (u.imei2) add("imei2", 50, "code128", true, "IMEI2");
  if (u.serial) add("serial", 20, null, true, "SN");
  if (spec === "gs1" && u.serial) add("gs1", 50, "code128", false, null);
  u.labelBottom = y - 15;
  return lines;
}

export const gs1Text = u => `]C101${"0" + u.gtin}21${u.serial}`;

// ---------------------------------------------------------------- geometry

function grid(units, cols, gapX, gapY, margin) {
  const out = [];
  let y = 0;
  for (let r = 0; r * cols < units.length; r++) {
    const row = units.slice(r * cols, r * cols + cols);
    let x = 0, rowH = 0;
    for (const u of row) {
      const h = u.labelBottom + margin;
      out.push({ unit: u.index, x, y, w: 220, h });
      x += 220 + gapX(); rowH = Math.max(rowH, h);
    }
    y += rowH + gapY();
  }
  return out;
}
const extent = ps => {
  const x0 = Math.min(...ps.map(p => p.x)), y0 = Math.min(...ps.map(p => p.y));
  return { x0, y0, x1: Math.max(...ps.map(p => p.x + p.w)), y1: Math.max(...ps.map(p => p.y + p.h)) };
};
const round1 = v => Math.round(v * 10) / 10;

function project(cam, px, py) {
  const c = Math.cos((cam.theta * Math.PI) / 180), s = Math.sin((cam.theta * Math.PI) / 180);
  const dx = cam.s * (px - cam.cx), dy = cam.s * (py - cam.cy);
  return [c * dx - s * dy + cam.W / 2 + (cam.jx ?? 0), s * dx + c * dy + cam.H / 2 + (cam.jy ?? 0)];
}
const aabb = pts => {
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)];
};
const inside = (p, W, H) => p[0] >= 2 && p[1] >= 2 && p[0] <= W - 2 && p[1] <= H - 2;
const overlapFrac = (b, o) => {
  const w = Math.max(0, Math.min(b[0] + b[2], o[0] + o[2]) - Math.max(b[0], o[0]));
  const h = Math.max(0, Math.min(b[1] + b[3], o[1] + o[3]) - Math.max(b[1], o[1]));
  return b[2] * b[3] > 0 ? (w * h) / (b[2] * b[3]) : 0;
};
function pText(theta) {
  const a = Math.abs(((theta % 180) + 180) % 180), t = Math.min(a, 180 - a);
  return t <= 15 ? 0.97 : t <= 30 ? 0.6 : t <= 45 ? 0.2 : 0;
}

// ---------------------------------------------------------------- one frame

/**
 * What the readers return for one frame, and its ground truth.
 * `cfg.hidden` / `cfg.barsOff` / `cfg.text` let a script force a line unread,
 * its bars undecoded, or its print read as a given value.
 */
function emitFrame(units, placements, cam, rng, cfg) {
  const barcodes = [], fields = [], gt = { barcodes: [], fields: [], collapsed: [] };
  const geo = []; // for regions: per unit, every line's projected corners
  const prob = cfg.deterministic ? { bars: 1, text: () => 1 } : { bars: 0.97, text: pText };
  for (const pl of placements) {
    const u = units[pl.unit];
    const corners = [];
    let allIn = true;
    for (const line of u.lines) {
      const x = pl.x + line.x, y = pl.y + line.y;
      const pts = [[x, y], [x + line.w, y], [x + line.w, y + line.h], [x, y + line.h]].map(p => project(cam, ...p));
      const key = `${u.index}:${line.role}`;
      // A script-hidden line is not on this view's surface at all (not a region's extent either).
      if (cfg.hidden?.has(key)) continue;
      corners.push(...pts);
      if (!pts.every(p => inside(p, cam.W, cam.H))) { allIn = false; continue; }
      const box = aabb(pts).map(round1);
      if (cfg.occluder && overlapFrac(box, cfg.occluder) > 0.4) continue;
      // Draw order is fixed per line whatever the branch, so one condition does not shift another's draws.
      const rDrop = rng(), rBars = rng(), rText = rng(), rMis = rng(), rPts = rng(), rBox = rng();
      if (rDrop < (cfg.dropout ?? 0)) continue;
      let barsRead = !!line.bars && rBars < prob.bars && !cfg.barsOff?.has(key);
      if (cfg.spec === "imei_adversarial" && line.role.startsWith("imei") && rBars < 0.3) barsRead = false;
      const textRead = line.text && rText < prob.text(cam.theta);
      const value = line.role === "gs1" ? gs1Text(u) : u[line.role];
      if (barsRead) {
        const cy = y + line.h / 2;
        const points = [project(cam, x + 10, cy), project(cam, x + line.w - 10, cy)].map(p => p.map(round1));
        const code = { format: line.bars, text: value, count: 1 };
        if (!(rPts < (cfg.missingPoints ?? 0))) code.points = points;
        if (barcodes.some(b => b.format === code.format && b.text === code.text)) gt.collapsed.push({ unit: u.index, role: line.role });
        else { barcodes.push(code); gt.barcodes.push({ unit: u.index, role: line.role, value, read: value, provenance: "code" }); }
      }
      if (textRead && line.role !== "gs1") {
        let read = value;
        if (cfg.text?.has(key)) read = cfg.text.get(key);
        else if (cfg.spec === "serial_adversarial" && line.role === "serial") {
          if (rMis < 0.15 && u.partner !== null) read = units[u.partner].serial;
          else if (rMis < 0.25) read = phantomSerial(u, rng);
        } else if (cfg.spec === "imei_adversarial" && line.role.startsWith("imei") && !barsRead && rMis < 0.5) read = transpose(value, u.transposeAt[line.role]);
        if (barsRead) read = value; // a labelled code's value is its bars
        const kind = line.role === "gtin" ? "gtin" : line.role.startsWith("imei") ? "imei" : "text";
        const check = kind === "imei" ? luhnOk(read) : kind === "gtin" ? gtinOk(read) : null;
        const bbox = rBox < (cfg.missingBox ?? 0) ? [NaN, NaN, NaN, NaN] : box;
        fields.push({ label: line.label, name: line.label ?? "Barcode", barcode_unread: false, value: read, kind,
          source: barsRead ? "both" : "text", check_digit_valid: check, barcode_format: barsRead ? line.bars : null, bbox });
        gt.fields.push({ unit: u.index, role: line.role, value, read, provenance: barsRead ? "both" : "text" });
      }
    }
    geo.push({ unit: u.index, corners, allIn });
  }
  return { width: cam.W, height: cam.H, barcodes, fields, gt, geo };
}

function phantomSerial(u, rng) {
  const positions = [4, 5, 6, 7, 8].filter(p => p !== u.pairPos);
  const q = positions[Math.floor(rng() * positions.length)];
  const c = u.serial[q];
  const to = CONFUSABLE[c] ?? pick(rng, SERIAL_ALPHABET.replace(c, ""));
  return u.serial.slice(0, q) + to + u.serial.slice(q + 1);
}

/** A manual region per unit whose label is wholly in view; faulty when another unit's observation centre is inside. */
function regionsFor(frame) {
  const pad = 6, regions = [], faulty = [];
  const centres = [
    ...frame.barcodes.map((b, i) => ({ unit: frame.gt.barcodes[i].unit, c: b.points ? [(b.points[0][0] + b.points[1][0]) / 2, (b.points[0][1] + b.points[1][1]) / 2] : null })),
    ...frame.fields.map((f, i) => ({ unit: frame.gt.fields[i].unit, c: f.bbox.every(Number.isFinite) ? [f.bbox[0] + f.bbox[2] / 2, f.bbox[1] + f.bbox[3] / 2] : null })),
  ];
  for (const g of frame.geo) {
    if (!g.allIn || !g.corners.length) continue;
    const b = aabb(g.corners);
    const bbox = [b[0] - pad, b[1] - pad, b[2] + 2 * pad, b[3] + 2 * pad].map(round1);
    const id = `r${g.unit + 1}`;
    regions.push({ id, bbox, origin: "manual" });
    const holds = centres.filter(x => x.c && x.c[0] >= bbox[0] && x.c[0] <= bbox[0] + bbox[2] && x.c[1] >= bbox[1] && x.c[1] <= bbox[1] + bbox[3]);
    const units = [...new Set(holds.map(x => x.unit))];
    if (units.some(x => x !== g.unit)) faulty.push({ id, units: units.sort((a, b) => a - b) });
  }
  return { regions, faulty };
}

// ---------------------------------------------------------------- camera scripts

const W0 = 1280, H0 = 960;
function fit(ext, W, H, k = 0.9) { return Math.min(1, (k * W) / (ext.x1 - ext.x0), (k * H) / (ext.y1 - ext.y0)); }

function cameraScript(camera, units, rng) {
  const gap = (lo, hi) => () => lo + rng() * (hi - lo);
  const centreOf = e => [(e.x0 + e.x1) / 2, (e.y0 + e.y1) / 2];
  const jit = (a = 3) => ({ jx: (rng() * 2 - 1) * a, jy: (rng() * 2 - 1) * a });
  const frames = [];
  let placements;
  const staticFrames = (n, extra = () => ({})) => {
    const e = extent(placements), [cx, cy] = centreOf(e), s = fit(e, W0, H0);
    for (let t = 0; t < n; t++) frames.push({ cam: { cx, cy, s, theta: (rng() * 2 - 1) * 0.5, W: W0, H: H0, ...jit() }, ...extra(t) });
  };
  switch (camera) {
    case "static": placements = grid(units, 4, gap(80, 80), gap(60, 60), 40); staticFrames(12); break;
    case "missing_points": placements = grid(units, 4, gap(80, 80), gap(60, 60), 40); staticFrames(12, () => ({ missingPoints: 0.35, missingBox: 0.1 })); break;
    case "contact": {
      placements = grid(units, 4, gap(0, 6), gap(0, 6), 10);
      const e = extent(placements), [cx, cy] = centreOf(e), s = fit(e, W0, H0, 0.95);
      for (let t = 0; t < 12; t++) frames.push({ cam: { cx: cx + (t - 6) * 3, cy, s, theta: (rng() * 2 - 1) * 0.5, W: W0, H: H0, ...jit(2) } });
      break;
    }
    case "contact_rotated": {
      placements = grid(units, 4, gap(0, 6), gap(0, 6), 10);
      const e = extent(placements), [cx, cy] = centreOf(e), s = fit(e, W0, H0, 0.75);
      const roll = 20 + rng() * 15, sign = rng() < 0.5 ? -1 : 1;
      for (let t = 0; t < 12; t++) frames.push({ cam: { cx: cx + (t - 6) * 3, cy, s, theta: sign * (roll + (rng() * 2 - 1) * 2), W: W0, H: H0, ...jit(2) } });
      break;
    }
    case "dense": {
      placements = grid(units, 6, gap(4, 4), gap(4, 4), 10);
      const e = extent(placements), [cx, cy] = centreOf(e), s = fit(e, W0, H0, 0.95);
      for (let t = 0; t < 12; t++) frames.push({ cam: { cx, cy, s, theta: (rng() * 2 - 1) * 0.5, W: W0, H: H0, ...jit(2) }, dropout: 0.1 });
      break;
    }
    case "occlusion": {
      placements = grid(units, 4, gap(80, 80), gap(60, 60), 40);
      const oy = 100 + rng() * 500;
      staticFrames(16, t => ({ occluder: [-300 + t * 110, oy, 300, 300], dropout: 0.2 }));
      break;
    }
    case "rotation": {
      placements = grid(units, 3, gap(80, 80), gap(60, 60), 40);
      const e = extent(placements), [cx, cy] = centreOf(e);
      const thetas = [0, 10, 20, 30, 40, 50, 60, 50, 40, 30, 20, 10, 0, 0, 0, 0, 90, 90, 90, 90];
      for (const theta of thetas) frames.push({ cam: { cx, cy, s: 0.9, theta: theta + (rng() * 2 - 1) * 0.5, W: W0, H: H0, ...jit() } });
      break;
    }
    case "repeat": {
      placements = grid(units, 3, gap(80, 80), gap(60, 60), 40);
      const e = extent(placements), [cx, cy] = centreOf(e), s = fit(e, W0, H0);
      for (let t = 0; t < 6; t++) { const cam = { cx, cy, s, theta: (rng() * 2 - 1) * 0.5, W: W0, H: H0, ...jit() }; for (let r = 0; r < 3; r++) frames.push({ cam, repeatOf: r ? frames.length - r : null, distinct: t }); }
      break;
    }
    case "pan": case "zoom": {
      placements = grid(units, units.length, gap(60, 60), gap(0, 0), 40);
      const e = extent(placements), cy = (e.y0 + e.y1) / 2, n = camera === "pan" ? 40 : 30;
      for (let t = 0; t < n; t++) {
        const f = t / (n - 1);
        let s = 1, W = W0, H = H0;
        if (camera === "zoom") { s = t <= 12 ? 1 - 0.45 * (t / 12) : 0.55 + 0.75 * ((t - 12) / (n - 1 - 12)); if (t >= 15) { W = 960; H = 1280; } }
        const half = W / 2 / s;
        frames.push({ cam: { cx: e.x0 + half - 100 + f * (e.x1 - e.x0 - 2 * half + 200), cy, s, theta: (rng() * 2 - 1) * 0.5, W, H, ...jit() } });
      }
      break;
    }
    default: throw new Error(camera);
  }
  return { placements, frames };
}

const UNITS_PER_CAMERA = { static: 8, pan: 10, contact: 8, contact_rotated: 8, occlusion: 8, rotation: 6, missing_points: 8, repeat: 6, zoom: 8, dense: 12 };

/** Evenly spaced saved views, at most MAX_VIEWS. */
export function viewIndices(n, max = MAX_VIEWS) {
  if (n <= max) return Array.from({ length: n }, (_, i) => i);
  return [...new Set(Array.from({ length: max }, (_, k) => Math.round((k * (n - 1)) / (max - 1))))];
}

function finish(seq, units, rawFrames) {
  const frames = rawFrames.map((f, i) => {
    const { regions, faulty } = regionsFor(f);
    const { geo, ...rest } = f;
    return { seq: i + 1, at: (i + 1) * 100, ...rest, regions: f.regionsOverride ?? regions, regionFaulty: f.faultyOverride ?? faulty };
  });
  return {
    ...seq,
    units: units.map(u => ({ index: u.index, id: u.id, model: u.model, gtin: u.gtin, imei1: u.imei1, imei2: u.imei2, serial: u.serial, accessory: u.accessory, partner: u.partner,
      printed: u.lines.map(l => l.role) })),
    frames,
  };
}

/** One factorial sequence: specimen x camera x seed. */
export function factorialSequence(specimen, camera, seed) {
  // Three independent streams: the specimen's units, the camera's motion, and the reads.
  const units = makeUnits(specimen, UNITS_PER_CAMERA[camera], mulberry32(seedOf(`item_stress|units|${specimen}|${UNITS_PER_CAMERA[camera]}|${seed}`)));
  const { placements, frames: script } = cameraScript(camera, units, mulberry32(seedOf(`item_stress|camera|${camera}|${seed}`)));
  const rng = mulberry32(seedOf(`item_stress|reads|${specimen}|${camera}|${seed}`));
  const raw = [];
  for (const f of script) {
    if (f.repeatOf !== null && f.repeatOf !== undefined) { raw.push(structuredClone(raw[f.repeatOf])); continue; }
    raw.push(emitFrame(units, placements, f.cam, rng, { spec: specimen, dropout: f.dropout, missingPoints: f.missingPoints, missingBox: f.missingBox, occluder: f.occluder }));
  }
  const split = SPLITS.dev.includes(seed) ? "dev" : "holdout";
  const seq = finish({ id: `${specimen}/${camera}/s${seed}`, kind: "factorial", specimen, camera, seed, split }, units, raw);
  if (camera === "repeat") {
    const distinct = script.map((f, i) => (f.repeatOf === null ? i : -1)).filter(i => i >= 0);
    seq.views = [distinct[0], distinct[0], distinct[2], distinct[2], distinct[4], distinct[4]];
    seq.dedup = { frames: distinct, views: [distinct[0], distinct[2], distinct[4]] };
  } else seq.views = viewIndices(seq.frames.length);
  return seq;
}

// ---------------------------------------------------------------- targeted scripts (written from code review, before any run)

const flat = { cx: W0 / 2, cy: H0 / 2, s: 1, theta: 0, W: W0, H: H0 };
function scripted(id, spec, units, framesSpec, note) {
  const rng = mulberry32(seedOf(`item_stress|script|${id}`));
  for (const u of units) u.lines = layout(u, spec);
  const raw = framesSpec.map(f => {
    const placements = f.place.map(([unit, x, y]) => ({ unit, x, y, w: 220, h: units[unit].labelBottom + 10 }));
    const fr = emitFrame(units, placements, f.cam ?? flat, rng, { spec: "script", deterministic: true, hidden: new Set(f.hidden ?? []), barsOff: new Set(f.barsOff ?? []), text: new Map(Object.entries(f.text ?? {})) });
    if (f.regions) {
      // Explicit regions spanning the named units' labels (a region over two units is input-faulty by construction).
      const regions = [], faulty = [];
      for (const r of f.regions) {
        const cs = fr.geo.filter(g => r.units.includes(g.unit)).flatMap(g => g.corners);
        const b = aabb(cs);
        regions.push({ id: r.id, bbox: [b[0] - 6, b[1] - 6, b[2] + 12, b[3] + 12].map(round1), origin: "manual" });
        if (r.units.length > 1) faulty.push({ id: r.id, units: [...r.units].sort((a, b) => a - b) });
      }
      fr.regionsOverride = regions; fr.faultyOverride = faulty;
    }
    return fr;
  });
  const seq = finish({ id: `script/${id}`, kind: "script", specimen: spec, camera: "script", seed: null, split: "script", note }, units, raw);
  seq.views = seq.frames.map((_, i) => i); // a photo batch: every frame is a saved view
  return seq;
}

function scriptUnits(n, rng, { sameModel = true, pairSerial = false, imeiPair = false } = {}) {
  const V = new Values(rng);
  const units = [];
  for (let k = 0; k < n; k++) {
    const u = { id: `u${k + 1}`, index: k, model: sameModel ? 1 : k + 1, imei1: null, imei2: V.imei(), serial: null, accessory: false, partner: null, transposeAt: {} };
    u.gtin = modelGtin(u.model);
    u.imei1 = imeiPair ? V.imei({ 6: "0", 7: "9" }) : V.imei();
    u.transposeAt.imei1 = 6;
    if (pairSerial && k % 2 === 1) { u.serial = swapAt(units[k - 1].serial, units[k - 1].pairPos); u.pairPos = units[k - 1].pairPos; u.partner = k - 1; units[k - 1].partner = k; V.taken.add(u.serial); }
    else if (pairSerial) { const p = 2; u.serial = V.serial(p); u.pairPos = 4 + p; }
    else u.serial = V.serial();
    units.push(u);
  }
  return units;
}

export function scripts() {
  const rng = mulberry32(seedOf("item_stress|script-values"));
  const out = [];
  // A1: a serial misread onto another unit's exact serial, inside a truthful region.
  {
    const u = scriptUnits(2, rng, { pairSerial: true }); // u0 = A, u1 = B
    out.push(scripted("A1_serial_collision_region", "script", u, [
      { place: [[1, 100, 100]], hidden: ["1:imei1", "1:imei2"], regions: [{ id: "rB", units: [1] }] },
      { place: [[1, 105, 102]], hidden: ["1:imei1", "1:imei2"], regions: [{ id: "rB", units: [1] }] },
      { place: [[0, 700, 100]], hidden: ["0:imei2"], text: { "0:serial": u[1].serial }, regions: [{ id: "rA", units: [0] }] },
      { place: [[0, 705, 100]], regions: [{ id: "rA", units: [0] }] },
      { place: [[0, 100, 100], [1, 700, 100]], regions: [{ id: "rA", units: [0] }, { id: "rB", units: [1] }] },
    ], "B seen by serial alone; A's serial misread as B's exactly while only A's IMEI1 is visible, in A's own region"));
  }
  // A2: one region drawn around two touching, partly read units.
  {
    const u = scriptUnits(2, rng);
    out.push(scripted("A2_region_spans_two_units", "script", u, [
      { place: [[0, 100, 100]], hidden: ["0:imei2", "0:serial"], regions: [{ id: "rA", units: [0] }] },
      { place: [[1, 700, 100]], hidden: ["1:imei1", "1:serial"], regions: [{ id: "rB", units: [1] }] },
      { place: [[0, 100, 100], [1, 324, 100]], hidden: ["0:imei2", "0:serial", "1:imei1", "1:serial"], regions: [{ id: "rAB", units: [0, 1] }] },
      { place: [[0, 100, 100], [1, 700, 100]], regions: [{ id: "rA", units: [0] }, { id: "rB", units: [1] }] },
    ], "an input-faulty region: staff drew one outline over two boxes, each with one IMEI read"));
  }
  // A3: a Luhn-valid print misread of IMEI1 (09/90) in the first view, correct afterwards.
  {
    const u = scriptUnits(1, rng, { imeiPair: true });
    const bad = transpose(u[0].imei1, 6);
    out.push(scripted("A3_luhn_valid_misread_first", "script", u, [
      { place: [[0, 100, 100]], barsOff: ["0:imei1"], text: { "0:imei1": bad }, regions: [{ id: "rA", units: [0] }] },
      { place: [[0, 104, 101]], regions: [{ id: "rA", units: [0] }] },
      { place: [[0, 108, 102]], regions: [{ id: "rA", units: [0] }] },
      { place: [[0, 112, 103]], regions: [{ id: "rA", units: [0] }] },
    ], "a phantom IMEI1 (Luhn-valid transposition) read first; correct reads follow"));
  }
  // A4: a neighbour's single IMEI code at the edge of a complete box (contact).
  {
    const u = scriptUnits(2, rng);
    const f = [];
    for (let t = 0; t < 4; t++) f.push({ place: [[0, 100 + t, 100], [1, 324 + t, 100]], hidden: ["1:gtin", "1:imei1", "1:serial"] });
    for (let t = 0; t < 4; t++) f.push({ place: [[0, 100 + t, 100], [1, 324 + t, 100]] });
    out.push(scripted("A4_stray_neighbour_imei", "script", u, f, "only the neighbour's IMEI2 is visible beside a complete box, then both boxes"));
  }
  // A5: a GTIN-only accessory of another model touching a phone whose GTIN is hidden.
  {
    const u = scriptUnits(1, rng, { sameModel: false });
    u.push({ id: "u2", index: 1, model: 2, gtin: modelGtin(2), imei1: null, imei2: null, serial: null, accessory: true, partner: null, transposeAt: {} });
    const f = [];
    for (let t = 0; t < 4; t++) f.push({ place: [[0, 100 + t, 100], [1, 324 + t, 100]], hidden: ["0:gtin"] });
    for (let t = 0; t < 2; t++) f.push({ place: [[0, 100 + t, 100], [1, 324 + t, 100]] });
    out.push(scripted("A5_accessory_gtin_touching", "script", u, f, "the documented gap: a touching product-only box lends its GTIN"));
  }
  // A6: a GS1-128 (01)(21) code beside the EAN-13 of the same GTIN.
  {
    const u = scriptUnits(2, rng);
    const f = [];
    for (let t = 0; t < 4; t++) f.push({ place: [[0, 100 + t, 100], [1, 700 + t, 100]] });
    out.push(scripted("A6_gs1_beside_ean13", "gs1", u, f, "GTIN as EAN-13 and as GS1 AI (01) GTIN-14 on one label"));
  }
  // A7: a serial-only unit alternately beside two complete units, then alone.
  {
    const u = scriptUnits(3, rng);
    const f = [];
    for (let t = 0; t < 8; t++) {
      const under = t % 2 === 0 ? 100 : 700;
      f.push({ place: [[0, 100, 100], [1, 700, 100], [2, under, 100 + u[0].labelBottom + 25]], hidden: ["2:gtin", "2:imei1", "2:imei2"] });
    }
    f.push({ place: [[2, 400, 500]], hidden: ["2:gtin", "2:imei1", "2:imei2"] });
    out.push(scripted("A7_contested_churn", "script", u, f, "a serial-only label sits under A, then B, alternately; finally alone"));
  }
  // A8: more confirmed units than live capacity (maxTracks 64).
  {
    const u = scriptUnits(140, rng);
    const f = [];
    for (let t = 0; t < 140 + 4; t++) {
      const place = [];
      for (let k = Math.max(0, t - 3); k <= Math.min(139, t); k++) place.push([k, (k - t + 3) * 290 + 60, 100]);
      f.push({ place });
    }
    out.push(scripted("A8_capacity", "script", u, f, "140 units each in view for 4 frames; live keeps at most 64 tracks"));
  }
  return out;
}

// ---------------------------------------------------------------- stress

/** Long live pan: 400 units in two rows, 3000 frames back and forth. */
export function longLive() {
  const rng = mulberry32(seedOf("item_stress|long_live"));
  const units = makeUnits("clean", 400, rng);
  const placements = grid(units, 200, () => 60, () => 40, 40);
  const e = extent(placements), cy = (e.y0 + e.y1) / 2, half = W0 / 2 / 0.7;
  const frames = [];
  for (let t = 0; t < 3000; t++) {
    const phase = (t % 1000) / 999, f = Math.floor(t / 1000) % 2 ? 1 - phase : phase;
    const cam = { cx: e.x0 + half + f * (e.x1 - e.x0 - 2 * half), cy, s: 0.7, theta: 0, W: W0, H: H0, ...{ jx: (rng() * 2 - 1) * 3, jy: (rng() * 2 - 1) * 3 } };
    const fr = emitFrame(units, placements, cam, rng, { spec: "clean" });
    frames.push({ seq: t + 1, at: (t + 1) * 100, width: fr.width, height: fr.height, barcodes: fr.barcodes, fields: [], gt: fr.gt });
  }
  return { id: "stress/long_live", units: units.map(u => ({ index: u.index, imei1: u.imei1, imei2: u.imei2, serial: u.serial, gtin: u.gtin, model: u.model })), frames };
}

/** A batch of 300 saved views of 12 distinct units each. */
export function longSaved() {
  const rng = mulberry32(seedOf("item_stress|long_saved"));
  const units = makeUnits("clean", 3600, rng);
  const frames = [];
  for (let v = 0; v < 300; v++) {
    const group = units.slice(v * 12, v * 12 + 12).map((u, i) => ({ ...u, index: i }));
    const placements = grid(group, 4, () => 80, () => 60, 40);
    const e = extent(placements);
    const cam = { cx: (e.x0 + e.x1) / 2, cy: (e.y0 + e.y1) / 2, s: fit(e, W0, H0), theta: 0, W: W0, H: H0 };
    const fr = emitFrame(group, placements, cam, rng, { spec: "clean" });
    frames.push({ width: fr.width, height: fr.height, barcodes: fr.barcodes, fields: fr.fields });
  }
  return { id: "stress/long_saved", frames };
}

/** One frame of 60 units: more than 200 members. */
export function denseFrame() {
  const rng = mulberry32(seedOf("item_stress|dense_frame"));
  const units = makeUnits("clean", 60, rng);
  const placements = grid(units, 10, () => 20, () => 20, 10);
  const e = extent(placements);
  const cam = { cx: (e.x0 + e.x1) / 2, cy: (e.y0 + e.y1) / 2, s: fit(e, 4000, 3000), theta: 0, W: 4000, H: 3000 };
  const fr = emitFrame(units, placements, cam, rng, { spec: "clean", deterministic: true });
  return { id: "stress/dense_frame", width: fr.width, height: fr.height, barcodes: fr.barcodes, fields: fr.fields, gt: fr.gt };
}

// ---------------------------------------------------------------- the frozen set

export function allSequences() {
  const seqs = [];
  for (const s of SPECIMENS) for (const c of CAMERAS) for (const seed of [...SPLITS.dev, ...SPLITS.holdout]) seqs.push(factorialSequence(s, c, seed));
  return [...seqs, ...scripts()];
}

const canonical = v => JSON.stringify(v, (_, x) => (typeof x === "number" && !Number.isFinite(x) ? `__${x}` : x));
export function digest(v) { return createHash("sha256").update(canonical(v)).digest("hex"); }

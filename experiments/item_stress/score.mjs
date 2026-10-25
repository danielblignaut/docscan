// Scores one pipeline run of one sequence against its ground truth. Pure: no
// I/O, no timing, no module under test imported. Definitions are those of
// protocol.json `metrics`; nothing here is a stock quantity.

const roleClass = r => (r === "gtin" ? "gtin" : r.startsWith("imei") ? "imei" : r === "serial" ? "sn" : null);
const keyOf = (cls, v) => (cls === "sn" ? v.toUpperCase().replace(/\s+/g, "") : v.replace(/\D/g, ""));
/** GS1: a GTIN-13 and the GTIN-14 with a leading zero are one GTIN. */
export const gtin14 = v => v.replace(/\D/g, "").padStart(14, "0");

export function registry(units) {
  const own = new Map();
  for (const u of units) {
    for (const r of ["imei1", "imei2"]) if (u[r]) own.set(`imei:${keyOf("imei", u[r])}`, u.index);
    if (u.serial) own.set(`sn:${keyOf("sn", u.serial)}`, u.index);
  }
  return {
    /** The unit whose true value this is; null for a value no unit has (a misread phantom). */
    owner: (role, value) => { const c = roleClass(role); return c && c !== "gtin" ? own.get(`${c}:${keyOf(c, value)}`) ?? null : null; },
    gtinOf: i => units[i].gtin,
  };
}

/** Ground truth of a grouping member: its observation in the fed frame. */
export function memberTruth(frame, member, labelFieldCount, units) {
  const gs1 = member.origins.find(o => o.kind === "gs1");
  if (gs1) {
    const g = frame.gt.barcodes[gs1.barcode];
    const u = units[g.unit];
    const value = member.role === "gtin" ? "0" + u.gtin : member.role === "serial" ? u.serial : null;
    return { unit: g.unit, role: member.role, value, read: member.value, provenance: "code" };
  }
  if (member.fieldIndex !== null && member.fieldIndex < labelFieldCount) return frame.gt.fields[member.fieldIndex];
  return frame.gt.barcodes[member.barcodeIndices[0]];
}

const anchorableMember = m =>
  (m.role.startsWith("imei") && m.check_digit_valid === true) || (m.role === "serial" && m.check_digit_valid !== false && m.value.replace(/\s+/g, "").length >= 5);
const correctRead = t => t && t.value !== null && (roleClass(t.role) === "gtin" ? gtin14(t.read) === gtin14(t.value) : t.read === t.value);

/**
 * @param fed     the frames fed to the pipeline, in order (duplicates included)
 * @param runs    per fed frame `{ grouping, update, labelFields }` (`update` may be null)
 * @param rows    trackedRows of the final state; `state` the final tracker state
 * @param regionsFed  the pipeline was given the frames' regions (attribution of faulty regions)
 */
export function scoreRun({ units, fed, runs, rows, state, regionsFed = false }) {
  const reg = registry(units);
  const out = {
    rows: rows.length, strong_false_merge_rows: 0, strong_false_merge_values: 0, sfm_causes: {},
    weak_foreign_values: 0, weak_foreign_rows: 0,
    displayed_foreign: { strong: 0, weak: 0 }, displayed_phantom: { strong: 0, weak: 0 },
    phantom_values: { strong: 0, weak: 0 }, phantom_rows: { tentative: 0, confirmed: 0 },
    gtin_wrong_model: { strong: 0, weak: 0 }, product_identity_rows: 0, unidentified_rows: 0,
    units_observable: 0, units_found: 0, missed_units: 0, fragmentation: 0, fragmentation_disclosed: 0,
    coverage: { strong: 0, weak: 0, absent: 0, on_foreign_row: 0 },
    contested: state?.contested?.length ?? 0, contested_owned: 0,
    frame: { members: 0, placed: 0, items: 0, mixed_items: { explicit: 0, unverified: 0 }, pairs: { explicit: [0, 0], unverified: [0, 0] }, recall: [0, 0], unassigned: {} },
    observation: { correct: 0, wrong: 0, track_gone: 0 },
    identities: [],
  };

  // What each unit offered: correctly read, placed, anchorable values (the pipeline's own inputs).
  const offered = new Map(); // unit -> Map(key -> {cls, value})
  const merged = new Map();
  const finalId = id => { while (merged.has(id)) id = merged.get(id); return id; };
  const matchedRecords = [];
  runs.forEach((run, i) => {
    const frame = fed[i], g = run.grouping;
    if (!g) return;
    const truth = g.members.map(m => memberTruth(frame, m, run.labelFields, units));
    out.frame.members += g.members.length;
    const placed = g.members.filter(m => m.geometry !== "none");
    out.frame.placed += placed.length;
    for (const m of placed) {
      const t = truth[m.index];
      if (!t || t.unit === null || !correctRead(t) || !anchorableMember(m)) continue;
      const cls = roleClass(m.role);
      if (!offered.has(t.unit)) offered.set(t.unit, new Map());
      offered.get(t.unit).set(`${cls}:${keyOf(cls, m.value)}`, { cls, value: m.value });
    }
    for (const u of g.unassigned) out.frame.unassigned[u.reason] = (out.frame.unassigned[u.reason] ?? 0) + 1;
    const itemOf = new Map();
    for (const it of g.items) {
      out.frame.items++;
      for (const m of it.members) itemOf.set(m, it.key);
      const unitsIn = new Set(it.members.map(m => truth[m]?.unit));
      if (unitsIn.size > 1) out.frame.mixed_items[it.strength]++;
      const p = out.frame.pairs[it.strength];
      for (let a = 0; a < it.members.length; a++) for (let b = a + 1; b < it.members.length; b++) {
        p[1]++; if (truth[it.members[a]]?.unit === truth[it.members[b]]?.unit) p[0]++;
      }
    }
    for (let a = 0; a < placed.length; a++) for (let b = a + 1; b < placed.length; b++) {
      if (truth[placed[a].index]?.unit !== truth[placed[b].index]?.unit) continue;
      out.frame.recall[1]++;
      const ka = itemOf.get(placed[a].index);
      if (ka !== undefined && ka === itemOf.get(placed[b].index)) out.frame.recall[0]++;
    }
    if (run.update) {
      for (const m of run.update.merged) merged.set(m.from, m.into);
      for (const mt of run.update.matched) {
        const it = g.items.find(x => x.key === mt.groupKey);
        for (const mi of it?.members ?? []) {
          const m = g.members[mi], t = truth[mi];
          if (roleClass(m.role) === "gtin" || roleClass(m.role) === null || !t || !correctRead(t)) continue;
          matchedRecords.push({ trackId: mt.trackId, unit: t.unit });
        }
      }
    }
  });

  // Rows.
  const rowUnitById = new Map();
  const rowsByUnit = new Map();
  for (const row of rows) {
    const vals = [
      ...row.imei1.values.map(v => ({ ...v, role: "imei1" })), ...row.imei2.values.map(v => ({ ...v, role: "imei2" })),
      ...row.imeiUnindexed.map(v => ({ ...v, role: "imei" })), ...row.serial.values.map(v => ({ ...v, role: "serial" })),
    ].filter(v => v.check_digit_valid !== false);
    const strong = v => v.association !== "unverified";
    if (!row.identity) out.unidentified_rows++;
    else if (roleClass(row.identity.role) === "gtin") out.product_identity_rows++;
    const idOwner = row.identity ? reg.owner(row.identity.role, row.identity.value) : null;
    const strongUnits = new Set([...vals.filter(strong).map(v => reg.owner(v.role, v.value)).filter(o => o !== null), ...(idOwner !== null ? [idOwner] : [])]);
    const rowUnit = idOwner ?? (strongUnits.size === 1 ? [...strongUnits][0] : null);
    rowUnitById.set(row.id, rowUnit);
    out.identities.push(row.identity ? `${roleClass(row.identity.role)}:${keyOf(roleClass(row.identity.role), row.identity.value)}` : "none");
    if (strongUnits.size >= 2) {
      out.strong_false_merge_rows++;
      out.strong_false_merge_values += vals.filter(v => strong(v) && reg.owner(v.role, v.value) !== null && reg.owner(v.role, v.value) !== rowUnit).length;
      const cause = sfmCause([...strongUnits], fed, reg, regionsFed);
      out.sfm_causes[cause] = (out.sfm_causes[cause] ?? 0) + 1;
    }
    let weak = 0;
    for (const v of vals) {
      const o = reg.owner(v.role, v.value);
      if (o === null) out.phantom_values[strong(v) ? "strong" : "weak"]++;
      else if (!strong(v) && o !== rowUnit) weak++;
    }
    out.weak_foreign_values += weak; if (weak) out.weak_foreign_rows++;
    for (const role of ["imei1", "imei2", "serial"]) {
      const r = row[role];
      if (r.status !== "found") continue;
      const o = reg.owner(role, r.value), a = r.association === "unverified" ? "weak" : "strong";
      if (o === null) out.displayed_phantom[a]++;
      else if (rowUnit !== null && o !== rowUnit) out.displayed_foreign[a]++;
    }
    if (row.gtin.status === "found" && rowUnit !== null && gtin14(row.gtin.value) !== gtin14(reg.gtinOf(rowUnit)))
      out.gtin_wrong_model[row.gtin.association === "unverified" ? "weak" : "strong"]++;
    if (rowUnit === null) out.phantom_rows[row.status]++;
    else { if (!rowsByUnit.has(rowUnit)) rowsByUnit.set(rowUnit, []); rowsByUnit.get(rowUnit).push(row); }
  }

  // Units.
  out.units_observable = offered.size;
  for (const [u, vals] of offered) {
    const mine = rowsByUnit.get(u) ?? [];
    if (!mine.length) { out.missed_units++; continue; }
    out.units_found++;
    out.fragmentation += mine.length - 1;
    const ids = new Set(mine.map(r => r.id));
    out.fragmentation_disclosed += mine.slice(1).filter(r => r.possiblySameAs.some(x => ids.has(x) && x !== r.id)).length;
    for (const [key, { cls }] of vals) {
      const onRow = rows.flatMap(r => [
        ...r.imei1.values.map(v => ({ r, v, role: "imei1" })), ...r.imei2.values.map(v => ({ r, v, role: "imei2" })),
        ...r.imeiUnindexed.map(v => ({ r, v, role: "imei" })), ...r.serial.values.map(v => ({ r, v, role: "serial" })),
      ]).filter(x => `${roleClass(x.role)}:${keyOf(roleClass(x.role), x.v.value)}` === key && roleClass(x.role) === cls);
      const own = onRow.filter(x => rowUnitById.get(x.r.id) === u);
      if (own.some(x => x.v.association !== "unverified")) out.coverage.strong++;
      else if (own.length) out.coverage.weak++;
      else out.coverage.absent++;
      if (onRow.some(x => rowUnitById.get(x.r.id) !== u)) out.coverage.on_foreign_row++;
    }
  }
  out.contested_owned = (state?.contested ?? []).filter(c => reg.owner(c.role, c.value) !== null).length;

  for (const rec of matchedRecords) {
    const id = finalId(rec.trackId);
    if (!rowUnitById.has(id)) out.observation.track_gone++;
    else if (rowUnitById.get(id) === rec.unit) out.observation.correct++;
    else out.observation.wrong++;
  }
  out.identities.sort();
  return out;
}

/** Why a row holds two units with association: an input-faulty region, a misread onto another unit's value, or neither (the module). */
function sfmCause(unitsOnRow, fed, reg, regionsFed) {
  const set = new Set(unitsOnRow);
  for (const f of fed) for (const r of f.regionFaulty ?? []) if (regionsFed && r.units.filter(u => set.has(u)).length >= 2) return "faulty_region";
  for (const f of fed) for (const t of [...f.gt.fields, ...f.gt.barcodes]) {
    if (!set.has(t.unit) || t.read === t.value) continue;
    const o = reg.owner(t.role, t.read);
    if (o !== null && o !== t.unit && set.has(o)) return "misread_collision";
  }
  return "module";
}

/** Adds numeric leaves of b into a (same shape); arrays of numbers element-wise. */
export function accumulate(a, b) {
  for (const [k, v] of Object.entries(b)) {
    if (k === "identities") continue;
    if (typeof v === "number") a[k] = (a[k] ?? 0) + v;
    else if (Array.isArray(v)) { a[k] ??= v.map(() => 0); v.forEach((x, i) => (a[k][i] += x)); }
    else if (v && typeof v === "object") accumulate((a[k] ??= {}), v);
  }
  return a;
}

// Diagnosis only (not frozen, not scored): replays one sequence through one
// pipeline and prints, per fed frame, its groups (members as unit:role, with
// misreads marked) and the tracker's update, then the final rows with the
// owner of every value.
//   node experiments/item_stress/inspect.mjs <sequence id> <live|saved|saved_regions> [baseline|candidate]
import { allSequences } from "./generate.mjs";
import { registry, memberTruth } from "./score.mjs";
import { loadArm, runLive, runSaved } from "./run.mjs";

const [id, pipeline = "saved_regions", armName = "baseline"] = process.argv.slice(2);
const seq = allSequences().find(s => s.id === id);
if (!seq) throw new Error(`no sequence ${id}`);
const arm = await loadArm(armName);
const idx = pipeline === "live" ? seq.frames.map((_, i) => i) : seq.views;
const fed = idx.map(i => seq.frames[i]);
const r = pipeline === "live" ? runLive(arm, fed) : runSaved(arm, fed, pipeline === "saved_regions");
const reg = registry(seq.units);
const U = i => (i === null || i === undefined ? "?" : `U${i}`);
r.runs.forEach((run, i) => {
  const g = run.grouping, u = run.update;
  console.log(`\n# view ${i + 1} (frame ${idx[i] + 1})${fed[i].regionFaulty?.length ? ` faulty regions ${JSON.stringify(fed[i].regionFaulty)}` : ""}`);
  for (const it of g.items) {
    const ms = it.members.map(m => {
      const mm = g.members[m], t = memberTruth(fed[i], mm, run.labelFields, seq.units);
      const mis = t && t.read !== t.value && t.role !== "gtin" ? `!misread->${U(reg.owner(t.role, t.read))}` : "";
      return `${U(t?.unit)}:${mm.role}${mm.source === "text" ? "(t)" : ""}${mis}`;
    });
    console.log(`  ${it.key} ${it.strength}${it.regionId ? ` ${it.regionId}` : ""}: ${ms.join(" ")}${it.conflicts.length ? ` conflicts=${it.conflicts}` : ""}`);
  }
  if (g.unassigned.length) console.log(`  unassigned ${g.unassigned.map(x => `${U(memberTruth(fed[i], g.members[x.member], run.labelFields, seq.units)?.unit)}:${g.members[x.member].role}/${x.reason}`).join(" ")}`);
  const brief = Object.fromEntries(Object.entries(u).filter(([k, v]) => Array.isArray(v) && v.length));
  console.log(`  update ${JSON.stringify(brief)}`);
});
console.log("\n# rows");
for (const row of r.rows) {
  const vals = ["imei1", "imei2", "serial"].flatMap(role => row[role].values.map(v => `${role}=${U(reg.owner(role, v.value))}/${v.association}/${v.frames}`));
  vals.push(...row.imeiUnindexed.map(v => `imei=${U(reg.owner("imei", v.value))}/${v.association}/${v.frames}`));
  console.log(`  ${row.id} ${row.status} id=${row.identity?.role}:${U(row.identity ? reg.owner(row.identity.role, row.identity.value) : null)} ${vals.join(" ")}${row.possiblySameAs.length ? ` same?${row.possiblySameAs}` : ""}${row.conflicts.length ? ` conflicts=${row.conflicts.map(c => `${c.role}:${U(reg.owner(c.role, c.value))}x${c.frames}`)}` : ""}`);
}

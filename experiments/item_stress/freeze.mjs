// Records what the benchmark is before it is run: sha256 of the protocol,
// generator, scorer and runner, and the digest of every sequence's gold.
// Refuses to overwrite an existing freeze.
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { allSequences, digest } from "./generate.mjs";

const here = new URL(".", import.meta.url);
const target = new URL("evidence/freeze.json", here);
if (existsSync(target)) { console.error("evidence/freeze.json exists: the benchmark is already frozen"); process.exit(1); }
const files = Object.fromEntries(["protocol.json", "generate.mjs", "score.mjs", "run.mjs"].map(f => [f, createHash("sha256").update(readFileSync(new URL(f, here))).digest("hex")]));
const seqs = allSequences();
const protocol = JSON.parse(readFileSync(new URL("protocol.json", here), "utf8"));
const freeze = {
  frozen_at: new Date().toISOString(), base_revision: protocol.base_revision, files, gold: digest(seqs),
  sequences: seqs.length, frames: seqs.reduce((n, s) => n + s.frames.length, 0),
  units: seqs.reduce((n, s) => n + s.units.length, 0),
  observations: seqs.reduce((n, s) => n + s.frames.reduce((m, f) => m + f.barcodes.length + f.fields.length, 0), 0),
  note: "written before the first run of the module under test; run.mjs refuses to run on any mismatch",
};
freeze.digest = digest(freeze);
writeFileSync(target, JSON.stringify(freeze, null, 1));
console.log(JSON.stringify(freeze, null, 1));

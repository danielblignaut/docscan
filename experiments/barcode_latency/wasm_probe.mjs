// Private WASM latency probe (DEV only): the single-threaded wasm package in
// Node (V8, as Chrome), one process per cold run.
//
//   node wasm_probe.mjs PKG_DIR MODELS_DIR RGBA_FILE WIDTH HEIGHT CALL REPEAT [MARGINS]
//
// CALL is `barcodes`, `labelled` or `labelled_near_bars` (MARGINS: five
// comma-separated numbers, or none for the frozen default). RGBA_FILE holds the
// decoded frame (written by run_wasm.py). Prints one JSON line: instantiate
// and model-load ms, then per-iteration ms (the first is the cold call), and
// the fields of the first call. The fields hold values: run_wasm.py reads
// them in memory and writes aggregates only.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [pkg, models, rgbaFile, width, height, call, repeat, margins = ""] = process.argv.slice(2);
const marginList = new Float32Array(margins ? margins.split(",").map(Number) : []);
const w = Number(width);
const h = Number(height);
const t0 = performance.now();
const mod = await import(pathToFileURL(join(pkg, "docscan.js")).href);
mod.initSync({ module: readFileSync(join(pkg, "docscan_bg.wasm")) });
const scanner = new mod.Scanner();
const instantiateMs = performance.now() - t0;
const t1 = performance.now();
if (call !== "barcodes") {
  scanner.load_ocr(readFileSync(join(models, "text-detection.rten")), readFileSync(join(models, "text-recognition.rten")));
}
const modelsMs = performance.now() - t1;
const rgba = new Uint8Array(readFileSync(rgbaFile));
const ms = [];
let first = null;
for (let i = 0; i < Number(repeat); i++) {
  const t = performance.now();
  const out = call === "barcodes" ? scanner.barcodes(rgba, w, h, [])
    : call === "labelled" ? scanner.labelled(rgba, w, h) : scanner.labelled_near_bars(rgba, w, h, marginList);
  ms.push(performance.now() - t);
  if (i === 0) first = out;
}
const fields = call === "barcodes"
  ? first.map((b) => ({ format: b.format, text: b.text }))
  : first.fields.map((f) => ({ label: f.label ?? null, value: f.value, kind: f.kind, source: f.source, check: f.check_digit_valid ?? null, format: f.barcode_format ?? null }));
console.log(JSON.stringify({ call, instantiateMs, modelsMs, ms, fields }));

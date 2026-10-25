// Private WASM label-speed probe (DEV only): the patched single-threaded
// package in Node (V8, as Chrome), one process per cold run.
//
//   node wasm_probe.mjs PKG_DIR MODELS_DIR RGBA_FILE WIDTH HEIGHT CALL REPEAT
//
// CALL is `labelled` (unchanged), `labelled_once` (page detector loaded) or
// `labelled_fast` (PP-OCRv6 tiny loaded). Prints one JSON line: instantiate
// and model-load ms, per-iteration ms (the first is the cold call), the wasm
// memory after the calls, and the fields of the first call. The fields hold
// values: run_wasm.py reads them in memory and writes aggregates only.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [pkg, models, rgbaFile, width, height, call, repeat] = process.argv.slice(2);
const w = Number(width);
const h = Number(height);
const m = (n) => readFileSync(join(models, n));
const t0 = performance.now();
const mod = await import(pathToFileURL(join(pkg, "docscan.js")).href);
const wasm = mod.initSync({ module: readFileSync(join(pkg, "docscan_bg.wasm")) });
const scanner = new mod.Scanner();
const instantiateMs = performance.now() - t0;
const t1 = performance.now();
scanner.load_ocr(m("text-detection.rten"), m("text-recognition.rten"));
if (call === "labelled_once") scanner.load_page_detector(m("text-detection-page.onnx"));
if (call === "labelled_fast") scanner.load_label_reader(m("ppocr-v6-tiny-det.onnx"), m("ppocr-v6-tiny-rec.onnx"));
const modelsMs = performance.now() - t1;
const rgba = new Uint8Array(readFileSync(rgbaFile));
const ms = [];
let first = null;
for (let i = 0; i < Number(repeat); i++) {
  const t = performance.now();
  const out = scanner[call](rgba, w, h);
  ms.push(performance.now() - t);
  if (i === 0) first = out;
}
const fields = first.fields.map((f) => ({ label: f.label ?? null, value: f.value, kind: f.kind, source: f.source, check_digit_valid: f.check_digit_valid ?? null }));
console.log(JSON.stringify({ call, instantiateMs, modelsMs, ms, memoryBytes: wasm.memory.buffer.byteLength, fields }));

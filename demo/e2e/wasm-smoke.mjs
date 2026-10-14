// A fast regression check of the built wasm, in Node, without a browser:
// every synthetic document goes through `barcodes()` and `document()`. It
// exists because a class of failure is wasm-only and invisible to the native
// tests: anything in a dependency reaching `std::time`, threads or the
// filesystem traps as `RuntimeError: unreachable` (rxing's `Utc::now()` on
// every decoded barcode did exactly that). Usage: node e2e/wasm-smoke.mjs
import { execFileSync } from "node:child_process";
import { readFileSync, readdirSync } from "node:fs";
import { initSync, Scanner } from "docscan";

const ROOT = new URL("../../", import.meta.url).pathname;
const PY = `${ROOT}testdata/.venv/bin/python`;
initSync({ module: readFileSync(`${ROOT}docscan/pkg/docscan_bg.wasm`) });

/** RGBA pixels of a PNG, at most `max` wide, decoded by the test venv's PIL. */
function rgba(path, max = 1280) {
  const script = `import sys; from PIL import Image
im = Image.open(sys.argv[1]).convert("RGBA")
if im.width > ${max}: im = im.resize((${max}, round(im.height * ${max} / im.width)))
sys.stdout.buffer.write(im.width.to_bytes(4, "little") + im.height.to_bytes(4, "little") + im.tobytes())`;
  const buf = execFileSync(PY, ["-c", script, path], { maxBuffer: 1 << 28 });
  return { w: buf.readUInt32LE(0), h: buf.readUInt32LE(4), data: new Uint8Array(buf.buffer, buf.byteOffset + 8) };
}

const scanner = new Scanner();
scanner.load_ocr(readFileSync(`${ROOT}models/text-detection.rten`), readFileSync(`${ROOT}models/text-recognition.rten`));
let failed = 0;
for (const name of readdirSync(`${ROOT}testdata/synth`).filter((f) => f.endsWith(".json"))) {
  const truth = JSON.parse(readFileSync(`${ROOT}testdata/synth/${name}`));
  const { w, h, data } = rgba(`${ROOT}testdata/${truth.image}`);
  try {
    const codes = scanner.barcodes(data, w, h, []);
    const doc = scanner.document(data, w, h, true, "auto");
    const want = (truth.barcodes ?? []).length;
    const ok = codes.length >= Math.min(1, want) && (truth.kind === "multi_barcode" || doc.kind !== "unknown");
    if (!ok) failed++;
    console.log(`${ok ? "ok  " : "FAIL"} ${truth.name}: ${codes.length}/${want} barcodes, kind ${doc.kind}, ${Math.round(doc.timings_ms.total)} ms`);
  } catch (e) {
    failed++;
    console.log(`FAIL ${truth.name}: ${e}`);
  }
}
process.exit(failed ? 1 : 0);
